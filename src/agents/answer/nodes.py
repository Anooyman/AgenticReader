"""
AnswerAgent Workflow节点方法

所有workflow节点的实现
"""

from __future__ import annotations
from typing import Dict, TYPE_CHECKING
import logging
import json
import re

from .state import AnswerState

if TYPE_CHECKING:
    from .agent import AnswerAgent

logger = logging.getLogger(__name__)


class AnswerNodes:
    """AnswerAgent Workflow节点方法集合"""

    def __init__(self, agent: 'AnswerAgent'):
        """
        Args:
            agent: AnswerAgent实例（依赖注入）
        """
        self.agent = agent

    async def analyze_intent(self, state: AnswerState) -> AnswerState:
        """
        步骤1：分析用户意图

        基于对话历史和上下文，判断是否需要检索文档内容来回答当前问题
        注意：对话历史已由 LLM Client 自动管理，无需手动处理
        """
        from src.config.prompts.answer_prompts import AnswerRole

        logger.info(f"🤔 [Analyze] 分析意图: {state['user_query'][:50]}...")

        try:
            # 简化的 prompt（对话历史由 LLM Client 管理）
            prompt = f"""
当前用户问题：{state['user_query']}

请判断是否需要从文档中检索新信息来回答这个问题。

返回JSON格式：
{{
    "needs_retrieval": true/false,
    "reason": "简要说明判断理由（20字以内）"
}}

只返回JSON，不要其他内容。
"""

            # 使用专门的意图分析 Role
            response = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.INTENT_ANALYZER,
                input_prompt=prompt,
                session_id="analyze_intent"
            )

            # 解析JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                needs_retrieval = result.get("needs_retrieval", True)
                reason = result.get("reason", "")
            else:
                # 默认需要检索
                logger.warning("⚠️ [Analyze] JSON解析失败，使用默认策略")
                needs_retrieval = True
                reason = "JSON解析失败，默认检索"

            logger.info(
                f"✅ [Analyze] 意图分析完成: "
                f"{'需要检索' if needs_retrieval else '直接回答'} - {reason}"
            )

            # 更新 state 并返回
            state["needs_retrieval"] = needs_retrieval
            state["analysis_reason"] = reason
            return state

        except Exception as e:
            logger.error(f"❌ [Analyze] 意图分析失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时默认需要检索（保守策略）
            state["needs_retrieval"] = True
            state["analysis_reason"] = "分析失败，采用保守策略"
            return state

    async def call_retrieval(self, state: AnswerState) -> AnswerState:
        """
        步骤2：调用Retrieval Agent检索（使用工具方法）

        编排Retrieval Agent进行内容检索
        """
        logger.info(f"🔍 [Retrieve] 调用Retrieval Agent")

        try:
            # 更新当前文档上下文
            self.agent.current_doc = state.get("current_doc")

            # 调用工具方法
            context = await self.agent.tools.call_retrieval_impl(state["user_query"])

            # 更新 state 并返回
            state["context"] = context
            return state

        except Exception as e:
            logger.error(f"❌ [Retrieve] 检索失败: {e}")

            # 更新 state 并返回
            state["context"] = ""
            return state

    async def generate_answer(self, state: AnswerState) -> AnswerState:
        """
        步骤3：生成最终回答

        结合检索到的文档上下文（如有）和历史对话（由LLM Client自动管理）生成回答
        """
        from src.config.prompts.answer_prompts import AnswerRole

        logger.info(f"💬 [Generate] 生成回答")

        try:
            context = state.get("context", "")
            user_query = state['user_query']

            if context:
                # 有检索上下文 - 提供文档参考内容
                prompt = f"""
用户问题：{user_query}

文档参考内容：
{context}
"""
                logger.info(f"📚 [Generate] 使用文档上下文 + 历史对话回答")
            else:
                # 无检索上下文 - 仅提供用户问题
                prompt = f"""
用户问题：{user_query}
"""
                logger.info(f"💬 [Generate] 仅使用历史对话回答")

            # 使用专门的对话式问答 role（历史对话由 LLM Client 自动管理）
            answer = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.CONVERSATIONAL_QA,
                input_prompt=prompt,
                session_id="generate_answer"
            )

            logger.info(f"✅ [Generate] 回答生成完成，长度: {len(answer)}")

            # 更新 state 并返回
            state["final_answer"] = answer
            state["is_complete"] = True
            return state

        except Exception as e:
            logger.error(f"❌ [Generate] 回答生成失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 更新 state 并返回
            state["final_answer"] = f"抱歉，生成回答时出现错误：{str(e)}"
            state["is_complete"] = True
            return state

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
