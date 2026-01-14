import logging
import markdown
from weasyprint import HTML
from typing import Any, Dict, List, Optional, Tuple

from langchain.docstore.document import Document
from langchain_community.vectorstores import FAISS
from src.core.llm.client import LLMBase
from src.core.vector_db.vector_db_client import VectorDBClient
from src.config.settings import (
    JSON_DATA_PATH,
    OUTPUT_PATH,
    VECTOR_DB_PATH,
)
from src.config.prompts.reader_prompts import ReaderRole
from src.config.constants import ProcessingLimits
from src.utils.helpers import *
from src.readers.parallel_processor import (
    run_parallel_chapter_processing,
    run_parallel_detail_summaries,
)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
MAX_CHAPTER_LEN = ProcessingLimits.MAX_CHAPTER_LENGTH
"""
基础阅读器类，提供PDF/网页等文档处理的通用功能，包括：
- 数据保存与加载
- 摘要生成（简要/详细）
- 向量数据库交互基础逻辑

该类继承自LLMBase，为子类（如PDFReader、WebReader）提供通用方法。
"""
class ReaderBase(LLMBase):
    """
    基础阅读器类，封装文档处理的核心流程与通用工具方法。
    """
    def __init__(self, provider: str = "openai") -> None:
        """
        初始化基础阅读器，配置LLM提供商及数据存储路径。
        
        参数:
            provider (str): LLM服务提供商，支持'azure'、'openai'、'ollama'。
        
        说明:
            数据存储路径依赖全局变量：
            - JSON_DATA_PATH: 原始数据JSON存储路径
            - OUTPUT_PATH: 生成文件（摘要等）输出路径
            - VECTOR_DB_PATH: 向量数据库存储路径
        """
        super().__init__(provider)
        self.json_data_path = JSON_DATA_PATH
        self.output_path = OUTPUT_PATH
        self.vector_db_path = VECTOR_DB_PATH
        self.agenda_dict = {}
        self.vector_db_obj: Optional[VectorDBClient] = None
        self.total_summary = {}
        self.raw_data_dict = {}

        for path in [self.json_data_path, self.output_path, self.vector_db_path]:
            makedir(path)

    def _ensure_vector_db_client(self) -> None:
        """
        确保向量数据库客户端已初始化

        Raises:
            RuntimeError: 如果 vector_db_obj 未初始化
        """
        if self.vector_db_obj is None:
            raise RuntimeError(
                f"{self.__class__.__name__} 向量数据库客户端未初始化。"
                f"请先调用文档处理方法（如 process_pdf 或 process_web）。"
            )

    def save_data_to_file(self, data: str, file_name: str, file_type_list: Optional[List[str]] = None) -> None:
        """
        将数据保存为指定类型的文件

        Args:
            data: 需要保存的数据内容
            file_name: 文件名（不包含扩展名）
            file_type_list: 要保存的文件类型列表，默认为["md", "pdf"]

        Raises:
            ValueError: 数据为空或文件名无效
            OSError: 文件写入失败
        """
        # 输入验证
        if not data:
            raise ValueError("保存的数据不能为空")

        if not file_name or not file_name.strip():
            raise ValueError("文件名不能为空")

        if file_type_list is None:
            file_type_list = ["md", "pdf"]

        # 支持的文件类型
        supported_types = {"md", "pdf"}

        # 确保输出目录存在
        makedir(self.output_path)

        # 遍历需要保存的文件类型列表
        for file_type in file_type_list:
            if file_type not in supported_types:
                logger.warning(f"不支持的文件类型: {file_type}，跳过")
                continue

            try:
                # 构建完整的文件路径
                path = f"{self.output_path}/{file_name}.{file_type}"

                if file_type == 'pdf':
                    # 将markdown格式数据转换为HTML
                    html = markdown.markdown(data)
                    # 将HTML内容写入PDF文件
                    HTML(string=html).write_pdf(path)
                    logger.info(f"PDF文件已生成: {path}")

                elif file_type == 'md':
                    # 使用安全的文件写入方式
                    with open(path, 'w', encoding='utf-8') as file:
                        file.write(data)
                    logger.info(f"Markdown文件已生成: {path}")

            except Exception as e:
                logger.error(f"保存{file_type}文件失败: {path}, 错误: {e}")
                # 继续处理其他文件类型，不中断整个过程

    def get_brief_summary(self, file_type_list: Optional[List[str]] = None) -> None:
        """
        生成文章的简要摘要，整合文章叙事结构、章节信息和背景知识

        Args:
            file_type_list: 要保存的文件类型列表，默认为["md", "pdf"]

        Raises:
            ValueError: 输入数据无效
            Exception: 摘要生成失败
        """
        if file_type_list is None:
            file_type_list = ["md", "pdf"]

        # 输入验证
        if not self.total_summary:
            logger.warning("总摘要数据为空，无法生成简要摘要")
            return

        if not file_type_list:
            logger.info("文件类型列表为空，无需生成摘要文件")
            return

        try:
            # 构造用于生成简要摘要的查询指令
            query = ("请按照文章本身的章节信息和叙事结构，整理这篇文章的主要内容，"
                    "每个章节都需要有一定的简单介绍。如果背景知识中有一些文章的基本信息也需要一并总结。"
                    "仅需要返回相关内容，多余的话无需返回。返回中文。")

            logger.info("开始生成文章简要摘要...")

            # 调用回答生成方法获取简要摘要
            answer = self.get_answer(self.total_summary, query)

            # 验证生成的摘要
            if not answer or not answer.strip():
                logger.error("生成的简要摘要为空")
                return

            logger.info(f"文章简要摘要生成完成，长度: {len(answer)} 字符")

            # 保存生成的简要摘要
            self.save_data_to_file(answer, "brief_summary", file_type_list)

        except Exception as e:
            logger.error(f"生成简要摘要时发生错误: {e}")
            raise

    def get_detail_summary(self, raw_data_dict: Dict[str, Any], file_type_list: Optional[List[str]] = None) -> None:
        """
        生成文章的详细摘要，使用并行处理加速

        Args:
            raw_data_dict: 原始数据字典，键为标题，值为包含分页内容的字典
            file_type_list: 要保存的文件类型列表，默认为["md", "pdf"]

        Raises:
            ValueError: 输入数据无效
            Exception: 摘要生成失败
        """
        if file_type_list is None:
            file_type_list = ["md", "pdf"]

        # 输入验证
        if not raw_data_dict:
            logger.warning("原始数据字典为空，无法生成详细摘要")
            return

        if not file_type_list:
            logger.info("文件类型列表为空，无需生成摘要文件")
            return

        try:
            # 构造用于生成详细摘要的查询模板
            query_template = ("按照人类的习惯理解并且总结 {title} 的内容。"
                            "需要注意标题(如果标题中有数字则需要写出到结果中)，换行，加粗关键信息。"
                            "仅需要返回相关内容的总结信息，多余的话无需返回。"
                            "不需要对章节进行单独总结。返回中文")

            logger.info(f"开始并行生成详细摘要，共包含 {len(raw_data_dict)} 个部分...")

            # 准备要处理的章节数据
            chapters_to_process = []
            for title, data_dict in raw_data_dict.items():
                if not title or not isinstance(data_dict, dict):
                    logger.warning(f"跳过无效的标题或数据: {title}")
                    continue

                # 收集并去重同一标题下的所有页面内容
                context_data = []
                for page, raw_data in data_dict.items():
                    if raw_data and raw_data not in context_data:
                        context_data.append(raw_data)

                if not context_data:
                    logger.warning(f"标题 '{title}' 下没有有效内容，跳过")
                    continue

                chapters_to_process.append({
                    'title': title,
                    'context_data': context_data,
                    'query': query_template.format(title=title)
                })

            # 使用并行处理工具
            results = run_parallel_detail_summaries(
                llm_client=self,
                chapters=chapters_to_process,
                answer_role=ReaderRole.CONTEXT_QA,
                max_concurrent=5
            )

            # 按原始顺序组装结果
            title_order = [ch['title'] for ch in chapters_to_process]
            results_dict = {r[0]: r[1] for r in results if r[1]}
            
            total_answer = ""
            for title in title_order:
                if title in results_dict:
                    total_answer += f"\n\n --- \n\n {results_dict[title]}"

            # 验证总摘要内容
            if not total_answer.strip():
                logger.error("详细摘要内容为空，无法保存")
                return

            # 保存合并后的详细摘要
            self.save_data_to_file(total_answer, "detail_summary", file_type_list)
            logger.info("详细摘要生成完成")

        except Exception as e:
            logger.error(f"生成详细摘要时发生错误: {e}")
            raise

    def generate_output_file(self, file_path: str, raw_data_dict: Dict[str, Any]) -> None:
        """
        生成输出文件（摘要文档）

        Args:
            file_path: 输出子目录名称
            raw_data_dict: 原始数据字典

        Raises:
            ValueError: 输入参数无效
            OSError: 文件操作失败
        """
        # 输入验证
        if not file_path or not file_path.strip():
            raise ValueError("输出路径不能为空")

        if not isinstance(raw_data_dict, dict):
            raise ValueError("原始数据字典必须是字典类型")

        logger.info(f"开始生成输出文件，目标目录: {file_path}")

        try:
            # 构建完整输出路径
            original_output_path = self.output_path
            self.output_path = f"{original_output_path}/{file_path}"

            # 创建输出目录
            makedir(self.output_path)

            # 定义摘要类型和文件格式
            # 默认只生成简单摘要的MD格式，提高处理速度
            # 如需详细摘要或PDF格式，可手动修改此配置
            summary_configs = {
                "brief_summary": {
                    "generator": self.get_brief_summary,
                    "data": ""
                },
                # 详细摘要已禁用（生成时间长），如需启用请取消注释
                # "detail_summary": {
                #     "generator": self.get_detail_summary,
                #     "data": raw_data_dict
                # }
            }

            # 默认只生成MD格式，如需PDF格式请添加 "pdf"
            file_types = ["md"]

            # 处理每种摘要类型
            for summary_type, config in summary_configs.items():
                logger.info(f"处理摘要类型: {summary_type}")

                # 检查缺失的文件格式
                missing_types = []
                for file_type in file_types:
                    file_full_path = f"{self.output_path}/{summary_type}.{file_type}"
                    if not is_file_exists(file_full_path):
                        missing_types.append(file_type)

                # 生成缺失的文件
                if missing_types:
                    logger.info(f"摘要类型 '{summary_type}' 需要生成格式: {missing_types}")

                    try:
                        # 根据摘要类型调用不同的方法
                        if summary_type == "brief_summary":
                            config["generator"](missing_types)
                        else:
                            config["generator"](config["data"], missing_types)
                        logger.info(f"摘要类型 '{summary_type}' 生成完成")
                    except Exception as e:
                        logger.error(f"生成摘要类型 '{summary_type}' 时出错: {e}")
                        continue
                else:
                    logger.info(f"摘要类型 '{summary_type}' 的所有文件已存在，跳过生成")

            logger.info("输出文件生成流程完成")

        except Exception as e:
            logger.error(f"生成输出文件时发生错误: {e}")
            raise
        finally:
            # 恢复原始输出路径
            if 'original_output_path' in locals():
                self.output_path = original_output_path

    def get_data_from_json_dict(self, chunks: list, json_data_dict: dict) -> None:
        """
        从分块数据中提取文档信息（基本信息、目录结构）并构建向量数据库内容。
        
        参数:
            chunks (list): 分块后的原始数据列表
            json_data_dict (dict): 原始JSON数据字典
        
        """
        vector_db_content_docs = []
        agenda_list = []
        logger.info(f"开始处理 {len(chunks)} 个数据块...")
        for index, chunk in enumerate(chunks):
            agenda = self.get_agenda(chunk)
            agenda_list.extend(agenda)

        # 合并所有 chunk 的目录结构后，按章节分组
        agenda_data_list, self.agenda_dict = group_data_by_sections_with_titles(agenda_list, json_data_dict)

        # 检查每个章节的长度，如果长度大于 MAX_CHAPTER_LEN，则需要重新获取目录结构
        agenda_list = self.check_len_of_each_chapter(agenda_list, agenda_data_list)

        # 重新分组
        agenda_data_list, self.agenda_dict = group_data_by_sections_with_titles(agenda_list, json_data_dict)
        logger.info(f"章节分组完成，共 {len(agenda_data_list)} 个章节")
        logger.info(f"开始并行处理章节总结...")

        # 使用并行处理工具
        chapter_results = run_parallel_chapter_processing(
            llm_client=self,
            agenda_data_list=agenda_data_list,
            summary_role=ReaderRole.CONTENT_SUMMARY,
            refactor_role=ReaderRole.CONTENT_MERGE,
            max_concurrent=5
        )

        # 处理并行执行的结果
        for title, summary, refactor_content, page, data in chapter_results:
            self.total_summary[title] = summary
            vector_db_content_docs.append(
                Document(
                    page_content=summary,
                    metadata={
                        "type": "context",
                        "title": title,
                        "pages": page,
                        "raw_data": data,
                        "refactor": refactor_content,
                    }
                )
            )
            vector_db_content_docs.append(
                Document(
                    page_content=title,
                    metadata={
                        "type": "title",
                        "pages": page,
                        "summary": summary,
                        "raw_data": data,
                        "refactor": refactor_content,
                    }
                )
            )
 
            self.raw_data_dict[title] = data

        # 添加文档结构信息（type="structure"）到向量数据库
        logger.info(f"添加文档结构信息到向量数据库...")
        structure_doc = Document(
            page_content="Document Structure",  # 简单的占位内容
            metadata={
                "type": "structure",
                "agenda_dict": self.agenda_dict,
                "doc_name": getattr(self, 'doc_name', 'unknown'),
                "total_chapters": len(self.agenda_dict)
            }
        )
        vector_db_content_docs.append(structure_doc)

        logger.info(f"所有章节摘要已完成，正在构建向量数据库...")
        self._ensure_vector_db_client()
        self.vector_db_obj.build_vector_db(vector_db_content_docs)
        logger.info(f"向量数据库构建完成。")

    def check_len_of_each_chapter(self, agenda_list: List[Dict[str, Any]], agenda_data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查每个章节的长度，如果长度大于限制则重新获取子目录结构

        Args:
            agenda_list: 原始议程列表
            agenda_data_list: 议程数据列表

        Returns:
            更新后的议程列表

        Raises:
            Exception: 子章节提取失败
        """
        if not agenda_data_list:
            logger.warning("议程数据列表为空，无需检查章节长度")
            return agenda_list

        max_retries = 5
        updated_agenda_list = list(agenda_list)  # 创建副本

        for agenda_data in agenda_data_list:
            try:
                title = agenda_data.get("title", "未知章节")
                data = agenda_data.get("data")
                pages = agenda_data.get("pages", [])

                if not pages or not isinstance(pages, list):
                    logger.warning(f"章节 '{title}' 页码信息无效，跳过")
                    continue

                # 检查章节长度
                if len(pages) > MAX_CHAPTER_LEN:
                    logger.info(f"章节 '{title}' 长度 {len(pages)} 大于限制 {MAX_CHAPTER_LEN}，需要拆分")

                    if not data:
                        logger.warning(f"章节 '{title}' 数据为空，无法拆分")
                        continue

                    # 尝试获取子章节
                    sub_agenda = None
                    for attempt in range(max_retries):
                        try:
                            sub_agenda = self.get_sub_agenda(data)
                            if sub_agenda and len(sub_agenda) > 1:
                                updated_agenda_list.extend(sub_agenda)
                                logger.info(f"章节 '{title}' 成功拆分为 {len(sub_agenda)} 个子章节")
                                break
                            else:
                                logger.warning(f"章节 '{title}' 子章节数量不足，重试第 {attempt + 1} 次")

                        except Exception as e:
                            logger.warning(f"提取章节 '{title}' 子章节失败，重试第 {attempt + 1} 次: {e}")

                        if attempt == max_retries - 1:
                            logger.error(f"章节 '{title}' 在 {max_retries} 次尝试后仍无法拆分")

            except Exception as e:
                logger.error(f"处理章节时发生错误: {e}")
                continue

        logger.info(f"章节长度检查完成，议程项目数: {len(agenda_list)} -> {len(updated_agenda_list)}")
        return updated_agenda_list

    def get_data_from_vector_db(self) -> None:
        """
        从向量数据库加载数据并初始化相关字典

        只加载 type='title' 的文档，因为这些文档包含了完整的章节信息：
        - page_content: 章节标题
        - metadata['summary']: 章节摘要
        - metadata['raw_data']: 原始数据
        - metadata['refactor']: 重构后的内容
        - metadata['pages']: 页码列表

        Raises:
            Exception: 向量数据库操作失败
        """
        try:
            # 确保向量数据库客户端已初始化
            self._ensure_vector_db_client()

            # 如果向量数据库未加载，则尝试加载
            if not self.vector_db_obj.vector_db:
                self.vector_db_obj.load_vector_db()

            if not self.vector_db_obj.vector_db:
                logger.error("向量数据库加载失败")
                return

            # 检索所有 type='title' 的文档
            try:
                all_db_res = self.vector_db_obj.search_with_metadata_filter(
                    query="",
                    k=99999,  # 获取所有匹配的文档
                    field_name="type",
                    field_value="title",
                    enable_dedup=False

                )
                logger.info(f"从向量数据库检索到 {len(all_db_res)} 个章节")
            except Exception as e:
                logger.error(f"向量数据库检索失败: {e}")
                return

            if not all_db_res:
                logger.warning("向量数据库中没有找到任何 type='title' 的文档")
                return

            # 按页码排序确保章节顺序正确
            try:
                all_db_res_sorted = sorted(
                    all_db_res,
                    key=lambda x: self._get_first_page_number(x[0].metadata)
                )
            except Exception as e:
                logger.warning(f"章节排序失败，使用原始顺序: {e}")
                all_db_res_sorted = all_db_res

            # 处理每个检索结果（type='title' 的文档）
            processed_count = 0
            for db_res in all_db_res_sorted:
                try:
                    if not db_res or len(db_res) < 1:
                        continue

                    document = db_res[0]
                    if not hasattr(document, 'metadata') or not hasattr(document, 'page_content'):
                        logger.warning("文档格式无效，跳过")
                        continue

                    metadata = document.metadata

                    # 验证文档类型
                    doc_type = metadata.get("type")
                    if doc_type != "title":
                        logger.warning(f"文档类型不是 'title' (实际: {doc_type})，跳过")
                        continue

                    # 新格式（type='title' 的文档）：
                    # - page_content: 章节标题
                    # - metadata['summary']: 章节摘要
                    # - metadata['raw_data']: 原始数据
                    # - metadata['refactor']: 重构后的内容
                    # - metadata['pages']: 页码列表
                    title = document.page_content
                    summary = metadata.get("summary")
                    pages = metadata.get("pages")
                    data = metadata.get("raw_data")

                    # 验证必要字段
                    if not title or not title.strip():
                        logger.warning("章节标题为空，跳过")
                        continue

                    # 处理章节信息
                    if summary:
                        self.total_summary[title] = summary

                    if pages and isinstance(pages, list):
                        self.agenda_dict[title] = pages

                    # 保存原始数据
                    if data:
                        self.raw_data_dict[title] = data

                    processed_count += 1

                except Exception as e:
                    logger.error(f"处理检索结果时出错: {e}")
                    import traceback
                    logger.error(f"错误堆栈: {traceback.format_exc()}")
                    continue

            logger.info(f"成功处理 {processed_count} 个章节")
            logger.info(f"当前文章目录结构: {len(self.agenda_dict)} 个章节")

        except Exception as e:
            logger.error(f"从向量数据库获取数据时发生错误: {e}")
            raise

    def _get_first_page_number(self, metadata: Dict[str, Any]) -> float:
        """
        获取元数据中的第一个页码，用于排序

        Args:
            metadata: 文档元数据

        Returns:
            第一个页码，如果无效则返回无穷大
        """
        try:
            pages = metadata.get("pages", [])
            if pages and isinstance(pages, list) and len(pages) > 0:
                return float(pages[0])
        except (ValueError, TypeError):
            pass

        return float('inf')

    def get_basic_info(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        获取文档的基本信息摘要

        Args:
            raw_data: 文档原始数据

        Returns:
            基本信息摘要字典，失败返回None

        Raises:
            ValueError: 输入数据无效
        """
        if not raw_data:
            raise ValueError("原始数据不能为空")

        try:
            input_prompt = f"这里是文章的完整内容: {raw_data}"
            response = self.call_llm_chain(ReaderRole.METADATA_EXTRACT, input_prompt, "metadata")

            if not response:
                logger.warning("LLM返回空响应")
                return None

            result = extract_data_from_LLM_res(response)
            logger.info("文档基本信息摘要获取成功")
            return result

        except Exception as e:
            logger.error(f"获取基本信息时出错: {e}")
            return None

    def get_agenda(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        获取文档的目录结构或议程

        Args:
            raw_data: 文档原始数据

        Returns:
            目录结构列表

        Raises:
            ValueError: 输入数据无效
        """
        if not raw_data:
            raise ValueError("原始数据不能为空")

        try:
            input_prompt = f"这里是文章的完整内容: {raw_data}"
            response = self.call_llm_chain(ReaderRole.CHAPTER_EXTRACT, input_prompt, "chapter_extract")

            if not response:
                logger.warning("LLM返回空响应")
                return []

            result = extract_data_from_LLM_res(response)
            logger.info(f"目录结构提取成功，包含 {len(result) if isinstance(result, list) else 0} 个条目")
            return result if isinstance(result, list) else []

        except Exception as e:
            logger.error(f"获取目录结构时出错: {e}")
            return []

    def get_sub_agenda(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        获取文档的子目录结构

        Args:
            raw_data: 文档原始数据

        Returns:
            子目录结构列表

        Raises:
            ValueError: 输入数据无效
        """
        if not raw_data:
            raise ValueError("原始数据不能为空")

        try:
            input_prompt = f"这里是文章的完整内容: {raw_data}"
            response = self.call_llm_chain(ReaderRole.SUB_CHAPTER_EXTRACT, input_prompt, "sub_chapter_extract")

            if not response:
                logger.warning("LLM返回空响应")
                return []

            result = extract_data_from_LLM_res(response)
            logger.info(f"子目录结构提取成功，包含 {len(result) if isinstance(result, list) else 0} 个条目")
            return result if isinstance(result, list) else []

        except Exception as e:
            logger.error(f"获取子目录结构时出错: {e}")
            return []

    def summary_content(self, title: str, content: Any) -> str:
        """
        对指定章节内容进行总结

        Args:
            title: 章节标题
            content: 章节内容

        Returns:
            总结内容字符串

        Raises:
            ValueError: 输入参数无效
        """
        if not title or not isinstance(title, str):
            raise ValueError("章节标题不能为空且必须是字符串")

        if not content:
            raise ValueError("章节内容不能为空")

        try:
            input_prompt = f"请总结{title}的内容，上下文如下：{content}"
            response = self.call_llm_chain(ReaderRole.CONTENT_SUMMARY, input_prompt, "content_summary")

            if not response:
                logger.warning(f"章节 '{title}' 总结返回空内容")
                return ""

            logger.info(f"章节 '{title}' 总结完成，长度: {len(response)} 字符")
            return response

        except Exception as e:
            logger.error(f"总结章节 '{title}' 时出错: {e}")
            return ""

    def refactor_content(self, title: str, content: Any) -> str:
        """
        对指定章节内容进行重构整理

        Args:
            title: 章节标题
            content: 章节内容

        Returns:
            重构后的内容字符串

        Raises:
            ValueError: 输入参数无效
        """
        if not title or not isinstance(title, str):
            raise ValueError("章节标题不能为空且必须是字符串")

        if not content:
            raise ValueError("章节内容不能为空")

        try:
            input_prompt = f"请重新整理Content中的内容。\n\n Content：{content}"
            response = self.call_llm_chain(ReaderRole.CONTENT_MERGE, input_prompt, "content_merge")

            if not response:
                logger.warning(f"章节 '{title}' 重构返回空内容")
                return ""

            logger.info(f"章节 '{title}' 内容重构完成，长度: {len(response)} 字符")
            return response

        except Exception as e:
            logger.error(f"重构章节 '{title}' 时出错: {e}")
            return ""

    def get_answer(self, context_data: Any, query: str) -> str:
        """
        基于上下文数据生成问题回答

        Args:
            context_data: 上下文数据
            query: 用户问题
            common_data: 背景信息，可选

        Returns:
            生成的回答字符串

        Raises:
            ValueError: 输入参数无效
        """
        if not query or not isinstance(query, str):
            raise ValueError("问题不能为空且必须是字符串")

        if not context_data:
            logger.warning("上下文数据为空，回答质量可能受影响")

        try:
            input_prompt = (
                f"请结合检索回来的上下文信息(Context data)回答客户问题\n\n"
                f"===== \n\nQuestion: {query}\n\n"
                f"===== \n\nContext data: {context_data}"
            )

            logger.info("开始生成回答...")
            response = self.call_llm_chain(ReaderRole.CONTEXT_QA, input_prompt, "context_qa")

            if not response:
                logger.warning("LLM返回空回答")
                return "抱歉，无法生成有效回答。"

            logger.info(f"回答生成完成，长度: {len(response)} 字符")
            return response

        except Exception as e:
            logger.error(f"生成回答时出错: {e}")
            return f"生成回答时发生错误: {e}"
