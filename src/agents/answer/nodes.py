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
        from .prompts import AnswerRole

        logger.info("=" * 80)
        logger.info("🤔 [Analyze] ========== 步骤0: 分析用户意图 ==========")
        logger.info("=" * 80)

        user_query = state['user_query']
        current_doc = state.get('current_doc', '无')

        logger.info(f"📝 [Analyze] 输入信息:")
        logger.info(f"   - 用户查询: {user_query}")
        logger.info(f"   - 当前文档: {current_doc}")
        logger.info(f"   - 查询长度: {len(user_query)} 字符")

        try:
            # 简化的 prompt（对话历史由 LLM Client 管理）
            prompt = f"""
当前用户问题：{user_query}

请判断是否需要从文档中检索新信息来回答这个问题。

返回JSON格式：
{{
    "needs_retrieval": true/false,
    "reason": "简要说明判断理由（20字以内）"
}}

只返回JSON，不要其他内容。
"""

            logger.info(f"🤖 [Analyze] 调用 LLM 进行意图分析...")

            # 使用专门的意图分析 Role
            response = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.INTENT_ANALYZER,
                input_prompt=prompt,
                session_id="analyze_intent"
            )

            logger.info(f"📤 [Analyze] LLM 响应预览: {response[:100]}...")

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

            logger.info("")
            logger.info("=" * 80)
            logger.info("✅ [Analyze] 意图分析结果")
            logger.info("=" * 80)
            logger.info(f"📊 [Analyze] 输出信息:")
            logger.info(f"   - 是否需要检索: {'是' if needs_retrieval else '否'}")
            logger.info(f"   - 判断理由: {reason}")
            logger.info(f"   - 下一步: {'调用 Retrieval Agent' if needs_retrieval else '直接生成答案'}")
            logger.info("=" * 80)
            logger.info("")

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

            logger.warning("")
            logger.warning("=" * 80)
            logger.warning("⚠️ [Analyze] 使用默认策略")
            logger.warning("=" * 80)
            logger.warning(f"   - 是否需要检索: 是（保守策略）")
            logger.warning(f"   - 原因: {state['analysis_reason']}")
            logger.warning("=" * 80)
            logger.warning("")

            return state

    async def call_retrieval(self, state: AnswerState) -> AnswerState:
        """
        步骤2：调用Retrieval Agent检索（使用工具方法）

        编排Retrieval Agent进行内容检索，直接返回检索结果作为最终答案
        """
        from langchain_core.messages import AIMessage

        logger.info("=" * 80)
        logger.info("🔍 [Retrieve] ========== 步骤1: 调用检索代理 ==========")
        logger.info("=" * 80)

        user_query = state["user_query"]
        current_doc = state.get("current_doc")

        logger.info(f"📝 [Retrieve] 输入信息:")
        logger.info(f"   - 用户查询: {user_query}")
        logger.info(f"   - 目标文档: {current_doc if current_doc else '未指定'}")

        try:
            # 更新当前文档上下文
            self.agent.current_doc = current_doc

            logger.info(f"🤖 [Retrieve] 调用 Retrieval Agent 进行检索...")

            # 调用工具方法
            context = await self.agent.tools.call_retrieval_impl(user_query)

            context_length = len(context) if context else 0
            context_preview = context[:200] if context else "无内容"

            logger.info("")
            logger.info("=" * 80)
            logger.info("✅ [Retrieve] 检索完成")
            logger.info("=" * 80)
            logger.info(f"📊 [Retrieve] 输出信息:")
            logger.info(f"   - 检索状态: {'成功' if context else '无结果'}")
            logger.info(f"   - 答案长度: {context_length} 字符")
            if context:
                logger.info(f"   - 答案预览: {context_preview}...")
            logger.info("=" * 80)
            logger.info("")

            # 直接将检索结果作为最终答案
            final_answer = context if context else "抱歉，未能检索到相关内容。"

            # 将结果添加到两个 session 的历史记录中（作为 AI 消息）
            ai_message = AIMessage(content=final_answer)

            # 添加到 generate_answer session
            self.agent.llm.add_message_to_history(
                session_id="generate_answer",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Retrieve] 已将答案添加到 generate_answer session 历史")

            # 添加到 analyze_intent session
            self.agent.llm.add_message_to_history(
                session_id="analyze_intent",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Retrieve] 已将答案添加到 analyze_intent session 历史")

            # 添加到 rewrite_query session
            self.agent.llm.add_message_to_history(
                session_id="rewrite_query",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Retrieve] 已将答案添加到 rewrite_query session 历史")

            # 更新 state 并返回
            state["context"] = context
            state["final_answer"] = final_answer
            state["is_complete"] = True

            logger.info(f"✅ [Retrieve] 直接返回检索结果，跳过 generate_answer 节点")
            return state

        except Exception as e:
            logger.error(f"❌ [Retrieve] 检索失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            logger.error("")
            logger.error("=" * 80)
            logger.error("❌ [Retrieve] 检索失败")
            logger.error("=" * 80)
            logger.error(f"   - 错误信息: {str(e)}")
            logger.error(f"   - 将继续执行 generate_answer 节点")
            logger.error("=" * 80)
            logger.error("")

            # 更新 state 并返回（不设置 final_answer，让 generate_answer 处理）
            state["context"] = ""
            return state

    async def generate_answer(self, state: AnswerState) -> AnswerState:
        """
        步骤3：生成最终回答

        结合检索到的文档上下文（如有）和历史对话（由LLM Client自动管理）生成回答

        注意：如果 call_retrieval 已经设置了 final_answer，则直接返回
        """
        from .prompts import AnswerRole

        logger.info("=" * 80)
        logger.info("💬 [Generate] ========== 步骤2: 生成最终答案 ==========")
        logger.info("=" * 80)

        # 检查是否已经有最终答案（由 call_retrieval 设置）
        if state.get("final_answer"):
            logger.info("✅ [Generate] 检测到已有最终答案（由检索代理提供），直接返回")
            logger.info(f"📊 [Generate] 答案长度: {len(state['final_answer'])} 字符")
            logger.info(f"📊 [Generate] 答案预览: {state['final_answer'][:200]}...")
            logger.info("=" * 80)
            logger.info("")
            return state

        context = state.get("context", "")
        user_query = state['user_query']

        logger.info(f"📝 [Generate] 输入信息:")
        logger.info(f"   - 用户查询: {user_query}")
        logger.info(f"   - 是否有检索上下文: {'是' if context else '否'}")
        if context:
            logger.info(f"   - 上下文长度: {len(context)} 字符")
            logger.info(f"   - 上下文预览: {context[:150]}...")

        try:
            if context:
                # 有检索上下文 - 提供文档参考内容
                prompt = f"""
用户问题：{user_query}

文档参考内容：
{context}
"""
                logger.info(f"📚 [Generate] 回答模式: 文档上下文 + 历史对话")
            else:
                # 无检索上下文 - 仅提供用户问题
                prompt = f"""
用户问题：{user_query}
"""
                logger.info(f"💬 [Generate] 回答模式: 仅历史对话")

            logger.info(f"🤖 [Generate] 调用 LLM 生成答案...")

            # 使用专门的对话式问答 role（历史对话由 LLM Client 自动管理）
            answer = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.CONVERSATIONAL_QA,
                input_prompt=prompt,
                session_id="generate_answer"
            )

            answer_preview = answer[:200] if len(answer) > 200 else answer

            logger.info("")
            logger.info("=" * 80)
            logger.info("✅ [Generate] 答案生成完成")
            logger.info("=" * 80)
            logger.info(f"📊 [Generate] 输出信息:")
            logger.info(f"   - 答案长度: {len(answer)} 字符")
            logger.info(f"   - 答案预览: {answer_preview}...")
            logger.info(f"   - 工作流状态: 完成")
            logger.info("=" * 80)
            logger.info("")

            # 更新 state 并返回
            state["final_answer"] = answer
            state["is_complete"] = True
            return state

        except Exception as e:
            logger.error(f"❌ [Generate] 回答生成失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            error_msg = f"抱歉，生成回答时出现错误：{str(e)}"

            logger.error("")
            logger.error("=" * 80)
            logger.error("❌ [Generate] 生成失败")
            logger.error("=" * 80)
            logger.error(f"   - 错误信息: {str(e)}")
            logger.error(f"   - 返回错误消息")
            logger.error("=" * 80)
            logger.error("")

            # 更新 state 并返回
            state["final_answer"] = error_msg
            state["is_complete"] = True
            return state

    def route_by_intent(self, state: AnswerState) -> str:
        """
        根据意图路由到不同节点

        Returns:
            "retrieve" 或 "direct"
        """
        needs_retrieval = state.get("needs_retrieval", False)
        reason = state.get("analysis_reason", "")

        if needs_retrieval:
            logger.info("🔀 [Route] 路由决策: 需要检索 → call_retrieval 节点")
            logger.info(f"   - 原因: {reason}")
            return "retrieve"
        else:
            logger.info("🔀 [Route] 路由决策: 直接回答 → generate_answer 节点")
            logger.info(f"   - 原因: {reason}")
            return "direct"
