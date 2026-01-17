"""
Indexing Agent - 文档索引构建Agent

负责文档的解析、摘要生成、标签分类、向量索引构建和文档注册
"""

from langgraph.graph import StateGraph, END
from typing import Dict, List, Any, Optional
import logging
import json
import re
import os
from pathlib import Path

from ..base import AgentBase
from .state import IndexingState
from .doc_registry import DocumentRegistry
from src.config.settings import (
    PDF_IMAGE_PATH,
    PDF_PATH,
    JSON_DATA_PATH,
    PDF_IMAGE_CONFIG,
)
from src.config.prompts.reader_prompts import ReaderRole, READER_PROMPTS
from src.config.constants import ReaderConstants
from src.utils.helpers import (
    pdf_to_images,
    read_images_in_directory,
    makedir,
    get_pdf_name,
)

logger = logging.getLogger(__name__)


class IndexingAgent(AgentBase):
    """
    索引构建Agent

    工作流程：
    1. parse - 解析文档内容
    2. chunk - 文本分块
    3. summarize - 生成摘要
    4. build_index - 构建向量索引
    5. register - 注册到文档库

    - extract_basic_info_impl - 提取基本信息
    - generate_summary_impl - 生成摘要
    - build_vector_index_impl - 构建向量索引
    """

    def __init__(self, provider: str = "openai", pdf_preset: str = "high"):
        """
        初始化 IndexingAgent

        Args:
            provider: LLM提供商 ('azure', 'openai', 'ollama')
            pdf_preset: PDF转图片质量预设 ('fast', 'balanced', 'high', 'ultra')
        """
        # 初始化基类（会初始化 self.llm 和 self.embedding_model）
        super().__init__(name="IndexingAgent", provider=provider)

        self.doc_registry = DocumentRegistry()

        # PDF 处理相关配置
        self.pdf_image_path = PDF_IMAGE_PATH
        self.pdf_path = PDF_PATH
        self.json_data_path = JSON_DATA_PATH
        self.chunk_count = ReaderConstants.DEFAULT_CHUNK_COUNT

        # 配置 PDF 转图片参数
        try:
            if pdf_preset in PDF_IMAGE_CONFIG.get("presets", {}):
                preset_config = PDF_IMAGE_CONFIG["presets"][pdf_preset]
                self.pdf_dpi = preset_config.get("dpi", PDF_IMAGE_CONFIG.get("dpi", 300))
                self.pdf_quality = pdf_preset
                logger.info(f"使用PDF转图片预设'{pdf_preset}': DPI={self.pdf_dpi}, 质量级别={self.pdf_quality}")
            else:
                self.pdf_dpi = PDF_IMAGE_CONFIG.get("dpi", 300)
                self.pdf_quality = PDF_IMAGE_CONFIG.get("quality", "high")
                logger.info(f"使用默认PDF转图片配置: DPI={self.pdf_dpi}, 质量={self.pdf_quality}")
        except Exception as e:
            logger.warning(f"PDF图片配置加载失败，使用默认值: {e}")
            self.pdf_dpi = 300
            self.pdf_quality = "high"

        # 确保目录存在
        for path in [self.pdf_image_path, self.pdf_path, self.json_data_path]:
            makedir(path)

        self.graph = self.build_graph()

    # ==================== 检查点辅助方法 ====================

    def _check_stage_files_exist(self, stage_name: str, output_files: List[str]) -> bool:
        """
        检查阶段输出文件是否存在

        Args:
            stage_name: 阶段名称
            output_files: 输出文件路径列表

        Returns:
            所有文件都存在返回True，否则返回False
        """
        if not output_files:
            return False

        for file_path in output_files:
            path = Path(file_path)
            # 检查文件或目录是否存在
            if not path.exists():
                logger.info(f"⏭️  [{stage_name}] 文件不存在，需要执行: {file_path}")
                return False

            # 如果是目录，检查是否为空
            if path.is_dir():
                if not any(path.iterdir()):
                    logger.info(f"⏭️  [{stage_name}] 目录为空，需要执行: {file_path}")
                    return False

        logger.info(f"✅ [{stage_name}] 所有输出文件已存在")
        return True

    def _should_skip_stage(self, doc_name: str, stage_name: str) -> tuple[bool, Optional[List[str]]]:
        """
        判断是否应该跳过某个阶段

        Args:
            doc_name: 文档名称
            stage_name: 阶段名称

        Returns:
            (should_skip, output_files): 是否跳过 和 输出文件列表
        """
        # 检查注册表中的阶段状态
        stage_info = self.doc_registry.get_stage_status(doc_name, stage_name)

        if not stage_info or stage_info.get("status") != "completed":
            logger.info(f"🔄 [{stage_name}] 阶段未完成，需要执行")
            return False, None

        # 检查输出文件是否存在
        output_files = stage_info.get("output_files", [])
        if self._check_stage_files_exist(stage_name, output_files):
            logger.info(f"⏭️  [{stage_name}] 阶段已完成且文件存在，跳过执行")
            return True, output_files
        else:
            logger.info(f"🔄 [{stage_name}] 阶段状态为完成但文件不存在，重新执行")
            return False, None

    # ==================== Graph构建 ====================

    def build_graph(self) -> StateGraph:
        """
        构建LangGraph workflow

        工作流程：
        1. check_cache - 检查所有阶段的文件，设置每个阶段的跳过标志
        2. parse - 解析文档（根据标志决定是否跳过）
        3. extract_structure - 提取目录结构（根据标志决定是否跳过）
        4. chunk - 构建章节数据列表（根据标志决定是否跳过）
        5. process_chapters - 并行处理章节（根据标志决定是否跳过）
        6. build_index - 构建向量数据库（根据标志决定是否跳过）
        7. generate_brief_summary - 生成简要摘要（根据标志决定是否跳过）
        8. register - 注册文档
        """
        workflow = StateGraph(IndexingState)

        # 添加节点
        workflow.add_node("check_cache", self.check_cache)  # 初始检查节点
        workflow.add_node("parse", self.parse_document)
        workflow.add_node("extract_structure", self.extract_structure)
        workflow.add_node("chunk", self.chunk_text)
        workflow.add_node("process_chapters", self.process_chapters)
        workflow.add_node("build_index", self.build_index)
        workflow.add_node("generate_brief_summary", self.generate_brief_summary)
        workflow.add_node("register", self.register_document)

        # 添加边 - 线性流程，每个节点内部根据标志决定是否跳过
        workflow.add_edge("check_cache", "parse")
        workflow.add_edge("parse", "extract_structure")
        workflow.add_edge("extract_structure", "chunk")
        workflow.add_edge("chunk", "process_chapters")
        workflow.add_edge("process_chapters", "build_index")
        workflow.add_edge("build_index", "generate_brief_summary")
        workflow.add_edge("generate_brief_summary", "register")
        workflow.add_edge("register", END)

        # 设置入口
        workflow.set_entry_point("check_cache")

        return workflow.compile()

    async def generate_summary_impl(
        self,
        context_data: Dict[str, Any],
        doc_name: str,
        session_id: str = "summary_generation"
    ) -> str:
        """
        生成文档简要摘要（工具方法）

        Args:
            context_data: 上下文数据（可以是全文内容或章节摘要字典）
            doc_name: 文档名称
            session_id: 会话ID，用于区分不同调用场景

        Returns:
            简要摘要文本
        """
        logger.info(f"📝 [Tool:generate_summary] 生成摘要: {doc_name}")

        try:
            from src.config.prompts.reader_prompts import ReaderRole

            query = (
                "请按照文章本身的章节信息和叙事结构，整理这篇文章的主要内容，"
                "每个章节都需要有一定的简单介绍。如果背景知识中有一些文章的基本信息也需要一并总结。"
                "仅需要返回相关内容，多余的话无需返回。返回中文。"
            )

            # 构建输入 prompt（与 ReaderBase.get_answer 相同的格式）
            input_prompt = (
                f"请结合检索回来的上下文信息(Context data)回答客户问题\n\n"
                f"===== \n\nQuestion: {query}\n\n"
                f"===== \n\nContext data: {context_data}"
            )

            # 使用异步调用（禁用历史总结，摘要生成不需要保留上下文）
            answer = await self.llm.async_call_llm_chain(
                ReaderRole.CONTEXT_QA,
                input_prompt,
                session_id,
                enable_llm_summary=False
            )

            if not answer or not answer.strip():
                logger.warning("生成的简要摘要为空")
                return f"文档 {doc_name} 的简要摘要（生成失败）"

            logger.info(f"✅ [Tool:generate_summary] 摘要生成完成，长度: {len(answer)} 字符")
            return answer

        except Exception as e:
            logger.error(f"❌ [Tool:generate_summary] 生成摘要失败: {e}")
            return f"文档 {doc_name} 的简要摘要（生成错误: {str(e)}）"


    async def build_vector_index_impl(
        self,
        doc_name: str,
        chunks: List[Dict[str, str]],
        metadata: Optional[Dict] = None
    ) -> str:
        """
        构建向量索引（工具方法）

        Args:
            doc_name: 文档名称
            chunks: 文本分块列表，格式：[{"data": str, "page": str}, ...]
            metadata: 元数据（包含tags, summary等）

        Returns:
            索引路径
        """
        logger.info(f"🔨 [Tool:build_index] 构建向量索引: {doc_name}, 分块数: {len(chunks)}")

        try:
            from pathlib import Path
            from src.config.settings import DATA_ROOT
            from src.core.vector_db.vector_db_client import VectorDBClient
            from langchain.docstore.document import Document

            # 构建索引路径
            index_dir = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
            index_dir.mkdir(parents=True, exist_ok=True)
            index_path = str(index_dir)

            # 创建 VectorDBClient，直接使用 self.embedding_model
            # self.embedding_model 来自 AgentBase，它从 self.llm.embedding_model 获取
            vector_db_client = VectorDBClient(index_path, embedding_model=self.embedding_model)

            # 准备文档列表
            vector_db_docs = []

            # 提取元数据
            summary = metadata.get("summary", "") if metadata else ""

            # 为每个分块创建Document对象
            for i, chunk_item in enumerate(chunks):
                chunk_data = chunk_item.get("data", "")
                chunk_page = chunk_item.get("page", f"chunk_{i+1}")

                if not chunk_data or not chunk_data.strip():
                    continue

                # 创建内容文档
                doc = Document(
                    page_content=chunk_data,
                    metadata={
                        "type": "content",
                        "chunk_id": i,
                        "page": chunk_page,
                        "doc_name": doc_name,
                    }
                )
                vector_db_docs.append(doc)

            # 添加文档结构信息
            structure_doc = Document(
                page_content="Document Structure",
                metadata={
                    "type": "structure",
                    "doc_name": doc_name,
                    "total_chunks": len(chunks),
                    "summary": summary,
                }
            )
            vector_db_docs.append(structure_doc)

            # 构建向量数据库
            logger.info(f"开始构建向量数据库，共 {len(vector_db_docs)} 个文档...")
            vector_db_client.build_vector_db(vector_db_docs)

            logger.info(f"✅ [Tool:build_index] 索引构建完成: {index_path}")
            return index_path

        except Exception as e:
            logger.error(f"❌ [Tool:build_index] 索引构建失败: {e}")
            raise


    async def extract_pdf_data_impl(self, pdf_file_path: str) -> Dict[str, Any]:
        """
        将 PDF 转为图片并用 LLM 提取每页内容（工具方法）

        Args:
            pdf_file_path: PDF 文件名（不含路径和扩展名）

        Returns:
            提取结果字典:
            {
                "pdf_data_list": List[Dict],  # 每页提取的内容
                "image_paths": List[str],      # 图片文件路径列表
                "json_path": str,              # JSON数据文件路径
                "image_folder": str            # 图片文件夹路径
            }

        Raises:
            ValueError: 输入参数无效
            FileNotFoundError: PDF文件不存在
            Exception: 处理过程中的其他错误
        """
        logger.info(f"📄 [Tool:extract_pdf] ========== 开始提取PDF内容 ==========")
        logger.info(f"📄 [Tool:extract_pdf] 输入文件名: {pdf_file_path}")

        # 输入验证
        if not pdf_file_path or not isinstance(pdf_file_path, str):
            raise ValueError("PDF文件路径不能为空且必须是字符串")

        # 构建路径
        output_folder_path = os.path.join(self.pdf_image_path, pdf_file_path)
        pdf_path = os.path.join(self.pdf_path, f"{pdf_file_path}.pdf")
        # JSON文件放在文档文件夹中
        doc_json_folder = os.path.join(self.json_data_path, pdf_file_path)
        output_json_path = os.path.join(doc_json_folder, "data.json")

        logger.info(f"📄 [Tool:extract_pdf] 完整路径:")
        logger.info(f"📄 [Tool:extract_pdf]   - PDF: {pdf_path}")
        logger.info(f"📄 [Tool:extract_pdf]   - 图片文件夹: {output_folder_path}")
        logger.info(f"📄 [Tool:extract_pdf]   - JSON输出: {output_json_path}")

        # 验证PDF文件存在
        if not os.path.exists(pdf_path):
            logger.error(f"📄 [Tool:extract_pdf] ❌ PDF文件不存在: {pdf_path}")
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        logger.info(f"📄 [Tool:extract_pdf] ✅ PDF文件存在")

        try:
            image_paths = []

            # 检查是否已有JSON数据
            if os.path.exists(output_json_path):
                logger.info(f"发现已存在的JSON数据: {output_json_path}")
                try:
                    with open(output_json_path, 'r', encoding='utf-8') as f:
                        image_content_list = json.load(f)

                    # 获取已存在的图片路径
                    if os.path.exists(output_folder_path):
                        image_paths = read_images_in_directory(output_folder_path)
                        # 排序图片路径
                        def safe_page_sort(path):
                            try:
                                match = re.search(r'page_(\d+)\.png', path)
                                return int(match.group(1)) if match else float('inf')
                            except:
                                return float('inf')
                        image_paths = sorted(image_paths, key=safe_page_sort)

                    logger.info(f"✅ [Tool:extract_pdf] 从缓存加载: {len(image_content_list)} 页")

                    return {
                        "pdf_data_list": image_content_list,
                        "image_paths": image_paths,
                        "json_path": output_json_path,
                        "image_folder": output_folder_path
                    }
                except Exception as e:
                    logger.warning(f"读取缓存JSON失败，将重新提取: {e}")

            # 转换PDF为图片
            logger.info(f"📄 [Tool:extract_pdf] 开始转换PDF为图片...")
            logger.info(f"📄 [Tool:extract_pdf]   - DPI: {self.pdf_dpi}")
            logger.info(f"📄 [Tool:extract_pdf]   - 质量预设: {self.pdf_quality}")
            conversion_stats = pdf_to_images(
                pdf_path, output_folder_path,
                dpi=self.pdf_dpi, quality=self.pdf_quality
            )
            logger.info(f"📄 [Tool:extract_pdf] ✅ PDF转图片完成: 成功 {conversion_stats['successful_pages']} 页")

            # 获取图片路径并排序
            image_paths = read_images_in_directory(output_folder_path)
            if not image_paths:
                logger.error("没有找到可处理的图片文件")
                return {
                    "pdf_data_list": [],
                    "image_paths": [],
                    "json_path": output_json_path,
                    "image_folder": output_folder_path
                }

            # 安全的页码排序
            def safe_page_sort(path):
                try:
                    match = re.search(r'page_(\d+)\.png', path)
                    return int(match.group(1)) if match else float('inf')
                except:
                    return float('inf')

            sorted_image_paths = sorted(image_paths, key=safe_page_sort)
            logger.info(f"找到 {len(sorted_image_paths)} 个图片文件待处理")

            # 使用并行处理提取图片内容
            extract_prompt = READER_PROMPTS.get(
                ReaderRole.IMAGE_EXTRACT, "请提取图片中的文字内容"
            )
            logger.info(f"📄 [Tool:extract_pdf] 开始并行提取图片内容...")
            logger.info(f"📄 [Tool:extract_pdf]   - 图片数量: {len(sorted_image_paths)}")
            logger.info(f"📄 [Tool:extract_pdf]   - 最大并发: 5")
            logger.info(f"📄 [Tool:extract_pdf]   - 使用LLM: {self.llm.provider}")

            # 直接使用异步方法（因为当前已经在async上下文中）
            from src.core.processing.parallel_processor import PageExtractor
            extractor = PageExtractor(self.llm, extract_prompt, max_concurrent=5)
            image_content_list = await extractor.extract_pages_parallel(sorted_image_paths)

            logger.info(f"📄 [Tool:extract_pdf] ✅ 图片内容提取完成")

            # 保存提取结果到JSON文件
            if image_content_list:
                try:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)

                    with open(output_json_path, 'w', encoding='utf-8') as file:
                        json.dump(image_content_list, file, ensure_ascii=False, indent=2)

                    logger.info(f"数据已保存到: {output_json_path}")
                    logger.info(f"✅ [Tool:extract_pdf] 提取统计: 成功{len(image_content_list)}页")
                except Exception as e:
                    logger.error(f"保存JSON文件失败: {e}")
                    raise
            else:
                logger.error("没有成功提取任何页面内容")

            return {
                "pdf_data_list": image_content_list,
                "image_paths": sorted_image_paths,
                "json_path": output_json_path,
                "image_folder": output_folder_path
            }

        except Exception as e:
            logger.error(f"❌ [Tool:extract_pdf] PDF数据提取失败: {e}")
            raise

    def split_pdf_raw_data(self, pdf_raw_data: List[Any]) -> List[List[Any]]:
        """
        将 PDF 原始数据按照 chunk_count 进行切分

        Args:
            pdf_raw_data: PDF原始数据列表

        Returns:
            切分后的数据块列表
        """
        if not isinstance(pdf_raw_data, list):
            logger.error("pdf_raw_data 不是 list，无法切分")
            return []

        chunks = [
            pdf_raw_data[i:i + self.chunk_count]
            for i in range(0, len(pdf_raw_data), self.chunk_count)
        ]
        logger.info(f"已将 pdf_raw_data 切分为 {len(chunks)} 个块，每块最多 {self.chunk_count} 条")
        return chunks

    async def extract_toc_from_pages_impl(
        self,
        pdf_data_list: List[Dict[str, str]],
        max_pages: int = 10
    ) -> tuple[Optional[Dict[str, List]], bool]:
        """
        从PDF前几页快速提取目录结构（工具方法）

        Args:
            pdf_data_list: PDF每页数据列表
            max_pages: 最多检查的页数

        Returns:
            (agenda_dict, has_toc): 目录字典和是否找到目录的标志
        """
        logger.info(f"📖 [Tool:extract_toc] 尝试从前 {max_pages} 页提取目录")

        try:
            from src.config.prompts.reader_prompts import ReaderRole
            from src.utils.helpers import extract_data_from_LLM_res

            # 合并前几页的内容
            toc_pages = pdf_data_list[:max_pages]
            combined_content = "\n\n".join([
                f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}"
                for i, item in enumerate(toc_pages)
            ])

            # 构建提取目录的 prompt
            input_prompt = f"这里是文章的前 {len(toc_pages)} 页内容，请查找并提取目录结构: {combined_content}"

            # 调用 LLM 提取目录
            response = self.llm.call_llm_chain(
                ReaderRole.CHAPTER_EXTRACT,
                input_prompt,
                "toc_extract"
            )

            if not response:
                logger.warning("LLM返回空响应，未找到目录")
                return None, False

            # 解析 LLM 返回的结果
            result = extract_data_from_LLM_res(response)

            if not result or not isinstance(result, list) or len(result) == 0:
                logger.info("未在前几页检测到目录结构")
                return None, False

            # 转换为 agenda_dict 格式: {title: [pages]}
            agenda_dict = {}
            for item in result:
                if isinstance(item, dict) and "title" in item and "pages" in item:
                    title = item["title"]
                    pages = item["pages"]
                    if isinstance(pages, list):
                        agenda_dict[title] = pages
                    else:
                        agenda_dict[title] = [pages]

            if agenda_dict:
                logger.info(f"✅ [Tool:extract_toc] 成功提取目录: {len(agenda_dict)} 个章节")
                return agenda_dict, True
            else:
                logger.info("解析结果为空，未找到有效目录")
                return None, False

        except Exception as e:
            logger.error(f"❌ [Tool:extract_toc] 提取目录失败: {e}")
            return None, False

    async def analyze_full_structure_impl(
        self,
        pdf_data_list: List[Dict[str, str]]
    ) -> Dict[str, List]:
        """
        分析整个PDF文档的结构（工具方法）

        当PDF没有明确目录时，遍历全文分析章节结构

        Args:
            pdf_data_list: PDF每页数据列表

        Returns:
            agenda_dict: 目录字典 {title: [pages]}
        """
        logger.info(f"🔍 [Tool:analyze_structure] 开始分析全文结构: {len(pdf_data_list)} 页")

        try:
            from src.config.prompts.reader_prompts import ReaderRole
            from src.utils.helpers import extract_data_from_LLM_res

            # 将PDF数据分块处理（避免单次处理过长）
            chunks = self.split_pdf_raw_data(pdf_data_list)

            all_agenda_list = []

            # 并行处理每个分块
            for i, chunk in enumerate(chunks):
                logger.info(f"处理分块 {i+1}/{len(chunks)}")

                # 合并分块内容
                chunk_content = "\n\n".join([
                    f"[Page {item.get('page', idx+1)}]\n{item.get('data', '')}"
                    for idx, item in enumerate(chunk)
                ])

                # 构建 prompt
                input_prompt = f"这里是文章的部分内容: {chunk_content}"

                # 调用 LLM 提取章节
                response = self.llm.call_llm_chain(
                    ReaderRole.CHAPTER_EXTRACT,
                    input_prompt,
                    f"structure_extract_chunk"
                )

                if response:
                    result = extract_data_from_LLM_res(response)
                    if isinstance(result, list):
                        all_agenda_list.extend(result)

            # 转换为 agenda_dict
            from src.utils.helpers import group_data_by_sections_with_titles

            # 直接使用 pdf_data_list（已经是正确格式：List[Dict[str, Any]]）
            # pdf_data_list 格式: [{"page": "1", "data": "..."}, ...]
            _, agenda_list = group_data_by_sections_with_titles(all_agenda_list, pdf_data_list)

            # 将列表格式转换为字典格式
            # agenda_list: [{'title': '章节1', 'pages': [1,2,3]}, ...]
            # agenda_dict: {'章节1': [1,2,3], ...}
            agenda_dict = {
                item['title']: item['pages']
                for item in agenda_list
            }

            logger.info(f"✅ [Tool:analyze_structure] 结构分析完成: {len(agenda_dict)} 个章节")

            return agenda_dict

        except Exception as e:
            logger.error(f"❌ [Tool:analyze_structure] 结构分析失败: {e}")
            # 返回默认结构（整个文档作为一个章节）
            return {"全文": list(range(1, len(pdf_data_list) + 1))}

    # ==================== Workflow节点方法 ====================

    async def check_cache(self, state: IndexingState) -> IndexingState:
        """
        步骤0：检查所有阶段的缓存文件

        检查每个阶段的输出文件是否存在，设置跳过标志，并尝试加载已有数据
        """
        logger.info(f"🔍 [CheckCache] ========== 步骤0: 检查所有缓存文件 ==========")
        logger.info(f"🔍 [CheckCache] 文档名称: {state['doc_name']}")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        # 初始化阶段状态字典
        stage_status = {
            "parse": {"skip": False, "files": []},
            "extract_structure": {"skip": False, "files": []},
            "chunk_text": {"skip": False, "files": []},
            "process_chapters": {"skip": False, "files": []},
            "build_index": {"skip": False, "files": []},
            "generate_summary": {"skip": False, "files": []},
        }

        # 定义所有文件路径
        from src.config.settings import DATA_ROOT
        # JSON 文件统一放在以文档名命名的文件夹中
        doc_json_folder = os.path.join(self.json_data_path, doc_name)
        json_path = os.path.join(doc_json_folder, "data.json")
        structure_json_path = os.path.join(doc_json_folder, "structure.json")
        chunk_json_path = os.path.join(doc_json_folder, "chunks.json")
        image_folder = os.path.join(self.pdf_image_path, doc_name)
        # 注意：不再使用单独的 chapters.json，数据存储在 vector db 中
        vector_db_path = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
        summary_txt_path = os.path.join(DATA_ROOT, "output", f"{doc_name}_brief_summary.md")

        # 检查每个阶段的文件
        logger.info(f"🔍 [CheckCache] 开始检查各阶段文件...")

        # 1. 检查 parse 阶段
        if Path(json_path).exists():
            logger.info(f"✅ [CheckCache] parse: JSON文件存在")
            stage_status["parse"]["skip"] = True
            stage_status["parse"]["files"] = [image_folder, json_path] if Path(image_folder).exists() else [json_path]

            # 尝试加载 PDF 数据
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    pdf_data_list = json.load(f)
                state["pdf_data_list"] = pdf_data_list
                state["json_data_dict"] = {str(item.get("page", i+1)): item.get("data", "") for i, item in enumerate(pdf_data_list)}
                state["raw_data"] = "\n\n".join([f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}" for i, item in enumerate(pdf_data_list)])
                logger.info(f"   📥 已加载 PDF 数据: {len(pdf_data_list)} 页")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] PDF 数据加载失败: {e}")
                stage_status["parse"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] parse: JSON文件不存在，需要执行")

        # 2. 检查 extract_structure 阶段
        if Path(structure_json_path).exists():
            logger.info(f"✅ [CheckCache] extract_structure: 结构文件存在")
            stage_status["extract_structure"]["skip"] = True
            stage_status["extract_structure"]["files"] = [structure_json_path]
            logger.debug(f"🔍 [CheckCache] 设置 stage_status['extract_structure']['skip'] = {stage_status['extract_structure']['skip']}")

            try:
                with open(structure_json_path, 'r', encoding='utf-8') as f:
                    structure_data = json.load(f)

                # 兼容两种格式：
                # 新格式: {"agenda_dict": {...}, "has_toc": true}
                # 旧格式: 直接是 agenda_dict 字典
                if isinstance(structure_data, dict):
                    if "agenda_dict" in structure_data:
                        # 新格式
                        state["agenda_dict"] = structure_data.get("agenda_dict", {})
                        state["has_toc"] = structure_data.get("has_toc", False)
                    else:
                        # 旧格式：整个文件就是 agenda_dict
                        state["agenda_dict"] = structure_data
                        state["has_toc"] = True  # 有结构文件就认为有目录

                    logger.info(f"   📥 已加载结构: {len(state['agenda_dict'])} 个章节, has_toc={state.get('has_toc')}")
                else:
                    logger.warning(f"⚠️  [CheckCache] 结构数据格式错误（非字典类型）")
                    stage_status["extract_structure"]["skip"] = False
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 结构数据加载失败: {e}")
                stage_status["extract_structure"]["skip"] = False
                logger.debug(f"🔍 [CheckCache] 加载失败，重置 stage_status['extract_structure']['skip'] = {stage_status['extract_structure']['skip']}")
        else:
            logger.info(f"❌ [CheckCache] extract_structure: 结构文件不存在，需要执行")

        # 3. 检查 chunk_text 阶段
        if Path(chunk_json_path).exists():
            logger.info(f"✅ [CheckCache] chunk_text: 章节数据文件存在")
            stage_status["chunk_text"]["skip"] = True
            stage_status["chunk_text"]["files"] = [chunk_json_path]

            try:
                with open(chunk_json_path, 'r', encoding='utf-8') as f:
                    agenda_data_list = json.load(f)
                state["agenda_data_list"] = agenda_data_list
                logger.info(f"   📥 已加载章节数据: {len(agenda_data_list)} 个章节")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 章节数据加载失败: {e}")
                stage_status["chunk_text"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] chunk_text: 章节数据文件不存在，需要执行")

        # 4 & 5. 检查 build_index 阶段（process_chapters 与 build_index 绑定）
        # 如果 vector db 存在，则同时跳过 process_chapters 和 build_index
        if vector_db_path.exists() and any(vector_db_path.iterdir()):
            logger.info(f"✅ [CheckCache] build_index: Vector DB存在")
            stage_status["build_index"]["skip"] = True
            stage_status["process_chapters"]["skip"] = True  # 绑定跳过
            stage_status["build_index"]["files"] = [str(vector_db_path)]
            stage_status["process_chapters"]["files"] = [str(vector_db_path)]
            state["index_path"] = str(vector_db_path)

            # 从 Vector DB 加载 chapter_summaries 数据
            try:
                from src.core.vector_db.vector_db_client import VectorDBClient

                logger.info(f"   📥 正在从 Vector DB 加载章节摘要数据...")

                # 使用 VectorDBClient 加载 vector db
                vector_db_client = VectorDBClient(str(vector_db_path), embedding_model=self.embedding_model)
                # VectorDBClient 在初始化时会自动加载已存在的 vector db（见 __init__ 的 auto-load 逻辑）

                # 从 docstore 中提取所有文档
                chapter_summaries = {}
                chapter_refactors = {}
                raw_data_dict = {}

                # 遍历 docstore 中的所有文档
                if vector_db_client.vector_db and vector_db_client.vector_db.docstore:
                    for doc_id, doc in vector_db_client.vector_db.docstore._dict.items():
                        metadata = doc.metadata
                        doc_type = metadata.get("type")

                        # 只处理 type="context" 的文档（包含摘要信息）
                        if doc_type == "context":
                            title = metadata.get("title", "")
                            if title:
                                # page_content 就是 summary
                                chapter_summaries[title] = doc.page_content
                                # metadata 中的其他信息
                                chapter_refactors[title] = metadata.get("refactor", "")
                                raw_data_dict[title] = metadata.get("raw_data", {})

                    state["chapter_summaries"] = chapter_summaries
                    state["chapter_refactors"] = chapter_refactors
                    state["raw_data_dict"] = raw_data_dict

                    logger.info(f"   📥 已从 Vector DB 加载: {len(chapter_summaries)} 个章节摘要")
                    logger.info(f"   ⏭️  process_chapters 和 build_index 都将跳过")
                else:
                    logger.warning(f"⚠️  [CheckCache] Vector DB 加载后为空")
                    stage_status["build_index"]["skip"] = False
                    stage_status["process_chapters"]["skip"] = False

            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 从 Vector DB 加载数据失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                # 加载失败，不跳过这两个阶段
                stage_status["build_index"]["skip"] = False
                stage_status["process_chapters"]["skip"] = False
                logger.info(f"   ❌ 需要重新执行 process_chapters 和 build_index")
        else:
            logger.info(f"❌ [CheckCache] build_index: Vector DB不存在，需要执行")
            logger.info(f"❌ [CheckCache] process_chapters: 需要执行")

        # 6. 检查 generate_summary 阶段
        if Path(summary_txt_path).exists():
            logger.info(f"✅ [CheckCache] generate_summary: 摘要文件存在")
            stage_status["generate_summary"]["skip"] = True
            stage_status["generate_summary"]["files"] = [summary_txt_path]

            try:
                with open(summary_txt_path, 'r', encoding='utf-8') as f:
                    brief_summary = f.read()
                state["brief_summary"] = brief_summary
                logger.info(f"   📥 已加载摘要: {len(brief_summary)} 字符")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 摘要加载失败: {e}")
                stage_status["generate_summary"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] generate_summary: 摘要文件不存在，需要执行")

        # 保存阶段状态到 state
        state["stage_status"] = stage_status
        logger.debug(f"🔍 [CheckCache] 保存到 state 的 stage_status: {stage_status}")

        # 统计信息
        skip_count = sum(1 for s in stage_status.values() if s["skip"])
        total_count = len(stage_status)
        logger.info(f"\n🔍 [CheckCache] 检查完成: {skip_count}/{total_count} 个阶段可跳过")

        # 详细输出每个阶段的状态
        for stage_name, status_info in stage_status.items():
            skip_status = "✅ 跳过" if status_info["skip"] else "❌ 执行"
            logger.debug(f"   {stage_name}: {skip_status}")

        # 更新 registry 状态（同步已有文件）
        for stage_name, status_info in stage_status.items():
            if status_info["skip"]:
                self.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name=stage_name,
                    status="completed",
                    output_files=status_info["files"]
                )

        return state

    async def extract_structure(self, state: IndexingState) -> IndexingState:
        """
        步骤2：提取文档目录结构

        策略：
        1. 先尝试从前 5-10 页提取目录（快速）
        2. 如果没找到，分析全文结构（慢但全面）
        """
        logger.info(f"📚 [ExtractStructure] ========== 步骤2: 提取文档结构 ==========")
        logger.info(f"📚 [ExtractStructure] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        logger.debug(f"🔍 [ExtractStructure] stage_status = {stage_status}")
        extract_status = stage_status.get("extract_structure", {})
        logger.debug(f"🔍 [ExtractStructure] extract_structure status = {extract_status}")
        should_skip = extract_status.get("skip", False)
        logger.debug(f"🔍 [ExtractStructure] should_skip = {should_skip}")
        if should_skip:
            logger.info(f"⏭️  [ExtractStructure] 已有缓存数据，跳过结构提取")
            logger.info(f"📚 [ExtractStructure] 已有 {len(state.get('agenda_dict', {}))} 个章节")
            return state

        logger.info(f"📚 [ExtractStructure] 开始提取文档结构...")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        # 仅PDF类型需要提取结构
        if doc_type != "pdf":
            logger.info("非PDF文档，跳过结构提取")
            state["has_toc"] = False
            state["agenda_dict"] = {}
            return state

        # 定义结构文件路径（使用文档文件夹）
        doc_json_folder = os.path.join(self.json_data_path, doc_name)
        structure_json_path = os.path.join(doc_json_folder, "structure.json")

        try:
            pdf_data_list = state.get("pdf_data_list", [])
            if not pdf_data_list:
                logger.warning("PDF数据为空，无法提取结构")
                state["has_toc"] = False
                state["agenda_dict"] = {}
                return state

            # 策略1：尝试从前几页快速提取目录
            logger.info("🚀 [ExtractStructure] 策略1: 尝试从前10页提取目录")
            agenda_dict, has_toc = await self.extract_toc_from_pages_impl(
                pdf_data_list,
                max_pages=10
            )

            if has_toc and agenda_dict:
                # 成功找到目录
                logger.info(f"✅ [ExtractStructure] 检测到目录结构: {len(agenda_dict)} 个章节")
                state["agenda_dict"] = agenda_dict
                state["has_toc"] = True
            else:
                # 策略2：没找到目录，分析全文结构
                logger.info("🔍 [ExtractStructure] 策略2: 分析全文结构")
                agenda_dict = await self.analyze_full_structure_impl(pdf_data_list)

                state["agenda_dict"] = agenda_dict
                state["has_toc"] = False
                logger.info(f"✅ [ExtractStructure] 全文分析完成: {len(agenda_dict)} 个章节")

            # 打印目录信息
            logger.info("📑 [ExtractStructure] 文档目录结构:")
            for title, pages in list(state["agenda_dict"].items())[:5]:
                logger.info(f"  - {title}: 第 {pages[0]}-{pages[-1]} 页")
            if len(state["agenda_dict"]) > 5:
                logger.info(f"  ... 还有 {len(state['agenda_dict']) - 5} 个章节")

            # 保存结构数据到文件
            structure_data = {
                "agenda_dict": state["agenda_dict"],
                "has_toc": state["has_toc"]
            }
            try:
                os.makedirs(os.path.dirname(structure_json_path), exist_ok=True)
                with open(structure_json_path, 'w', encoding='utf-8') as f:
                    json.dump(structure_data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 [ExtractStructure] 结构数据已保存: {structure_json_path}")
            except Exception as e:
                logger.warning(f"⚠️  [ExtractStructure] 保存结构数据失败: {e}")

            # 更新阶段状态
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="extract_structure",
                status="completed",
                output_files=[structure_json_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [ExtractStructure] 结构提取失败: {e}")
            # 失败时设置默认值
            state["has_toc"] = False
            state["agenda_dict"] = {}

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="extract_structure",
                status="failed",
                output_files=[]
            )

            return state

    async def parse_document(self, state: IndexingState) -> IndexingState:
        """
        步骤1：解析文档内容

        根据 check_cache 设置的标志决定是否跳过
        """
        logger.info(f"📄 [Parse] ========== 步骤1: 解析文档 ==========")
        logger.info(f"📄 [Parse] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("parse", {}).get("skip"):
            logger.info(f"⏭️  [Parse] 已有缓存数据，跳过解析")
            state["status"] = "parsed"
            return state

        logger.info(f"📄 [Parse] 开始解析文档...")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        try:
            doc_path = state["doc_path"]

            # 初始化 generated_files（如果不存在）
            if "generated_files" not in state:
                state["generated_files"] = {
                    "images": [],
                    "json_data": "",
                    "vector_db": "",
                    "summaries": []
                }
                logger.debug(f"📄 [Parse] 初始化 generated_files")

            if doc_type == "pdf":
                # 使用实际的PDF提取功能
                logger.info(f"📄 [Parse] 使用PDF提取器处理: {doc_path}")

                # doc_name 已经是不含扩展名的文件名，直接使用
                pdf_file_name = doc_name
                logger.info(f"📄 [Parse] PDF文件名（无扩展名）: {pdf_file_name}")

                # 提取PDF数据（返回包含所有信息的字典，避免重复读取）
                logger.info(f"📄 [Parse] 开始调用 extract_pdf_data_impl...")
                extract_result = await self.extract_pdf_data_impl(pdf_file_name)
                logger.info(f"📄 [Parse] PDF数据提取完成")

                pdf_data_list = extract_result["pdf_data_list"]
                if not pdf_data_list:
                    raise ValueError(f"PDF提取失败，未获取任何数据: {doc_path}")

                # 将提取的数据转换为原始文本
                raw_data = "\n\n".join([
                    f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}"
                    for i, item in enumerate(pdf_data_list)
                ])

                # 创建 json_data_dict（以页码为key）
                json_data_dict = {
                    str(item.get("page", i+1)): item.get("data", "")
                    for i, item in enumerate(pdf_data_list)
                }

                # 直接在 state 上修改
                state["raw_data"] = raw_data
                state["pdf_data_list"] = pdf_data_list  # 保存原始数据供后续使用
                state["json_data_dict"] = json_data_dict  # 页码为key的数据字典
                state["generated_files"]["images"] = extract_result["image_paths"]
                state["generated_files"]["json_data"] = extract_result["json_path"]
                state["status"] = "parsed"

                logger.info(f"✅ [Parse] PDF解析完成，提取 {len(pdf_data_list)} 页，总长度: {len(raw_data)} 字符")
                logger.info(f"📁 [Parse] 生成文件: 图片{len(state['generated_files']['images'])}个, JSON: {state['generated_files']['json_data']}")

                # 更新阶段状态
                image_folder = extract_result.get("image_folder", "")
                json_path = extract_result.get("json_path", "")
                output_files = []
                if image_folder:
                    output_files.append(image_folder)
                if json_path:
                    output_files.append(json_path)

                self.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name="parse",
                    status="completed",
                    output_files=output_files
                )

            elif doc_type == "url":
                # TODO: 使用WebReader提取内容
                logger.warning("URL类型文档暂未实现，使用占位符")
                state["raw_data"] = f"Web content from {doc_path}"
                state["status"] = "parsed"

            else:
                raise ValueError(f"不支持的文档类型: {doc_type}")

            return state

        except Exception as e:
            logger.error(f"❌ [Parse] 解析失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="parse",
                status="failed",
                output_files=[]
            )

            return state

    async def chunk_text(self, state: IndexingState) -> IndexingState:
        """
        步骤3：构建章节数据列表

        直接基于 extract_structure 得到的 agenda_dict 构建 agenda_data_list
        """
        logger.info(f"📦 [Chunk] ========== 步骤3: 构建章节数据列表 ==========")
        logger.info(f"📦 [Chunk] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("chunk_text", {}).get("skip"):
            logger.info(f"⏭️  [Chunk] 已有缓存数据，跳过章节数据构建")
            logger.info(f"📦 [Chunk] 已有 {len(state.get('agenda_data_list', []))} 个章节")
            return state

        logger.info(f"📦 [Chunk] 开始构建章节数据...")

        doc_name = state["doc_name"]

        # 定义章节数据文件路径（使用文档文件夹）
        doc_json_folder = os.path.join(self.json_data_path, doc_name)
        chunk_json_path = os.path.join(doc_json_folder, "chunks.json")

        try:
            agenda_dict = state.get("agenda_dict", {})
            json_data_dict = state.get("json_data_dict", {})

            if not agenda_dict:
                logger.warning("agenda_dict 为空，无法构建章节数据")
                state["agenda_data_list"] = []
                state["status"] = "chunked"
                return state

            if not json_data_dict:
                logger.warning("json_data_dict 为空，无法构建章节数据")
                state["agenda_data_list"] = []
                state["status"] = "chunked"
                return state

            # 直接基于 agenda_dict 构建 agenda_data_list
            agenda_data_list = []

            for title, page_numbers in agenda_dict.items():
                # 收集该章节的所有页面数据
                chapter_data = {}

                for page_num in page_numbers:
                    page_key = str(page_num)
                    if page_key in json_data_dict:
                        chapter_data[page_key] = json_data_dict[page_key]
                    else:
                        logger.warning(f"页码 {page_key} 不在 json_data_dict 中")

                if chapter_data:
                    agenda_data_list.append({
                        "title": title,
                        "data": chapter_data,
                        "pages": page_numbers
                    })
                else:
                    logger.warning(f"章节 '{title}' 没有找到对应的数据")

            logger.info(f"✅ [Chunk] 章节数据构建完成: {len(agenda_data_list)} 个章节")

            # 打印章节信息
            for item in agenda_data_list:
                title = item.get("title", "未知")
                pages = item.get("pages", [])
                data_pages = len(item.get("data", {}))
                logger.info(f"  - {title}: {len(pages)} 页 (实际数据: {data_pages} 页)")

            # 保存章节数据到文件
            try:
                os.makedirs(os.path.dirname(chunk_json_path), exist_ok=True)
                with open(chunk_json_path, 'w', encoding='utf-8') as f:
                    json.dump(agenda_data_list, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 [Chunk] 章节数据已保存: {chunk_json_path}")
            except Exception as e:
                logger.warning(f"⚠️  [Chunk] 保存章节数据失败: {e}")

            # 直接在 state 上修改
            state["agenda_data_list"] = agenda_data_list
            state["status"] = "chunked"

            # 更新阶段状态
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="chunk_text",
                status="completed",
                output_files=[chunk_json_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Chunk] 章节数据构建失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="chunk_text",
                status="failed",
                output_files=[]
            )

            return state

    async def process_chapters(self, state: IndexingState) -> IndexingState:
        """
        步骤4：处理章节（并行生成摘要和重构内容）

        对每个章节：
        1. 生成摘要（summary）
        2. 重构内容（refactor）
        """
        logger.info(f"📝 [ProcessChapters] ========== 步骤4: 处理章节 ==========")
        logger.info(f"📝 [ProcessChapters] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("process_chapters", {}).get("skip"):
            logger.info(f"⏭️  [ProcessChapters] 已有缓存数据，跳过章节处理")
            logger.info(f"📝 [ProcessChapters] 已有 {len(state.get('chapter_summaries', {}))} 个章节摘要")
            return state

        logger.info(f"📝 [ProcessChapters] 开始处理章节...")

        doc_name = state["doc_name"]

        # 注意：章节处理结果不再保存到单独文件，而是直接在 build_index 阶段存入 vector db

        try:
            agenda_data_list = state.get("agenda_data_list", [])
            logger.info(f"📝 [ProcessChapters] 章节数量: {len(agenda_data_list)}")

            if not agenda_data_list:
                logger.warning("📝 [ProcessChapters] ⚠️ agenda_data_list 为空，跳过章节处理")
                state["chapter_summaries"] = {}
                state["chapter_refactors"] = {}
                state["raw_data_dict"] = {}
                state["status"] = "summarized"
                return state

            # 使用并行处理工具
            from src.core.processing.parallel_processor import ChapterProcessor
            from src.config.prompts.reader_prompts import ReaderRole

            logger.info(f"开始并行处理 {len(agenda_data_list)} 个章节...")

            # 直接使用异步方法（因为当前已经在async上下文中）
            processor = ChapterProcessor(self.llm, max_concurrent=10)
            chapter_results = await processor.process_chapters_summary_and_refactor(
                agenda_data_list=agenda_data_list,
                summary_role=ReaderRole.CONTENT_SUMMARY,
                refactor_role=ReaderRole.CONTENT_MERGE
            )

            # 处理结果
            chapter_summaries = {}
            chapter_refactors = {}
            raw_data_dict = {}

            for title, summary, refactor_content, _, data in chapter_results:
                chapter_summaries[title] = summary
                chapter_refactors[title] = refactor_content
                raw_data_dict[title] = data

                logger.info(f"✅ 章节处理完成: {title}")

            logger.info(f"✅ [ProcessChapters] 所有章节处理完成: {len(chapter_summaries)} 个章节")
            logger.info(f"📌 [ProcessChapters] 数据将在 build_index 阶段存入 Vector DB")

            # 直接在 state 上修改
            state["chapter_summaries"] = chapter_summaries
            state["chapter_refactors"] = chapter_refactors
            state["raw_data_dict"] = raw_data_dict
            state["status"] = "summarized"

            # 更新阶段状态（数据存储在 vector db 中，无单独文件）
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="process_chapters",
                status="completed",
                output_files=[]  # 数据在 vector db 中
            )

            return state

        except Exception as e:
            logger.error(f"❌ [ProcessChapters] 章节处理失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="process_chapters",
                status="failed",
                output_files=[]
            )

            return state

    async def generate_brief_summary(self, state: IndexingState) -> IndexingState:
        """
        步骤6：生成简要摘要（基于所有章节摘要）

        这是最后一步摘要生成，整合所有章节的摘要
        """
        logger.info(f"📝 [BriefSummary] ========== 步骤6: 生成简要摘要 ==========")
        logger.info(f"📝 [BriefSummary] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("generate_summary", {}).get("skip"):
            logger.info(f"⏭️  [BriefSummary] 已有摘要文件，跳过生成")
            logger.info(f"📝 [BriefSummary] 摘要长度: {len(state.get('brief_summary', ''))} 字符")
            return state

        logger.info(f"📝 [BriefSummary] 开始生成简要摘要...")

        doc_name = state["doc_name"]

        # 定义摘要文件路径
        from src.config.settings import DATA_ROOT
        summary_txt_path = os.path.join(DATA_ROOT, "output", f"{doc_name}_brief_summary.md")

        try:
            chapter_summaries = state.get("chapter_summaries", {})
            logger.info(f"📝 [BriefSummary] 章节摘要数量: {len(chapter_summaries)}")

            if not chapter_summaries:
                logger.warning("章节摘要为空，无法生成简要摘要")
                state["brief_summary"] = ""
                return state

            # 复用 generate_summary_impl，传入章节摘要
            answer = await self.generate_summary_impl(
                context_data=chapter_summaries,
                doc_name=doc_name,
                session_id="brief_summary"
            )

            logger.info(f"✅ [BriefSummary] 简要摘要生成完成，长度: {len(answer)} 字符")

            # 保存摘要到文件
            try:
                os.makedirs(os.path.dirname(summary_txt_path), exist_ok=True)
                with open(summary_txt_path, 'w', encoding='utf-8') as f:
                    f.write(answer)
                logger.info(f"💾 [BriefSummary] 简要摘要已保存: {summary_txt_path}")

                # 更新 generated_files
                if "generated_files" not in state:
                    state["generated_files"] = {"images": [], "json_data": "", "vector_db": "", "summaries": []}
                if "summaries" not in state["generated_files"]:
                    state["generated_files"]["summaries"] = []
                state["generated_files"]["summaries"].append(summary_txt_path)

            except Exception as e:
                logger.warning(f"⚠️  [BriefSummary] 保存简要摘要失败: {e}")

            # 直接在 state 上修改
            state["brief_summary"] = answer

            # 更新阶段状态
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="generate_summary",
                status="completed",
                output_files=[summary_txt_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [BriefSummary] 简要摘要生成失败: {e}")
            state["brief_summary"] = f"文档 {state['doc_name']} 的简要摘要（生成错误: {str(e)}）"

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="generate_summary",
                status="failed",
                output_files=[]
            )

            return state

    async def build_index(self, state: IndexingState) -> IndexingState:
        """
        步骤5：构建向量索引

        基于章节摘要构建 Document 对象：
        1. type="context": 章节摘要作为检索内容
        2. type="title": 章节标题作为检索内容
        3. type="structure": 文档结构信息
        """
        logger.info(f"🔨 [BuildIndex] ========== 步骤5: 构建向量索引 ==========")
        logger.info(f"🔨 [BuildIndex] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("build_index", {}).get("skip"):
            logger.info(f"⏭️  [BuildIndex] 已有 Vector DB，跳过构建")
            logger.info(f"🔨 [BuildIndex] Vector DB 路径: {state.get('index_path')}")
            state["status"] = "indexed"
            return state

        logger.info(f"🔨 [BuildIndex] 开始构建向量索引...")

        doc_name = state["doc_name"]

        # 构建索引路径
        from pathlib import Path
        from src.config.settings import DATA_ROOT
        index_path = str(Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index")

        try:
            from langchain.docstore.document import Document
            from src.core.vector_db.vector_db_client import VectorDBClient

            chapter_summaries = state.get("chapter_summaries", {})
            chapter_refactors = state.get("chapter_refactors", {})
            raw_data_dict = state.get("raw_data_dict", {})
            agenda_dict = state.get("agenda_dict", {})

            if not chapter_summaries:
                logger.warning("章节摘要为空，无法构建索引")
                state["status"] = "error"
                state["error"] = "章节摘要为空"
                return state

            # 构建 Document 列表
            vector_db_docs = []

            logger.info("开始构建 Document 对象...")

            # 遍历每个章节
            for title, summary in chapter_summaries.items():
                refactor_content = chapter_refactors.get(title, "")
                raw_data = raw_data_dict.get(title, {})
                pages = agenda_dict.get(title, [])

                # Document 1: type="context" - 摘要作为检索内容
                vector_db_docs.append(
                    Document(
                        page_content=summary,
                        metadata={
                            "type": "context",
                            "title": title,
                            "pages": pages,
                            "raw_data": raw_data,
                            "refactor": refactor_content,
                        }
                    )
                )

                # Document 2: type="title" - 标题作为检索内容
                vector_db_docs.append(
                    Document(
                        page_content=title,
                        metadata={
                            "type": "title",
                            "pages": pages,
                            "summary": summary,
                            "raw_data": raw_data,
                            "refactor": refactor_content,
                        }
                    )
                )

            # Document 3: type="structure" - 文档结构信息
            structure_doc = Document(
                page_content="Document Structure",
                metadata={
                    "type": "structure",
                    "agenda_dict": agenda_dict,
                    "doc_name": doc_name,
                    "total_chapters": len(agenda_dict)
                }
            )
            vector_db_docs.append(structure_doc)

            logger.info(f"Document 对象构建完成: {len(vector_db_docs)} 个文档")

            # 构建索引路径
            index_dir = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
            index_dir.mkdir(parents=True, exist_ok=True)
            index_path = str(index_dir)

            # 创建 VectorDBClient 并构建向量数据库
            vector_db_client = VectorDBClient(index_path, embedding_model=self.embedding_model)
            vector_db_client.build_vector_db(vector_db_docs)

            logger.info(f"✅ [BuildIndex] 向量数据库构建完成: {index_path}")

            # 直接在 state 上修改
            state["index_path"] = index_path
            state["vector_db_docs"] = vector_db_docs
            if "generated_files" not in state:
                state["generated_files"] = {
                    "images": [],
                    "json_data": "",
                    "vector_db": "",
                    "summaries": []
                }
            state["generated_files"]["vector_db"] = index_path
            state["status"] = "indexed"

            # 更新阶段状态
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="build_index",
                status="completed",
                output_files=[index_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [BuildIndex] 索引构建失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="build_index",
                status="failed",
                output_files=[]
            )
            return state

    # ==================== 批量处理和管理方法 ====================

    async def process_documents_batch(
        self,
        doc_list: List[Dict[str, Any]],
        max_concurrent: int = 3
    ) -> List[Dict[str, Any]]:
        """
        批量处理文档列表

        Args:
            doc_list: 文档列表，每个元素格式：
                {
                    "doc_name": str,
                    "doc_path": str,
                    "doc_type": "pdf" | "url"
                }
            max_concurrent: 最大并发处理数

        Returns:
            处理结果列表
        """
        import asyncio

        logger.info(f"📦 开始批量处理文档: 共 {len(doc_list)} 个文档")

        results = []

        # 分批处理避免过载
        for i in range(0, len(doc_list), max_concurrent):
            batch = doc_list[i:i + max_concurrent]
            logger.info(f"处理第 {i // max_concurrent + 1} 批: {len(batch)} 个文档")

            # 并发处理当前批次
            tasks = []
            for doc_info in batch:
                # 构建初始状态
                state = {
                    "doc_name": doc_info["doc_name"],
                    "doc_path": doc_info["doc_path"],
                    "doc_type": doc_info["doc_type"],
                    "status": "pending"
                }
                # 创建处理任务
                task = self.graph.ainvoke(state)
                tasks.append(task)

            # 等待当前批次完成
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for j, result in enumerate(batch_results):
                doc_name = batch[j]["doc_name"]
                if isinstance(result, Exception):
                    logger.error(f"❌ 文档处理失败: {doc_name}, 错误: {result}")
                    results.append({
                        "doc_name": doc_name,
                        "status": "error",
                        "error": str(result)
                    })
                else:
                    logger.info(f"✅ 文档处理完成: {doc_name}, 状态: {result.get('status')}")
                    results.append(result)

        logger.info(f"✅ 批量处理完成: 成功 {sum(1 for r in results if r.get('status') == 'completed')} 个, 失败 {sum(1 for r in results if r.get('status') == 'error')} 个")

        return results

    def delete_document(self, doc_id: str, delete_source: bool = False) -> Dict[str, Any]:
        """
        删除文档及其所有关联文件

        Args:
            doc_id: 文档ID
            delete_source: 是否删除源文件

        Returns:
            删除结果字典
        """
        logger.info(f"🗑️ 删除文档: {doc_id}, 删除源文件: {delete_source}")

        result = self.doc_registry.delete_all_files(doc_id, delete_source=delete_source)

        if result["success"]:
            logger.info(f"✅ 文档删除成功: 删除 {len(result['deleted_files'])} 个文件")
        else:
            logger.error(f"❌ 文档删除部分失败: 成功 {len(result['deleted_files'])} 个, 失败 {len(result['failed_files'])} 个")

        return result

    def list_documents(self, **filters) -> List[Dict]:
        """
        列出所有文档

        Args:
            **filters: 过滤条件（可选）
                - doc_type: 文档类型过滤

        Returns:
            文档列表
        """
        all_docs = self.doc_registry.list_all()

        # 应用过滤器
        if "doc_type" in filters:
            all_docs = [d for d in all_docs if d.get("doc_type") == filters["doc_type"]]

        return all_docs

    def get_document_info(self, doc_id: str) -> Optional[Dict]:
        """
        获取文档详细信息

        Args:
            doc_id: 文档ID

        Returns:
            文档信息字典
        """
        doc_info = self.doc_registry.get(doc_id)
        if doc_info:
            # 添加文件统计信息
            file_stats = self.doc_registry.get_file_stats(doc_id)
            if file_stats:
                doc_info["file_stats"] = file_stats

        return doc_info


    def get_statistics(self) -> Dict:
        """
        获取文档统计信息

        Returns:
            统计信息字典
        """
        return self.doc_registry.get_statistics()

    # ==================== Workflow节点方法 ====================

    async def register_document(self, state: IndexingState) -> IndexingState:
        """
        步骤7：注册到文档库
        """
        logger.info(f"📋 [Register] ========== 步骤7: 注册文档 ==========")
        logger.info(f"📋 [Register] 文档名称: {state['doc_name']}")

        doc_name = state["doc_name"]

        try:
            # 注意：不在这里检查是否已存在
            # register 方法会处理更新已存在记录的逻辑
            # 获取生成的文件信息
            generated_files = state.get("generated_files", {
                "images": [],
                "json_data": "",
                "vector_db": "",
                "summaries": []
            })

            # 注册文档
            doc_id = self.doc_registry.register(
                doc_name=state["doc_name"],
                doc_path=state["doc_path"],
                doc_type=state["doc_type"],
                index_path=state.get("index_path", ""),
                brief_summary=state.get("brief_summary", ""),
                metadata={},
                generated_files=generated_files
            )

            logger.info(f"✅ [Register] 文档注册完成: {doc_id}")
            logger.info(f"📁 [Register] 关联文件统计:")
            logger.info(f"  - 图片: {len(generated_files.get('images', []))} 个")
            logger.info(f"  - JSON: {1 if generated_files.get('json_data') else 0} 个")
            logger.info(f"  - 向量DB: {1 if generated_files.get('vector_db') else 0} 个")
            logger.info(f"  - 摘要: {len(generated_files.get('summaries', []))} 个")

            # 直接在 state 上修改
            state["doc_id"] = doc_id
            state["status"] = "completed"
            state["is_complete"] = True  # ✅ 设置完成标志

            # 更新阶段状态 (注册阶段完成就意味着整个流程完成)
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="register",
                status="completed",
                output_files=[]  # 注册本身不生成文件
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Register] 文档注册失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="register",
                status="failed",
                output_files=[]
            )

            return state
