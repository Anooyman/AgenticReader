import asyncio
import json
import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple, Union

from langchain.docstore.document import Document
from langchain_core.messages import HumanMessage, AIMessage

from src.readers.base import ReaderBase
from src.readers.retrieval import RetrivalAgent
from src.core.processing.text_splitter import StrictOverlapSplitter
from src.config.settings import (
    MCP_CONFIG,
    MCPToolName,
    WEB_MAX_TOKEN_COUNT,
)
from src.config.constants import ReaderConstants
from src.config.prompts.reader_prompts import ReaderRole, READER_PROMPTS
from src.services.mcp_client import MCPClient
from src.core.llm.client import LLMBase
from src.utils.helpers import extract_name_from_url, makedir, extract_data_from_LLM_res
from src.core.vector_db.vector_db_client import VectorDBClient

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class WebReader(ReaderBase):
    """
    Web内容读取器，用于从URL获取网页内容并进行处理、摘要和问答交互。

    该类继承自ReaderBase，支持通过MCP服务获取网页内容，处理大文件时分块存储到向量数据库，
    并提供与用户的交互式对话功能。

    Attributes:
        web_content (str): 存储处理后的网页内容
        spliter (StrictOverlapSplitter): 文本分块器实例，用于大文本分块
        vector_db_obj (VectorDBClient): 向量数据库客户端实例，用于存储和检索分块数据
    """

    def __init__(self, provider: str = "openai") -> None:
        """
        初始化WebReader对象，设置LLM提供商和文本分块器。

        Args:
            provider (str): LLM服务提供商，可选值为'azure'、'openai'、'ollama'，默认为'openai'
        """
        super().__init__(provider)
        self.web_content: str = ""  # 初始化网页内容为空字符串
        self.spliter = StrictOverlapSplitter(
            overlap=1,
            token_threshold=10000,
            delimiter='\n\n',  # 以空行作为文本切分符
        )
        self.vector_db_obj: Optional[VectorDBClient] = None  # 向量数据库客户端，延迟初始化
        self.retrieval_data_agent: Optional[RetrivalAgent] = None  # 检索代理，延迟初始化

    def remove_error_blocks(self, text: str) -> Tuple[str, List[str]]:
        """
        移除文本中包含的<error>错误块内容

        错误块指被<error>和</error>标签包裹的内容，通常为MCP服务返回的错误信息。
        该方法会清理文本并记录错误块，便于后续排查问题。

        Args:
            text (str): 原始文本内容，可能包含<error>标签

        Returns:
            tuple: 包含两个元素
                - 清理后的文本（移除所有错误块）
                - 匹配到的错误块列表（保留原始错误内容）
        """
        # 正则表达式模式：匹配<error>和</error>之间的所有内容（包括换行符）
        pattern = r'<error>.*?</error>'
        # 使用re.DOTALL让.匹配包括换行符在内的所有字符
        matched_blocks = re.findall(pattern, text, flags=re.DOTALL)
        # 清理文本中的错误块
        cleaned_text = re.sub(pattern, '', text, flags=re.DOTALL)
        
        if matched_blocks:
            logger.warning(f"已移除{len(matched_blocks)}个错误块内容，示例: {matched_blocks[0][:50]}...")
        return cleaned_text, matched_blocks

    async def call_mcp_server(self, input_prompt: str, mcp_config: dict, session_id: str) -> List[str]:
        """
        调用MCP服务处理输入提示并获取网页内容

        使用MCPClient的集成工具调用功能，简化了原有的ReAct循环逻辑。
        MCP客户端会自动处理工具发现、调用和错误处理。

        Args:
            input_prompt (str): 用户输入提示，用于指导MCP服务获取内容
            mcp_config (dict): MCP服务配置，包含服务地址、认证信息等
            session_id (str): 会话ID，用于跟踪本次MCP服务调用

        Returns:
            List[str]: 网页内容片段列表，已移除错误块
        """
        # 初始化LLM客户端和MCP客户端，使用依赖注入模式
        llm_client = LLMBase(provider=self.provider)
        
        # 使用配置中的 Web MCP system prompt
        web_system_prompt = READER_PROMPTS.get(ReaderRole.WEB_MCP)
        
        mcp_client = MCPClient(llm_client, mcp_config, system_prompt=web_system_prompt)
        await mcp_client.initialize()

        try:
            # 使用MCPClient的集成工具调用功能
            response = await mcp_client.process_query_with_tools(
                query=input_prompt,
                session_id=session_id,
                max_iterations=5  # 减少迭代次数，因为网页获取通常不需要太多轮
            )
            
            # 清理响应中的错误块
            cleaned_response, error_blocks = self.remove_error_blocks(response)
            
            if error_blocks:
                logger.warning(f"移除了{len(error_blocks)}个错误块")
            
            # 将响应按段落分割，便于后续处理
            web_result = [cleaned_response] if cleaned_response.strip() else []

            return web_result

        except Exception as e:
            logger.error(f"MCP服务调用失败: {e}")
            return []
        finally:
            # 清理MCP客户端资源
            await mcp_client.cleanup()

    async def get_web_content(self, url: str, url_name: str) -> List[str]:
        """
        从指定URL获取网页内容并保存到JSON文件

        通过调用MCP服务获取网页内容，并将原始结果保存到本地JSON文件，
        便于后续复用（避免重复网络请求）。

        Args:
            url (str): 网页URL地址（需http/https协议）
            url_name (str): URL名称（用于生成本地保存文件名，通常为URL提取的标识）

        Returns:
            list: 网页内容片段列表（MCP服务返回的原始结果，已处理错误块）
        """
        # 获取MCP服务配置
        config = MCP_CONFIG.get(MCPToolName.WEB_SEARCH)
        if not config:
            raise ValueError(f"未找到MCP工具配置: {MCPToolName.WEB_SEARCH}")

        # 构建获取网页内容的提示词（要求Markdown格式便于后续处理）
        input_prompt = f"请获取该URL的所有当前内容: {url}，并以Markdown格式返回全部和文章主要内容相关的文字信息。需要保持web页面原始的语言和文字，不要进行修改删除。"
        logger.info(f"开始获取网页内容: {url}")

        # 调用MCP服务获取内容
        web_content = await self.call_mcp_server(input_prompt, config, MCPToolName.WEB_SEARCH)

        # 保存内容到本地JSON文件
        save_path = os.path.join(self.json_data_path, f"{url_name}.json")
        with open(save_path, 'w', encoding='utf-8') as file:
            json.dump(web_content, file, ensure_ascii=False)
        logger.info(f"网页内容已保存到本地: {save_path}")

        return web_content

    async def process_web(self, url: str, save_data_flag: bool = True) -> None:
        """
        处理网页内容：优先从本地加载，本地不存在则从网络获取，根据内容大小选择处理方式

        处理逻辑：
        1. 尝试加载本地缓存的网页内容（JSON文件）
        2. 本地无缓存时，调用MCP服务获取并保存
        3. 根据内容token数判断：
           - 小于等于阈值：直接生成摘要并保存
           - 大于阈值：分块后存入向量数据库，用于后续检索问答

        Args:
            url (str): 网页URL地址
            save_data_flag (bool): 是否保存处理后的数据（摘要或向量数据库），默认为True
        """
        # 从URL提取名称（用于文件命名）
        url_name = extract_name_from_url(url)
        logger.info(f"开始处理网页: {url}，提取名称: {url_name}")

        # 尝试加载本地缓存
        try:
            cache_path = os.path.join(self.json_data_path, f"{url_name}.json")
            with open(cache_path, 'r', encoding='utf-8') as f:
                web_content = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"本地缓存加载失败（{type(e).__name__}），将重新获取: {e}")
            web_content = await self.get_web_content(url, url_name)

        # 计算内容总token数，判断处理方式
        content_str = ', '.join(web_content)
        token_count = self.spliter.count_tokens(content_str)

        if token_count <= WEB_MAX_TOKEN_COUNT:
            # 内容较小，直接生成摘要
            self.output_path += f"/{url_name}"  # 构建输出路径

            # 检查是否已生成摘要
            summary_md_path = os.path.join(self.output_path, "summary.md")
            if not os.path.exists(summary_md_path):  # 避免重复生成摘要
                # 构建摘要链
                summary_chain = self.build_chain(
                    self.chat_model,
                    READER_PROMPTS.get(ReaderRole.SUMMARY)
                )
                # 构建摘要提示词
                query = f"请分析总结当前web页面的内容，按照文章本身的写作顺序给出详细的总结：{content_str}。返回中文"
                summary = summary_chain.invoke(
                    {"input_prompt": query},
                    config={"configurable": {"session_id": "summary"}}
                )

                if save_data_flag:
                    makedir(self.output_path)  # 创建输出目录
                    self.save_data_to_file(summary, "summary", file_type_list=["md"])  # 保存摘要（只保存md格式）
                    logger.info(f"摘要已保存到: {self.output_path}/summary.md")
                print(f"Web Summary: {summary}")
            else:
                logger.info(f"摘要文件已存在，跳过生成: {summary_md_path}")

            self.web_content = content_str  # 保存完整内容用于问答

        else:
            # 内容较大，分块存入向量数据库
            vector_db_path = os.path.join(self.vector_db_path, f"{url_name}{ReaderConstants.VECTOR_DB_SUFFIX}")
            self.vector_db_obj = VectorDBClient(vector_db_path, provider=self.provider)

            if self.vector_db_obj.vector_db is not None:
                # 向量数据库已在初始化时自动加载
                self.get_data_from_vector_db()
            else:
                # 文本分块处理
                raw_web_data_list = self.spliter.split_text(content_str)

                # 保存分块数据到本地
                format_data_path = os.path.join(self.json_data_path, f"{url_name}{ReaderConstants.FORMAT_DATA_SUFFIX}")
                with open(format_data_path, 'w', encoding='utf-8') as file:
                    json.dump(raw_web_data_list, file, ensure_ascii=False)

                # 分块入库
                chunks = self.spliter.split_into_chunks(raw_web_data_list)
                self.get_data_from_json_dict(chunks, raw_web_data_list)
                logger.info(f"分块数据已存入向量数据库: {vector_db_path}")

            if save_data_flag:
                # 生成输出文件
                self.generate_output_file(url_name, self.raw_data_dict)
                logger.info(f"向量数据库输出文件已生成: {url_name}")

        logger.info(f"网页处理流程结束: {url}")

    def chat(self, input_prompt: str) -> str:
        """
        处理用户对话输入并生成回答

        回答逻辑：
        1. 若已加载完整网页内容（小文件），直接基于内容生成回答
        2. 若内容已分块存入向量数据库（大文件），使用 RetrivalAgent 检索相关分块再生成回答

        Args:
            input_prompt (str): 用户输入的问题（需与网页内容相关）

        Returns:
            str: 生成的回答内容（自然语言）
        """
        if self.web_content:
            # 基于完整内容回答（小文件直接回答）
            logger.info(f"使用完整网页内容回答问题: {input_prompt[:50]}...")
            answer = self.get_answer(self.web_content, input_prompt)
        else:
            # 基于向量数据库检索回答（大文件使用 RetrivalAgent）
            if not self.vector_db_obj:
                raise RuntimeError("向量数据库未初始化，请先调用process_web处理URL")

            # 初始化 RetrivalAgent（延迟初始化）
            if self.retrieval_data_agent is None:
                self.retrieval_data_agent = RetrivalAgent(
                    agenda_dict=self.agenda_dict,
                    provider=self.provider,
                    vector_db_obj=self.vector_db_obj,
                )
            
            # 使用 RetrivalAgent 检索相关数据
            context_data = self.retrieval_data_agent.retrieval_data(input_prompt)
            logger.info(f"检索到{len(context_data)}条相关分块数据")

            # 基于检索结果生成回答
            answer = self.get_answer(context_data, input_prompt)

        logger.info(f"对话回答生成完毕，长度: {len(answer)}字符")
        return answer

    async def main(self, url: str, save_data_flag: bool=True) -> None:
        """
        程序主入口，处理网页URL并启动交互式对话

        流程：
        1. 调用process_web处理URL（加载/获取内容，根据大小处理）
        2. 启动交互式命令行对话，接收用户输入并返回回答
        3. 支持用户输入"退出"等指令结束对话

        Args:
            url (str): 要处理的网页URL（需完整且可访问）
        """
        await self.process_web(url, save_data_flag)
        logger.info("网页内容处理完成，开始交互式对话（输入'退出'结束）")

        while True:
            user_input = input("You: ")

            # 检查退出指令
            if user_input.lower() in ["退出", "再见", "bye", "exit", "quit"]:
                print("Chatbot: 再见！期待下次与您对话。")
                break

            # 生成回答并记录对话历史
            answer = self.chat(user_input)
            self.add_message_to_history(session_id="chat", message=AIMessage(answer))

            # 打印对话内容
            print(f"User: {user_input}")
            print(f"ChatBot: {answer}")
            print("======" * 10)


if __name__ == "__main__":
    # 示例：创建WebReader实例并运行（实际使用需传入具体URL）
    web_reader_obj = WebReader()
    target_url = input("请输入要处理的网页URL: ")
    asyncio.run(web_reader_obj.main(target_url))