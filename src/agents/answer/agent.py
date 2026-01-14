"""
Answer Agent - 用户对话接口Agent

负责：
1. 分析用户意图
2. 决定是否需要检索
3. 调用Retrieval Agent获取上下文
4. 生成最终回答
"""

from langgraph.graph import StateGraph, END
from typing import Dict, Optional, List
import logging
import json
import re

from ..base import AgentBase
from .state import AnswerState

logger = logging.getLogger(__name__)


class AnswerAgent(AgentBase):
    """
    对话Agent

    工作流程：
    1. analyze_intent - 分析用户意图
    2. retrieve (可选) - 调用Retrieval Agent检索
    3. generate_answer - 生成最终回答

    工具方法（直接在类中实现）：
    - call_retrieval_impl - 调用检索Agent
    - direct_answer_impl - 直接回答
    """

    def __init__(self, doc_name: str = None):
        super().__init__(name="AnswerAgent")

        # 延迟加载Retrieval Agent
        self.retrieval_agent = None

        # 当前文档上下文
        self.current_doc = doc_name

        self.graph = self.build_graph()

    # ==================== 工具方法实现 ====================

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
            if self.retrieval_agent is None:
                from ..retrieval import RetrievalAgent
                self.retrieval_agent = RetrievalAgent(doc_name=self.current_doc)
                logger.info("✅ Retrieval Agent已加载")

            # 调用Retrieval Agent的graph
            result = await self.retrieval_agent.graph.ainvoke({
                "query": query,
                "doc_name": self.current_doc,
                "tags": None,
                "max_iterations": 5,
                # 初始化其他必需字段
                "thoughts": [],
                "actions": [],
                "observations": [],
                "current_iteration": 0,
                "retrieved_content": {},
                "is_complete": False
            })

            # 提取检索到的上下文
            context = result.get("final_context", "")

            logger.info(f"✅ [Tool:call_retrieval] 检索完成，上下文长度: {len(context)}")
            return context

        except Exception as e:
            logger.error(f"❌ [Tool:call_retrieval] 检索失败: {e}")
            return ""

    async def direct_answer_impl(self, query: str) -> str:
        """
        直接回答用户问题（工具方法）

        Args:
            query: 用户问题

        Returns:
            回答文本
        """
        logger.info(f"💬 [Tool:direct_answer] 直接回答: {query[:50]}...")

        try:
            prompt = f"""
请回答用户问题。

用户问题：{query}

要求：
1. 礼貌友好
2. 简洁明了
"""

            # 使用Agent的LLM实例
            answer = await self.llm.async_get_response(prompt)

            logger.info(f"✅ [Tool:direct_answer] 回答生成完成")
            return answer

        except Exception as e:
            logger.error(f"❌ [Tool:direct_answer] 回答生成失败: {e}")
            return f"抱歉，生成回答时出现错误：{str(e)}"

    # ==================== Workflow节点方法 ====================

    def build_graph(self) -> StateGraph:
        """构建workflow"""
        workflow = StateGraph(AnswerState)

        # 添加节点
        workflow.add_node("analyze", self.analyze_intent)
        workflow.add_node("retrieve", self.call_retrieval)
        workflow.add_node("generate", self.generate_answer)

        # 添加条件边：根据是否需要检索选择路径
        workflow.add_conditional_edges(
            "analyze",
            self.route_by_intent,
            {
                "retrieve": "retrieve",  # 需要检索
                "direct": "generate"  # 直接回答
            }
        )

        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)

        # 设置入口
        workflow.set_entry_point("analyze")

        return workflow.compile()

    async def analyze_intent(self, state: AnswerState) -> Dict:
        """
        步骤1：分析用户意图

        判断是否需要检索文档内容
        """
        logger.info(f"🤔 [Analyze] 分析意图: {state['user_query'][:50]}...")

        try:
            # 使用Agent级别的LLM实例
            llm = self.llm

            prompt = f"""
分析用户查询，判断是否需要检索文档内容。

用户查询：{state['user_query']}

如果查询是以下类型，需要检索：
- 询问文档具体内容
- 需要引用文档细节
- 需要查找特定信息

如果查询是以下类型，不需要检索：
- 打招呼、闲聊
- 一般性问题（不涉及文档）
- 请求帮助、说明

返回JSON格式：
{{
    "needs_retrieval": true/false,
    "reason": "判断原因"
}}

只返回JSON，不要其他内容。
"""

            response = await llm.async_get_response(prompt)

            # 解析JSON
            import json
            import re

            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                needs_retrieval = result.get("needs_retrieval", True)
                reason = result.get("reason", "")
            else:
                # 默认需要检索
                needs_retrieval = True
                reason = "默认策略"

            logger.info(
                f"✅ [Analyze] 意图分析完成: "
                f"{'需要检索' if needs_retrieval else '直接回答'} - {reason}"
            )

            return {
                "needs_retrieval": needs_retrieval
            }

        except Exception as e:
            logger.error(f"❌ [Analyze] 意图分析失败: {e}")

            # 失败时默认需要检索
            return {
                "needs_retrieval": True
            }

    def route_by_intent(self, state: AnswerState) -> str:
        """
        根据意图路由到不同节点

        Returns:
            "retrieve" 或 "direct"
        """
        if state.get("needs_retrieval", False):
            return "retrieve"
        else:
            return "direct"

    async def call_retrieval(self, state: AnswerState) -> Dict:
        """
        步骤2：调用Retrieval Agent检索（使用工具方法）

        编排Retrieval Agent进行内容检索
        """
        logger.info(f"🔍 [Retrieve] 调用Retrieval Agent")

        try:
            # 更新当前文档上下文
            self.current_doc = state.get("current_doc")

            # 调用工具方法
            context = await self.call_retrieval_impl(state["user_query"])

            return {
                "context": context
            }

        except Exception as e:
            logger.error(f"❌ [Retrieve] 检索失败: {e}")

            return {
                "context": ""
            }

    async def generate_answer(self, state: AnswerState) -> Dict:
        """
        步骤3：生成最终回答（使用工具方法）
        """
        logger.info(f"💬 [Generate] 生成回答")

        try:
            context = state.get("context", "")

            if context:
                # 有检索上下文 - 基于文档回答
                prompt = f"""
请基于以下文档内容回答用户问题。

用户问题：{state['user_query']}

相关内容：
{context}

要求：
1. 基于文档内容回答
2. 如果文档中没有相关信息，请明确说明
3. 保持回答简洁准确
"""
                # 使用Agent的LLM实例
                answer = await self.llm.async_get_response(prompt)
            else:
                # 无检索上下文 - 直接回答
                answer = await self.direct_answer_impl(state['user_query'])

            logger.info(f"✅ [Generate] 回答生成完成，长度: {len(answer)}")

            return {
                "final_answer": answer,
                "is_complete": True
            }

        except Exception as e:
            logger.error(f"❌ [Generate] 回答生成失败: {e}")

            return {
                "final_answer": f"抱歉，生成回答时出现错误：{str(e)}",
                "is_complete": True
            }
