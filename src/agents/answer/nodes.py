"""
AnswerAgent Workflow节点方法

所有workflow节点的实现
"""

from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING
import logging
import json
import re

from .state import AnswerState
from .components import AnswerFormatter

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

    async def _send_progress(self, stage: str, stage_name: str, status: str = "processing",
                            message: str = "", state: AnswerState = None, **kwargs):
        """
        发送进度更新（通过progress_callback）

        Args:
            stage: 阶段标识（analyze_intent/retrieve_single/select_docs/rewrite_queries/retrieve_multi/synthesize/generate）
            stage_name: 阶段中文名称
            status: 状态（processing/completed/error）
            message: 详细消息
            state: 当前状态（可选，用于提取额外信息）
            **kwargs: 额外的进度数据（如 tool, iteration 等）
        """
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

            # 添加额外的进度信息（如果提供）
            progress_data.update(kwargs)

            await self.agent.progress_callback(progress_data)
        except Exception as e:
            logger.warning(f"⚠️ 发送进度更新失败: {e}")

    def _save_persistent_state(self, state: AnswerState):
        """
        保存状态供下一轮对话使用（内部方法）

        只保存需要持久化的字段：
        - selected_documents: 文档选择结果
        - doc_specific_queries: 查询改写结果
        - retrieval_mode: 检索模式
        """
        self.agent.persistent_state = {}

        # 只保存需要的字段
        if "selected_documents" in state and state["selected_documents"]:
            self.agent.persistent_state["selected_documents"] = state["selected_documents"]
            logger.info(f"💾 保存 selected_documents: {len(state['selected_documents'])} 个文档")

        if "doc_specific_queries" in state and state["doc_specific_queries"]:
            self.agent.persistent_state["doc_specific_queries"] = state["doc_specific_queries"]
            logger.info(f"💾 保存 doc_specific_queries: {len(state['doc_specific_queries'])} 个")

        if "retrieval_mode" in state and state["retrieval_mode"]:
            self.agent.persistent_state["retrieval_mode"] = state["retrieval_mode"]
            logger.info(f"💾 保存 retrieval_mode: {state['retrieval_mode']}")

    async def analyze_intent(self, state: AnswerState) -> AnswerState:
        """
        步骤1：分析用户意图

        基于对话历史和上下文，判断是否需要检索文档内容来回答当前问题
        注意：对话历史已由 LLM Client 自动管理，无需手动处理

        状态持久化：自动从 persistent_state 恢复之前的状态信息
        """
        from .prompts import AnswerRole

        logger.info("=" * 80)
        logger.info("🤔 [Analyze] ========== 步骤0: 分析用户意图 ==========")
        logger.info("=" * 80)

        user_query = state['user_query']
        current_doc = state.get('current_doc', '无')
        manual_selected_docs = state.get('manual_selected_docs', [])

        # 发送进度更新
        await self._send_progress(
            stage="analyze_intent",
            stage_name="意图分析",
            status="processing",
            message=f"正在分析查询: {user_query[:30]}..."
        )

        # ============ 状态持久化：恢复之前的状态 ============
        if self.agent.persistent_state:
            # 判断当前模式
            persistent_mode = self.agent.persistent_state.get("retrieval_mode", "")
            current_mode = "cross_doc_manual" if manual_selected_docs else (
                "single_doc" if current_doc else "cross_doc_auto"
            )

            # 只在模式相同时恢复状态
            if persistent_mode == current_mode:
                logger.info("🔄 检测到持久化状态，保留以下信息:")

                # 恢复文档选择
                if "selected_documents" in self.agent.persistent_state:
                    state["selected_documents"] = self.agent.persistent_state["selected_documents"]
                    logger.info(f"   - selected_documents: {len(state['selected_documents'])} 个文档")

                # 恢复查询改写
                if "doc_specific_queries" in self.agent.persistent_state:
                    state["doc_specific_queries"] = self.agent.persistent_state["doc_specific_queries"]
                    logger.info(f"   - doc_specific_queries: {len(state['doc_specific_queries'])} 个")

                # 恢复检索模式
                if "retrieval_mode" in self.agent.persistent_state:
                    state["retrieval_mode"] = self.agent.persistent_state["retrieval_mode"]
                    logger.info(f"   - retrieval_mode: {state['retrieval_mode']}")
            else:
                logger.info(f"🔄 检测到模式切换 ({persistent_mode} → {current_mode})，清除持久化状态")
                self.agent.persistent_state = None

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

            # 发送进度完成更新
            await self._send_progress(
                stage="analyze_intent",
                stage_name="意图分析",
                status="completed",
                message=f"{'需要检索' if needs_retrieval else '直接回答'}: {reason}"
            )

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

        # 设置模式标识
        state["retrieval_mode"] = "single_doc"

        logger.info(f"📝 [Retrieve] 输入信息:")
        logger.info(f"   - 用户查询: {user_query}")
        logger.info(f"   - 目标文档: {current_doc if current_doc else '未指定'}")

        # 发送进度更新 - 开始检索
        await self._send_progress(
            stage="retrieve_single",
            stage_name="单文档检索",
            status="processing",
            message=f"正在检索文档: {current_doc or 'unknown'}",
            state=state
        )

        try:
            # 更新当前文档上下文
            self.agent.current_doc = current_doc

            logger.info(f"🤖 [Retrieve] 调用 Retrieval Agent 进行检索...")
            logger.info(f"ℹ️  [Retrieve] Retrieval Agent 的详细进度将实时显示...")

            # 调用工具方法（Retrieval Agent 的进度会通过 progress_callback 实时更新）
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

            # 将结果添加到历史记录中（作为 AI 消息）
            ai_message = AIMessage(content=final_answer)

            # 1. 添加到 Answer Agent 的 analyze_intent session（用于意图分析）
            self.agent.llm.add_message_to_history(
                session_id="analyze_intent",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Retrieve] 已将答案添加到 Answer Agent 的 analyze_intent session 历史")

            # 2. 添加到 Retrieval Agent 的 rewrite_query session（用于查询改写）
            if current_doc and current_doc in self.agent.retrieval_agents:
                retrieval_agent = self.agent.retrieval_agents[current_doc]
                retrieval_agent.llm.add_message_to_history(
                    session_id="rewrite_query",
                    message=ai_message,
                    enable_llm_summary=True
                )
                logger.info(f"📝 [Retrieve] 已将答案添加到 Retrieval Agent 的 rewrite_query session 历史")
            else:
                logger.warning(f"⚠️ [Retrieve] 未找到文档 '{current_doc}' 的 Retrieval Agent，无法添加历史记录")

            # 更新 state 并返回
            state["context"] = context
            state["final_answer"] = final_answer
            state["is_complete"] = True

            # 发送进度完成更新
            await self._send_progress(
                stage="retrieve_single",
                stage_name="单文档检索",
                status="completed",
                message="检索完成",
                state=state
            )

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

            # 发送进度错误更新
            await self._send_progress(
                stage="retrieve_single",
                stage_name="单文档检索",
                status="error",
                message=f"检索失败: {str(e)}",
                state=state
            )

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

            # ============ 状态持久化：保存当前状态供下一轮使用 ============
            self._save_persistent_state(state)

            return state

        context = state.get("context", "")
        user_query = state['user_query']

        logger.info(f"📝 [Generate] 输入信息:")
        logger.info(f"   - 用户查询: {user_query}")
        logger.info(f"   - 是否有检索上下文: {'是' if context else '否'}")
        if context:
            logger.info(f"   - 上下文长度: {len(context)} 字符")
            logger.info(f"   - 上下文预览: {context[:150]}...")

        # 发送进度更新
        await self._send_progress(
            stage="generate",
            stage_name="生成答案",
            status="processing",
            message="正在生成回答...",
            state=state
        )

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

            # 格式化答案以优化UI展示
            logger.info("🎨 [Generate] 格式化答案以优化展示效果...")
            formatted_answer = AnswerFormatter.format_answer(
                answer,
                enhance_math=True,
                enhance_structure=True
            )
            logger.info(f"✅ [Generate] 答案格式化完成")

            # 更新 state 并返回
            state["final_answer"] = formatted_answer
            state["is_complete"] = True

            # 发送进度完成更新
            await self._send_progress(
                stage="generate",
                stage_name="生成答案",
                status="completed",
                message="答案生成完成",
                state=state
            )

            # ============ 状态持久化：保存当前状态供下一轮使用 ============
            self._save_persistent_state(state)

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

            # 发送进度错误更新
            await self._send_progress(
                stage="generate",
                stage_name="生成答案",
                status="error",
                message=f"生成失败: {str(e)}",
                state=state
            )

            # 更新 state 并返回
            state["final_answer"] = error_msg
            state["is_complete"] = True

            # ============ 状态持久化：即使失败也保存状态 ============
            self._save_persistent_state(state)

            return state

    def route_by_intent(self, state: AnswerState) -> str:
        """
        根据意图和模式路由到不同节点

        Returns:
            "direct" | "single_doc" | "cross_doc_auto" | "cross_doc_manual"
        """
        needs_retrieval = state.get("needs_retrieval", False)
        current_doc = state.get("current_doc")
        manual_selected_docs = state.get("manual_selected_docs")
        reason = state.get("analysis_reason", "")

        logger.info("")
        logger.info("🔀 [Route] ========== 路由决策 ==========")

        if not needs_retrieval:
            logger.info("🔀 [Route] 决策: 直接回答 → generate 节点")
            logger.info(f"   - 原因: {reason}")
            return "direct"

        # 优先检查手动选择模式
        if manual_selected_docs and len(manual_selected_docs) > 0:
            logger.info("🔀 [Route] 决策: 跨文档手动选择 → rewrite_queries 节点")
            logger.info(f"   - 手动选择文档: {manual_selected_docs}")
            return "cross_doc_manual"

        # 有明确文档指定 → 单文档模式
        if current_doc:
            logger.info("🔀 [Route] 决策: 单文档检索 → retrieve_single 节点")
            logger.info(f"   - 文档: {current_doc}")
            logger.info(f"   - 原因: {reason}")
            return "single_doc"

        # 无文档指定，无手动选择 → 跨文档自动选择模式
        logger.info("🔀 [Route] 决策: 跨文档自动选择 → select_docs 节点")
        logger.info(f"   - 原因: {reason}")
        return "cross_doc_auto"

    def route_after_selection(self, state: AnswerState) -> str:
        """
        文档选择后的路由

        Returns:
            "no_docs" | "retrieve"
        """
        selected_docs = state.get("selected_documents", [])

        logger.info("")
        logger.info("🔀 [Route] ========== 文档选择后路由 ==========")

        if len(selected_docs) == 0:
            logger.warning("⚠️  [Route] 未找到相关文档，将直接生成答案")
            return "no_docs"

        logger.info(f"✅ [Route] 选择了 {len(selected_docs)} 个文档，继续检索")
        return "retrieve"

    # ==================== 跨文档模式节点 ====================

    async def select_documents(self, state: AnswerState) -> AnswerState:
        """
        步骤1（跨文档模式）：选择相关文档

        使用DocumentSelector智能筛选与查询相关的文档
        """
        from .components import DocumentSelector

        logger.info("==" * 40)
        logger.info("🔍 [SelectDocs] ========== 步骤1: 选择相关文档 ==========")
        logger.info("==" * 40)

        user_query = state["user_query"]

        # 发送进度更新
        await self._send_progress(
            stage="select_docs",
            stage_name="文档选择",
            status="processing",
            message="正在自动选择相关文档..."
        )

        try:
            # 初始化DocumentSelector
            selector = DocumentSelector(self.agent.llm, self.agent.registry)

            # 智能选择文档
            from src.config.settings import DOCUMENT_SELECTION_CONFIG

            selected_docs = await selector.select_relevant_documents(
                query=user_query,
                max_docs=DOCUMENT_SELECTION_CONFIG.get("max_selected_docs", 5)
            )

            logger.info(f"✅ [SelectDocs] 文档选择完成: {len(selected_docs)} 个文档")

            # 更新 state
            state["selected_documents"] = selected_docs
            state["retrieval_mode"] = "cross_doc_auto"  # 设置模式标识

            # 发送进度完成更新
            await self._send_progress(
                stage="select_docs",
                stage_name="文档选择",
                status="completed",
                message=f"已选择 {len(selected_docs)} 个相关文档"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [SelectDocs] 文档选择失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时返回空列表
            state["selected_documents"] = []
            return state

    async def rewrite_queries_for_docs(self, state: AnswerState) -> AnswerState:
        """
        步骤1.5（跨文档模式）：为每个选中的文档生成针对性的改写查询

        根据每个文档的简介（brief_summary）和用户查询，生成适合在该文档中检索的针对性查询
        """
        from .prompts import AnswerRole

        logger.info("==" * 40)
        logger.info("✍️  [RewriteQueries] ========== 步骤1.5: 为文档改写查询 ==========")
        logger.info("==" * 40)

        user_query = state["user_query"]

        # 发送进度更新
        await self._send_progress(
            stage="rewrite_queries",
            stage_name="查询改写",
            status="processing",
            message="正在为各文档改写查询..."
        )

        # 检查是否是手动选择模式
        if "selected_documents" not in state or not state.get("selected_documents"):
            # 手动选择模式：从 manual_selected_docs 构建 selected_documents
            manual_selected_docs = state.get("manual_selected_docs", [])
            if manual_selected_docs:
                logger.info("🔧 [RewriteQueries] 检测到手动选择模式，构建 selected_documents")

                selected_documents = []
                for doc_name in manual_selected_docs:
                    doc_info = self.agent.registry.get_by_name(doc_name)
                    if doc_info:
                        selected_documents.append({
                            "doc_name": doc_name,
                            "brief_summary": doc_info.get("brief_summary", ""),
                            "score": 1.0,
                            "reason": "用户手动选择"
                        })
                    else:
                        logger.warning(f"⚠️  [RewriteQueries] 文档 '{doc_name}' 未找到，跳过")

                state["selected_documents"] = selected_documents
                state["retrieval_mode"] = "cross_doc_manual"  # 设置模式标识
                logger.info(f"✅ [RewriteQueries] 已构建 {len(selected_documents)} 个文档信息（手动选择模式）")
            else:
                logger.error("❌ [RewriteQueries] 没有 selected_documents 也没有 manual_selected_docs")
                state["selected_documents"] = []
        else:
            # 自动选择模式
            if "retrieval_mode" not in state:
                state["retrieval_mode"] = "cross_doc_auto"

        selected_docs = state["selected_documents"]

        logger.info(f"📝 [RewriteQueries] 原始查询: {user_query}")
        logger.info(f"📊 [RewriteQueries] 需要为 {len(selected_docs)} 个文档生成针对性查询")

        try:
            doc_specific_queries = {}

            # 为每个文档并行生成改写查询
            async def rewrite_for_single_doc(doc_info: Dict[str, Any]) -> tuple:
                """为单个文档改写查询"""
                doc_name = doc_info["doc_name"]

                # brief_summary 在 DocumentRegistry 的顶级字段中，不在 metadata 里
                # 需要从 registry 获取完整的文档记录
                from src.core.document_management import DocumentRegistry
                registry = DocumentRegistry()

                doc_record = registry.get_by_name(doc_name)
                if not doc_record:
                    logger.warning(f"⚠️  [RewriteQueries] 无法从注册表获取文档 '{doc_name}' 的信息，使用原始查询")
                    return (doc_name, user_query)

                brief_summary = doc_record.get("brief_summary", "无简介信息")

                # 智能判断：如果 summary 信息不足，直接使用原始查询
                # 避免为了改写而改写
                if not brief_summary or brief_summary == "无简介信息" or len(brief_summary.strip()) < 20:
                    logger.info(f"   ⏭️  文档 '{doc_name}' 简介信息不足（长度: {len(brief_summary)}），跳过改写")
                    return (doc_name, user_query)

                logger.info(f"")
                logger.info(f"📄 [RewriteQueries] 处理文档: {doc_name}")
                logger.info(f"   简介: {brief_summary[:100]}...")

                # 构建提示词
                prompt = f"""原始查询：{user_query}

文档简介：{brief_summary}

请根据文档简介的特点，将原始查询改写成适合在该文档中检索的针对性查询。"""

                try:
                    # 调用 LLM 改写查询
                    rewritten_query = await self.agent.llm.async_call_llm_chain(
                        role=AnswerRole.DOC_SPECIFIC_QUERY_REWRITER,
                        input_prompt=prompt,
                        session_id=f"doc_query_rewrite_{doc_name}"
                    )

                    rewritten_query = rewritten_query.strip()
                    logger.info(f"   改写结果: {rewritten_query}")

                    return (doc_name, rewritten_query)

                except Exception as e:
                    logger.error(f"❌ [RewriteQueries] 文档 '{doc_name}' 查询改写失败: {e}")
                    # 失败时使用原始查询
                    return (doc_name, user_query)

            # 并行处理所有文档
            import asyncio
            rewrite_tasks = [rewrite_for_single_doc(doc) for doc in selected_docs]
            rewrite_results = await asyncio.gather(*rewrite_tasks, return_exceptions=True)

            # 整理结果
            for result in rewrite_results:
                if isinstance(result, Exception):
                    logger.error(f"❌ [RewriteQueries] 改写任务异常: {result}")
                    continue
                doc_name, rewritten_query = result
                doc_specific_queries[doc_name] = rewritten_query

            logger.info("")
            logger.info("==" * 40)
            logger.info("✅ [RewriteQueries] 查询改写完成")
            logger.info("==" * 40)
            logger.info(f"📊 [RewriteQueries] 成功为 {len(doc_specific_queries)} 个文档生成针对性查询")
            logger.info("")
            logger.info(f"📝 [RewriteQueries] 改写结果汇总:")
            for doc_name, query in doc_specific_queries.items():
                logger.info(f"   - {doc_name}: {query[:80]}...")
            logger.info("==" * 40)
            logger.info("")

            # 更新 state
            state["doc_specific_queries"] = doc_specific_queries

            # 发送进度完成更新
            await self._send_progress(
                stage="rewrite_queries",
                stage_name="查询改写",
                status="completed",
                message=f"已为 {len(doc_specific_queries)} 个文档改写查询"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [RewriteQueries] 批量查询改写失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时使用原始查询作为备份
            fallback_queries = {doc["doc_name"]: user_query for doc in selected_docs}
            state["doc_specific_queries"] = fallback_queries

            logger.warning(f"⚠️  [RewriteQueries] 使用原始查询作为备份")
            return state

    async def call_multi_retrieval(self, state: AnswerState) -> AnswerState:
        """
        步骤2（跨文档模式）：并行检索多个文档

        使用ParallelRetrievalCoordinator并行调用多个RetrievalAgent
        使用为每个文档定制的改写查询
        """
        from src.core.parallel import ParallelRetrievalCoordinator

        logger.info("==" * 40)
        logger.info("🚀 [MultiRetrieval] ========== 步骤2: 并行检索多文档 ==========")
        logger.info("==" * 40)

        user_query = state["user_query"]
        selected_docs = state["selected_documents"]
        doc_specific_queries = state.get("doc_specific_queries", {})

        logger.info(f"📝 [MultiRetrieval] 原始查询: {user_query}")
        logger.info(f"📊 [MultiRetrieval] 已为 {len(doc_specific_queries)} 个文档准备了定制查询")

        # 发送进度更新
        await self._send_progress(
            stage="retrieve_multi",
            stage_name="多文档检索",
            status="processing",
            message=f"正在并行检索 {len(selected_docs)} 个文档..."
        )

        try:
            # 初始化协调器
            coordinator = ParallelRetrievalCoordinator(self.agent)

            # 并行检索（使用改写后的查询）
            from src.config.settings import CROSS_DOC_CONFIG

            multi_results = await coordinator.retrieve_from_multiple_docs(
                query=user_query,  # 保留原始查询作为备份
                doc_list=selected_docs,
                doc_specific_queries=doc_specific_queries,  # 传递文档特定的改写查询
                max_iterations=CROSS_DOC_CONFIG.get("max_iterations", 10),
                max_concurrent=CROSS_DOC_CONFIG.get("max_parallel_retrievals", 5),
                timeout_per_doc=CROSS_DOC_CONFIG.get("retrieval_timeout", 120)
            )

            logger.info(f"✅ [MultiRetrieval] 完成 {len(multi_results)} 个文档的检索")

            # 更新 state
            state["multi_doc_results"] = multi_results

            # 发送进度完成更新
            await self._send_progress(
                stage="retrieve_multi",
                stage_name="多文档检索",
                status="completed",
                message=f"已完成 {len(multi_results)} 个文档的检索"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [MultiRetrieval] 并行检索失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时返回空结果
            state["multi_doc_results"] = {}
            return state

    async def synthesize_multi_docs(self, state: AnswerState) -> AnswerState:
        """
        步骤3（跨文档模式）：综合多文档结果

        使用CrossDocumentSynthesizer综合生成最终答案
        """
        from .components import CrossDocumentSynthesizer
        from langchain_core.messages import AIMessage

        logger.info("==" * 40)
        logger.info("🔗 [Synthesize] ========== 步骤3: 综合多文档结果 ==========")
        logger.info("==" * 40)

        user_query = state["user_query"]
        multi_results = state["multi_doc_results"]

        # 发送进度更新
        await self._send_progress(
            stage="synthesize",
            stage_name="综合答案",
            status="processing",
            message=f"正在综合 {len(multi_results)} 个文档的检索结果..."
        )

        try:
            # 初始化综合器
            synthesizer = CrossDocumentSynthesizer(self.agent.llm)

            # 综合生成答案
            final_answer = await synthesizer.synthesize(user_query, multi_results)

            logger.info(f"✅ [Synthesize] 综合答案生成完成（长度: {len(final_answer)}）")

            # 格式化跨文档综合答案以优化UI展示
            logger.info("🎨 [Synthesize] 格式化跨文档综合答案...")
            selected_docs = state.get("selected_documents", [])
            # 提取文档名称列表（selected_documents 是字典列表）
            doc_names = [doc.get("doc_name") for doc in selected_docs if isinstance(doc, dict)]
            formatted_answer = AnswerFormatter.format_cross_doc_synthesis(
                final_answer,
                doc_names=doc_names
            )
            logger.info(f"✅ [Synthesize] 综合答案格式化完成")

            # 直接设置最终答案（跳过generate节点）
            state["final_answer"] = formatted_answer
            state["is_complete"] = True

            # 将结果添加到历史记录中（作为 AI 消息）
            ai_message = AIMessage(content=final_answer)

            # 1. 添加到 Answer Agent 的 analyze_intent session（用于意图分析）
            self.agent.llm.add_message_to_history(
                session_id="analyze_intent",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Synthesize] 已将答案添加到 Answer Agent 的 analyze_intent session 历史")

            # 2. 添加到每个 Retrieval Agent 的 rewrite_query session（用于查询改写）
            selected_docs = state.get("selected_documents", [])
            for doc_info in selected_docs:
                doc_name = doc_info.get("doc_name")
                if doc_name and doc_name in self.agent.retrieval_agents:
                    retrieval_agent = self.agent.retrieval_agents[doc_name]
                    retrieval_agent.llm.add_message_to_history(
                        session_id="rewrite_query",
                        message=ai_message,
                        enable_llm_summary=True
                    )
                    logger.info(f"📝 [Synthesize] 已将答案添加到文档 '{doc_name}' 的 Retrieval Agent rewrite_query session 历史")

            logger.info(f"📝 [Synthesize] 已将跨文档综合答案添加到 {len(selected_docs)} 个 Retrieval Agent 的 rewrite_query session")

            # 发送进度完成更新
            await self._send_progress(
                stage="synthesize",
                stage_name="综合答案",
                status="completed",
                message="跨文档综合完成"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Synthesize] 综合失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时设置错误消息
            error_msg = f"抱歉，综合多文档结果时出现错误：{str(e)}"
            state["final_answer"] = error_msg
            state["is_complete"] = True

            return state
