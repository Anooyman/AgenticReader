import base64
import json
import os
import re
import logging
from typing import List, Dict, Any
from tqdm import tqdm

from langchain_core.messages import HumanMessage, AIMessage

from src.readers.retrieval import RetrivalAgent
from src.readers.base import ReaderBase
from src.config.settings import (
    PDF_IMAGE_PATH,
    PDF_PATH,
    PDF_IMAGE_CONFIG,
)
from src.config.constants import ReaderConstants
from src.config.prompts.reader_prompts import ReaderRole, READER_PROMPTS
from src.utils.helpers import *
from src.core.vector_db.vector_db_client import VectorDBClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class PDFReader(ReaderBase):
    """
    PDFReader 类用于处理 PDF 文件，包括：
    1. PDF 转图片
    2. 图片内容提取
    3. 调用 LLM 进行内容分析与总结
    4. 构建和使用向量数据库
    5. 支持交互式问答

    This class provides a full pipeline for PDF document analysis, including image conversion, content extraction, LLM-based summarization, vector DB construction, and interactive Q&A.
    """
    def __init__(self, provider: str = "openai", pdf_preset: str = "high") -> None:
        """
        初始化 PDFReader 对象，支持多 LLM provider。
        Args:
            provider: LLM服务提供商，可选：'azure'、'openai'、'ollama'
            pdf_preset: PDF转图片质量预设，可选："fast", "balanced", "high", "ultra"
            pdf_dpi: 自定义DPI分辨率（优先级高于preset）
            pdf_quality: 自定义质量级别（优先级高于preset）

        PDF质量预设说明：
        - fast: 150 DPI + low quality (快速处理，适合预览)
        - balanced: 200 DPI + medium quality (平衡速度和质量)
        - high: 300 DPI + high quality (高质量，推荐用于OCR)
        - ultra: 600 DPI + ultra quality (超高质量，适合精细文档)
        """
        super().__init__(provider)
        self.pdf_image_path = PDF_IMAGE_PATH
        self.pdf_path = PDF_PATH
        self.pdf_raw_data = None
        self.chunk_count = ReaderConstants.DEFAULT_CHUNK_COUNT  # 每个分块的大小
        self.retrieval_data_agent = None

        # 配置PDF转图片参数
        try:
            if pdf_preset in PDF_IMAGE_CONFIG.get("presets", {}):
                # 使用预设配置
                preset_config = PDF_IMAGE_CONFIG["presets"][pdf_preset]
                self.pdf_dpi = preset_config.get("dpi", PDF_IMAGE_CONFIG.get("dpi", 300))
                # 注意：预设中使用的是scale，不是quality字符串
                self.pdf_quality = pdf_preset  # 直接使用预设名称作为quality
                logger.info(f"使用PDF转图片预设'{pdf_preset}': DPI={self.pdf_dpi}, 质量级别={self.pdf_quality}")
            else:
                # 使用默认配置
                self.pdf_dpi = PDF_IMAGE_CONFIG.get("dpi", 300)
                self.pdf_quality = PDF_IMAGE_CONFIG.get("quality", "high")
                logger.info(f"使用默认PDF转图片配置: DPI={self.pdf_dpi}, 质量={self.pdf_quality}")
        except Exception as e:
            # 回退到安全的默认值
            logger.warning(f"PDF图片配置加载失败，使用默认值: {e}")
            self.pdf_dpi = 300
            self.pdf_quality = "high"

        for path in [self.pdf_image_path, self.pdf_path]:
            makedir(path)

    def extract_pdf_data(self, pdf_file_path: str) -> List[Dict[str, Any]]:
        """
        将 PDF 转为图片并用 LLM 提取每页内容，结果保存为 JSON

        Args:
            pdf_file_path: PDF 文件名（不含路径和扩展名）

        Returns:
            每页提取的内容列表

        Raises:
            ValueError: 输入参数无效
            FileNotFoundError: PDF文件不存在
            Exception: 处理过程中的其他错误
        """
        # 输入验证
        if not pdf_file_path or not isinstance(pdf_file_path, str):
            raise ValueError("PDF文件路径不能为空且必须是字符串")

        # 构建路径
        output_folder_path = os.path.join(self.pdf_image_path, pdf_file_path)
        pdf_path = os.path.join(self.pdf_path, f"{pdf_file_path}.pdf")
        output_json_path = os.path.join(self.json_data_path, f"{pdf_file_path}.json")

        # 验证PDF文件存在
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        logger.info(f"开始处理PDF: {pdf_path}")

        try:
            # 转换PDF为图片
            conversion_stats = pdf_to_images(
                pdf_path, output_folder_path,
                dpi=self.pdf_dpi, quality=self.pdf_quality
            )
            logger.info(f"PDF转图片完成: 成功{conversion_stats['successful_pages']}页")

            # 获取图片路径并排序
            image_paths = read_images_in_directory(output_folder_path)
            if not image_paths:
                logger.error("没有找到可处理的图片文件")
                return []

            # 安全的页码排序
            def safe_page_sort(path):
                try:
                    match = re.search(r'page_(\d+)\.png', path)
                    return int(match.group(1)) if match else float('inf')
                except:
                    return float('inf')

            sorted_image_paths = sorted(image_paths, key=safe_page_sort)
            logger.info(f"找到 {len(sorted_image_paths)} 个图片文件待处理")

            # 处理每个图片页面
            image_content_list = []
            error_pages_list = []
            successful_extractions = 0

            for idx, path in enumerate(tqdm(sorted_image_paths, desc="提取图片内容")):
                encoded_image = None
                try:
                    # 读取并编码图片文件
                    with open(path, 'rb') as img_file:
                        img_data = img_file.read()
                        encoded_image = base64.b64encode(img_data).decode('ascii')
                        del img_data  # 立即释放内存

                    # 构建LLM消息
                    message = [HumanMessage(
                        content=[
                            {
                                "type": "text",
                                "text": READER_PROMPTS.get(ReaderRole.IMAGE_EXTRACT, "请提取图片中的文字内容")
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
                            },
                        ],
                    )]

                    # 调用LLM处理
                    response = self.chat_model.invoke(message)

                    if not response or not response.content:
                        logger.warning(f"页面 {idx + 1} LLM返回空内容")
                        continue

                    # 提取页码
                    page_num = extract_page_num(path)
                    if not page_num:
                        page_num = str(idx + 1)  # 使用索引作为备用页码

                    # 保存结果
                    image_content_list.append({
                        "data": response.content,
                        "page": page_num
                    })

                    successful_extractions += 1

                except FileNotFoundError:
                    logger.error(f"图片文件不存在: {path}")
                    error_pages_list.append(path)
                except MemoryError:
                    logger.error(f"处理图片时内存不足: {path}")
                    error_pages_list.append(path)
                    # 强制垃圾回收
                    import gc
                    gc.collect()
                except Exception as e:
                    logger.error(f"处理图片 {path} 时发生错误: {e}")
                    error_pages_list.append(path)
                finally:
                    # 确保释放编码后的图片数据内存
                    if encoded_image is not None:
                        del encoded_image

            # 保存提取结果到JSON文件
            if image_content_list:
                try:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)

                    with open(output_json_path, 'w', encoding='utf-8') as file:
                        json.dump(image_content_list, file, ensure_ascii=False, indent=2)

                    logger.info(f"数据已保存到: {output_json_path}")
                    logger.info(f"提取统计: 成功{successful_extractions}页, 失败{len(error_pages_list)}页")
                except Exception as e:
                    logger.error(f"保存JSON文件失败: {e}")
                    raise
            else:
                logger.error("没有成功提取任何页面内容")

            # 报告错误页面
            if error_pages_list:
                logger.warning(f"以下页面提取失败: {error_pages_list}")
                logger.warning("请检查这些页面的图片质量或手动处理")

            return image_content_list

        except Exception as e:
            logger.error(f"PDF数据提取过程中发生错误: {e}")
            raise
   
    def split_pdf_raw_data(self):
        """
        将 self.pdf_raw_data 按照 self.chunk_count 进行切分。
        Split self.pdf_raw_data into chunks of size self.chunk_count.
        Returns:
            List[List[Any]]: 切分后的数据块列表。
        """
        if not isinstance(self.pdf_raw_data, list):
            logger.error("pdf_raw_data 不是 list，无法切分。")
            return []
        chunks = [self.pdf_raw_data[i:i + self.chunk_count] for i in range(0, len(self.pdf_raw_data), self.chunk_count)]
        logger.info(f"已将 pdf_raw_data 切分为 {len(chunks)} 个块，每块最多 {self.chunk_count} 条。")
        return chunks

    def process_pdf(self, pdf_file_path: str, save_data_flag: bool=True) -> Any:
        """
        主流程：读取 PDF 数据，提取结构，分章节总结，最终生成详细回答。
        Main pipeline: read PDF data, extract structure, summarize by section, and generate final answer.
        Args:
            pdf_file_path (str): PDF 文件名（不含路径）。
        Returns:
            None
        """
        vector_db_path = os.path.join(f"{self.vector_db_path}/{pdf_file_path}_data_index")
        self.vector_db_obj = VectorDBClient(vector_db_path, provider=self.provider)
        logger.info(f"开始处理PDF主流程: {pdf_file_path}")
        try:
            with open(f"{self.json_data_path}/{pdf_file_path}.json", 'r', encoding='utf-8') as f:
                self.pdf_raw_data = json.load(f)
        except Exception as e:
            logger.warning(f"读取本地JSON失败，将重新提取: {e}")
            self.pdf_raw_data = self.extract_pdf_data(pdf_file_path)
        if self.vector_db_obj.vector_db is not None:
            # 向量数据库已在初始化时自动加载
            self.get_data_from_vector_db()
        else:
            # 按 chunk_count 切分 pdf_raw_data，便于大文件分批处理
            chunks = self.split_pdf_raw_data()
            self.get_data_from_json_dict(chunks, self.pdf_raw_data)

        if save_data_flag:
            self.generate_output_file(pdf_file_path, self.raw_data_dict)

        logger.info(f"PDF处理流程结束。")

    def chat(self, input_prompt: str) -> Any:
        """
        针对用户输入进行对话。
        Interactive chat for user input.
        Args:
            input_prompt (str): 用户输入。
        Returns:
            Any: 回答内容。
        """
        #response = self.call_llm_chain(
        #    ReaderRole.REWRITE,
        #    input_prompt,
        #    "chat",
        #)
        ##self.delete_last_message_in_history(session_id="chat")
        #print("====="*10)
        #print(response)

        if self.retrieval_data_agent is None:
            self.retrieval_data_agent = RetrivalAgent(
                agenda_dict=self.agenda_dict,
                provider=self.provider,
                vector_db_obj=self.vector_db_obj,
            )
        context_data = self.retrieval_data_agent.retrieval_data(input_prompt)

        answer = self.get_answer(context_data, input_prompt)

        logger.info(f"对话回答生成完毕。")
        return answer

    def main(self, pdf_file_path: str, save_data_flag: bool=True) -> None:
        """
        主入口，启动 PDF 处理和对话。
        Main entry point, starts PDF processing and interactive chat.
        Args:
            pdf_file_path (str): PDF 文件名。
            save_data_flag (bool): 是否需要存储文件
        Returns:
            None
        """
        logger.info(f"启动主流程，处理 PDF 文件: {pdf_file_path}")

        self.process_pdf(get_pdf_name(pdf_file_path), save_data_flag)
        while True:
            user_input = input("You: ")
            if user_input.lower() in ["退出", "再见", "bye", "exit", "quit"]:
                print("Chatbot: 再见！期待下次与您对话。")
                logger.info("用户主动退出对话。")
                break

            answer = self.chat(user_input)
            self.add_message_to_history(session_id="chat", message=AIMessage(answer))
            print(f"User: {user_input}")
            print(f"ChatBot: {answer}")
            print("======"*10)