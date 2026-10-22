"""
Indexing Agent - 文档索引构建Agent

负责文档的解析、摘要生成、标签分类、向量索引构建和文档注册
"""

from langgraph.graph import StateGraph, END
from typing import Dict, List, Any, Optional
import logging

from ..base import AgentBase
from .state import IndexingState
from src.core.document_management import DocumentRegistry
from .tools import IndexingTools
from .nodes import IndexingNodes
from .utils import IndexingUtils

logger = logging.getLogger(__name__)


def _route_on_error(next_node: str):
    """
    错误短路路由工厂：state 中存在 error 时直接跳到 register 节点
    （register 内部有守卫，不会把失败文档注册为 completed），否则走正常下一节点
    """
    def router(state: IndexingState) -> str:
        if state.get("error"):
            logger.warning(f"⚠️ [Graph] 检测到错误，跳过后续生成类节点，直达 register: {state['error']}")
            return "register"
        return next_node
    return router


class IndexingAgent(AgentBase):
    """
    索引构建Agent

    工作流程：
    check_cache → parse → extract_structure → chunk →
    process_chapters → build_index → generate_brief_summary → register

    职责：
    - 解析PDF文档并提取文本
    - 提取文档目录结构
    - 生成章节摘要和重构内容
    - 构建向量索引
    - 注册文档到文档库
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

        # 初始化功能模块（使用依赖注入）
        self.utils = IndexingUtils(self)
        self.tools = IndexingTools(self)
        self.nodes = IndexingNodes(self)

        # PDF 处理相关配置
        self._setup_pdf_config(pdf_preset)

        # 构建workflow
        self.graph = self.build_graph()
        self.rebuild_graph = self.build_rebuild_graph()

    def _setup_pdf_config(self, pdf_preset: str):
        """
        配置PDF转图片参数

        Args:
            pdf_preset: 质量预设名称
        """
        from src.config.settings import (
            PDF_IMAGE_PATH,
            PDF_PATH,
            JSON_DATA_PATH,
            PDF_IMAGE_CONFIG,
        )
        from src.config.constants import ReaderConstants
        from src.utils.helpers import makedir

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

        # 添加节点（委托给 nodes 模块）
        workflow.add_node("check_cache", self.nodes.check_cache)
        workflow.add_node("parse", self.nodes.parse_document)
        workflow.add_node("extract_structure", self.nodes.extract_structure)
        workflow.add_node("chunk", self.nodes.chunk_text)
        workflow.add_node("process_chapters", self.nodes.process_chapters)
        workflow.add_node("build_index", self.nodes.build_index)
        workflow.add_node("generate_brief_summary", self.nodes.generate_brief_summary)
        workflow.add_node("register", self.nodes.register_document)

        # 添加边 - 线性流程，每个节点内部根据标志决定是否跳过；
        # 高风险节点（parse/extract/chunk/process/build）后加错误短路：
        # state 有 error 时跳过剩余生成类节点直达 register（register 内有守卫）
        workflow.add_edge("check_cache", "parse")
        workflow.add_conditional_edges("parse", _route_on_error("extract_structure"),
                                        {"extract_structure": "extract_structure", "register": "register"})
        workflow.add_conditional_edges("extract_structure", _route_on_error("chunk"),
                                        {"chunk": "chunk", "register": "register"})
        workflow.add_conditional_edges("chunk", _route_on_error("process_chapters"),
                                        {"process_chapters": "process_chapters", "register": "register"})
        workflow.add_conditional_edges("process_chapters", _route_on_error("build_index"),
                                        {"build_index": "build_index", "register": "register"})
        workflow.add_conditional_edges("build_index", _route_on_error("generate_brief_summary"),
                                        {"generate_brief_summary": "generate_brief_summary", "register": "register"})
        workflow.add_edge("generate_brief_summary", "register")
        workflow.add_edge("register", END)

        # 设置入口
        workflow.set_entry_point("check_cache")

        return workflow.compile()

    def build_rebuild_graph(self) -> StateGraph:
        """
        构建重建专用工作流

        假设条件：
        - data.json 已存在（PDF 原始数据）
        - structure.json 已存在（手动编辑的结构）
        - 旧的生成文件已被删除

        执行流程：
        1. chunk_text - 基于新 structure 重建章节数据
        2. process_chapters - 重新处理所有章节（摘要+重构）
        3. build_index - 重建向量数据库
        4. generate_brief_summary - 重新生成文档摘要
        5. register_document - 更新文档注册信息

        Returns:
            编译后的 StateGraph
        """
        workflow = StateGraph(IndexingState)

        # 只添加重建需要的节点
        workflow.add_node("chunk", self.nodes.chunk_text)
        workflow.add_node("process_chapters", self.nodes.process_chapters)
        workflow.add_node("build_index", self.nodes.build_index)
        workflow.add_node("generate_brief_summary", self.nodes.generate_brief_summary)
        workflow.add_node("register", self.nodes.register_document)

        # 线性流程（与主图一致：节点后加错误短路，有 error 直达 register）
        workflow.add_conditional_edges("chunk", _route_on_error("process_chapters"),
                                        {"process_chapters": "process_chapters", "register": "register"})
        workflow.add_conditional_edges("process_chapters", _route_on_error("build_index"),
                                        {"build_index": "build_index", "register": "register"})
        workflow.add_conditional_edges("build_index", _route_on_error("generate_brief_summary"),
                                        {"generate_brief_summary": "generate_brief_summary", "register": "register"})
        workflow.add_edge("generate_brief_summary", "register")
        workflow.add_edge("register", END)

        # 从 chunk 开始
        workflow.set_entry_point("chunk")

        return workflow.compile()

    # ==================== 对外接口方法 ====================

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
        return await self.tools.process_documents_batch(doc_list, max_concurrent)

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

    async def rebuild_from_structure(
        self,
        doc_name: str,
        doc_path: str
    ) -> Dict[str, Any]:
        """
        基于已有的 structure.json 重建文档数据

        保持不变的文件：
        - structure.json: 手动编辑的结构
        - data.json: PDF 原始数据
        - pdf_image/: PDF 图片文件

        重新生成的内容：
        - chunks.json: 基于新结构重建章节数据
        - 章节摘要: 重新生成所有章节的摘要和重构内容
        - 向量数据库: 完全重建 FAISS 索引
        - 简要摘要: 重新生成整体文档摘要

        Args:
            doc_name: 文档名称
            doc_path: 文档路径

        Returns:
            重建结果字典
        """
        return await self.tools.rebuild_from_structure(doc_name, doc_path)
