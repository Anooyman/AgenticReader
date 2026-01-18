"""
AnswerAgent 工具方法实现

所有可复用的工具方法
"""

from typing import TYPE_CHECKING
import logging

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

    async def call_retrieval_impl(self, query: str) -> str:
        """
        调用Retrieval Agent检索文档内容（工具方法）

        Args:
            query: 用户查询

        Returns:
            检索到的上下文内容
        """
        logger.info(f"🔍 [Tool:call_retrieval] 调用检索: {query[:50]}...")

        try:
            # 延迟加载Retrieval Agent
            if self.agent.retrieval_agent is None:
                from ..retrieval import RetrievalAgent
                self.agent.retrieval_agent = RetrievalAgent(doc_name=self.agent.current_doc)
                logger.info("✅ Retrieval Agent已加载")

            # 调用Retrieval Agent的graph
            result = await self.agent.retrieval_agent.graph.ainvoke({
                "query": query,
                "doc_name": self.agent.current_doc,
                "max_iterations": 10,
                "current_iteration": 0,
                "is_complete": False,
                "thoughts": [],
                "actions": [],
                "observations": [],
                "retrieved_content": []
            })

            # 提取检索到的上下文
            context = result.get("final_summary", "")

            logger.info(f"✅ [Tool:call_retrieval] 检索完成，上下文长度: {len(context)}")
            return context

        except Exception as e:
            logger.error(f"❌ [Tool:call_retrieval] 检索失败: {e}")
            return ""
