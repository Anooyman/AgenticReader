"""
并行检索协调器

并行调用多个RetrievalAgent，高效完成跨文档检索
"""

import logging
import asyncio
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ParallelRetrievalCoordinator:
    """并行检索协调器 - 协调多个RetrievalAgent并行工作"""

    def __init__(self, answer_agent):
        """
        Args:
            answer_agent: AnswerAgent实例（需要访问retrieval_agents池和conversation_turns）
        """
        self.answer_agent = answer_agent

    async def retrieve_from_multiple_docs(
        self,
        query: str,
        doc_list: List[Dict[str, Any]],
        doc_specific_queries: Dict[str, str] = None,
        max_iterations: int = 10,
        max_concurrent: int = 3,
        timeout_per_doc: int = 120
    ) -> Dict[str, Any]:
        """
        并行从多个文档中检索

        Args:
            query: 原始用户查询（作为备份）
            doc_list: 文档列表（来自DocumentSelector）
            doc_specific_queries: 每个文档的定制查询 {doc_name: rewritten_query}
            max_iterations: 每个检索的最大迭代次数
            max_concurrent: 最大并发检索数
            timeout_per_doc: 单个文档检索超时（秒）

        Returns:
        {
            "doc1_name": {
                "final_summary": "...",
                "formatted_data": [...],
                "is_complete": True,
                "source_metadata": {...},
                "used_query": "实际使用的查询"
            },
            "doc2_name": {...},
            ...
        }
        """
        logger.info(f"")
        logger.info(f"=" * 80)
        logger.info(f"🚀 [ParallelCoordinator] ========== 并行检索多文档 ==========")
        logger.info(f"=" * 80)
        logger.info(f"📝 [ParallelCoordinator] 原始查询: {query[:100]}...")
        logger.info(f"📊 [ParallelCoordinator] 配置:")
        logger.info(f"   - 文档数量: {len(doc_list)}")
        logger.info(f"   - 最大迭代: {max_iterations}")
        logger.info(f"   - 最大并发: {max_concurrent}")
        logger.info(f"   - 单文档超时: {timeout_per_doc}秒")
        logger.info(f"   - 使用定制查询: {'是' if doc_specific_queries else '否'}")

        if not doc_list:
            logger.warning(f"⚠️  [ParallelCoordinator] 文档列表为空，返回空结果")
            return {}

        # 创建信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)

        # 创建检索任务列表
        tasks = []
        for doc_info in doc_list:
            doc_name = doc_info["doc_name"]

            # 为每个文档使用定制的查询（如果有）
            doc_query = query  # 默认使用原始查询
            if doc_specific_queries and doc_name in doc_specific_queries:
                doc_query = doc_specific_queries[doc_name]
                logger.info(f"📄 [ParallelCoordinator] 文档 '{doc_name}' 使用定制查询: {doc_query[:60]}...")
            else:
                logger.info(f"📄 [ParallelCoordinator] 文档 '{doc_name}' 使用原始查询")

            task = self._retrieve_single_doc_with_limit(
                semaphore=semaphore,
                doc_info=doc_info,
                query=doc_query,  # 使用定制查询
                max_iterations=max_iterations,
                timeout=timeout_per_doc
            )
            tasks.append((doc_name, task))

        # 并行执行所有检索任务
        logger.info(f"")
        logger.info(f"🔄 [ParallelCoordinator] 开始并行检索...")

        results = {}
        task_results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )

        # 整理结果
        for (doc_name, _), result in zip(tasks, task_results):
            if isinstance(result, Exception):
                logger.error(f"❌ [ParallelCoordinator] 检索文档 '{doc_name}' 失败: {result}")
                results[doc_name] = {
                    "error": str(result),
                    "is_complete": False
                }
            else:
                results[doc_name] = result

        # 统计结果
        success_count = sum(1 for r in results.values() if r.get("is_complete", False))
        error_count = len(results) - success_count

        logger.info(f"")
        logger.info(f"=" * 80)
        logger.info(f"✅ [ParallelCoordinator] 并行检索完成")
        logger.info(f"=" * 80)
        logger.info(f"📊 [ParallelCoordinator] 结果统计:")
        logger.info(f"   - 成功: {success_count} 个文档")
        logger.info(f"   - 失败: {error_count} 个文档")
        logger.info(f"=" * 80)
        logger.info(f"")

        return results

    async def _retrieve_single_doc_with_limit(
        self,
        semaphore: asyncio.Semaphore,
        doc_info: Dict[str, Any],
        query: str,
        max_iterations: int,
        timeout: int
    ) -> Dict[str, Any]:
        """
        带并发限制和超时的单文档检索

        Args:
            semaphore: 并发控制信号量
            doc_info: 文档信息（包含doc_name, similarity_score等）
            query: 用户查询
            max_iterations: 最大迭代次数
            timeout: 超时时间（秒）

        Returns:
            检索结果字典
        """
        doc_name = doc_info["doc_name"]

        async with semaphore:
            try:
                logger.info(f"📖 [ParallelCoordinator] 开始检索文档: {doc_name} (相似度: {doc_info.get('similarity_score', 'N/A')})")

                # 设置超时
                result = await asyncio.wait_for(
                    self._retrieve_single_doc(
                        doc_info=doc_info,
                        query=query,
                        max_iterations=max_iterations
                    ),
                    timeout=timeout
                )

                logger.info(f"✅ [ParallelCoordinator] 文档 '{doc_name}' 检索完成")
                return result

            except asyncio.TimeoutError:
                logger.error(f"⏱️  [ParallelCoordinator] 文档 '{doc_name}' 检索超时（{timeout}秒）")
                return {
                    "error": f"检索超时（{timeout}秒）",
                    "is_complete": False
                }
            except Exception as e:
                logger.error(f"❌ [ParallelCoordinator] 文档 '{doc_name}' 检索异常: {e}")
                return {
                    "error": str(e),
                    "is_complete": False
                }

    async def _retrieve_single_doc(
        self,
        doc_info: Dict[str, Any],
        query: str,
        max_iterations: int
    ) -> Dict[str, Any]:
        """
        检索单个文档

        Args:
            doc_info: 文档信息
            query: 用户查询
            max_iterations: 最大迭代次数

        Returns:
            检索结果
        """
        doc_name = doc_info["doc_name"]

        # 获取或创建该文档的RetrievalAgent
        if doc_name not in self.answer_agent.retrieval_agents:
            from src.agents.retrieval import RetrievalAgent
            self.answer_agent.retrieval_agents[doc_name] = RetrievalAgent(doc_name=doc_name)
            logger.info(f"✨ [ParallelCoordinator] 为文档 '{doc_name}' 创建新的 Retrieval Agent")

        retrieval_agent = self.answer_agent.retrieval_agents[doc_name]

        # 获取对话轮次
        if doc_name not in self.answer_agent.conversation_turns:
            self.answer_agent.conversation_turns[doc_name] = 0

        current_turn = self.answer_agent.conversation_turns[doc_name]

        # 调用RetrievalAgent
        from src.config.constants import ProcessingLimits

        # 计算递归限制
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
        self.answer_agent.conversation_turns[doc_name] += 1

        # 添加源文档元数据和使用的查询到结果
        result["source_metadata"] = doc_info
        result["used_query"] = query  # 记录实际使用的查询（可能是原始查询或改写后的查询）

        return result
