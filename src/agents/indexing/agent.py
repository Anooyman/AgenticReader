"""
Indexing Agent - 文档索引构建Agent

负责文档的解析、摘要生成、标签分类、向量索引构建和文档注册
"""

from langgraph.graph import StateGraph, END
from typing import Any, Callable, Dict, Optional
import inspect
import logging
import traceback

from ..base import AgentBase
from .state import IndexingState
from src.core.document_management import DocumentRegistry
from .tools import IndexingTools
from .nodes import IndexingNodes

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
        # 初始化基类（self.llm 就绪；embedding 客户端改为首次使用时才构造）
        super().__init__(name="IndexingAgent", provider=provider)

        self.doc_registry = DocumentRegistry()

        # 初始化功能模块（使用依赖注入）
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

    async def index_document(
        self,
        doc_name: str,
        doc_path: str,
        doc_type: str = "pdf",
        *,
        pdf_preset: Optional[str] = None,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, Any]:
        """
        索引一个文档（唯一对外入口，内部跑已编译的主图）

        5 个调用方（core/document_management/indexer.py、UI documents.py /
        data.py、SearchAgent.call_indexing_agent、pipeline/process_pdf_queue.py）
        的初始 state 语义并集集中在这里构造，调用方不再手拼 state、也不再
        直接碰 self.graph——历史上手拼漏 doc_type 会让 parse 节点直接抛
        "不支持的文档类型: None"，漏后缀/漏字段则是同类缺陷的根源。

        Args:
            doc_name: 文档名（不含扩展名，调用方自行去掉 .pdf）
            doc_path: 文档路径。doc_type="pdf" 时是 PDF 文件路径；
                doc_type="url" 时是 SearchAgent.save_web_content() 产出的 JSON 路径
            doc_type: "pdf" | "url"
            pdf_preset: 可选，覆盖构造期的 PDF 转图片预设
                （'fast'/'balanced'/'high'/'ultra'）；为 None 时沿用构造期配置
            progress_callback: 可选的进度回调，签名 ``cb(stage: str, progress: int,
                message: str = "")``，同步或异步均可。只上报阶段，UI 侧写
                task_service 的落库逻辑留在调用方回调里，不塞进 agent。

        Returns:
            {
                "is_complete": bool,   # 整图是否成功跑完（register 的守卫保证
                                       # 失败文档不会被标成 completed）
                "index_path": str,     # 向量库目录（见 constants.get_vector_db_path）
                "doc_id": str,         # DocumentRegistry 里的文档 ID
                "error": str | None,   # 失败原因，成功时为 None
                "status": str,         # 图最终 status（completed / error / ...）
                "brief_summary": str,  # 便于 CLI 打印
                "agenda_dict": dict,   # 便于 CLI 打印章节数
            }
        """
        if pdf_preset:
            # 调用期覆盖构造期配置（重跑一次目录/预设准备，幂等）
            self._setup_pdf_config(pdf_preset)

        async def _notify(stage: str, progress: int, message: str = "") -> None:
            """进度上报（回调异常绝不影响索引主流程）"""
            if progress_callback is None:
                return
            try:
                outcome = progress_callback(stage, progress, message)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception as cb_e:  # noqa: BLE001 - 进度上报失败不应影响索引
                logger.warning(f"[IndexDocument] 进度回调异常({stage}): {cb_e}")

        initial_state: IndexingState = {
            "doc_name": doc_name,
            "doc_path": doc_path,
            "doc_type": doc_type,
            "status": "pending",
            "is_complete": False,
            "error": None,
        }

        logger.info(f"🚀 [IndexDocument] 开始索引: {doc_name} (type={doc_type})")
        await _notify("start", 0, doc_name)

        try:
            await _notify("graph", 10, doc_name)
            result_state = await self.graph.ainvoke(initial_state)
        except Exception as e:
            logger.error(f"❌ [IndexDocument] 索引异常: {doc_name}: {e}")
            logger.error(traceback.format_exc())
            await _notify("error", 100, str(e))
            return {
                "is_complete": False,
                "index_path": "",
                "doc_id": "",
                "error": str(e),
                "status": "error",
                "brief_summary": "",
                "agenda_dict": {},
            }

        error = result_state.get("error")
        is_complete = bool(result_state.get("is_complete", False))
        message = error or f"索引完成: {doc_name}"
        await _notify("error" if error or not is_complete else "done", 100, message)

        if error:
            logger.error(f"❌ [IndexDocument] 索引失败: {doc_name}: {error}")
        elif not is_complete:
            logger.warning(f"⚠️  [IndexDocument] 索引未完成: {doc_name}")
        else:
            logger.info(f"✅ [IndexDocument] 索引完成: {doc_name}")

        return {
            "is_complete": is_complete,
            "index_path": result_state.get("index_path", "") or "",
            "doc_id": result_state.get("doc_id", "") or "",
            "error": error,
            "status": result_state.get("status", "") or "",
            "brief_summary": result_state.get("brief_summary", "") or "",
            "agenda_dict": result_state.get("agenda_dict", {}) or {},
        }

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
