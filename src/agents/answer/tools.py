"""
AnswerAgent 工具方法实现

所有可复用的工具方法
"""

from typing import TYPE_CHECKING
import logging

from src.config.constants import ProcessingLimits

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

            # 获取当前对话轮次
            current_turn = self.agent.conversation_turn
            logger.info(f"🔢 [Tool:call_retrieval] 对话轮次: {current_turn}")

            # 调用Retrieval Agent的graph
            max_iterations = ProcessingLimits.MAX_RETRIEVAL_ITERATIONS
            logger.info(f"🔧 [Tool:call_retrieval] 配置最大迭代次数: {max_iterations}")

            # 计算递归限制：每次迭代执行 5 个节点（rewrite, think, act, summary, evaluate）
            # 加上初始化节点和 format 节点，需要额外的安全余量
            recursion_limit = max_iterations * 5 + 10
            logger.info(f"🔧 [Tool:call_retrieval] 配置递归限制: {recursion_limit}")

            result = await self.agent.retrieval_agent.graph.ainvoke(
                {
                    "query": query,
                    "doc_name": self.agent.current_doc,
                    "max_iterations": max_iterations,
                    "conversation_turn": current_turn,  # 传递对话轮次
                    "current_iteration": 0,
                    "is_complete": False,
                    "thoughts": [],
                    "actions": [],
                    "observations": [],
                    "retrieved_content": []
                },
                config={"recursion_limit": recursion_limit}
            )

            # 递增对话轮次（检索完成后）
            self.agent.conversation_turn += 1
            logger.info(f"🔢 [Tool:call_retrieval] 对话轮次递增至: {self.agent.conversation_turn}")

            # 提取检索到的上下文
            context = result.get("final_summary", "")

            logger.info(f"✅ [Tool:call_retrieval] 检索完成，上下文长度: {len(context)}")
            return context

        except Exception as e:
            logger.error(f"❌ [Tool:call_retrieval] 检索失败: {e}")
            return ""
