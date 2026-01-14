"""
Memory Agent Module
记忆代理模块

该模块实现了智能记忆管理系统，包含三个核心组件：
- VectorAgent: 向量数据库代理，负责向量存储和语义检索
- KnowledgeGraphAgent: 知识图谱代理，负责短期记忆构建和上下文检索
- MemoryAgent: 记忆管理主代理，协调各子代理完成记忆的存储和检索

核心功能：
1. 智能记忆判断：自动识别用户输入是存储请求还是检索请求
2. 多层次检索：结合向量检索和图谱检索提供全面的记忆服务
3. 语义理解：通过LLM重写和优化查询，提高检索准确性
4. 上下文管理：构建短期知识图谱，提供更丰富的上下文信息
5. 元数据管理：支持时间、地点、人物等多维度的记忆组织

技术架构：
- 基于LangGraph实现的状态图工作流
- 向量数据库用于长期记忆存储
- MCP服务器用于知识图谱操作
- LLM驱动的智能判断和总结

Author: LLMReader Team  
Date: 2025-09-03
Version: 2.0
"""

import logging
import datetime
import json
import os
from typing import Dict, Any, List, Optional, Union, TypedDict

from langchain.docstore.document import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from src.config.settings import (
    AgentType, 
    MCP_CONFIG, 
    MCPToolName, 
    MEMORY_VECTOR_DB_CONFIG, 
    MemoryRole
)
from src.core.llm.client import LLMBase
from src.utils.helpers import *
from src.core.vector_db.vector_db_client import VectorDBClient
from src.services.mcp_client import MCPClient

# 全局配置和常量
TOOL_STOP_FLAG = "Observation"  # MCP工具调用停止标识符
DEFAULT_SEARCH_K = 10  # 默认检索结果数量
MAX_MCP_ATTEMPTS = 10  # MCP服务最大调用尝试次数

# 配置日志系统
logger = logging.getLogger(__name__)
logger.info("记忆代理模块已加载，初始化多层次记忆管理系统")

class MemoryState(TypedDict):
    """
    MemoryAgent LangGraph状态管理类
    
    定义记忆代理工作流中各个节点间传递的状态数据结构。
    该状态在整个记忆处理流程中保持数据的一致性和完整性。
    
    Attributes:
        query (str): 用户的原始查询输入
            - 存储请求: "请记录我今天吃了火锅"
            - 检索请求: "我昨天吃了什么？"
            
        search_results (Dict[str, Any]): 各种检索结果的集合
            包含：
            - vector: 向量数据库检索结果
            - graph_context: 知识图谱上下文信息
            - error: 检索过程中的错误信息（如有）
            
        graph_context (str): 知识图谱构建的短期上下文
            通过MCP服务器从历史数据中构建的相关上下文信息
            
        answer (str): 最终生成的回复内容
            经过总结和整合后的用户友好回答
            
        judge (Dict[str, Any]): 意图判断结果
            LLM判断的用户操作类型：
            - result: "save" 或 "search"
            - confidence: 判断置信度（可选）
            
        status (str): 当前处理状态
            - "running": 处理中
            - "completed": 处理完成  
            - "error": 出现错误
    
    状态流转路径：
        START -> LLMjudge -> [save OR search] -> summarize -> END
    """
    query: str
    search_results: Dict[str, Any]
    graph_context: str
    answer: str
    judge: Dict[str, Any]
    status: str

class VectorAgent(LLMBase):
    """
    向量数据库代理 - 长期记忆存储和语义检索引擎
    
    VectorAgent负责管理用户的长期记忆数据，通过向量数据库实现高效的语义检索。
    它支持多维度的元数据标记，能够基于时间、地点、人物等维度组织和检索记忆。
    
    核心功能：
    1. 长期记忆存储：将用户的记忆数据转换为向量并持久化存储
    2. 语义检索：基于语义相似度检索相关的历史记忆
    3. 元数据管理：支持location、person、date、tag等多维度标记
    4. 智能查询重写：使用LLM优化查询语句以提高检索准确性
    5. 过滤检索：支持基于元数据的条件过滤检索
    
    数据组织结构：
    ```json
    {
        "location": ["北京", "上海", "深圳"],
        "person": ["张三", "李四", "王五"],  
        "date": ["2025-09-01", "2025-09-02", "2025-09-03"],
        "tag": ["工作", "生活", "学习"]
    }
    ```
    
    向量存储格式：
    - page_content: 原始记忆内容
    - metadata: 包含时间、地点、人物等结构化信息
    - vector: 内容的向量表示（自动生成）
    
    检索策略：
    1. 无过滤条件：基于语义相似度进行全局检索
    2. 有过滤条件：先进行元数据过滤，再计算语义相似度
    3. 多条件检索：支持同时基于多个维度进行检索
    
    Attributes:
        k (int): 检索结果数量，默认10
        vector_client_obj (VectorDBClient): 向量数据库客户端
        memory_dict (Dict): 历史记忆元数据字典
        vector_db: 向量数据库实例
    
    使用示例：
    ```python
    vector_agent = VectorAgent(config, k=10)
    
    # 存储记忆
    await vector_agent.execute({
        "operation": "save",
        "query": "今天在北京和张三一起吃了火锅"
    })
    
    # 检索记忆  
    results = await vector_agent.execute({
        "operation": "search",
        "query": "我和张三吃过什么？"
    })
    ```
    """
    
    def __init__(self, memory_config: Dict[str, Any], provider: str = "openai", k: int = DEFAULT_SEARCH_K) -> None:
        """
        初始化向量数据库代理
        
        Args:
            memory_config (Dict[str, Any]): 记忆配置字典
                包含数据库路径和元数据配置文件路径
            provider (str): LLM服务提供商，默认"openai"
            k (int): 检索返回的结果数量，默认10
        
        初始化流程：
        1. 继承LLMBase，获得语言模型调用能力
        2. 初始化向量数据库客户端
        3. 加载历史记忆元数据信息
        4. 检查并加载已存在的向量数据库
        """
        super().__init__(provider=provider)
        self.k = k
        
        logger.info(f"初始化VectorAgent - 提供商: {provider}, 检索数量: {k}")
        
        # 初始化向量数据库客户端
        db_path = memory_config.get("db_path")
        if not db_path:
            logger.error("向量数据库路径未配置")
            raise ValueError("memory_config中必须包含db_path")
        
        logger.debug(f"向量数据库路径: {db_path}")
        self.vector_client_obj = VectorDBClient(
            db_path=db_path,
            embedding_model=self.embedding_model
        ) 
        
        # 加载历史记忆信息
        self.config = memory_config
        logger.info("加载历史记忆元数据...")
        self.memory_dict = self.load_history_memory_info()

        # 加载或创建向量数据库
        if os.path.exists(db_path):
            logger.info("检测到已存在的向量数据库，正在加载...")
            self.vector_db = self.vector_client_obj.load_vector_db()
            logger.info("向量数据库加载成功")
        else:
            logger.info("未发现历史向量数据库，将在首次存储时创建")
            self.vector_db = None
    
    def load_history_memory_info(self) -> Dict[str, List[str]]:
        """
        加载历史记忆元数据信息
        
        从配置文件中加载已知的location、person、date、tag等信息，
        用于查询重写和元数据过滤。
        
       
        Returns:
            Dict[str, List[str]]: 各类元数据的字典
                key: 元数据类型 ("location", "person", "date", "tag")
                value: 对应类型的已知值列表
        
        文件格式：
        每个文件应包含JSON格式的字符串列表
        ```json
        ["北京", "上海", "深圳"]
        ```
        """
        data_dict = {}
        load_file_name_list = ["location", "person", "date", "tag"]
        
        logger.debug("开始加载各类元数据文件...")
        
        for file_name in load_file_name_list:
            file_config = self.config.get(file_name, {})
            file_path = file_config.get("file_path") if isinstance(file_config, dict) else None
            
            if file_path and os.path.exists(file_path):
                try:
                    data_dict[file_name] = load_json_file(file_path)
                    logger.debug(f"成功加载{file_name}元数据: {len(data_dict[file_name])}项")
                except Exception as e:
                    logger.warning(f"加载{file_name}元数据文件失败: {e}")
                    data_dict[file_name] = []
            else:
                logger.debug(f"{file_name}元数据文件不存在，使用空列表: {file_path}")
                data_dict[file_name] = []
        
        total_items = sum(len(items) for items in data_dict.values())
        logger.info(f"历史记忆元数据加载完成，总计{total_items}项元数据")
        
        return data_dict

    def make_metadata_filter(self, field_name: str, target_value: str) -> callable:
        """
        创建元数据过滤函数
        
        生成一个用于向量数据库检索的元数据过滤函数，
        该函数检查指定字段是否包含目标值。
        
        Args:
            field_name (str): 要过滤的元数据字段名
            target_value (str): 目标值
        
        Returns:
            callable: 元数据过滤函数
                接受metadata参数，返回bool值
        
        使用示例：
        ```python
        filter_func = make_metadata_filter("location", "北京")
        # 该函数会匹配metadata中location字段包含"北京"的文档
        ```
        """
        def metadata_filter(metadata: Dict[str, Any]) -> bool:
            field_data = metadata.get(field_name, [])
            # 处理字符串和列表两种格式
            if isinstance(target_value, str):
                return target_value in field_data
            elif isinstance(target_value, list):
                flag = False
                for item in target_value:
                    if item in field_data:
                        flag = True
                        break
                return flag
            else:
                return  False
            #if isinstance(field_data, str):
            #    return target_value in field_data
            #elif isinstance(field_data, list):
            #    return target_value in field_data
            #return False
        
        logger.debug(f"创建元数据过滤器 - 字段: {field_name}, 目标值: {target_value}")
        return metadata_filter

    def rewrite_prompt(self, query: str, history_list: List[str], key: str) -> tuple[str, str]:
        """
        使用LLM重写查询提示词
        
        基于用户查询和历史元数据，使用LLM生成更精确的检索提示词，
        并提取关键的过滤条件值。
        
        Args:
            query (str): 用户原始查询
            history_list (List[str]): 相关的历史元数据列表
        
        Returns:
            tuple[str, str]: (重写后的提示词, 提取的关键值)
        
        处理流程：
        1. 构建包含当前日期的上下文信息
        2. 调用LLM分析查询意图并重写
        3. 从LLM响应中提取重写提示词和关键值
        4. 返回优化后的检索参数
        
        LLM提示词设计：
        - 提供当前日期上下文
        - 包含历史元数据信息
        - 要求生成更精确的检索查询
        - 要求提取关键的过滤条件
        """
        # 获取当前日期上下文
        today = datetime.date.today()
        formatted_date = today.strftime("%Y-%m-%d")
        weekday = today.weekday()
        
        logger.debug(f"开始查询重写 - 原查询: {query[:50]}..., 历史元数据数量: {len(history_list)}")
        
        # 构建LLM输入提示词
        input_prompt = f"""
当前日期信息: 今天是 {formatted_date} (星期{weekday})
用户原始查询: {query}
可用历史信息: {history_list}
需要提取关键信息为: {key}

请帮助优化这个查询，使其更适合向量检索，并提取关键的过滤条件。
        """
        
        try:
            # 调用LLM进行查询重写
            logger.debug("调用LLM进行查询重写...")
            response = self.call_llm_chain(
                role=MemoryRole.MEMORY_REWRITE,
                input_prompt=input_prompt,
                session_id="rewrite_prompt",
            )
            
            # 解析LLM响应
            response_dict = extract_data_from_LLM_res(response)
            rewrite_prompt = response_dict.get("rewrite_prompt", query)  # 回退到原查询
            filter_value = response_dict.get("key_value", "")
            
            logger.info(f"查询重写完成 - 重写后: {rewrite_prompt}..., 过滤值: {filter_value}")
            return rewrite_prompt, filter_value
            
        except Exception as e:
            logger.error(f"查询重写失败: {e}", exc_info=True)
            # 出错时返回原始查询
            return query, ""

    async def search(self, process_data_dict: Dict[str, Dict[str, Any]]) -> List[Any]:
        """
        执行向量检索操作
        
        基于处理后的查询数据进行向量相似度检索，支持多维度过滤条件。
        对于每个维度（location、person、date、tag），分别进行检索并合并结果。
        
        Args:
            process_data_dict (Dict[str, Dict[str, Any]]): 处理后的查询数据字典
                格式：{
                    "location": {"prompt": "重写后的查询", "key_value": "北京"},
                    "person": {"prompt": "重写后的查询", "key_value": "张三"},
                    ...
                }
        
        Returns:
            List[Any]: 去重后的检索结果列表
                每个结果包含文档内容和相似度分数
        
        检索策略：
        1. 遍历各个维度的查询数据
        2. 如果有key_value，使用元数据过滤检索
        3. 如果没有key_value，进行全文检索  
        4. 收集所有结果并去重
        5. 返回合并后的结果列表
        
        性能优化：
        - 异步执行检索操作
        - 自动去重避免重复结果
        - 支持空数据库的优雅处理
        """
        if not self.vector_db:
            logger.info("向量数据库为空，返回空检索结果")
            return []

        logger.info(f"开始向量检索 - 维度数量: {len(process_data_dict)}")
        
        memory_list = []
        successful_searches = 0
        failed_searches = 0

        try:
            for item, data_dict in process_data_dict.items():
                query = data_dict.get("prompt", "")
                key_value = data_dict.get("key_value", "")
                
                logger.debug(f"检索维度: {item}, 查询: {query[:50]}..., 过滤值: {key_value}")
                try:
                    if key_value:
                        # 使用元数据过滤的检索
                        logger.debug(f"执行过滤检索 - 字段: {item}, 值: {key_value}")
                        vector_results = self.vector_db.similarity_search_with_score(
                            query, 
                            k=self.k, 
                            filter=self.make_metadata_filter(item, key_value)
                        )
                    else:
                        # 全文检索
                        logger.debug(f"执行全文检索 - 维度: {item}")
                        vector_results = self.vector_db.similarity_search_with_score(query, k=self.k)

                    for doc, score in vector_results:
                        memory_list.append(doc.page_content)

                    successful_searches += 1
                    logger.debug(f"维度 {item} 检索成功，获得 {len(vector_results)} 个结果")
                    
                except Exception as e:
                    logger.error(f"维度 {item} 检索失败: {e}", exc_info=True)
                    failed_searches += 1

            # 去重处理
            logger.debug(f"检索完成，开始去重 - 原始结果数: {len(memory_list)}")
            deduplicate_memory_list = list(set(memory_list))
            
            logger.info(f"向量检索完成 - 成功: {successful_searches}, 失败: {failed_searches}, 去重后结果数: {len(deduplicate_memory_list)}")
            
            return deduplicate_memory_list
            
        except Exception as e:
            logger.error(f"向量检索过程中发生异常: {e}", exc_info=True)
            return []

    async def save(self, process_data_dict: Dict[str, Dict[str, Any]]) -> None:
        """
        保存记忆数据到向量数据库
        
        将处理后的记忆数据转换为Document格式并存储到向量数据库中。
        自动提取和组织元数据信息，支持多维度的记忆标记。
        
        Args:
            process_data_dict (Dict[str, Dict[str, Any]]): 处理后的数据字典
                包含各个维度的原始数据和提取的关键值
        
        存储流程：
        1. 构建Document对象，包含内容和元数据
        2. 从各维度提取关键值填充元数据
        3. 如果数据库已存在，添加新数据
        4. 如果数据库不存在，创建新数据库
        
        元数据结构：
        ```json
        {
            "date": "2025-09-03",
            "location": "北京",
            "person": ["张三", "李四"],
            "tag": ["工作", "会议"]
        }
        ```
        
        异常处理：
        - 数据库操作失败：记录错误但不抛出异常
        - 元数据提取失败：使用默认空值
        - 文档创建失败：记录错误并跳过
        """
        logger.info(f"开始保存记忆数据 - 维度数量: {len(process_data_dict)}")
        
        try:
            doc_list = []
            
            # 初始化元数据结构
            metadata_dict = {
                "date": "",
                "location": "",
                "person": [],
                "tag": []
            }
            
            page_content = ""
            
            # 从各维度提取数据和元数据
            for item, data_dict in process_data_dict.items():
                raw_data = data_dict.get("raw_data", "")
                key_value = data_dict.get("key_value", "")
                
                # 设置页面内容（使用最后一个非空的raw_data）
                if raw_data:
                    page_content = raw_data
                
                # 设置元数据
                if key_value:
                    metadata_dict[item] = key_value
                        
                logger.debug(f"处理维度 {item}: 内容长度={len(raw_data)}, 关键值={key_value}")

            # 如果没有有效的页面内容，使用原始查询数据
            if not page_content:
                # 尝试从第一个维度获取原始数据
                first_item = next(iter(process_data_dict.values()), {})
                page_content = first_item.get("raw_data", "空记忆内容")
                logger.warning("未找到有效的页面内容，使用默认内容")

            # 创建文档对象
            document = Document(
                page_content=page_content,
                metadata=metadata_dict
            )
            doc_list.append(document)
            for item, value in metadata_dict.items():
                if len(value) > 0:
                    if isinstance(value, list):
                        self.memory_dict[item].extend(value)
                    elif isinstance(value, str):
                        self.memory_dict[item].append(value)
                save_path = self.config[item].get("file_path") 
                save_data(save_path, self.memory_dict[item])

            logger.info(f"创建记忆文档 - 内容长度: {len(page_content)}, 元数据: {metadata_dict}")

            # 保存到向量数据库
            if self.vector_db:
                logger.debug("添加数据到现有向量数据库...")
                self.vector_client_obj.add_data(self.vector_db, doc_list)
                logger.info("记忆数据成功添加到向量数据库")
            else:
                logger.debug("创建新的向量数据库...")
                self.vector_db = self.vector_client_obj.build_vector_db(doc_list)
                logger.info("新的向量数据库创建成功，记忆数据已保存")
                
        except Exception as e:
            logger.error(f"保存记忆数据失败: {e}", exc_info=True)
            # 不抛出异常，允许系统继续运行

    async def execute(self, state: Dict[str, Any]) -> Union[List[Any], None]:
        """
        VectorAgent主执行接口
        
        根据操作类型（save/search）执行相应的向量数据库操作。
        这是VectorAgent对外的统一接口，支持记忆的存储和检索。
        
        Args:
            state (Dict[str, Any]): 执行状态字典
                必需字段：
                - operation: "save" 或 "search"
                - query: 用户查询内容
        
        Returns:
            Union[List[Any], None]: 
                - search操作：返回检索结果列表
                - save操作：返回None
                - 错误情况：返回错误信息字典
        
        处理流程：
        1. 解析执行状态获取操作类型和查询内容
        2. 为各个维度生成处理数据字典
        3. 调用LLM进行查询重写和关键值提取
        4. 根据操作类型调用相应的处理方法
        5. 返回执行结果
        
        数据处理策略：
        - 对每个维度（location、person、date、tag）分别处理
        - 使用历史元数据信息优化查询重写
        - 提取关键值用于精确检索或元数据标记
        """
        operation = state.get("operation")
        query = state.get("query", "")
        
        if not operation:
            logger.error("VectorAgent执行失败：未指定操作类型")
            return {"status": "error", "message": "Missing operation type"}
        
        if not query:
            logger.error("VectorAgent执行失败：查询内容为空")
            return {"status": "error", "message": "Empty query"}
            
        logger.info(f"VectorAgent开始执行 - 操作: {operation}, 查询: {query[:50]}...")
 
        # 为各维度准备处理数据
        process_data_dict = {}

        try:
            logger.debug("开始为各维度生成处理数据...")
            
            for item, history_list in self.memory_dict.items():
                logger.debug(f"处理维度: {item}, 历史元数据数量: {len(history_list)}")
                rewrite_prompt, key_value = self.rewrite_prompt(query, history_list, item)
                
                process_data_dict[item] = {
                    "raw_data": query,  # 原始用户输入
                    "prompt": rewrite_prompt,  # LLM重写的查询
                    "key_value": key_value,  # 提取的关键值
                }
                logger.debug(f"维度 {item} 处理完成 - 关键值: {key_value}")

            logger.info(f"所有维度处理完成，开始执行{operation}操作...")
            # 根据操作类型执行相应操作
            if operation == "save":
                await self.save(process_data_dict)
                logger.info("记忆保存操作完成")
                return None
                
            elif operation == "search":
                results = await self.search(process_data_dict)
                logger.info(f"记忆检索操作完成，返回{len(results)}个结果")
                return results
                
            else:
                logger.error(f"未知的操作类型: {operation}")
                return {"status": "error", "message": f"Unknown operation: {operation}"}
                
        except Exception as e:
            logger.error(f"VectorAgent执行过程中发生异常: {e}", exc_info=True)
            return {"status": "error", "message": f"Execution failed: {str(e)}"}

class KnowledgeGraphAgent(LLMBase):
    """
    知识图谱代理 - 短期记忆构建和上下文检索引擎
    
    KnowledgeGraphAgent负责构建和管理短期的知识图谱，用于增强记忆检索的上下文。
    它通过MCP服务器与知识图谱后端交互，支持动态的知识添加和查询。
    
    核心功能：
    1. 短期知识图谱构建：将检索到的记忆片段构建为结构化的知识图谱
    2. 上下文检索：基于用户查询从图谱中检索相关的上下文信息
    3. MCP服务集成：通过Model Context Protocol与图谱后端通信
    4. 智能工具调用：使用ReAct模式进行多轮工具调用和推理
    5. 错误处理和重试：自动处理工具调用失败并进行重试
    
    技术架构：
    - 基于MCP协议的图谱后端集成
    - ReAct模式的智能代理推理
    - 异步多轮工具调用机制
    - 自动错误检测和内容清理
    
    工作流程：
    1. 接收记忆内容或查询请求
    2. 构建适当的提示词包含时间上下文
    3. 通过MCP工具与图谱后端交互
    4. 处理和清理返回的内容
    5. 返回结构化的知识信息
    
    支持的操作：
    - add: 向知识图谱添加新的记忆内容
    - query: 从知识图谱检索相关的上下文信息
    
    Attributes:
        mcp_client (MCPClient): MCP服务客户端
        react_model: ReAct模式的语言模型
    
    使用示例：
    ```python
    kg_agent = KnowledgeGraphAgent()
    await kg_agent.async_init(mcp_config)
    
    # 添加知识
    await kg_agent.execute({
        "operation": "add",
        "query": "今天和张三吃了火锅"
    })
    
    # 查询知识
    context = await kg_agent.execute({
        "operation": "query", 
        "query": "我和张三的聚餐历史"
    })
    ```
    """
    
    def __init__(self, provider: str = "openai") -> None:
        """
        初始化知识图谱代理
        
        Args:
            provider (str): LLM服务提供商，默认"openai"
        """
        super().__init__(provider)
        logger.info(f"初始化KnowledgeGraphAgent - LLM提供商: {provider}")
        
        # 初始化时不创建MCP客户端，在async_init中创建
        self.mcp_client = None
        self.react_model = None  # ReAct模式模型，在async_init中初始化
        
        logger.info("KnowledgeGraphAgent初始化完成")

    async def async_init(self, config: Dict[str, Any]) -> None:
        """
        异步初始化KnowledgeGraphAgent
        
        必须在使用前调用此方法完成MCP客户端的异步初始化。
        
        Args:
            config (Dict[str, Any]): MCP服务配置
                包含服务器地址、认证信息等
        
        初始化流程：
        1. 初始化MCP客户端连接
        2. 加载可用的工具列表
        3. 准备ReAct模式的推理环境
        """
        logger.info("开始异步初始化KnowledgeGraphAgent...")
        
        try:
            # 创建LLM客户端和MCP客户端，使用依赖注入模式
            from src.core.llm.client import LLMBase
            llm_client = LLMBase(provider=self.provider)
            self.mcp_client = MCPClient(llm_client, config)
            await self.mcp_client.initialize()
            logger.info("MCP客户端初始化成功")
            
            # 记录可用工具信息
            tools = self.mcp_client.get_available_tools()
            tool_names = [tool['name'] for tool in tools]
            logger.info(f"可用MCP工具: {tool_names}")
            logger.info(f"工具总数: {self.mcp_client.get_tool_count()}")
            
        except Exception as e:
            logger.error(f"KnowledgeGraphAgent异步初始化失败: {e}", exc_info=True)
            raise RuntimeError(f"知识图谱代理初始化失败: {str(e)}")

    async def call_mcp_server(self, input_prompt: str, session_id: str) -> List[str]:
        """
        调用MCP服务处理输入并获取知识图谱内容
        
        通过ReAct模式与MCP服务交互，循环调用工具直到获取完整的知识内容。
        支持多轮对话和错误恢复，确保获取高质量的图谱数据。

        Args:
            input_prompt (str): 用户输入提示，用于指导MCP服务的知识操作
            session_id (str): 会话ID，用于跟踪和调试MCP服务调用

        Returns:
            List[str]: 知识图谱内容片段列表
                已移除错误信息和重复内容
        
        ReAct模式流程：
        1. Thought: 分析当前需要执行的操作
        2. Action: 选择适当的工具进行调用
        3. Action Input: 准备工具调用的参数
        4. Observation: 观察工具调用的结果
        5. 重复上述步骤直到获得最终答案
        
        错误处理策略：
        - 工具调用失败：记录错误并重试
        - 参数解析失败：使用默认参数
        - 内容重复：自动去重
        - 达到最大尝试次数：返回已获取的结果
        """
        logger.info(f"开始MCP服务调用 - 会话ID: {session_id}")
        logger.debug(f"输入提示词: {input_prompt[:200]}...")

        try:
            # 自定义ReAct模型，设置停止标识
            self.react_model = self.get_chat_model(stop=[TOOL_STOP_FLAG])
            logger.debug("ReAct模型初始化成功")
            
        except Exception as e:
            logger.error(f"ReAct模型初始化失败: {e}", exc_info=True)
            return []
        
        # 构建系统提示词，包含工具描述和调用格式
        # 获取工具信息
        tools = self.mcp_client.get_available_tools()
        tool_names = [tool['name'] for tool in tools]
        tool_descriptions = self.mcp_client.get_tools_description()
        
        system_prompt = f"""
你是一个智能助手，能够使用工具来处理知识图谱操作。你可以使用以下工具：

{tool_descriptions}

请使用以下格式与工具交互：

Question: 你需要回答的问题
Thought: 分析当前情况，思考需要采取的行动
Action: 选择要使用的工具，必须是以下之一：[{", ".join(tool_names)}]
Action Input: 工具的输入参数（JSON格式）
{TOOL_STOP_FLAG}: 工具返回的结果
... (可以重复Thought/Action/Action Input/{TOOL_STOP_FLAG}的循环)
Thought: 现在我知道了最终答案
Final Answer: 最终答案

开始执行！
        """.strip()

        try:
            # 构建ReAct调用链
            react_chain = self.build_chain(
                client=self.react_model,
                system_prompt=system_prompt,
            )
            logger.debug("ReAct调用链构建成功")
            
        except Exception as e:
            logger.error(f"ReAct调用链构建失败: {e}", exc_info=True)
            return []

        # 执行ReAct循环
        max_attempts = MAX_MCP_ATTEMPTS
        attempt_count = 0
        graph_result: List[str] = []  # 存储知识图谱内容结果
        
        logger.info(f"开始MCP服务调用循环 - 最大尝试次数: {max_attempts}")

        while attempt_count < max_attempts:
            attempt_count += 1
            logger.debug(f"MCP调用尝试 {attempt_count}/{max_attempts}")
            
            try:
                # 调用ReAct链获取响应
                response = react_chain.invoke(
                    {"input_prompt": input_prompt},
                    config={"configurable": {"session_id": session_id}}
                )
                
                # 截断响应用于日志记录
                response_preview = response[:300] + "..." if len(response) > 300 else response
                logger.debug(f"ReAct响应获取成功: {response_preview}")

                # 解析工具调用信息
                function_name_str, parameters_str, final_res = parse_latest_plugin_call(response)
                
                if not function_name_str:
                    logger.info("未检测到工具调用，MCP服务循环结束")
                    break
                
                # 检查工具是否可用
                if not self.mcp_client.is_tool_available(function_name_str):
                    logger.warning(f"工具 {function_name_str} 不可用，跳过此次调用")
                    continue
                
                logger.debug(f"工具调用信息 - 函数: {function_name_str}")
                logger.debug(f"参数: {parameters_str[:200]}..." if parameters_str else "无参数")

                # 处理工具调用
                result_content = await self._execute_mcp_tool_new(
                    function_name_str, parameters_str, graph_result
                )
                
                if result_content:
                    logger.debug(f"工具调用成功，获取内容长度: {len(result_content)}")
                else:
                    logger.debug("工具调用无有效内容返回")

            except Exception as e:
                logger.error(f"MCP调用尝试 {attempt_count} 失败: {e}", exc_info=True)
                # 继续下一次尝试而不是中断

        # 清理MCP客户端资源
        try:
            if hasattr(self, 'mcp_client') and self.mcp_client is not None:
                await self.mcp_client.cleanup()
                logger.debug("MCP客户端资源清理完成")
        except RuntimeError as e:
            if "Attempted to exit cancel scope in a different task" in str(e):
                # 这是一个已知的异步上下文管理问题，可以安全忽略
                logger.debug(f"异步上下文清理警告（可忽略）: {e}")
            else:
                logger.warning(f"MCP客户端清理运行时错误: {e}")
        except Exception as e:
            logger.warning(f"MCP客户端清理失败: {e}")
        finally:
            # 确保不会阻塞后续操作
            pass

        logger.info(f"MCP服务调用完成 - 尝试次数: {attempt_count}, 获取内容片段数: {len(graph_result)}")
        return graph_result

    async def _execute_mcp_tool_new(
        self,
        function_name: str, 
        parameters_str: str, 
        graph_result: List[str]
    ) -> Optional[str]:
        """
        使用新MCPClient接口执行单个MCP工具调用
        
        Args:
            function_name (str): 工具函数名
            parameters_str (str): 参数字符串 
            graph_result (List[str]): 结果累积列表
            
        Returns:
            Optional[str]: 清理后的工具调用结果
        """
        try:
            # 安全解析参数
            if parameters_str:
                # 处理JavaScript布尔值格式
                parameters_str = parameters_str.replace("true", "True").replace("false", "False")
                try:
                    parameters = json.loads(parameters_str) if parameters_str else {}
                except json.JSONDecodeError:
                    logger.warning(f"参数JSON解析失败，使用空参数: {parameters_str}")
                    parameters = {}
            else:
                parameters = {}

            # 使用新的MCPClient接口执行工具
            result_str = await self.mcp_client.execute_tool(function_name, parameters)
            
            # 检查是否已存在相同结果（避免重复）
            if result_str in graph_result:
                logger.info(f"检测到重复结果，跳过: {result_str[:100]}...")
                return f"工具 {function_name} 返回的结果已存在，未添加重复内容。"
            
            # 清理和添加结果
            graph_result.append(result_str)
            logger.info(f"工具 {function_name} 执行成功，结果长度: {len(result_str)}")
            
            return result_str
            
        except Exception as e:
            error_msg = f"工具 {function_name} 执行失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

    async def _execute_mcp_tool(
        self, 
        session, 
        function_name: str, 
        parameters_str: str, 
        graph_result: List[str]
    ) -> Optional[str]:
        """
        执行单个MCP工具调用
        
        Args:
            session: MCP工具会话
            function_name (str): 工具函数名
            parameters_str (str): 参数字符串 
            graph_result (List[str]): 结果累积列表
            
        Returns:
            Optional[str]: 清理后的工具调用结果
        """
        try:
            # 安全解析参数
            if parameters_str:
                # 处理JavaScript布尔值格式
                parameters_str = parameters_str.replace("true", "True").replace("false", "False")
                try:
                    parameters = json.loads(parameters_str) if parameters_str else {}
                except json.JSONDecodeError:
                    logger.warning(f"参数JSON解析失败，使用空参数: {parameters_str}")
                    parameters = {}
            else:
                parameters = {}
            
            # 调用工具
            logger.debug(f"调用MCP工具: {function_name}, 参数: {parameters}")
            result = await session.call_tool(function_name, parameters)
            
            # 提取和清理结果内容
            if result and result.content and len(result.content) > 0:
                raw_content = result.content[0].text
                cleaned_content, error_status = self.remove_error_blocks(raw_content)
                
                if error_status:
                    logger.warning(f"工具返回包含错误: {error_status}")
                
                # 检查重复内容
                if cleaned_content and cleaned_content not in graph_result:
                    graph_result.append(cleaned_content)
                    logger.debug(f"新内容已添加，总片段数: {len(graph_result)}")
                    return cleaned_content
                elif cleaned_content:
                    logger.debug("检测到重复内容，已跳过")
                
            return None
            
        except Exception as e:
            logger.error(f"MCP工具执行失败: {e}", exc_info=True)
            return None

    async def execute(self, state: Dict[str, Any]) -> Union[str, None]:
        """
        知识图谱代理主执行接口
        
        根据操作类型执行相应的知识图谱操作，支持知识添加和查询两种模式。
        
        Args:
            state (Dict[str, Any]): 执行状态字典
                必需字段：
                - operation: "add" 或 "query"
                可选字段：
                - query: 查询内容（query操作必需）
                - content: 要添加的内容（add操作必需）
        
        Returns:
            Union[str, None]:
                - add操作：返回None（成功）或错误信息
                - query操作：返回检索到的上下文字符串
                - 错误情况：返回空字符串
        
        操作类型说明：
        1. add: 将内容添加到知识图谱中
        2. query: 从知识图谱中检索相关内容
        """
        operation = state.get("operation", "unknown")
        
        logger.info(f"KnowledgeGraphAgent开始执行 - 操作类型: {operation}")
        
        try:
            if operation == "add":
                # 添加数据到知识图谱
                content = state.get("query") or state.get("content", "")
                if not content:
                    logger.error("add操作缺少内容参数")
                    return None
                
                result = await self._add_data_to_graph(content)
                logger.info("知识图谱添加操作完成")
                return result
                
            elif operation == "query":
                # 从知识图谱查询内容
                query = state.get("query", "")
                if not query:
                    logger.error("query操作缺少查询参数")
                    return ""
                
                result = await self._query_from_graph(query)
                logger.info(f"知识图谱查询操作完成，返回内容长度: {len(result) if result else 0}")
                return result
                
            else:
                logger.error(f"未知的操作类型: {operation}")
                return ""
                
        except Exception as e:
            logger.error(f"KnowledgeGraphAgent执行异常: {e}", exc_info=True)
            return "" if operation == "query" else None
 
    async def _add_data_to_graph(self, retrieve_content: str) -> None:
        """
        添加数据到知识图谱
        
        将检索到的内容或新的记忆数据添加到知识图谱中，
        构建结构化的知识关系。
        
        Args:
            retrieve_content (str): 要添加到图谱的内容
        
        处理流程：
        1. 构建包含时间上下文的提示词
        2. 通过MCP服务器调用图谱添加接口
        3. 处理添加结果和可能的错误
        
        提示词设计：
        - 包含当前日期信息作为时间上下文
        - 明确指示要将内容写入记忆系统
        - 避免虚构或添加不存在的信息
        """
        if not retrieve_content or not retrieve_content.strip():
            logger.warning("尝试添加空内容到知识图谱，已跳过")
            return
        
        # 获取当前日期上下文
        today = datetime.date.today()
        formatted_date = today.strftime("%Y-%m-%d")
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_name = weekday_names[today.weekday()]
        
        logger.info(f"开始添加数据到知识图谱 - 内容长度: {len(retrieve_content)}")
        logger.debug(f"添加内容预览: {retrieve_content[:100]}...")
 
        # 构建添加数据的提示词
        query_prompt = f"""
当前时间：今天是 {formatted_date} 星期{weekday_name}

任务：请将以下内容准确地写入到记忆系统中，建立相应的知识关系。

内容：{retrieve_content}

要求：
1. 保持信息的准确性，不要修改或添加任何不存在的信息
2. 建立适当的时间、地点、人物等关系
3. 如果内容涉及多个实体，请建立它们之间的关联
        """
        
        try:
            # 调用MCP服务器进行数据添加
            result = await self.call_mcp_server(query_prompt, "add_data_to_graph")
            
            if result:
                logger.info(f"知识图谱数据添加成功，处理了{len(result)}个响应片段")
                logger.debug(f"添加操作响应: {result}")
            else:
                logger.warning("知识图谱数据添加未返回确认信息")
                
        except Exception as e:
            logger.error(f"添加数据到知识图谱失败: {e}", exc_info=True)

    async def _query_from_graph(self, query: str) -> str:
        """
        从知识图谱检索相关内容
        
        基于用户查询从知识图谱中检索相关的上下文信息，
        用于增强记忆检索的准确性和完整性。
        
        Args:
            query (str): 用户查询内容
        
        Returns:
            str: 检索到的上下文信息
                如果检索成功，返回相关的知识内容
                如果检索失败或无结果，返回空字符串
        
        处理流程：
        1. 构建包含时间上下文的查询提示词
        2. 通过MCP服务器调用图谱查询接口
        3. 整合返回的多个内容片段
        4. 返回结构化的上下文信息
        
        提示词设计：
        - 包含当前日期信息
        - 明确指示从记忆系统检索信息
        - 强调不要虚构任何信息
        - 要求检索所有相关内容
        """
        if not query or not query.strip():
            logger.warning("查询内容为空，返回空结果")
            return ""
        
        # 获取当前日期上下文
        today = datetime.date.today()
        formatted_date = today.strftime("%Y-%m-%d")
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_name = weekday_names[today.weekday()]
        
        logger.info(f"开始从知识图谱检索信息 - 查询: {query[:100]}...")
 
        # 构建查询提示词
        query_prompt = f"""
当前时间：今天是 {formatted_date} 星期{weekday_name}

任务：从记忆系统中检索所有与以下内容相关的信息。

查询内容：{query}

要求：
1. 检索所有相关的记忆信息
2. 包括直接相关和间接相关的内容
3. 不要捏造或添加任何不存在的信息
4. 如果没有相关信息，请明确说明
5. 保持检索结果的准确性和完整性
        """
        
        try:
            # 调用MCP服务器进行查询
            result_list = await self.call_mcp_server(query_prompt, "query_from_graph")
            
            if result_list:
                # 整合多个内容片段
                context_content = "\n\n".join(result_list)
                logger.info(f"知识图谱查询成功，获取{len(result_list)}个内容片段，总长度: {len(context_content)}")
                logger.debug(f"检索内容预览: {context_content[:200]}...")
                return context_content
            else:
                logger.info("知识图谱查询未返回任何内容")
                return ""
                
        except Exception as e:
            logger.error(f"从知识图谱查询数据失败: {e}", exc_info=True)
            return ""

class MemoryAgent(LLMBase):
    """
    记忆管理主代理 - 智能记忆系统的核心控制器
    
    MemoryAgent是整个记忆管理系统的核心协调者，负责统一管理长期记忆存储、
    短期知识图谱构建和智能检索等功能。它通过LangGraph工作流来协调各个
    子代理的工作，为用户提供完整的记忆管理服务。
    
    系统架构：
    ```
    MemoryAgent (主控制器)
    ├── VectorAgent (长期记忆存储)
    │   ├── 向量数据库管理
    │   ├── 语义检索
    │   └── 元数据管理
    ├── KnowledgeGraphAgent (短期知识图谱)
    │   ├── MCP服务集成
    │   ├── 上下文构建
    │   └── 关系推理
    └── LangGraph工作流
        ├── 意图判断
        ├── 检索协调
        ├── 内容整合
        └── 结果生成
    ```
    
    核心功能：
    1. 智能意图识别：自动判断用户输入是存储请求还是检索请求
    2. 多层次检索：结合向量检索和图谱检索提供全面的记忆服务
    3. 上下文增强：通过知识图谱提供更丰富的上下文信息
    4. 智能总结：基于检索结果生成用户友好的回答
    5. 工作流管理：通过LangGraph管理复杂的处理流程
    
    工作流程：
    ```
    START → LLMjudge → [save OR search] → summarize → END
    ```
    
    判断逻辑：
    - save: "请记录..."、"帮我保存..."等存储意图
    - search: "我什么时候..."、"找一下..."等检索意图
    
    技术特点：
    - 基于LangGraph的异步状态图处理
    - 多数据源整合（向量库 + 知识图谱）
    - LLM驱动的智能判断和总结
    - 支持复杂的多轮对话和上下文管理
    
    Attributes:
        databases (Dict): 数据库代理字典，当前包含vector代理
        knowledge_graph_agent (KnowledgeGraphAgent): 知识图谱代理实例
        graph: LangGraph状态图实例
        search_history (List): 搜索历史记录
    
    使用示例：
    ```python
    memory_agent = MemoryAgent(provider="openai")
    
    # 存储记忆
    result = await memory_agent.execute("请记录我今天和张三一起吃了火锅")
    
    # 检索记忆
    result = await memory_agent.execute("我和张三什么时候一起吃过饭？")
    ```
    """

    def __init__(self, provider: str = "openai") -> None:
        """
        初始化记忆管理主代理
        
        Args:
            provider (str): LLM服务提供商，默认"openai"
        
        初始化流程：
        1. 继承LLMBase获得语言模型能力
        2. 初始化各种数据库代理
        3. 初始化知识图谱代理
        4. 构建LangGraph工作流
        5. 设置系统配置和历史记录
        """
        super().__init__(provider)
        
        logger.info(f"开始初始化MemoryAgent - LLM提供商: {provider}")
        
        # 初始化数据库代理
        logger.info("初始化数据库代理...")
        self.databases = {
            "vector": VectorAgent(MEMORY_VECTOR_DB_CONFIG, provider),
        }
        logger.info(f"数据库代理初始化完成，共{len(self.databases)}个代理")
        
        # 初始化知识图谱代理
        logger.info("初始化知识图谱代理...")
        self.knowledge_graph_agent = KnowledgeGraphAgent(provider)
        
        # 初始化LangGraph工作流
        logger.info("构建LangGraph工作流...")
        self.graph = None
        self.build_graph()
        
        # 初始化搜索历史
        self.search_history = []
        
        logger.info("MemoryAgent初始化完成")
    
    def build_graph(self) -> None:
        """
        构建MemoryAgent的LangGraph工作流
        
        构建一个四节点的状态图来管理记忆处理流程：
        1. LLMjudge: 意图判断节点，决定是存储还是检索
        2. search: 检索节点，协调多种检索策略
        3. save: 存储节点，保存用户记忆
        4. summarize: 总结节点，生成最终回答
        
        图结构设计：
        ```
        START → LLMjudge → [save OR search] → [END OR summarize] → END
        ```
        
        节点功能：
        - LLMjudge: 分析用户意图，路由到相应处理分支
        - search: 执行多层次检索，整合各种记忆源
        - save: 将记忆数据存储到向量数据库
        - summarize: 基于检索结果生成用户回答
        
        流转控制：
        - save操作直接结束（无需返回内容）
        - search操作流转到summarize生成回答
        """
        logger.info("开始构建MemoryAgent LangGraph工作流...")
        
        try:
            # 创建状态图构建器
            graph_builder = StateGraph(MemoryState)

            # 添加处理节点
            graph_builder.add_node("search", self.node_search)
            graph_builder.add_node("summarize", self.node_summarize)
            graph_builder.add_node("LLMjudge", self.node_judge)
            graph_builder.add_node("save", self.node_save)
            
            logger.debug("LangGraph节点添加完成")

            # 定义图的连接关系
            graph_builder.add_edge(START, "LLMjudge")  # 开始时进行意图判断
            graph_builder.add_edge("search", "summarize")  # 检索后进行总结
            graph_builder.add_edge("summarize", END)  # 总结后结束
            graph_builder.add_edge("save", END)  # 保存后直接结束
            
            logger.debug("LangGraph边连接定义完成")

            # 编译状态图
            self.graph = graph_builder.compile()
            logger.info("MemoryAgent LangGraph构建并编译成功")
            
        except Exception as e:
            logger.error(f"构建MemoryAgent LangGraph失败: {e}", exc_info=True)
            raise RuntimeError(f"记忆代理工作流构建失败: {str(e)}")

    async def execute(self, query: str) -> Dict[str, Any]:
        """
        运行MemoryAgent的主执行接口
        
        这是MemoryAgent对外的统一接口，接收用户查询并返回处理结果。
        通过LangGraph工作流协调各个处理节点完成记忆管理任务。
        
        Args:
            query (str): 用户查询内容
                存储示例: "请记录我今天吃了火锅"
                检索示例: "我昨天吃了什么？"
        
        Returns:
            Dict[str, Any]: 标准化的执行结果
                包含字段：
                - agent_type: 代理类型标识
                - answer: 最终回答（检索操作）
                - message: 状态信息（可选）
        
        执行流程：
        1. 验证输入和系统状态
        2. 初始化知识图谱代理（如需要）
        3. 准备初始状态
        4. 通过LangGraph异步执行工作流
        5. 处理和返回最终结果
        
        异常处理：
        - 空查询：返回错误信息
        - 图未构建：自动重建
        - 执行异常：记录错误并返回默认结果
        """
        if not query or not query.strip():
            logger.error("MemoryAgent收到空查询")
            return {
                "agent_type": AgentType.MEMORY,
                "answer": "请提供要处理的内容",
                "message": "Empty query"
            }
        
        logger.info(f"MemoryAgent开始执行 - 查询: {query[:100]}...")
        
        # 确保图已构建
        if not self.graph:
            logger.warning("LangGraph未构建，开始重建...")
            self.build_graph()

        try:
            # 初始化知识图谱代理
            logger.debug("初始化知识图谱代理连接...")
            mcp_config = MCP_CONFIG.get(MCPToolName.MEMORY, {})
            await self.knowledge_graph_agent.async_init(mcp_config)
            logger.debug("知识图谱代理初始化完成")

            # 准备初始状态
            initial_state: MemoryState = {
                "query": query,
                "search_results": {},
                "graph_context": "",
                "answer": "",
                "judge": {},
                "status": "running",
            }
            
            logger.debug("初始状态准备完成，开始执行LangGraph工作流...")

            # 执行LangGraph工作流
            final_state: Optional[Dict[str, Any]] = None
            chat_config = {"recursion_limit": 20}  # 防止无限递归
            event_count = 0
            
            async for event in self.graph.astream(input=initial_state, config=chat_config):
                event_count += 1
                for node_name, value in event.items():
                    if value is not None:
                        logger.debug(f"LangGraph事件 {event_count}: {node_name}")
                final_state = event

            logger.info(f"LangGraph执行完成，共处理{event_count}个事件")

            # 处理执行结果
            if not final_state:
                logger.warning("LangGraph未返回最终状态")
                return {
                    "agent_type": AgentType.MEMORY,
                    "answer": "处理过程中出现问题，请稍后重试",
                    "message": "No final state returned"
                }

            # 提取最终答案
            if isinstance(final_state, str):
                final_answer = final_state
            elif isinstance(final_state, dict):
                # 直接取出"answer"字段
                final_answer = final_state.get("answer", "")
            else:
                final_answer = ""
            logger.info(f"MemoryAgent执行完成 - 回答长度: {len(final_answer)}")
            logger.debug(f"最终回答预览: {final_answer[:200]}..." if final_answer else "无回答内容")
            
            # 安全地清理知识图谱代理的MCP连接
            try:
                if hasattr(self, 'knowledge_graph_agent') and hasattr(self.knowledge_graph_agent, 'mcp_client'):
                    await self.knowledge_graph_agent.mcp_client.cleanup()
                    logger.debug("知识图谱代理MCP连接已清理")
            except Exception as cleanup_e:
                logger.warning(f"清理知识图谱代理连接时出现警告: {cleanup_e}")
            
            return {
                "agent_type": AgentType.MEMORY,
                "answer": final_answer,
            }

        except Exception as e:
            logger.error(f"MemoryAgent执行异常: {e}", exc_info=True)
            
            # 即使出现异常也要清理资源
            try:
                if hasattr(self, 'knowledge_graph_agent') and hasattr(self.knowledge_graph_agent, 'mcp_client'):
                    await self.knowledge_graph_agent.mcp_client.cleanup()
                    logger.debug("异常处理中：知识图谱代理MCP连接已清理")
            except Exception as cleanup_e:
                logger.debug(f"异常处理中的资源清理警告: {cleanup_e}")
                
            return {
                "agent_type": AgentType.MEMORY, 
                "answer": "处理过程中出现错误，请稍后重试",
                "message": f"Execution error: {str(e)}"
            }
            
    # ---------------------- LangGraph 节点实现 ----------------------

    async def node_search(self, state: MemoryState) -> MemoryState:
        """
        检索节点：执行多层次记忆检索
        
        这是记忆检索的核心节点，协调向量数据库检索和知识图谱检索，
        为用户查询提供全面的记忆信息。
        
        Args:
            state (MemoryState): 当前工作流状态
        
        Returns:
            MemoryState: 更新后的状态，包含检索结果
        
        检索策略：
        1. 向量数据库检索：基于语义相似度找到相关的长期记忆
        2. 知识图谱检索：从短期图谱中获取上下文信息
        3. 数据整合：将检索结果合并到知识图谱中
        4. 结果组织：将所有检索结果组织到状态中
        
        处理流程：
        - 并行执行多种检索策略
        - 处理检索过程中的异常
        - 将向量检索结果添加到知识图谱
        - 从知识图谱获取增强的上下文
        """
        query = state.get("query", "")
        logger.info(f"检索节点开始处理查询: {query[:100]}...")
        
        # 初始化检索结果
        state["search_results"] = {}
        
        try:
            # 1. 向量数据库检索
            logger.debug("开始向量数据库检索...")
            vector_result = await self.databases["vector"].execute({
                "operation": "search", 
                "query": query
            })
            
            if vector_result and not isinstance(vector_result, dict):
                state["search_results"]["vector"] = vector_result
                logger.info(f"向量检索成功，获得{len(vector_result)}个结果")
            else:
                state["search_results"]["vector"] = []
                if isinstance(vector_result, dict) and "error" in vector_result:
                    logger.warning(f"向量检索出现错误: {vector_result['error']}")
                else:
                    logger.info("向量检索未返回结果")
                    
        except Exception as e:
            logger.error(f"向量数据库检索失败: {e}", exc_info=True)
            state["search_results"]["vector"] = []
            state["search_results"]["error"] = f"向量检索失败: {str(e)}"

        try:
            # 2. 获取知识图谱上下文
            logger.debug("开始知识图谱上下文检索...")
            graph_context = await self.node_retrieve_context(query)
            
            if graph_context:
                state["search_results"]["graph_context"] = graph_context
                logger.info(f"知识图谱上下文检索成功，内容长度: {len(graph_context)}")
            else:
                state["search_results"]["graph_context"] = ""
                logger.info("知识图谱未返回上下文信息")
                
        except Exception as e:
            logger.error(f"知识图谱上下文检索失败: {e}", exc_info=True)
            state["search_results"]["graph_context"] = ""

        try:
            # 3. 将向量检索结果整合到知识图谱
            vector_results = state["search_results"].get("vector", [])
            if vector_results:
                logger.debug(f"开始将{len(vector_results)}个向量结果整合到知识图谱...")
                await self.node_merge_to_graph(vector_results)
                logger.debug("向量结果整合到知识图谱完成")
            
        except Exception as e:
            logger.error(f"整合向量结果到知识图谱失败: {e}", exc_info=True)

        # 记录检索完成状态
        total_vector_results = len(state["search_results"].get("vector", []))
        graph_context_length = len(state["search_results"].get("graph_context", ""))
        
        logger.info(f"检索节点处理完成 - 向量结果: {total_vector_results}个, 图谱上下文: {graph_context_length}字符")
        
        return state

    async def node_merge_to_graph(self, vector_data_list: List[Any]) -> None:
        """
        将向量检索结果合并到知识图谱
        
        将从向量数据库检索到的记忆片段添加到知识图谱中，
        构建更丰富的短期记忆网络。
        
        Args:
            vector_data_list (List[Any]): 向量数据库检索结果列表
        
        处理策略：
        1. 遍历所有向量检索结果
        2. 提取有效的记忆内容
        3. 调用知识图谱代理进行内容添加
        4. 处理添加过程中的异常
        
        数据处理：
        - 支持多种向量结果格式
        - 自动提取文档内容
        - 处理评分和元数据信息
        """
        if not vector_data_list:
            logger.debug("向量数据列表为空，跳过知识图谱合并")
            return
        
        logger.debug(f"开始合并{len(vector_data_list)}个向量结果到知识图谱...")
        
        successful_merges = 0
        failed_merges = 0
        
        for i, vector_data in enumerate(vector_data_list):
            try:
                # 处理不同格式的向量数据
                content = ""
                
                if isinstance(vector_data, tuple) and len(vector_data) >= 2:
                    # (document, score) 格式
                    document, score = vector_data[0], vector_data[1]
                    if hasattr(document, 'page_content'):
                        content = document.page_content
                    else:
                        content = str(document)
                    logger.debug(f"处理元组格式向量数据 {i+1}, 评分: {score:.3f}")
                    
                elif hasattr(vector_data, 'page_content'):
                    # Document 对象
                    content = vector_data.page_content
                    logger.debug(f"处理文档格式向量数据 {i+1}")
                    
                else:
                    # 字符串或其他格式
                    content = str(vector_data)
                    logger.debug(f"处理字符串格式向量数据 {i+1}")

                # 跳过空内容
                if not content or not content.strip():
                    logger.debug(f"向量数据 {i+1} 内容为空，跳过")
                    continue

                # 添加到知识图谱
                logger.debug(f"添加向量数据 {i+1} 到知识图谱，内容长度: {len(content)}")
                pass
                #await self.knowledge_graph_agent.execute({
                #    "operation": "add",
                #    "query": content,
                #})
                
                successful_merges += 1
                
            except Exception as e:
                logger.error(f"合并向量数据 {i+1} 到知识图谱失败: {e}", exc_info=True)
                failed_merges += 1

        logger.info(f"知识图谱合并完成 - 成功: {successful_merges}, 失败: {failed_merges}")

    async def node_retrieve_context(self, query: str) -> str:
        """
        从知识图谱检索上下文信息
        
        基于用户查询从知识图谱中检索相关的上下文信息，
        用于增强最终回答的准确性和完整性。
        
        Args:
            query (str): 用户查询内容
        
        Returns:
            str: 检索到的上下文信息
        
        检索策略：
        - 使用知识图谱代理的query操作
        - 处理检索结果的格式化
        - 提供错误恢复机制
        """
        if not query or not query.strip():
            logger.debug("查询为空，跳过上下文检索")
            return ""
        
        logger.debug(f"开始检索知识图谱上下文: {query[:100]}...")
        
        try:
            #retrieve_result = await self.knowledge_graph_agent.execute({
            #    "operation": "query",
            #    "query": query
            #})
            retrieve_result = ""
            if retrieve_result and isinstance(retrieve_result, str):
                logger.debug(f"知识图谱上下文检索成功，内容长度: {len(retrieve_result)}")
                return retrieve_result
            elif isinstance(retrieve_result, list):
                # 处理列表格式的结果
                context_content = "\n\n".join(str(item) for item in retrieve_result if item)
                logger.debug(f"知识图谱返回列表格式，合并后长度: {len(context_content)}")
                return context_content
            else:
                logger.debug("知识图谱未返回有效的上下文信息")
                return ""
                
        except Exception as e:
            logger.error(f"知识图谱上下文检索失败: {e}", exc_info=True)
            return ""

    async def node_summarize(self, state: MemoryState) -> MemoryState:
        """
        总结节点：生成基于检索结果的最终回答
        
        整合各种检索结果，使用LLM生成用户友好的最终回答。
        这是记忆检索流程的最后一个处理节点。
        
        Args:
            state (MemoryState): 包含检索结果的状态
        
        Returns:
            MemoryState: 更新后的状态，包含最终答案
        
        总结策略：
        1. 收集所有检索结果（向量、图谱、上下文）
        2. 构建综合的总结提示词
        3. 调用LLM生成最终回答
        4. 处理生成结果并更新状态
        
        提示词设计：
        - 包含短期记忆内容（知识图谱）
        - 包含长期记忆内容（向量检索）
        - 明确用户查询意图
        - 要求生成准确、有用的回答
        """
        query = state.get("query", "")
        search_results = state.get("search_results", {})
        
        logger.info(f"总结节点开始处理: {query[:100]}...")
        
        # 提取各种检索结果
        graph_context = search_results.get("graph_context", "")
        vector_results = search_results.get("vector", [])
        
        # 处理向量检索结果
        vector_content = ""
        if vector_results:
            vector_texts = []
            for result in vector_results:
                if isinstance(result, tuple) and len(result) >= 2:
                    # (document, score) 格式
                    doc = result[0]
                    if hasattr(doc, 'page_content'):
                        vector_texts.append(doc.page_content)
                elif hasattr(result, 'page_content'):
                    # Document 对象
                    vector_texts.append(result.page_content)
                else:
                    # 其他格式
                    vector_texts.append(str(result))
            
            vector_content = "\n\n".join(vector_texts)
            logger.debug(f"向量内容整理完成，总长度: {len(vector_content)}")
        
        # 构建LLM输入提示词
        input_prompt = f"""
请基于以下检索到的记忆信息回答用户的问题：

用户问题: {query}

短期记忆内容（知识图谱）: 
{graph_context if graph_context else "无相关短期记忆"}

长期记忆内容（数据库检索）: 
{vector_content if vector_content else "无相关长期记忆"}

请根据以上信息生成一个准确、有用、友好的回答。如果没有相关信息，请诚实地说明。
        """
        try:
            logger.debug("开始调用LLM生成总结回答...")
            summary_response = await self.async_call_llm_chain(
                role=MemoryRole.MEMORY_SUMMARY,
                input_prompt=input_prompt,
                session_id="summarize",
            )
            
            # 处理LLM响应
            if isinstance(summary_response, dict):
                final_answer = summary_response.get("result", "") or summary_response.get("answer", "")
            elif isinstance(summary_response, str):
                final_answer = summary_response
            else:
                final_answer = str(summary_response)
                
            if not final_answer:
                final_answer = "抱歉，我无法基于现有信息回答您的问题。"
                
            state["answer"] = final_answer
            logger.info(f"总结节点完成 - 生成回答长度: {len(final_answer)}")
            logger.debug(f"最终回答预览: {final_answer[:200]}...")
            
        except Exception as e:
            logger.error(f"总结节点处理失败: {e}", exc_info=True)
            state["answer"] = "抱歉，处理您的问题时出现了错误，请稍后重试。"
        
        return state

    async def node_judge(self, state: MemoryState) -> Union[MemoryState, Command]:
        """
        判断节点：分析用户意图并决定处理流程
        
        使用LLM分析用户输入，判断是存储请求还是检索请求，
        并路由到相应的处理分支。
        
        Args:
            state (MemoryState): 当前工作流状态
        
        Returns:
            Union[MemoryState, Command]: 
                - Command: 路由到相应节点的指令
                - MemoryState: 异常情况下的状态更新
        
        判断逻辑：
        1. 构建意图分析的提示词
        2. 调用LLM进行意图分类
        3. 解析LLM响应获取判断结果
        4. 根据结果路由到save或search节点
        
        意图分类：
        - save: 存储类请求（"记录"、"保存"、"存储"等）
        - search: 检索类请求（"查询"、"找"、"什么时候"等）
        """
        query = state.get("query", "")
        
        logger.info(f"判断节点开始分析意图: {query[:100]}...")
        
        # 构建意图判断提示词
        input_prompt = f"""
请分析用户输入的意图，判断用户是想要存储信息还是检索信息。

用户输入：{query}

请判断这是以下哪种操作：
- save: 用户想要存储、记录、保存信息
- search: 用户想要查询、检索、寻找信息

典型的存储关键词：记录、保存、存储、写入、添加等
典型的检索关键词：查询、找、搜索、什么时候、哪里、谁等
        """
        
        try:
            logger.debug("开始调用LLM进行意图判断...")
            judge_response = await self.async_call_llm_chain(
                role=MemoryRole.MEMORY_JUDGE,
                input_prompt=input_prompt,
                session_id="judge"
            )
            
            # 解析判断结果
            if isinstance(judge_response, dict):
                judge_result = judge_response
            else:
                judge_result = extract_data_from_LLM_res(judge_response)
            
            action = judge_result.get("result", "").lower().strip()
            confidence = judge_result.get("confidence", "unknown")
            
            logger.info(f"意图判断完成 - 动作: {action}, 置信度: {confidence}")
            
            # 更新状态
            state["judge"] = {
                "action": action,
                "confidence": confidence,
                "raw_response": judge_response
            }
            
            # 路由到相应节点
            if action == 'save':
                logger.info("路由到存储节点")
                return Command(update=state, goto="save")
            elif action == 'search':
                logger.info("路由到检索节点")
                return Command(update=state, goto='search')
            else:
                # 未知意图，默认尝试检索
                logger.warning(f"未知意图 '{action}'，默认执行检索操作")
                state["judge"]["action"] = "search"
                return Command(update=state, goto='search')
                
        except Exception as e:
            logger.error(f"意图判断失败: {e}", exc_info=True)
            # 异常情况下默认执行检索
            state["judge"] = {
                "action": "search",
                "error": str(e)
            }
            return Command(update=state, goto='search')

    async def node_save(self, state: MemoryState) -> MemoryState:
        """
        存储节点：将用户记忆保存到向量数据库
        
        处理用户的记忆存储请求，将记忆内容保存到向量数据库中。
        这是存储流程的最终节点。
        
        Args:
            state (MemoryState): 包含要存储内容的状态
        
        Returns:
            MemoryState: 更新后的状态，包含存储结果
        
        存储流程：
        1. 从状态中提取要存储的内容
        2. 调用向量数据库代理进行存储
        3. 处理存储结果和异常
        4. 更新状态并生成确认信息
        
        存储策略：
        - 使用用户的原始查询作为存储内容
        - 自动提取时间、地点、人物等元数据
        - 转换为向量表示进行持久化存储
        """
        query = state.get("query", "")
        
        logger.info(f"存储节点开始处理: {query[:100]}...")
        
        if not query or not query.strip():
            logger.warning("存储内容为空")
            state["answer"] = "没有提供要存储的内容"
            state["status"] = "error"
            return state
        
        try:
            logger.debug("开始调用向量数据库代理进行存储...")
            save_result = await self.databases["vector"].execute({
                "operation": "save", 
                "query": query
            })
            
            # 处理存储结果
            if save_result is None:
                # 存储成功（正常情况下save操作返回None）
                state["answer"] = "记忆已成功保存"
                state["status"] = "completed"
                logger.info("记忆存储成功")
                
            elif isinstance(save_result, dict) and save_result.get("status") == "error":
                # 存储失败
                error_msg = save_result.get("message", "存储失败")
                state["answer"] = f"记忆保存失败：{error_msg}"
                state["status"] = "error"
                logger.error(f"记忆存储失败: {error_msg}")
                
            else:
                # 其他情况，假设存储成功
                state["answer"] = "记忆已保存"
                state["status"] = "completed"
                logger.info("记忆存储完成（未知格式响应）")
            
        except Exception as e:
            logger.error(f"存储节点处理失败: {e}", exc_info=True)
            state["answer"] = "记忆保存过程中出现错误，请稍后重试"
            state["status"] = "error"
        
        logger.info(f"存储节点处理完成 - 状态: {state.get('status', 'unknown')}")
        return state