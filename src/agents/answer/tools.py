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

        为每个文档维护独立的 Retrieval Agent 实例，保留检索缓存

        Args:
            query: 用户查询

        Returns:
            检索到的上下文内容
        """
        logger.info(f"🔍 [Tool:call_retrieval] 调用检索: {query[:50]}...")

        try:
            doc_name = self.agent.current_doc

            # 为每个文档获取或创建独立的 Retrieval Agent 实例
            if doc_name not in self.agent.retrieval_agents:
                from ..retrieval import RetrievalAgent
                self.agent.retrieval_agents[doc_name] = RetrievalAgent(
                    doc_name=doc_name,
                    provider=self.agent.llm.provider,  # 从 AnswerAgent 继承 provider
                    progress_callback=self.agent.progress_callback  # 传递进度回调
                )
                logger.info(f"✅ [Tool:call_retrieval] 为文档 '{doc_name}' 创建新的 Retrieval Agent (provider={self.agent.llm.provider})")
                logger.info(f"📊 [Tool:call_retrieval] 当前管理的文档数: {len(self.agent.retrieval_agents)}")
            else:
                logger.info(f"♻️  [Tool:call_retrieval] 复用文档 '{doc_name}' 的 Retrieval Agent")
                # 显示缓存统计
                agent = self.agent.retrieval_agents[doc_name]
                cache_count = len(agent.retrieval_data_dict) if hasattr(agent, 'retrieval_data_dict') else 0
                logger.info(f"📦 [Tool:call_retrieval] 检索缓存中已有 {cache_count} 个章节")

            # 获取当前文档的对话轮次
            if doc_name not in self.agent.conversation_turns:
                self.agent.conversation_turns[doc_name] = 0

            current_turn = self.agent.conversation_turns[doc_name]
            logger.info(f"🔢 [Tool:call_retrieval] 文档 '{doc_name}' 对话轮次: {current_turn}")

            # 获取当前文档的 Retrieval Agent
            retrieval_agent = self.agent.retrieval_agents[doc_name]

            # 调用Retrieval Agent的graph
            max_iterations = ProcessingLimits.MAX_RETRIEVAL_ITERATIONS
            logger.info(f"🔧 [Tool:call_retrieval] 配置最大迭代次数: {max_iterations}")

            # 计算递归限制：每次迭代执行 5 个节点（rewrite, think, act, summary, evaluate）
            # 加上初始化节点和 format 节点，需要额外的安全余量
            recursion_limit = max_iterations * 5 + 10
            logger.info(f"🔧 [Tool:call_retrieval] 配置递归限制: {recursion_limit}")

            result = await retrieval_agent.graph.ainvoke(
                {
                    "query": query,
                    "doc_name": doc_name,
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

            # 递增当前文档的对话轮次（检索完成后）
            self.agent.conversation_turns[doc_name] += 1
            logger.info(f"🔢 [Tool:call_retrieval] 文档 '{doc_name}' 对话轮次递增至: {self.agent.conversation_turns[doc_name]}")

            # 提取检索到的上下文
            context = result.get("final_summary", "")

            logger.info(f"✅ [Tool:call_retrieval] 检索完成，上下文长度: {len(context)}")
            return context

        except Exception as e:
            logger.error(f"❌ [Tool:call_retrieval] 检索失败: {e}")
            return ""
