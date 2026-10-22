"""
AnswerAgent Workflow节点方法

单轮确定性架构：rewrite_query → plan → execute → evaluate → generate
（不再回环到 plan 做二次规划，evaluate 仅作终止标记）
"""

from __future__ import annotations
from typing import Dict, Any, List, TYPE_CHECKING
import logging

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

    # ==================== 进度回调 ====================

    async def _send_progress(self, stage: str, stage_name: str, status: str = "processing",
                             message: str = "", **kwargs):
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
            progress_data.update(kwargs)
            await self.agent.progress_callback(progress_data)
        except Exception as e:
            logger.warning(f"⚠️ 发送进度更新失败: {e}")

    # ==================== Node 1: plan ====================

    # 寒暄关键词（用于快速过滤，避免不必要的工具调用）
    _GREETING_PATTERNS = {
        "你好", "您好", "早上好", "下午好", "晚上好", "晚安",
        "谢谢", "感谢", "多谢", "非常感谢",
        "再见", "拜拜", "bye",
        "hi", "hello", "hey", "thanks", "thank you",
        "good morning", "good afternoon", "good evening",
    }

    # ==================== Node 0: rewrite_query ====================

    async def rewrite_query(self, state: AnswerState) -> AnswerState:
        """
        上下文查询改写节点

        根据对话历史和文档简介，将用户的简略查询改写为完整、明确的查询。
        处理省略、指代、上下文依赖等情况。

        改写依据：
        1. 对话历史：补全省略的主语、动作、话题延续
        2. 文档简介：结合文档主题，使查询更贴合文档内容

        例如：
        - 历史："南京天气怎么样？" → 当前："北京和成都呢？"
          改写后："北京和成都的天气怎么样？"
        - 文档："Transformer论文" → 当前："有哪些优点？"
          改写后："Transformer模型有哪些优点？"
        """
        from .prompts import AnswerRole
        from langchain_core.messages import HumanMessage

        logger.info("=" * 80)
        logger.info("✏️  [RewriteQuery] ========== 上下文查询改写 ==========")
        logger.info("=" * 80)

        user_query = state["user_query"]
        logger.info(f"📝 [RewriteQuery] 原始查询: {user_query}")

        await self._send_progress(
            stage="rewrite_query",
            stage_name="查询改写",
            status="processing",
            message="正在根据上下文改写查询..."
        )

        try:
            # 获取对话历史
            history_obj = self.agent.llm.get_message_history("tool_planning", enable_llm_summary=True)
            history = history_obj.messages if history_obj else []

            # 获取选中的文档信息
            selected_docs = state.get("selected_docs", [])
            doc_context = ""

            if selected_docs:
                # 从 DocumentRegistry 获取文档简介
                doc_summaries = []
                for doc_name in selected_docs:
                    doc_info = self.agent.registry.get_by_name(doc_name)
                    if doc_info:
                        brief_summary = doc_info.get("brief_summary", "")
                        if brief_summary:
                            doc_summaries.append(f"- **{doc_name}**: {brief_summary}")
                        else:
                            doc_summaries.append(f"- **{doc_name}**: (无简介)")

                if doc_summaries:
                    doc_context = f"""

选中的文档信息：
{chr(10).join(doc_summaries)}"""
                    logger.info(f"📚 [RewriteQuery] 已加载 {len(doc_summaries)} 个文档的简介")

            # 快速路径：如果没有历史记录且没有文档上下文，直接使用原始查询
            if (not history or len(history) == 0) and not doc_context:
                logger.info(f"💡 [RewriteQuery] 无历史记录和文档上下文，使用原始查询")
                state["rewritten_query"] = user_query
                await self._send_progress(
                    stage="rewrite_query",
                    stage_name="查询改写",
                    status="completed",
                    message="无需改写"
                )
                return state

            # 智能判断：对于完整查询，跳过 LLM 调用以提升性能
            if self._is_query_complete(user_query, history, doc_context):
                logger.info(f"💡 [RewriteQuery] 查询已完整，跳过 LLM 调用")
                state["rewritten_query"] = user_query
                await self._send_progress(
                    stage="rewrite_query",
                    stage_name="查询改写",
                    status="completed",
                    message="查询完整，无需改写"
                )
                return state

            # 构造改写提示
            # 格式化历史记录（只取最近5轮）
            history_text = ""
            if history and len(history) > 0:
                recent_history = history[-10:] if len(history) > 10 else history
                for msg in recent_history:
                    if hasattr(msg, 'type'):
                        if msg.type == "human":
                            history_text += f"用户: {msg.content}\n"
                        elif msg.type == "ai":
                            history_text += f"助手: {msg.content[:200]}...\n"  # 截断长回复
                history_text = f"""对话历史：
{history_text}"""
            else:
                history_text = ""

            prompt = f"""{history_text}{doc_context}

当前用户查询：
{user_query}

请根据{'对话历史和' if history_text else ''}文档信息改写当前查询，使其完整、明确、更贴合文档主题。如果当前查询已经完整，则直接返回原查询。

改写后的查询："""

            # 调用 LLM
            rewritten = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.CONTEXT_QUERY_REWRITER,
                input_prompt=prompt,
                session_id="rewrite_query_session"
            )

            # 清理结果
            rewritten = rewritten.strip()

            # 如果改写结果为空或过短，使用原始查询
            if not rewritten or len(rewritten) < 2:
                logger.warning(f"⚠️  [RewriteQuery] 改写结果无效，使用原始查询")
                rewritten = user_query

            state["rewritten_query"] = rewritten

            if rewritten != user_query:
                logger.info(f"✅ [RewriteQuery] 查询已改写")
                logger.info(f"   原始: {user_query}")
                logger.info(f"   改写: {rewritten}")
            else:
                logger.info(f"💡 [RewriteQuery] 查询无需改写")

            await self._send_progress(
                stage="rewrite_query",
                stage_name="查询改写",
                status="completed",
                message=f"改写完成" if rewritten != user_query else "无需改写"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [RewriteQuery] 改写失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 失败时使用原始查询
            state["rewritten_query"] = user_query

            await self._send_progress(
                stage="rewrite_query",
                stage_name="查询改写",
                status="error",
                message=f"改写失败，使用原始查询: {str(e)}"
            )

            return state

    def _is_query_complete(self, query: str, history, doc_context: str) -> bool:
        """
        判断查询是否已经完整，无需改写

        完整查询的特征：
        1. 长度足够（>= 5个字符）
        2. 不包含明显的省略标记（呢、它、这个、那个等）
        3. 不是纯粹的追问（什么、哪些、怎么样等单独出现）

        优化目标：跳过不必要的 LLM 调用，提升首次查询速度
        """
        # 移除空格和标点符号后的查询
        clean_query = query.strip().rstrip("!！?？.。~")

        # 1. 寒暄直接跳过
        if self._is_greeting(query):
            return True

        # 2. 查询过短，可能需要补全
        if len(clean_query) < 5:
            return False

        # 3. 包含明显的省略标记
        ellipsis_markers = ["呢", "它", "这个", "那个", "那", "哪"]
        if any(marker in clean_query for marker in ellipsis_markers):
            return False

        # 4. 只是简单的疑问词（什么、为什么、怎么等单独出现）
        simple_questions = ["什么", "为什么", "怎么", "如何", "哪些", "哪个"]
        if clean_query in simple_questions:
            return False

        # 5. 如果有历史记录，更倾向于调用 LLM（可能是追问）
        if history and len(history) > 0:
            # 但如果查询很长且完整（>= 15字），即使有历史也可能不需要改写
            if len(clean_query) >= 15:
                return True
            # 查询较短且有历史，可能需要改写
            return False

        # 6. 首次查询且有文档上下文
        if doc_context:
            # 如果查询已经包含文档相关的关键词，可能不需要改写
            # 但保守起见，对于首次查询 + 有文档的情况，让 LLM 判断
            # 除非查询非常完整（>= 10字）
            if len(clean_query) >= 10:
                return True

        # 默认：首次查询且查询足够长，认为是完整的
        return len(clean_query) >= 8

    # ==================== Node 1: plan ====================

    async def plan(self, state: AnswerState) -> AnswerState:
        """
        Plan 节点（确定性逻辑，无 LLM 参与）

        用户通过 enabled_tools 控制使用哪些工具，plan 节点只做：
        1. 初始化状态字段
        2. 寒暄过滤（纯寒暄不调用工具）
        3. 按用户选择确定性地构造工具调用
        """
        iteration = state.get("current_iteration", 0)

        logger.info("=" * 80)
        logger.info("🧠 [Plan] ========== 工具规划 ==========")
        logger.info("=" * 80)

        user_query = state["user_query"]
        enabled_tools = state.get("enabled_tools", [])
        selected_docs = state.get("selected_docs")
        tool_results = state.get("tool_results", [])

        await self._send_progress(
            stage="plan",
            stage_name="工具规划",
            status="processing",
            message=f"正在分析查询: {user_query[:30]}..."
        )

        # 初始化状态字段
        # （current_iteration / max_iterations 仅作兼容保留，不再驱动多轮规划）
        if "thoughts" not in state:
            state["thoughts"] = []
        if "tool_calls" not in state:
            state["tool_calls"] = []
        if "tool_results" not in state:
            state["tool_results"] = []
        if "current_iteration" not in state:
            state["current_iteration"] = 0
        if "max_iterations" not in state:
            state["max_iterations"] = 3

        logger.info(f"📝 [Plan] 用户查询: {user_query}")
        logger.info(f"📝 [Plan] 启用工具: {enabled_tools}")
        logger.info(f"📝 [Plan] 选择文档: {selected_docs}")
        if tool_results:
            logger.info(f"📝 [Plan] 已有 {len(tool_results)} 个工具结果")

        # ========== 判断逻辑 ==========

        # 情况1：用户没有启用任何工具 → 纯对话
        if not enabled_tools:
            state["is_complete"] = True
            state["thoughts"].append("用户未启用任何工具，纯对话模式")
            logger.info(f"✅ [Plan] 无启用工具，纯对话模式")
            await self._send_progress(stage="plan", stage_name="工具规划",
                                      status="completed", message="纯对话模式")
            return state

        # 情况2：已有工具结果（多轮迭代）→ 已经检索过，直接生成
        if tool_results:
            state["is_complete"] = True
            state["thoughts"].append("已有工具结果，直接生成答案")
            logger.info(f"✅ [Plan] 已有工具结果，跳过重复调用")
            await self._send_progress(stage="plan", stage_name="工具规划",
                                      status="completed", message="使用已有结果")
            return state

        # 情况3：寒暄过滤
        if self._is_greeting(user_query):
            state["is_complete"] = True
            state["thoughts"].append("寒暄对话，无需调用工具")
            logger.info(f"✅ [Plan] 寒暄检测，跳过工具调用")
            await self._send_progress(stage="plan", stage_name="工具规划",
                                      status="completed", message="直接回答")
            return state

        # 情况4：按用户选择构造工具调用
        new_tool_calls = self._build_tool_calls_from_user_selection(state)
        for tc in new_tool_calls:
            tc["iteration"] = iteration
        state["tool_calls"].extend(new_tool_calls)
        state["thoughts"].append(f"按用户选择调用 {len(new_tool_calls)} 个工具")
        logger.info(f"🔧 [Plan] 构造 {len(new_tool_calls)} 个工具调用: {[tc['tool'] for tc in new_tool_calls]}")

        await self._send_progress(
            stage="plan",
            stage_name="工具规划",
            status="completed",
            message=f"调用 {len(new_tool_calls)} 个工具"
        )

        return state

    def _is_greeting(self, query: str) -> bool:
        """检测是否为寒暄"""
        normalized = query.strip().lower().rstrip("!！?？.。~")
        return normalized in self._GREETING_PATTERNS

    def _build_tool_calls_from_user_selection(self, state: AnswerState) -> List[Dict[str, Any]]:
        """按用户的 enabled_tools 和 selected_docs 构造工具调用"""
        # 优先使用改写后的查询，如果没有则使用原始查询
        query = state.get("rewritten_query") or state["user_query"]
        enabled_tools = state.get("enabled_tools", [])
        selected_docs = state.get("selected_docs")

        calls = []

        for tool_name in enabled_tools:
            if tool_name == "retrieve_documents":
                args = {"query": query}
                if selected_docs:
                    args["doc_names"] = selected_docs
                calls.append({"tool": "retrieve_documents", "args": args})

            elif tool_name == "search_web":
                calls.append({"tool": "search_web", "args": {"query": query}})

        return calls

    # ==================== Router: route_after_plan ====================

    def route_after_plan(self, state: AnswerState) -> str:
        """plan 节点后的路由"""
        if state.get("is_complete", False):
            logger.info("🔀 [Route] plan → generate（不需要工具）")
            return "direct"

        # 检查是否有新的工具调用（尚未执行的）
        tool_calls = state.get("tool_calls", [])
        tool_results = state.get("tool_results", [])
        if len(tool_calls) > len(tool_results):
            logger.info("🔀 [Route] plan → execute（有新的工具调用）")
            return "execute"

        # 没有新的工具调用，直接生成
        logger.info("🔀 [Route] plan → generate（无新工具调用）")
        return "direct"

    # ==================== Node 2: execute_tools ====================

    async def execute_tools(self, state: AnswerState) -> AnswerState:
        """
        Execute 节点

        执行 plan 节点决定的工具调用。
        """
        import asyncio

        logger.info("=" * 80)
        logger.info("⚡ [Execute] ========== 执行工具调用 ==========")
        logger.info("=" * 80)

        tool_calls = state.get("tool_calls", [])
        tool_results = state.get("tool_results", [])

        # 取出尚未执行的工具调用
        executed_count = len(tool_results)
        pending_calls = tool_calls[executed_count:]

        if not pending_calls:
            logger.info("⏭️  [Execute] 没有待执行的工具调用")
            return state

        logger.info(f"🔧 [Execute] 待执行 {len(pending_calls)} 个工具调用")

        await self._send_progress(
            stage="execute_tools",
            stage_name="执行工具",
            status="processing",
            message=f"正在执行 {len(pending_calls)} 个工具调用..."
        )

        # 并行执行所有工具调用
        async def execute_single(tc: Dict) -> Dict:
            tool_name = tc["tool"]
            args = tc.get("args", {})
            logger.info(f"   🔧 执行工具: {tool_name}({args})")

            try:
                result = await self._dispatch_tool(tool_name, args)
                success = result.get("success", False)
                logger.info(f"   {'✅' if success else '❌'} {tool_name}: {'成功' if success else '失败'}")
                return {
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                    "success": success
                }
            except Exception as e:
                logger.error(f"   ❌ {tool_name} 执行异常: {e}")
                return {
                    "tool": tool_name,
                    "args": args,
                    "result": {"success": False, "error": str(e)},
                    "success": False
                }

        results = await asyncio.gather(*[execute_single(tc) for tc in pending_calls])

        # 追加结果
        state["tool_results"].extend(results)

        # 递增迭代计数
        state["current_iteration"] = state.get("current_iteration", 0) + 1

        success_count = sum(1 for r in results if r["success"])
        logger.info(f"✅ [Execute] 完成: {success_count}/{len(results)} 个工具调用成功")

        await self._send_progress(
            stage="execute_tools",
            stage_name="执行工具",
            status="completed",
            message=f"执行完成: {success_count}/{len(results)} 成功"
        )

        return state

    async def _dispatch_tool(self, tool_name: str, args: Dict) -> Dict:
        """工具分发"""
        from .tools_config import is_tool_enabled

        if not is_tool_enabled(tool_name):
            return {"success": False, "error": f"工具 '{tool_name}' 未启用"}

        if tool_name == "retrieve_documents":
            return await self.agent.tools.retrieve_documents(**args)
        elif tool_name == "search_web":
            return await self.agent.tools.search_web(**args)
        else:
            return {"success": False, "error": f"未知工具: {tool_name}"}

    # ==================== Node 3: evaluate ====================

    async def evaluate(self, state: AnswerState) -> AnswerState:
        """
        Evaluate 节点

        评估是否已有足够信息回答用户问题，设置 is_complete 终止标记。
        在当前单轮架构下，该节点后直接进入 generate，不再回环到 plan，
        因此不再依赖 current_iteration / max_iterations 做迭代终止判断
        （这两个字段仅保留以兼容旧代码引用）。
        """
        logger.info("=" * 80)
        logger.info("📊 [Evaluate] ========== 评估完整性 ==========")
        logger.info("=" * 80)

        tool_results = state.get("tool_results", [])

        # 终止条件1：所有工具调用都失败
        if tool_results:
            all_failed = all(not r.get("success", False) for r in tool_results)
            if all_failed:
                logger.warning(f"⚠️ [Evaluate] 所有工具调用都失败，进入生成")
                state["is_complete"] = True
                return state

        # 终止条件2：有成功的工具结果（单轮架构下一轮成功即足够）
        # 对于大多数文档检索场景，一轮检索已足够
        has_success = any(r.get("success", False) for r in tool_results)
        if has_success:
            # 检查最近一轮的结果是否有实质内容
            latest_results = [r for r in tool_results if r.get("success", False)]
            has_content = False
            for r in latest_results:
                result_data = r.get("result", {})
                answer = result_data.get("answer", "") if isinstance(result_data, dict) else ""
                if answer and len(answer) > 10:
                    has_content = True
                    break

            if has_content:
                logger.info(f"✅ [Evaluate] 有充足的工具结果，准备生成答案")
            else:
                logger.info(f"ℹ️  [Evaluate] 工具成功但内容较少，单轮架构下直接进入 generate")
            state["is_complete"] = True
            return state

        # 没有工具结果（不应该到这里，但安全起见）
        logger.info(f"⚠️ [Evaluate] 无工具结果，标记完成")
        state["is_complete"] = True
        return state

    # ==================== Node 4: generate_answer ====================

    async def generate_answer(self, state: AnswerState) -> AnswerState:
        """
        生成最终答案

        基于所有工具结果和对话历史生成最终回答。
        """
        from .prompts import AnswerRole
        from langchain_core.messages import AIMessage

        logger.info("=" * 80)
        logger.info("💬 [Generate] ========== 生成最终答案 ==========")
        logger.info("=" * 80)

        user_query = state["user_query"]
        tool_results = state.get("tool_results", [])

        await self._send_progress(
            stage="generate",
            stage_name="生成答案",
            status="processing",
            message="正在生成回答..."
        )

        try:
            # 提取工具结果中的答案内容
            context_parts = []
            for tr in tool_results:
                if not tr.get("success", False):
                    continue
                result = tr.get("result", {})
                if isinstance(result, dict):
                    answer = result.get("answer", "")
                    mode = result.get("mode", "")
                    doc_names = result.get("doc_names", [])
                    if answer:
                        context_parts.append(answer)

            context = "\n\n".join(context_parts)

            # 特殊处理：单文档检索结果直接作为最终答案
            if (len(tool_results) == 1
                and tool_results[0].get("success")
                and isinstance(tool_results[0].get("result"), dict)
                and tool_results[0]["result"].get("mode") == "single"):
                # 单文档模式：RetrievalAgent 已经生成了完整的答案
                final_answer = tool_results[0]["result"].get("answer", "")
                if final_answer:
                    logger.info(f"✅ [Generate] 单文档模式，直接使用检索结果（长度: {len(final_answer)}）")
                    state["final_answer"] = final_answer
                    state["is_complete"] = True
                    # 添加到历史记录
                    self._add_to_history(final_answer)
                    await self._send_progress(
                        stage="generate",
                        stage_name="生成答案",
                        status="completed",
                        message="答案生成完成"
                    )
                    return state
                else:
                    logger.warning(f"⚠️  [Generate] 单文档模式返回空答案，切换到通用路径")

            # 特殊处理：多文档综合结果直接使用
            if (len(tool_results) == 1
                and tool_results[0].get("success")
                and isinstance(tool_results[0].get("result"), dict)
                and tool_results[0]["result"].get("mode") in ("multi", "auto")):
                final_answer = tool_results[0]["result"].get("answer", "")
                if final_answer:
                    logger.info(f"✅ [Generate] 多文档模式，直接使用综合结果（长度: {len(final_answer)}）")
                    state["final_answer"] = final_answer
                    state["is_complete"] = True
                    self._add_to_history(final_answer)
                    await self._send_progress(
                        stage="generate",
                        stage_name="生成答案",
                        status="completed",
                        message="答案生成完成"
                    )
                    return state
                else:
                    logger.warning(f"⚠️  [Generate] 多文档模式返回空答案，切换到通用路径")

            # 通用路径：使用 LLM 生成答案
            if context:
                prompt = f"""用户问题：{user_query}

文档参考内容：
{context}"""
                logger.info(f"📚 [Generate] 回答模式: 基于工具结果 + 历史对话")
            else:
                prompt = f"""用户问题：{user_query}"""
                logger.info(f"💬 [Generate] 回答模式: 仅历史对话（无工具结果）")

            answer = await self.agent.llm.async_call_llm_chain(
                role=AnswerRole.CONVERSATIONAL_QA,
                input_prompt=prompt,
                session_id="generate_answer"
            )

            # 格式化答案
            formatted_answer = AnswerFormatter.format_answer(
                answer,
                enhance_math=True,
                enhance_structure=True
            )

            # 确保答案不为空
            if not formatted_answer or not formatted_answer.strip():
                logger.warning(f"⚠️  [Generate] LLM 返回空答案，使用默认回复")
                formatted_answer = "抱歉，我暂时无法回答这个问题。请尝试换个方式提问。"

            state["final_answer"] = formatted_answer
            state["is_complete"] = True

            logger.info(f"✅ [Generate] 答案生成完成（长度: {len(formatted_answer)}）")

            # 添加到历史记录
            self._add_to_history(formatted_answer)

            await self._send_progress(
                stage="generate",
                stage_name="生成答案",
                status="completed",
                message="答案生成完成"
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Generate] 生成失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            error_msg = f"抱歉，生成回答时出现错误：{str(e)}"
            state["final_answer"] = error_msg
            state["is_complete"] = True
            state["error"] = str(e)

            await self._send_progress(
                stage="generate",
                stage_name="生成答案",
                status="error",
                message=f"生成失败: {str(e)}"
            )

            return state

    def _add_to_history(self, answer: str):
        """将答案添加到对话历史"""
        from langchain_core.messages import AIMessage

        ai_message = AIMessage(content=answer)

        # 添加到 Answer Agent 的 tool_planning session
        self.agent.llm.add_message_to_history(
            session_id="tool_planning",
            message=ai_message,
            enable_llm_summary=True
        )
        logger.info(f"📝 [Generate] 已将答案添加到 tool_planning session 历史")

        # 添加到每个 Retrieval Agent 的 rewrite_query session
        for doc_name, retrieval_agent in self.agent.retrieval_agents.items():
            retrieval_agent.llm.add_message_to_history(
                session_id="rewrite_query",
                message=ai_message,
                enable_llm_summary=True
            )
            logger.info(f"📝 [Generate] 已将答案添加到文档 '{doc_name}' 的 Retrieval Agent 历史")
