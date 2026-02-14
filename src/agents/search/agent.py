"""
SearchAgent - 网络搜索与URL内容分析Agent

支持两种使用场景：
1. 搜索引擎检索：通过搜索引擎获取最新信息
2. 指定URL分析：分析特定网页内容，支持智能索引决策
"""

from langgraph.graph import StateGraph, END
from typing import Optional, Dict
import logging

from ..base import AgentBase
from .state import SearchState
from .tools import SearchTools
from .nodes import SearchNodes
from .utils import SearchUtils

logger = logging.getLogger(__name__)


class SearchAgent(AgentBase):
    """
    SearchAgent - 网络搜索与内容分析Agent

    工作流程：
    1. initialize → 初始化环境
    2. analyze_query → 分析查询类型（search vs url_analysis）
    3. route_by_use_case → 根据类型路由

    Use Case 1 (搜索引擎检索):
        web_search → select_urls → scrape_content → extract_and_merge → evaluate → format

    Use Case 2 (URL分析):
        scrape_content → evaluate_content_size → extract_and_merge → evaluate → format
                                ↓ (如果需要索引)
                        call_indexing_agent → 基于索引对话
    """

    def __init__(self, provider: str = 'openai', progress_callback=None):
        """
        初始化 SearchAgent

        Args:
            provider: LLM provider ("openai", "azure", "ollama")
            progress_callback: 进度回调函数（可选）
        """
        super().__init__(name="SearchAgent", provider=provider)

        # 进度回调函数
        self.progress_callback = progress_callback

        # 初始化功能模块（使用依赖注入）
        self.utils = SearchUtils(self)
        self.tools = SearchTools(self)
        self.nodes = SearchNodes(self)

        # 构建 workflow
        self.graph = self.build_graph()

        logger.info("✅ SearchAgent 初始化完成")

    # ========== Workflow 构建 ==========

    def build_graph(self) -> StateGraph:
        """构建双 use case workflow"""
        workflow = StateGraph(SearchState)

        # ========== 添加节点 ==========

        # 通用节点
        workflow.add_node("initialize", self.nodes.initialize)
        workflow.add_node("analyze_query", self.nodes.analyze_query)
        workflow.add_node("extract_and_merge", self.nodes.extract_and_merge)
        workflow.add_node("evaluate_completeness", self.nodes.evaluate_completeness)
        workflow.add_node("format_answer", self.nodes.format_answer)

        # Use Case 1: 搜索引擎检索专用节点
        workflow.add_node("web_search", self.nodes.web_search)
        workflow.add_node("select_urls", self.nodes.select_urls)

        # 共用节点
        workflow.add_node("scrape_content", self.nodes.scrape_content)

        # Use Case 2: URL分析专用节点
        workflow.add_node("evaluate_content_size", self.nodes.evaluate_content_size)

        # ========== 添加边 ==========

        # 初始化流程
        workflow.add_edge("initialize", "analyze_query")

        # 根据 use case 路由
        workflow.add_conditional_edges(
            "analyze_query",
            self.nodes.route_by_use_case,
            {
                "search": "web_search",        # Use Case 1: 搜索引擎检索
                "url_analysis": "scrape_content"  # Use Case 2: URL分析
            }
        )

        # ========== Use Case 1 路径 ==========
        workflow.add_edge("web_search", "select_urls")
        workflow.add_edge("select_urls", "scrape_content")

        # ========== Use Case 2 路径 ==========
        # scrape_content 后判断：
        # - 如果是 search 模式 → extract_and_merge
        # - 如果是 url_analysis 模式 → evaluate_content_size
        workflow.add_conditional_edges(
            "scrape_content",
            self._route_after_scrape,
            {
                "extract": "extract_and_merge",  # search 模式直接提取
                "evaluate_size": "evaluate_content_size"  # url_analysis 需要评估大小
            }
        )

        # 内容量评估后 → 提取内容
        # NOTE: 实际的索引调用会在这里处理（未来扩展）
        workflow.add_edge("evaluate_content_size", "extract_and_merge")

        # ========== 通用后续流程 ==========
        workflow.add_edge("extract_and_merge", "evaluate_completeness")

        # 评估完整性后决定：继续 or 结束
        workflow.add_conditional_edges(
            "evaluate_completeness",
            self.nodes.should_continue,
            {
                "continue": "scrape_content",  # 继续检索（重新爬取）
                "format": "format_answer"       # 生成答案
            }
        )

        # 生成答案后结束
        workflow.add_edge("format_answer", END)

        # 设置入口
        workflow.set_entry_point("initialize")

        return workflow.compile()

    def _route_after_scrape(self, state: SearchState) -> str:
        """
        爬取内容后的路由逻辑

        Args:
            state: 当前状态

        Returns:
            下一个节点名称
        """
        detected_use_case = state.get('detected_use_case', 'search')

        if detected_use_case == "url_analysis":
            # URL分析模式：需要评估内容大小
            return "evaluate_size"
        else:
            # 搜索模式：直接提取内容
            return "extract"

    # ========== 公共接口 ==========

    async def search(
        self,
        query: str,
        target_urls: Optional[list] = None,
        use_case: Optional[str] = None,
        max_iterations: int = 3
    ) -> Dict:
        """
        执行搜索任务

        Args:
            query: 用户查询/问题
            target_urls: 指定URL列表（可选，用于 url_analysis 模式）
            use_case: 使用场景 ("search" 或 "url_analysis"，可选，自动检测）
            max_iterations: 最大迭代次数

        Returns:
            包含 final_answer, sources 等的结果字典
        """
        logger.info(f"🚀 [SearchAgent] 开始搜索任务: {query}")

        # 构建初始状态
        initial_state: SearchState = {
            "query": query,
            "max_iterations": max_iterations,
            "current_iteration": 0,
            "is_complete": False
        }

        # 可选参数
        if target_urls:
            initial_state["target_urls"] = target_urls

        if use_case:
            initial_state["use_case"] = use_case

        try:
            # 执行 workflow
            final_state = await self.graph.ainvoke(initial_state)

            # 提取结果
            result = {
                "success": True,
                "query": query,
                "use_case": final_state.get('detected_use_case', 'unknown'),
                "answer": final_state.get('final_answer', ''),
                "sources": final_state.get('sources', []),
                "processing_strategy": final_state.get('processing_strategy', ''),
                "scraped_count": len(final_state.get('scraped_results', [])),
                "content_size": final_state.get('content_size', 0),
                "warnings": final_state.get('warnings', [])
            }

            # 如果有错误
            if 'error' in final_state:
                result['success'] = False
                result['error'] = final_state['error']

            logger.info("✅ [SearchAgent] 搜索任务完成")
            logger.info(f"   - Use Case: {result['use_case']}")
            logger.info(f"   - 答案长度: {len(result['answer'])} 字符")
            logger.info(f"   - 来源数: {len(result['sources'])}")

            return result

        except Exception as e:
            logger.error(f"❌ [SearchAgent] 搜索任务失败: {e}", exc_info=True)
            return {
                "success": False,
                "query": query,
                "error": str(e),
                "answer": "",
                "sources": []
            }

        finally:
            # 清理 MCP clients
            await self.utils.cleanup_mcp_clients()

    async def analyze_url(
        self,
        url: str,
        question: Optional[str] = None,
        auto_index: bool = True
    ) -> Dict:
        """
        分析单个URL的内容

        Args:
            url: 目标URL
            question: 用户问题（可选，默认为"总结这个网页的内容"）
            auto_index: 是否自动判断是否需要索引（默认True）

        Returns:
            分析结果
        """
        query = question or "总结这个网页的内容"

        result = await self.search(
            query=query,
            target_urls=[url],
            use_case="url_analysis",
            max_iterations=1
        )

        return result

    # ========== 辅助方法 ==========

    async def call_indexing_agent(
        self,
        content: Optional[str] = None,
        source_url: str = "",
        doc_name: Optional[str] = None,
        json_path: Optional[str] = None
    ) -> Dict:
        """
        调用 IndexingAgent 对内容进行索引

        这个方法将在 Use Case 2 中使用，当内容量超过阈值时调用。

        Args:
            content: 要索引的文本内容（如果 json_path 未提供）
            source_url: 内容来源URL
            doc_name: 文档名称（可选，默认使用URL生成）
            json_path: JSON 文件路径（优先使用，如果提供）

        Returns:
            索引结果
        """
        logger.info("📚 [CallIndexingAgent] 准备调用 IndexingAgent...")

        try:
            from ..indexing import IndexingAgent
            import tempfile
            import os
            import json

            # 如果提供了 JSON 路径，从 JSON 读取内容
            if json_path and os.path.exists(json_path):
                logger.info(f"📄 [CallIndexingAgent] 从 JSON 文件读取内容: {json_path}")
                with open(json_path, 'r', encoding='utf-8') as f:
                    web_data = json.load(f)

                content = web_data.get('content', {}).get('text', '')
                if not source_url:
                    source_url = web_data.get('url', '')

                logger.info(f"   - 内容长度: {len(content)} 字符")

            # 如果没有内容，报错
            if not content:
                raise ValueError("没有可索引的内容")

            # 生成文档名称
            if not doc_name and source_url:
                doc_name = self.utils.generate_doc_name_from_url(source_url)

            logger.info(f"📚 [CallIndexingAgent] 文档名: {doc_name}")

            # 创建临时文件保存内容
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                suffix='.txt',
                delete=False
            )

            try:
                temp_file.write(content)
                temp_file.close()

                # 调用 IndexingAgent
                indexing_agent = IndexingAgent(provider=self.provider)

                # 执行索引
                # 注意：IndexingAgent 的 process 方法需要 pdf_path 和 pdf_name
                # 但我们是 web 内容，所以需要适配
                # 暂时使用临时文件路径
                logger.info(f"🔄 [CallIndexingAgent] 开始索引文档...")

                # TODO: 这里需要调用 IndexingAgent 的正确方法
                # 现在暂时返回占位符，等待实际集成
                logger.warning("⚠️  [CallIndexingAgent] IndexingAgent 集成尚未完成，返回占位符")

                return {
                    "success": True,
                    "doc_name": doc_name,
                    "index_path": "",  # 待实现
                    "indexed": False,  # 待实现
                    "message": "IndexingAgent 集成待完成"
                }

            finally:
                # 清理临时文件
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)

        except Exception as e:
            logger.error(f"❌ [CallIndexingAgent] 索引失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "indexed": False
            }

    def __del__(self):
        """清理资源"""
        import asyncio

        try:
            # 清理 MCP clients
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.utils.cleanup_mcp_clients())
            else:
                asyncio.run(self.utils.cleanup_mcp_clients())
        except Exception:
            pass
