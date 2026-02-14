"""
AnswerAgent 工具方法实现

统一的工具调用接口，支持文档检索和（未来的）网络搜索。
"""

from typing import TYPE_CHECKING, Optional, List, Dict, Any
import logging
import asyncio

from src.config.constants import ProcessingLimits
from src.config.settings import CROSS_DOC_CONFIG, DOCUMENT_SELECTION_CONFIG

if TYPE_CHECKING:
    from .agent import AnswerAgent

logger = logging.getLogger(__name__)


class AnswerTools:
    """AnswerAgent 工具方法集合"""

    def __init__(self, agent: 'AnswerAgent'):
        """
        Args:
            agent: AnswerAgent实例（依赖注入）
        """
        self.agent = agent

    # ==================== 统一文档检索工具 ====================

    async def retrieve_documents(
        self,
        query: str,
        doc_names: Optional[List[str]] = None,
        max_docs: int = 5
    ) -> Dict[str, Any]:
        """
        统一文档检索工具 - 将三种检索模式合一

        Args:
            query: 用户查询
            doc_names: 指定文档名列表
                - 提供 → 直接检索这些文档
                - 不提供 → 自动选择相关文档
            max_docs: 自动选择时的最大文档数

        Returns:
            {
                "success": bool,
                "mode": "single" | "multi" | "auto",
                "doc_names": [...],
                "answer": "检索结果或综合答案",
                "total_docs": int
            }
        """
        logger.info(f"🔍 [Tool:retrieve_documents] 开始文档检索: {query[:50]}...")
        logger.info(f"   - 指定文档: {doc_names if doc_names else '自动选择'}")

        try:
            # ========== 阶段1：确定文档列表 ==========
            if doc_names is None:
                # 自动选择模式
                mode = "auto"
                doc_names = await self._auto_select_documents(query, max_docs)
                if not doc_names:
                    return {
                        "success": False,
                        "mode": mode,
                        "doc_names": [],
                        "answer": "",
                        "total_docs": 0,
                        "error": "未找到相关文档"
                    }
                logger.info(f"📄 [Tool:retrieve_documents] 自动选择了 {len(doc_names)} 个文档: {doc_names}")
            elif len(doc_names) == 1:
                mode = "single"
            else:
                mode = "multi"

            # ========== 阶段2：执行检索 ==========
            if len(doc_names) == 1:
                # 单文档检索
                answer = await self._retrieve_single(query, doc_names[0])
                return {
                    "success": bool(answer),
                    "mode": mode,
                    "doc_names": doc_names,
                    "answer": answer or "未能检索到相关内容。",
                    "total_docs": 1
                }
            else:
                # 多文档并行检索 + 综合
                answer = await self._retrieve_multi_and_synthesize(query, doc_names)
                return {
                    "success": bool(answer),
                    "mode": mode,
                    "doc_names": doc_names,
                    "answer": answer or "未能从多个文档中检索到相关内容。",
                    "total_docs": len(doc_names)
                }

        except Exception as e:
            logger.error(f"❌ [Tool:retrieve_documents] 检索失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "mode": doc_names and (
                    "single" if len(doc_names) == 1 else "multi"
                ) or "auto",
                "doc_names": doc_names or [],
                "answer": "",
                "total_docs": 0,
                "error": str(e)
            }

    # ==================== 网络搜索工具 ====================

    async def search_web(
        self,
        query: str,
        target_urls: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        网络搜索工具 - 使用 SearchAgent 进行网络搜索或URL分析

        Args:
            query: 搜索查询
            target_urls: 指定URL列表（可选，用于URL分析模式）

        Returns:
            {
                "success": bool,
                "answer": str,
                "sources": [...],
                "error": str (可选)
            }
        """
        logger.info(f"🌐 [Tool:search_web] 开始网络搜索: {query[:50]}...")
        logger.info(f"   - 指定URL: {target_urls if target_urls else '搜索引擎模式'}")

        try:
            # 发送进度更新
            await self._send_progress(
                stage="search_web",
                stage_name="网络搜索",
                status="processing",
                message="正在搜索互联网..." if not target_urls else f"正在分析 {len(target_urls)} 个URL..."
            )

            # 获取或创建 SearchAgent
            if not hasattr(self.agent, 'search_agent') or self.agent.search_agent is None:
                from ..search import SearchAgent
                self.agent.search_agent = SearchAgent(
                    provider=self.agent.llm.provider,
                    progress_callback=self.agent.progress_callback
                )
                logger.info("✅ [Tool:search_web] 创建新的 SearchAgent")
            else:
                logger.info("♻️  [Tool:search_web] 复用现有 SearchAgent")

            # 调用 SearchAgent
            result = await self.agent.search_agent.search(
                query=query,
                target_urls=target_urls,
                max_iterations=3
            )

            # 提取返回值
            success = result.get("success", False)
            answer = result.get("answer", "")
            sources = result.get("sources", [])
            error = result.get("error")

            logger.info(f"✅ [Tool:search_web] 搜索完成，答案长度: {len(answer)}, 来源数: {len(sources)}")

            await self._send_progress(
                stage="search_web",
                stage_name="网络搜索",
                status="completed",
                message=f"搜索完成，找到 {len(sources)} 个来源"
            )

            return {
                "success": success,
                "answer": answer,
                "sources": sources,
                "error": error
            }

        except Exception as e:
            logger.error(f"❌ [Tool:search_web] 搜索失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            await self._send_progress(
                stage="search_web",
                stage_name="网络搜索",
                status="error",
                message=f"搜索失败: {str(e)}"
            )

            return {
                "success": False,
                "answer": "",
                "sources": [],
                "error": str(e)
            }

    # ==================== 内部方法 ====================

    async def _auto_select_documents(self, query: str, max_docs: int) -> List[str]:
        """
        自动选择相关文档

        Args:
            query: 用户查询
            max_docs: 最大文档数

        Returns:
            文档名列表
        """
        from .components import DocumentSelector

        logger.info(f"🔍 [Tool:retrieve_documents] 自动选择文档...")

        # 发送进度更新
        await self._send_progress(
            stage="select_docs",
            stage_name="文档选择",
            status="processing",
            message="正在自动选择相关文档..."
        )

        selector = DocumentSelector(self.agent.llm, self.agent.registry)
        selected_docs = await selector.select_relevant_documents(
            query=query,
            max_docs=max_docs
        )

        doc_names = [doc["doc_name"] for doc in selected_docs]

        await self._send_progress(
            stage="select_docs",
            stage_name="文档选择",
            status="completed",
            message=f"已选择 {len(doc_names)} 个相关文档"
        )

        return doc_names

    async def _retrieve_single(self, query: str, doc_name: str) -> str:
        """
        单文档检索

        Args:
            query: 用户查询
            doc_name: 文档名

        Returns:
            检索结果文本
        """
        logger.info(f"📄 [Tool:retrieve_documents] 单文档检索: {doc_name}")

        await self._send_progress(
            stage="retrieve",
            stage_name="文档检索",
            status="processing",
            message=f"正在检索文档: {doc_name}"
        )

        # 获取或创建 Retrieval Agent
        if doc_name not in self.agent.retrieval_agents:
            from ..retrieval import RetrievalAgent
            self.agent.retrieval_agents[doc_name] = RetrievalAgent(
                doc_name=doc_name,
                provider=self.agent.llm.provider,
                progress_callback=self.agent.progress_callback
            )
            logger.info(f"✅ [Tool:retrieve_documents] 为文档 '{doc_name}' 创建新的 RetrievalAgent")
        else:
            logger.info(f"♻️  [Tool:retrieve_documents] 复用文档 '{doc_name}' 的 RetrievalAgent")
            agent = self.agent.retrieval_agents[doc_name]
            cache_count = len(agent.retrieval_data_dict) if hasattr(agent, 'retrieval_data_dict') else 0
            logger.info(f"📦 [Tool:retrieve_documents] 缓存中已有 {cache_count} 个章节")

        # 获取对话轮次
        if doc_name not in self.agent.conversation_turns:
            self.agent.conversation_turns[doc_name] = 0
        current_turn = self.agent.conversation_turns[doc_name]
        logger.info(f"🔢 [Tool:retrieve_documents] 文档 '{doc_name}' 对话轮次: {current_turn}")

        # 调用 Retrieval Agent
        retrieval_agent = self.agent.retrieval_agents[doc_name]
        max_iterations = ProcessingLimits.MAX_RETRIEVAL_ITERATIONS
        recursion_limit = max_iterations * 5 + 10

        result = await retrieval_agent.graph.ainvoke(
            {
                "query": query,
                "doc_name": doc_name,
                "max_iterations": max_iterations,
                "conversation_turn": current_turn,
                "current_iteration": 0,
                "is_complete": False,
                "thoughts": [],
                "actions": [],
                "observations": [],
                "retrieved_content": []
            },
            config={"recursion_limit": recursion_limit}
        )

        # 递增对话轮次
        self.agent.conversation_turns[doc_name] += 1
        logger.info(f"🔢 [Tool:retrieve_documents] 文档 '{doc_name}' 对话轮次递增至: {self.agent.conversation_turns[doc_name]}")

        context = result.get("final_summary", "")
        logger.info(f"✅ [Tool:retrieve_documents] 单文档检索完成，长度: {len(context)}")

        await self._send_progress(
            stage="retrieve",
            stage_name="文档检索",
            status="completed",
            message=f"文档 {doc_name} 检索完成"
        )

        return context

    async def _retrieve_multi_and_synthesize(self, query: str, doc_names: List[str]) -> str:
        """
        多文档并行检索 + 综合

        Args:
            query: 用户查询
            doc_names: 文档名列表

        Returns:
            综合后的答案
        """
        from .prompts import AnswerRole
        from .components import CrossDocumentSynthesizer, AnswerFormatter
        from src.core.parallel import ParallelRetrievalCoordinator

        logger.info(f"📚 [Tool:retrieve_documents] 多文档检索: {doc_names}")

        # ========== 步骤1：为每个文档改写查询 ==========
        await self._send_progress(
            stage="rewrite_queries",
            stage_name="查询改写",
            status="processing",
            message=f"正在为 {len(doc_names)} 个文档改写查询..."
        )

        doc_specific_queries = await self._rewrite_queries_for_docs(query, doc_names)

        await self._send_progress(
            stage="rewrite_queries",
            stage_name="查询改写",
            status="completed",
            message=f"已为 {len(doc_specific_queries)} 个文档改写查询"
        )

        # ========== 步骤2：并行检索 ==========
        await self._send_progress(
            stage="retrieve_multi",
            stage_name="多文档检索",
            status="processing",
            message=f"正在并行检索 {len(doc_names)} 个文档..."
        )

        # 构建 doc_list 格式（ParallelRetrievalCoordinator 需要的格式）
        doc_list = []
        for name in doc_names:
            doc_info = self.agent.registry.get_by_name(name)
            doc_list.append({
                "doc_name": name,
                "brief_summary": doc_info.get("brief_summary", "") if doc_info else "",
                "score": 1.0
            })

        coordinator = ParallelRetrievalCoordinator(self.agent)
        multi_results = await coordinator.retrieve_from_multiple_docs(
            query=query,
            doc_list=doc_list,
            doc_specific_queries=doc_specific_queries,
            max_iterations=CROSS_DOC_CONFIG.get("max_iterations", 10),
            max_concurrent=CROSS_DOC_CONFIG.get("max_parallel_retrievals", 3),
            timeout_per_doc=CROSS_DOC_CONFIG.get("retrieval_timeout", 1200)
        )

        await self._send_progress(
            stage="retrieve_multi",
            stage_name="多文档检索",
            status="completed",
            message=f"已完成 {len(multi_results)} 个文档的检索"
        )

        # ========== 步骤3：综合多文档结果 ==========
        await self._send_progress(
            stage="synthesize",
            stage_name="综合答案",
            status="processing",
            message=f"正在综合 {len(multi_results)} 个文档的结果..."
        )

        synthesizer = CrossDocumentSynthesizer(self.agent.llm)
        final_answer = await synthesizer.synthesize(query, multi_results)

        # 格式化
        formatted_answer = AnswerFormatter.format_cross_doc_synthesis(
            final_answer,
            doc_names=doc_names
        )

        await self._send_progress(
            stage="synthesize",
            stage_name="综合答案",
            status="completed",
            message="跨文档综合完成"
        )

        logger.info(f"✅ [Tool:retrieve_documents] 多文档检索+综合完成，长度: {len(formatted_answer)}")
        return formatted_answer

    async def _rewrite_queries_for_docs(
        self,
        query: str,
        doc_names: List[str]
    ) -> Dict[str, str]:
        """
        为每个文档并行改写查询

        Args:
            query: 原始用户查询
            doc_names: 文档名列表

        Returns:
            {doc_name: rewritten_query}
        """
        from .prompts import AnswerRole
        from src.core.document_management import DocumentRegistry

        logger.info(f"✍️  [Tool:retrieve_documents] 为 {len(doc_names)} 个文档改写查询...")

        registry = DocumentRegistry()

        async def rewrite_for_doc(doc_name: str) -> tuple:
            """为单个文档改写查询"""
            doc_record = registry.get_by_name(doc_name)
            if not doc_record:
                logger.warning(f"⚠️  文档 '{doc_name}' 未找到，使用原始查询")
                return (doc_name, query)

            brief_summary = doc_record.get("brief_summary", "")
            if not brief_summary or len(brief_summary.strip()) < 20:
                logger.info(f"   ⏭️  文档 '{doc_name}' 简介不足，跳过改写")
                return (doc_name, query)

            prompt = f"""原始查询：{query}

文档简介：{brief_summary}

请根据文档简介的特点，将原始查询改写成适合在该文档中检索的针对性查询。"""

            try:
                rewritten = await self.agent.llm.async_call_llm_chain(
                    role=AnswerRole.DOC_SPECIFIC_QUERY_REWRITER,
                    input_prompt=prompt,
                    session_id=f"doc_query_rewrite_{doc_name}"
                )
                rewritten = rewritten.strip()
                logger.info(f"   ✅ {doc_name}: {rewritten[:60]}...")
                return (doc_name, rewritten)
            except Exception as e:
                logger.error(f"   ❌ {doc_name} 改写失败: {e}")
                return (doc_name, query)

        # 并行改写
        tasks = [rewrite_for_doc(name) for name in doc_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        doc_specific_queries = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"❌ 改写任务异常: {result}")
                continue
            doc_name, rewritten_query = result
            doc_specific_queries[doc_name] = rewritten_query

        logger.info(f"✅ [Tool:retrieve_documents] 查询改写完成: {len(doc_specific_queries)} 个文档")
        return doc_specific_queries

    # ==================== 进度回调辅助 ====================

    async def _send_progress(self, stage: str, stage_name: str,
                             status: str = "processing", message: str = ""):
        """发送进度更新"""
        if not self.agent.progress_callback:
            return

        try:
            progress_data = {
                "agent": "answer",
                "stage": stage,
                "stage_name": stage_name,
                "status": status,
                "message": message,
                "doc_name": self.agent.current_doc or "MultiDoc"
            }
            await self.agent.progress_callback(progress_data)
        except Exception as e:
            logger.warning(f"⚠️ 发送进度更新失败: {e}")
