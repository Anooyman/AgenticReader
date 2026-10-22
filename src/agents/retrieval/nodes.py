"""
RetrievalAgent Workflow节点方法

所有workflow节点的实现
"""

from __future__ import annotations
from typing import Dict, TYPE_CHECKING
import logging
import json
import re

from .state import RetrievalState
from .prompts import RetrievalRole
from .tools_config import format_all_tools_for_llm, get_tool_by_name
from src.config.constants import ProcessingLimits

if TYPE_CHECKING:
    from .agent import RetrievalAgent

logger = logging.getLogger(__name__)


class RetrievalNodes:
    """RetrievalAgent Workflow节点方法集合"""

    def __init__(self, agent: 'RetrievalAgent'):
        """
        Args:
            agent: RetrievalAgent实例（依赖注入）
        """
        self.agent = agent

    def _doc_tag(self) -> str:
        """
        获取文档标识（用于日志前缀，便于并行场景下区分）

        Returns:
            文档名标签，如 "doc.pdf" 或 "MultiDoc"
        """
        return self.agent.current_doc or "MultiDoc"

    async def _send_progress(self, stage: str, stage_name: str, state: RetrievalState,
                            status: str = "processing", message: str = "", tool: str = None):
        """
        发送进度更新（通过progress_callback）

        Args:
            stage: 阶段标识（rewrite/think/act/summary/evaluate/format）
            stage_name: 阶段中文名称
            state: 当前状态
            status: 状态（processing/completed/error）
            message: 详细消息
            tool: 当前使用的工具（可选）
        """
        if not self.agent.progress_callback:
            return

        try:
            progress_data = {
                "agent": "retrieval",
                "stage": stage,
                "stage_name": stage_name,
                "iteration": state.get("current_iteration", 0) + 1,  # +1 显示从1开始
                "max_iterations": state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS),
                "status": status,
                "message": message,
                "doc_name": self._doc_tag()
            }

            if tool:
                progress_data["tool"] = tool

            await self.agent.progress_callback(progress_data)
        except Exception as e:
            logger.warning(f"⚠️  发送进度更新失败: {e}")

    def _save_persistent_state(self, state: RetrievalState):
        """
        保存状态供下一轮检索使用（内部方法）

        保存的字段：
        - thoughts: 思考过程（累积）
        - actions: 动作历史（累积）
        - observations: 观察结果（累积）
        - retrieved_content: 检索内容（累积）
        - formatted_data: 格式化数据（累积）
        - intermediate_summary: 中间总结（用于 query rewrite）
        """
        self.agent.persistent_state = {}

        # 保存 ReAct 历史（累积）
        if "thoughts" in state and state["thoughts"]:
            self.agent.persistent_state["thoughts"] = state["thoughts"].copy()
            logger.info(f"💾 [{self._doc_tag()}] 保存 thoughts: {len(state['thoughts'])} 条")

        if "actions" in state and state["actions"]:
            self.agent.persistent_state["actions"] = state["actions"].copy()
            logger.info(f"💾 [{self._doc_tag()}] 保存 actions: {len(state['actions'])} 个")

        if "observations" in state and state["observations"]:
            self.agent.persistent_state["observations"] = state["observations"].copy()
            logger.info(f"💾 [{self._doc_tag()}] 保存 observations: {len(state['observations'])} 条")

        # 保存检索内容（累积）
        if "retrieved_content" in state and state["retrieved_content"]:
            self.agent.persistent_state["retrieved_content"] = state["retrieved_content"].copy()
            logger.info(f"💾 [{self._doc_tag()}] 保存 retrieved_content: {len(state['retrieved_content'])} 个")

        if "formatted_data" in state and state["formatted_data"]:
            self.agent.persistent_state["formatted_data"] = state["formatted_data"].copy()
            logger.info(f"💾 [{self._doc_tag()}] 保存 formatted_data: {len(state['formatted_data'])} 个")

        # 保存中间总结（用于 query rewrite）
        if "intermediate_summary" in state and state["intermediate_summary"]:
            self.agent.persistent_state["intermediate_summary"] = state["intermediate_summary"]
            logger.info(f"💾 [{self._doc_tag()}] 保存 intermediate_summary: {len(state['intermediate_summary'])} 字符")

    async def initialize(self, state: RetrievalState) -> Dict:
        """初始化节点：设置Agent的上下文环境"""
        logger.info(f"🔧 [Initialize|{self._doc_tag()}] ========== RetrievalAgent 初始化 ==========")

        try:
            # 验证state
            self.agent.utils.validate_state(state)

            # 从state中读取并设置文档上下文
            doc_name_from_state = state.get('doc_name')
            self.agent.current_doc = doc_name_from_state or self.agent.current_doc

            # 同步当前对话轮次给向量库去重窗口
            # （去重记录只保留最近 N 轮，更早的自动淘汰，避免检索空间单调收窄）
            conversation_turn = state.get("conversation_turn", 0) or 0
            self.agent.current_conversation_turn = conversation_turn
            logger.info(f"🔧 [Initialize|{self._doc_tag()}] 对话轮次: {conversation_turn}")

            logger.info(f"🔧 [Initialize|{self._doc_tag()}] 配置信息:")
            logger.info(f"🔧 [Initialize|{self._doc_tag()}]   - 文档名称: {self.agent.current_doc or '多文档模式'}")
            logger.info(f"🔧 [Initialize|{self._doc_tag()}]   - 查询内容: {state['query']}")
            logger.info(f"🔧 [Initialize|{self._doc_tag()}]   - 最大迭代: {state['max_iterations']}")

            # 创建或更新 VectorDBClient
            if self.agent.current_doc:
                if self.agent.vector_db_client is None:
                    self.agent.vector_db_client = self.agent.utils.create_vector_db_client(self.agent.current_doc)
                    logger.info(f"✅ [Initialize|{self._doc_tag()}] VectorDBClient 已创建并加载")
                elif doc_name_from_state and doc_name_from_state != self.agent.current_doc:
                    logger.info(f"🔄 [Initialize|{self._doc_tag()}] 文档名称变化，重新创建VectorDBClient")
                    self.agent.vector_db_client = self.agent.utils.create_vector_db_client(doc_name_from_state)
                    self.agent.current_doc = doc_name_from_state

            # 把当前对话轮次同步给去重窗口（新客户端会在这里完成对齐）
            if self.agent.vector_db_client:
                self.agent.vector_db_client.set_current_turn(conversation_turn)

            # ============ 状态持久化：恢复之前的检索历史 ============
            if self.agent.persistent_state:
                logger.info(f"🔄 [Initialize|{self._doc_tag()}] 检测到持久化状态，恢复历史信息:")

                # 获取历史长度限制（避免上下文无限增长）
                max_history = ProcessingLimits.MAX_PERSISTENT_HISTORY_LENGTH

                # 恢复 ReAct 历史（只保留最近的 N 条）
                if "thoughts" in self.agent.persistent_state:
                    full_thoughts = self.agent.persistent_state["thoughts"]
                    state["thoughts"] = full_thoughts[-max_history:].copy() if len(full_thoughts) > max_history else full_thoughts.copy()
                    if len(full_thoughts) > max_history:
                        logger.info(f"   - thoughts: {len(full_thoughts)} 条 → 裁剪至最近 {len(state['thoughts'])} 条")
                    else:
                        logger.info(f"   - thoughts: {len(state['thoughts'])} 条")

                if "actions" in self.agent.persistent_state:
                    full_actions = self.agent.persistent_state["actions"]
                    state["actions"] = full_actions[-max_history:].copy() if len(full_actions) > max_history else full_actions.copy()
                    if len(full_actions) > max_history:
                        logger.info(f"   - actions: {len(full_actions)} 个 → 裁剪至最近 {len(state['actions'])} 个")
                    else:
                        logger.info(f"   - actions: {len(state['actions'])} 个")

                if "observations" in self.agent.persistent_state:
                    full_observations = self.agent.persistent_state["observations"]
                    state["observations"] = full_observations[-max_history:].copy() if len(full_observations) > max_history else full_observations.copy()
                    if len(full_observations) > max_history:
                        logger.info(f"   - observations: {len(full_observations)} 条 → 裁剪至最近 {len(state['observations'])} 条")
                    else:
                        logger.info(f"   - observations: {len(state['observations'])} 条")

                # 恢复检索内容（只保留最近的 N 个）
                if "retrieved_content" in self.agent.persistent_state:
                    full_content = self.agent.persistent_state["retrieved_content"]
                    state["retrieved_content"] = full_content[-max_history:].copy() if len(full_content) > max_history else full_content.copy()
                    if len(full_content) > max_history:
                        logger.info(f"   - retrieved_content: {len(full_content)} 个 → 裁剪至最近 {len(state['retrieved_content'])} 个")
                    else:
                        logger.info(f"   - retrieved_content: {len(state['retrieved_content'])} 个")

                if "formatted_data" in self.agent.persistent_state:
                    full_data = self.agent.persistent_state["formatted_data"]
                    state["formatted_data"] = full_data[-max_history:].copy() if len(full_data) > max_history else full_data.copy()
                    if len(full_data) > max_history:
                        logger.info(f"   - formatted_data: {len(full_data)} 个 → 裁剪至最近 {len(state['formatted_data'])} 个")
                    else:
                        logger.info(f"   - formatted_data: {len(state['formatted_data'])} 个")

                # 恢复中间总结（用于 query rewrite）
                if "intermediate_summary" in self.agent.persistent_state:
                    state["intermediate_summary"] = self.agent.persistent_state["intermediate_summary"]
                    logger.info(f"   - intermediate_summary: {len(state.get('intermediate_summary', ''))} 字符")

            # 初始化state字段（如果没有持久化状态）
            for field in ['retrieved_content', 'formatted_data', 'thoughts', 'actions', 'observations']:
                if field not in state:
                    state[field] = []
            if 'current_iteration' not in state:
                state['current_iteration'] = 0

            logger.info(f"✅ [Initialize|{self._doc_tag()}] 初始化完成")
            return state

        except Exception as e:
            logger.error(f"❌ [Initialize|{self._doc_tag()}] 初始化失败: {e}", exc_info=True)
            raise

    async def rewrite(self, state: RetrievalState) -> Dict:
        """查询重写节点"""

        conversation_turn = state.get("conversation_turn", 0)
        current_iteration = state.get("current_iteration", 0)
        intermediate_summary = state.get("intermediate_summary", "")
        original_query = state["query"]

        logger.info(f"🔄 [Rewrite|{self._doc_tag()}] ========== 步骤0: 查询重写 ==========")
        logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 对话轮次: {conversation_turn}")
        logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 内部迭代: {current_iteration}")
        logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 原始查询: {original_query}")

        # 发送进度更新
        await self._send_progress(
            stage="rewrite",
            stage_name="查询重写",
            state=state,
            status="processing",
            message=f"正在优化查询: {original_query[:30]}..."
        )

        try:
            # 只有外部对话轮次和内部迭代次数都为0时，才跳过重写
            # 其他情况（外部非首轮 或 内部非首次）都需要重写
            if conversation_turn == 0 and current_iteration == 0:
                logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 判断: 外部首轮对话且内部首次迭代，跳过查询重写")
                state["rewritten_query"] = original_query
                logger.info(f"✅ [Rewrite|{self._doc_tag()}] 输出查询: {original_query}")

                await self._send_progress(
                    stage="rewrite",
                    stage_name="查询重写",
                    state=state,
                    status="completed",
                    message="首次查询，无需重写"
                )
                return state

            logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 判断: 外部非首轮({conversation_turn}) 或 内部非首次({current_iteration})，进行查询优化")

            # 获取上一轮 evaluate 节点的评估（包含建议）
            last_reason = state.get("reason", "")
            
            # 构建prompt
            if last_reason and current_iteration > 0:
                # 如果有上一轮的评估，基于评估重写查询
                logger.info(f"🔄 [Rewrite|{self._doc_tag()}] 使用上一轮评估: {last_reason[:100]}...")
                input_prompt = f"""原始查询: {original_query}

上一轮检索评估: {last_reason}

任务: 基于评估中的建议，优化查询以便进行下一轮检索。
- 如果评估建议检索特定章节，保持原查询不变（工具选择会处理）
- 如果评估建议更换关键词，提取建议的关键词
- 如果评估建议切换策略，调整查询以适应新策略

只返回优化后的查询字符串，不要解释。"""
            else:
                # 没有评估或首次检索，使用通用优化
                input_prompt = f"原始查询: {original_query}\n优化该查询"
            
            #session_id = f"rewrite_{state.get('doc_name', 'default')}"
            rewritten = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.QUERY_REWRITE,
                input_prompt=input_prompt,
                session_id="rewrite_query"
            )

            rewritten_clean = rewritten.strip().strip('"').strip("'").strip()
            state["rewritten_query"] = rewritten_clean
            logger.info(f"✅ [Rewrite|{self._doc_tag()}] 重写后查询: {rewritten_clean}")

            await self._send_progress(
                stage="rewrite",
                stage_name="查询重写",
                state=state,
                status="completed",
                message=f"查询已优化: {rewritten_clean[:30]}..."
            )
            return state

        except Exception as e:
            logger.error(f"❌ [Rewrite|{self._doc_tag()}] 失败: {e}", exc_info=True)
            state["rewritten_query"] = original_query
            logger.info(f"⚠️  [Rewrite|{self._doc_tag()}] 回退到原始查询: {original_query}")

            await self._send_progress(
                stage="rewrite",
                stage_name="查询重写",
                state=state,
                status="error",
                message="查询优化失败，使用原始查询"
            )
            return state

    async def think(self, state: RetrievalState) -> Dict:
        """思考节点：选择工具"""

        current_iteration = state.get("current_iteration", 0)
        logger.info(f"🤔 [Think|{self._doc_tag()}] ========== 步骤1: 思考工具选择 ==========")
        logger.info(f"🤔 [Think|{self._doc_tag()}] 迭代进度: 第 {current_iteration + 1}/{state['max_iterations']} 轮")

        await self._send_progress(
            stage="think",
            stage_name="思考工具选择",
            state=state,
            status="processing",
            message="正在分析查询并选择合适的检索工具..."
        )

        try:
            tools_description = format_all_tools_for_llm()
            current_query = state.get("rewritten_query", state["query"])
            original_query = state["query"]
            last_reason = state.get("reason", "")

            logger.info(f"🤔 [Think|{self._doc_tag()}] 输入:")
            logger.info(f"🤔 [Think|{self._doc_tag()}]   - 原始查询: {original_query}")
            logger.info(f"🤔 [Think|{self._doc_tag()}]   - 当前查询: {current_query}")

            # 构建历史执行信息（不针对任何特定工具做解析）
            actions_history = state.get("actions", [])
            observations = state.get("observations", [])
            retrieved_content = state.get("retrieved_content", [])

            executed_tools = [action.get("tool", "") for action in actions_history]

            logger.info(f"🤔 [Think|{self._doc_tag()}] 上下文:")
            logger.info(f"🤔 [Think|{self._doc_tag()}]   - 已执行工具数: {len(actions_history)}")
            logger.info(f"🤔 [Think|{self._doc_tag()}]   - 已检索内容数: {len(retrieved_content)}")

            # 统一的历史 JSON（基于 tool_response_format 中的字段）
            history_data = []
            for idx, (action, observation) in enumerate(zip(actions_history, observations), 1):
                history_data.append({
                    "round": idx,
                    "tool": action.get("tool", "unknown"),
                    "params": action.get("params", {}),
                    "observation": observation
                })

            history_json = json.dumps(history_data, ensure_ascii=False, indent=2)

            # 统一统计 retrieved_content 中各类型的数量（符合 ToolResponse.type）
            content_count = sum(1 for item in retrieved_content if isinstance(item, dict) and item.get("type") == "content")
            metadata_count = sum(1 for item in retrieved_content if isinstance(item, dict) and item.get("type") == "metadata")
            structure_count = sum(1 for item in retrieved_content if isinstance(item, dict) and item.get("type") == "structure")
            unknown_count = len(retrieved_content) - (content_count + metadata_count + structure_count)

            if actions_history:
                history_info = f"""## 检索历史（JSON 格式）

```json
{history_json}
```

## 当前累积内容统计
- 内容(content): {content_count} 条
- 元数据(metadata): {metadata_count} 条
- 结构(structure): {structure_count} 条
- 未知类型: {unknown_count} 条
- 总计: {len(retrieved_content)} 条
"""
            else:
                history_info = "## 首次检索\n暂无历史执行记录。"

            reason_info = f"\n## 上一轮评估理由\n{last_reason}\n" if last_reason else ""

            # 构建简洁的 prompt（完全依赖工具描述和统一格式，不做工具特定处理）
            prompt = f"""# 当前任务信息

**用户原始查询**: {original_query}
**当前优化查询**: {current_query}
**迭代进度**: 第 {current_iteration + 1}/{state['max_iterations']} 轮

{history_info}
{reason_info}

# 请选择下一步工具

请基于检索历史和当前统计，选择最合适的工具继续检索。严格遵循工具描述中的参数格式。
**重要提示**:
- 避免重复完全相同的工具+参数组合
- 如果 observation 显示未找到或重复，考虑更换策略或参数
- action_input 必须符合工具的参数规范（例如需要数组的工具传数组）

返回严格的 JSON 格式：
{{
  "thought": "你的思考过程",
  "action": "工具名称",
  "action_input": "工具参数"
}}
"""

            logger.info(f"🤔 [Think|{self._doc_tag()}] 调用 LLM 进行工具选择...")
            session_id = f"think_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL,
                input_prompt=prompt,
                session_id=session_id,
                system_format_dict={"tool_info_dict": tools_description}
            )

            # 解析JSON
            logger.info(f"🤔 [Think|{self._doc_tag()}] LLM 响应: {response[:200]}...")
            decision = json.loads(response.strip()) if response.strip().startswith('{') else None
            if decision:
                thought = decision.get("thought", "")
                action = decision.get("action", "search_by_context")
                action_input = decision.get("action_input", current_query)

                logger.info(f"🤔 [Think|{self._doc_tag()}] 决策结果:")
                logger.info(f"🤔 [Think|{self._doc_tag()}]   - 思考: {thought}")
                logger.info(f"🤔 [Think|{self._doc_tag()}]   - 选择工具: {action}")
                logger.info(f"🤔 [Think|{self._doc_tag()}]   - 工具参数: {action_input}")
            else:
                logger.warning(f"⚠️  [Think|{self._doc_tag()}] JSON 解析失败，使用默认工具")
                action = "search_by_context"
                action_input = current_query
                logger.info(f"🤔 [Think|{self._doc_tag()}]   - 默认工具: {action}")
                logger.info(f"🤔 [Think|{self._doc_tag()}]   - 默认参数: {action_input}")

            state["current_tool"] = action
            state["action_input"] = action_input

            # 记录参数（统一从工具配置中推断首个参数名，避免针对具体工具的硬编码）
            tool_config = get_tool_by_name(action)
            if tool_config:
                params_spec = tool_config.get("parameters", {})
                if params_spec:
                    param_name = list(params_spec.keys())[0]
                    current_params = {param_name: action_input}
                else:
                    current_params = {}
            else:
                current_params = {"query": action_input}

            state["current_params"] = current_params
            logger.info(f"🤔 [Think|{self._doc_tag()}]   - 记录参数: {current_params}")

            state["current_iteration"] = current_iteration + 1

            # 安全地显示参数（可能是字符串或列表）
            if isinstance(action_input, str):
                param_preview = action_input[:50] + "..." if len(action_input) > 50 else action_input
            elif isinstance(action_input, list):
                param_preview = str(action_input)[:100] + "..." if len(str(action_input)) > 100 else str(action_input)
            else:
                param_preview = str(action_input)

            logger.info(f"✅ [Think|{self._doc_tag()}] 输出: 工具={action}, 参数类型={type(action_input).__name__}, 参数={param_preview}")
            return state

        except Exception as e:
            logger.error(f"❌ [Think|{self._doc_tag()}] 失败: {e}", exc_info=True)
            state["current_tool"] = "search_by_context"
            state["action_input"] = state.get("rewritten_query", state["query"])
            state["current_iteration"] = current_iteration + 1
            logger.info(f"⚠️  [Think|{self._doc_tag()}] 错误回退: 使用 search_by_context")
            return state

    async def act(self, state: RetrievalState) -> Dict:
        """执行工具调用"""

        tool_name = state["current_tool"]
        action_input = state.get("action_input", state.get("rewritten_query", state["query"]))

        logger.info(f"🔧 [Act|{self._doc_tag()}] ========== 步骤2: 执行工具 ==========")
        logger.info(f"🔧 [Act|{self._doc_tag()}] 工具名称: {tool_name}")
        logger.info(f"🔧 [Act|{self._doc_tag()}] 工具参数: {action_input}")

        await self._send_progress(
            stage="act",
            stage_name="执行检索",
            state=state,
            status="processing",
            message=f"正在使用 {tool_name} 检索...",
            tool=tool_name
        )

        try:
            # 构建可用工具
            available_tools = self.agent.utils.build_retrieval_tools()
            logger.info(f"🔧 [Act|{self._doc_tag()}] 可用工具列表: {list(available_tools.keys())}")

            if tool_name in available_tools:
                logger.info(f"🔧 [Act|{self._doc_tag()}] 调用工具: {tool_name}")
                tool_func = available_tools[tool_name]["function"]

                # 调用工具（传入action_input）
                result = await tool_func(action_input)
            else:
                logger.warning(f"⚠️  [Act|{self._doc_tag()}] 工具 '{tool_name}' 不在可用列表中，使用默认工具")
                result = await self.agent.tools.search_by_context(action_input)

            # 统计结果（基于标准格式）
            if isinstance(result, dict) and "type" in result and "items" in result:
                # 标准格式响应
                tool_type = result["type"]
                items = result["items"]
                metadata = result.get("metadata", {})
                result_count = len(items)

                logger.info(f"🔧 [Act|{self._doc_tag()}] 工具执行完成，返回 {result_count} 项 (type={tool_type})")

                if tool_type == "content" and result_count > 0:
                    # 内容检索工具：显示章节信息
                    logger.info(f"🔧 [Act|{self._doc_tag()}]   检索到的内容:")
                    for idx, item in enumerate(items[:3], 1):
                        if isinstance(item, dict):
                            title = item.get("title", "无标题")
                            pages = item.get("pages", [])
                            content_preview = item.get("content", "")[:50] + "..." if item.get("content", "") else ""
                            logger.info(f"🔧 [Act|{self._doc_tag()}]     {idx}. 章节: {title} (页码: {pages})")
                            logger.info(f"🔧 [Act|{self._doc_tag()}]        内容预览: {content_preview}")
                    if len(items) > 3:
                        logger.info(f"🔧 [Act|{self._doc_tag()}]     ... (还有 {len(items) - 3} 条)")

                elif tool_type in ["metadata", "structure"] and result_count > 0:
                    # 结构化工具：显示数据预览
                    preview_items = items[:5] if len(items) > 5 else items
                    logger.info(f"🔧 [Act|{self._doc_tag()}]   数据预览（前{len(preview_items)}项）:")
                    for idx, item in enumerate(preview_items, 1):
                        logger.info(f"🔧 [Act|{self._doc_tag()}]     {idx}. {item}")
                    if len(items) > 5:
                        logger.info(f"🔧 [Act|{self._doc_tag()}]     ... (还有 {len(items) - 5} 项)")

                    # 如果有metadata（如reason），也打印
                    if metadata:
                        logger.info(f"🔧 [Act|{self._doc_tag()}]   元数据: {metadata}")
            else:
                # 非标准格式（向后兼容）
                result_count = 0
                logger.warning(f"⚠️  [Act|{self._doc_tag()}] 工具返回非标准格式，类型: {type(result)}")

            state["last_result"] = result

            # 记录action（包含tool和params）
            current_params = state.get("current_params", {})
            state["actions"] = state.get("actions", []) + [{"tool": tool_name, "params": current_params}]

            logger.info(f"✅ [Act|{self._doc_tag()}] 输出: {result_count} 条结果")
            return state

        except Exception as e:
            logger.error(f"❌ [Act|{self._doc_tag()}] 失败: {e}", exc_info=True)
            state["last_result"] = []
            logger.info(f"⚠️  [Act|{self._doc_tag()}] 错误回退: 返回空结果")
            return state

    async def summary(self, state: RetrievalState) -> Dict:
        """累积并总结数据（始终累积，按需总结）"""

        logger.info(f"📝 [Summary|{self._doc_tag()}] ========== 步骤3: 累积并总结数据 ==========")

        try:
            last_result = state.get("last_result", [])
            retrieved_content = state.get("retrieved_content", [])

            logger.info(f"📝 [Summary|{self._doc_tag()}] 输入:")
            logger.info(f"📝 [Summary|{self._doc_tag()}]   - 本轮结果数: {len(last_result) if isinstance(last_result, list) else 0}")
            logger.info(f"📝 [Summary|{self._doc_tag()}]   - 累积结果数: {len(retrieved_content)}")

            # ========== 第一步：始终累积数据（统一的标准格式处理）==========
            new_items = 0
            current_tool = state.get("current_tool", "unknown")

            # 检查是否是标准格式（所有工具现在都返回这个格式）
            if isinstance(last_result, dict) and "type" in last_result and "tool" in last_result and "items" in last_result:
                # 标准格式：{"type": "...", "tool": "...", "items": [...], "metadata": {...}}
                tool_type = last_result["type"]
                tool_name = last_result["tool"]
                items = last_result["items"]
                metadata = last_result.get("metadata", {})

                logger.info(f"📝 [Summary|{self._doc_tag()}] 处理标准格式响应: type={tool_type}, tool={tool_name}")

                if tool_type == "content":
                    # 内容类型：items 是 List[Dict]，每个Dict包含 content, title, pages, raw_data
                    # 提取已有的内容（用于跨迭代去重）
                    existing_contents = [
                        item.get("content", "")
                        for item in retrieved_content
                        if isinstance(item, dict) and item.get("type") != "structured_info"
                    ]

                    for item in items:
                        if isinstance(item, dict):
                            item_content = item.get("content", "")
                            # 检查是否重复（跨迭代去重）
                            if item_content and item_content not in existing_contents:
                                retrieved_content.append(item)
                                new_items += 1
                                existing_contents.append(item_content)  # 更新已有内容列表
                            # else: 重复内容，不添加，new_items 不增加

                    logger.info(f"📝 [Summary|{self._doc_tag()}] 工具返回 {len(items)} 条，去重后新增 {new_items} 条")

                elif tool_type in ["metadata", "structure"]:
                    # 元数据/结构类型：items 是 List[str]，需要包装成 structured_info
                    structured_info = {
                        "type": "structured_info",
                        "tool": tool_name,
                        "data": items
                    }
                    # 如果有metadata，添加到structured_info中
                    if metadata:
                        structured_info["metadata"] = metadata

                    retrieved_content.append(structured_info)
                    new_items = 1
                    logger.info(f"📝 [Summary|{self._doc_tag()}] 累积结构化信息: {tool_name}, {len(items)} 项")
                    if metadata:
                        logger.info(f"📝 [Summary|{self._doc_tag()}]   - 元数据: {metadata}")

                else:
                    logger.warning(f"⚠️  [Summary|{self._doc_tag()}] 未知的type类型: {tool_type}")

            else:
                # 非标准格式（向后兼容，理论上不应该出现）
                logger.warning(f"⚠️  [Summary|{self._doc_tag()}] 工具返回非标准格式，尝试兼容处理")
                logger.warning(f"⚠️  [Summary|{self._doc_tag()}] last_result类型: {type(last_result)}")

                # 简单处理：如果是dict就添加，如果是list就逐个添加
                if isinstance(last_result, dict):
                    retrieved_content.append(last_result)
                    new_items = 1
                elif isinstance(last_result, list):
                    for item in last_result:
                        if isinstance(item, dict):
                            retrieved_content.append(item)
                            new_items += 1

            state["retrieved_content"] = retrieved_content
            logger.info(f"📝 [Summary|{self._doc_tag()}] 新增 {new_items} 条内容，总计 {len(retrieved_content)} 条")

            if not retrieved_content:
                logger.warning(f"⚠️  [Summary|{self._doc_tag()}] 无检索内容，跳过总结")
                state["intermediate_summary"] = "未检索到相关内容"
                return state

            # 构建格式化数据
            formatted_data = []
            for idx, item in enumerate(retrieved_content, 1):
                # 检查是否是结构化信息
                if isinstance(item, dict) and item.get("type") == "structured_info":
                    # 结构化信息（文档结构或标题列表）
                    tool_name = item.get("tool", "unknown")
                    data = item.get("data", [])
                    metadata = item.get("metadata", {})

                    formatted_item = {
                        "index": idx,
                        "type": "structured_info",
                        "tool": tool_name,
                        "data": data,
                        "title": f"[{tool_name}]",
                        "pages": [],
                        "content": "\n".join(data) if isinstance(data, list) else str(data)
                    }

                    # 如果有元数据（如reason等），也加入
                    if metadata:
                        formatted_item["metadata"] = metadata
                        # 向后兼容：如果metadata中有reason，也提取到顶层
                        if "reason" in metadata:
                            formatted_item["reason"] = metadata["reason"]

                    formatted_data.append(formatted_item)
                else:
                    # 常规内容
                    formatted_data.append({
                        "index": idx,
                        "type": "content",
                        "title": item.get("title", ""),
                        "pages": item.get("pages", []),
                        "content": item.get("content", ""),
                        "raw_data": item.get("raw_data", {})  # 传递原始数据
                    })

            state["formatted_data"] = formatted_data
            logger.info(f"📝 [Summary|{self._doc_tag()}] 格式化 {len(formatted_data)} 条数据")

            # 记录observation（统一基于标准格式，无需hardcode工具名）
            if isinstance(last_result, dict) and "type" in last_result:
                # 标准格式
                tool_type = last_result["type"]
                items = last_result.get("items", [])
                tool_name = last_result.get("tool", current_tool)

                if new_items > 0:
                    # 有新内容被添加
                    if tool_type == "content":
                        # 内容类型：显示新增数量
                        observation = f"新增 {new_items} 个结果"
                    elif tool_type in ["metadata", "structure"]:
                        # 元数据/结构类型：显示获取的项数
                        observation = f"获取 {len(items)} 项数据"
                    else:
                        observation = f"完成（type={tool_type}）"
                else:
                    # 没有新内容（可能是重复或未找到）
                    if tool_type == "content" and len(items) > 0:
                        # 工具返回了结果，但都是重复的
                        observation = f"返回 {len(items)} 个结果，但均为重复内容"
                    else:
                        # 完全未找到
                        observation = "未找到新内容"
            else:
                # 非标准格式（向后兼容）
                if new_items > 0:
                    observation = f"新增 {new_items} 个结果"
                else:
                    observation = "未找到新内容"

            state["observations"] = state.get("observations", []) + [observation]
            logger.info(f"📝 [Summary|{self._doc_tag()}] 记录observation: {observation}")

            return state

        except Exception as e:
            logger.error(f"❌ [Summary|{self._doc_tag()}] 失败: {e}", exc_info=True)
            state["intermediate_summary"] = "总结失败"
            return state

    async def evaluate(self, state: RetrievalState) -> Dict:
        """评估检索结果"""

        logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] ========== 步骤4: 评估检索结果 ==========")

        await self._send_progress(
            stage="evaluate",
            stage_name="评估结果",
            state=state,
            status="processing",
            message="正在评估检索结果的完整性..."
        )

        try:
            formatted_data = state.get("formatted_data", [])
            current_iteration = state.get("current_iteration", 0)
            max_iterations = state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS)
            original_query = state["query"]
            actions = state.get("actions", [])
            observations = state.get("observations", [])

            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 输入:")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 用户查询: {original_query}")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 格式化数据数: {len(formatted_data)}")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 当前迭代: {current_iteration}/{max_iterations}")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 历史动作数: {len(actions)}")

            if not formatted_data:
                logger.warning(f"⚠️  [Evaluate|{self._doc_tag()}] 无检索内容，判断为不完整")
                state["is_complete"] = False
                state["reason"] = "无检索内容，继续检索"
                logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 输出: is_complete=False, reason='{state['reason']}'")
                return state

            # 构建检索内容摘要（章节标题 + 页码，不包含完整内容）
            content_summary_parts = []
            for idx, item in enumerate(formatted_data, 1):
                if item.get("type") == "structured_info":
                    # 结构化信息（通用处理）
                    tool_name = item.get("tool", "unknown")
                    data = item.get("data", [])
                    metadata = item.get("metadata", {})

                    # 如果有reason，显示详细信息
                    reason = metadata.get("reason", "") or item.get("reason", "")
                    if reason:
                        content_summary_parts.append(f"{idx}. {tool_name}: {data} ({reason})")
                    else:
                        content_summary_parts.append(f"{idx}. {tool_name}: {len(data)} 项")
                else:
                    # 实际内容
                    title = item.get("title", "未知章节")
                    pages = item.get("pages", [])
                    content_length = len(item.get("content", ""))
                    page_info = f"页码: {pages}" if pages else "无页码"
                    content_summary_parts.append(f"{idx}. {title} ({page_info}, {content_length} 字符)")

            content_summary = "\n".join(content_summary_parts)

            # 构建检索轨迹（包含observation的关键信息：检索数量、重复情况等）
            def format_param_value(value, max_len=60):
                """通用参数格式化函数"""
                if isinstance(value, str):
                    # 字符串：适当截断
                    return f"'{value[:max_len]}...'" if len(value) > max_len else f"'{value}'"
                elif isinstance(value, list):
                    # 列表：对于标题列表等关键参数，显示更多信息
                    if not value:
                        return "[]"

                    # 检查列表项的长度，如果都是较短的字符串（如章节标题），尝试显示所有项
                    if len(value) <= 5:
                        # 少于5项，显示所有项，但每项限制长度
                        items_preview = ", ".join([f"'{str(v)[:50]}'" if len(str(v)) > 50 else f"'{str(v)}'" for v in value])
                        return f"[{items_preview}]"
                    else:
                        # 多于5项，显示前3项
                        items_preview = ", ".join([f"'{str(v)[:50]}'" if len(str(v)) > 50 else f"'{str(v)}'" for v in value[:3]])
                        suffix = f", ...共{len(value)}项"
                        return f"[{items_preview}{suffix}]"
                elif isinstance(value, dict):
                    # 字典：显示键值对数量
                    return f"{{{len(value)}个参数}}"
                elif value is None:
                    return "None"
                else:
                    # 其他类型：转字符串并截断
                    value_str = str(value)
                    return value_str[:max_len] if len(value_str) > max_len else value_str

            def extract_observation_summary(observation: str) -> str:
                """从observation中提取关键信息摘要（通用方式）"""
                if not observation:
                    return ""

                obs_str = str(observation)

                # 提取关键数字（章节数、结果数等）
                import re

                # 检查是否未找到内容
                if "未找到" in obs_str or "无相关" in obs_str or "没有" in obs_str or "0个" in obs_str:
                    return " → 未找到内容"

                # 检查是否重复检索（这个信息可能在observation中）
                if "已存在" in obs_str or "重复" in obs_str:
                    return " → 重复检索"

                # 提取关键信息（通用方式，无需hardcode工具名）
                # 观察字符串现在是标准化的，如："新增 3 个结果"、"获取 5 项数据"、"返回 2 个结果，但均为重复内容"

                # 提取数字信息
                numbers = re.findall(r'(\d+)\s*(?:个|条|项)', obs_str)
                if numbers:
                    count = numbers[0]
                    # 根据观察字符串的内容判断类型
                    if "新增" in obs_str:
                        return f" → 新增{count}项"
                    elif "获取" in obs_str:
                        return f" → 获取{count}项"
                    elif "重复" in obs_str:
                        return f" → {count}项重复"
                    else:
                        return f" → {count}项"

                # 默认：直接使用observation的简化版本
                if len(obs_str) <= 20:
                    return f" → {obs_str}"
                else:
                    return f" → {obs_str[:17]}..."

            retrieval_trace = []
            for i, (action, observation) in enumerate(zip(actions, observations), 1):
                tool = action.get("tool", "unknown")
                params = action.get("params", {})

                # 通用参数格式化
                if params:
                    params_str = ", ".join([
                        f"{key}={format_param_value(value)}"
                        for key, value in params.items()
                    ])
                    action_str = f"{tool}({params_str})"
                else:
                    action_str = f"{tool}()"

                # 添加observation摘要
                obs_summary = extract_observation_summary(observation)
                trace_item = f"{i}. {action_str}{obs_summary}"

                retrieval_trace.append(trace_item)

            history_summary = "\n".join(retrieval_trace) if retrieval_trace else "无检索历史"

            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 构建检索内容摘要:")
            logger.info(f"{content_summary}")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 构建检索历史摘要:")
            logger.info(f"{history_summary}")

            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 调用 LLM 评估检索完整性...")

            # 计算当前迭代信息
            current_iter = len(actions)
            is_last_iteration = current_iteration >= max_iterations - 1

            # ========== 分析检索策略效果 ==========
            attempted_strategies = []
            # ========== 简化：直接构建检索历史 JSON ==========
            observations = state.get("observations", [])
            
            history_data = []
            for idx, (action, observation) in enumerate(zip(actions, observations), 1):
                history_data.append({
                    "round": idx,
                    "tool": action.get("tool", "unknown"),
                    "params": action.get("params", {}),
                    "observation": observation
                })
            
            import json
            history_json = json.dumps(history_data, ensure_ascii=False, indent=2)
            
            prompt = f"""# 用户查询
{original_query}

# 检索历史（JSON 格式）
```json
{history_json}
```

# 检索到的内容摘要
{content_summary}

# 当前状态
- 已执行检索次数: {current_iter}
- 最大允许次数: {max_iterations}
- 是否最后一次机会: {"是" if is_last_iteration else "否"}

# 任务
根据系统提示中的评估标准，判断当前检索内容是否足以回答用户问题。
**重要**：
1. 仔细分析检索历史 JSON，识别是否有重复的检索（相同工具+相同参数）
2. 观察每次检索的 observation，判断检索效果
3. 如果单次检索失败，reason 中必须给出具体的替代方案建议


返回严格的 JSON 格式：
{{"is_complete": true/false, "reason": "..."}}

**reason 字段要求**：
- 如果 is_complete=true：说明为什么停止
- 如果 is_complete=false：必须包含具体的下一步建议
"""

            session_id = f"evaluate_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL_EVALUATOR,
                input_prompt=prompt,
                session_id=session_id
            )

            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] LLM 响应: {response[:200]}...")

            evaluation = json.loads(response.strip()) if response.strip().startswith('{') else {}
            is_complete = evaluation.get("is_complete", False)
            reason = evaluation.get("reason", "")

            state["is_complete"] = is_complete
            state["reason"] = reason

            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}] 评估结果:")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 是否完整: {is_complete}")
            logger.info(f"⚖️ [Evaluate|{self._doc_tag()}]   - 判断理由: {reason}")

            if is_complete:
                logger.info(f"✅ [Evaluate|{self._doc_tag()}] 检索完成，准备生成最终答案")
            else:
                logger.info(f"🔄 [Evaluate|{self._doc_tag()}] 检索未完成，将继续下一轮")

            return state

        except Exception as e:
            logger.error(f"❌ [Evaluate|{self._doc_tag()}] 失败: {e}", exc_info=True)
            is_complete_fallback = current_iteration >= state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS)
            state["is_complete"] = is_complete_fallback
            state["reason"] = f"评估失败，基于迭代次数判断: {is_complete_fallback}"
            logger.info(f"⚠️  [Evaluate|{self._doc_tag()}] 错误回退: is_complete={is_complete_fallback}")
            return state

    async def format(self, state: RetrievalState) -> Dict:
        """生成最终精准总结"""

        logger.info(f"🎯 [Format|{self._doc_tag()}] ========== 步骤5: 生成最终总结 ==========")

        await self._send_progress(
            stage="format",
            stage_name="生成答案",
            state=state,
            status="processing",
            message="正在生成最终答案..."
        )

        try:
            formatted_data = state.get("formatted_data", [])
            intermediate_summary = state.get("intermediate_summary", "")
            original_query = state["query"]

            logger.info(f"🎯 [Format|{self._doc_tag()}] 输入:")
            logger.info(f"🎯 [Format|{self._doc_tag()}]   - 用户查询: {original_query}")
            logger.info(f"🎯 [Format|{self._doc_tag()}]   - 格式化数据数: {len(formatted_data)}")
            #logger.info(f"🎯 [Format|{self._doc_tag()}]   - 中间总结长度: {len(intermediate_summary)} 字符")

            if not formatted_data:
                logger.warning(f"⚠️  [Format|{self._doc_tag()}] 无格式化数据，使用中间总结作为最终答案")
                #state["final_summary"] = intermediate_summary
                #logger.info(f"🎯 [Format|{self._doc_tag()}] 输出: 使用中间总结 (长度: {len(intermediate_summary)})")

                # ============ 状态持久化：保存当前状态供下一轮使用 ============
                self._save_persistent_state(state)

                return state

            # 构建最终总结
            logger.info(f"🎯 [Format|{self._doc_tag()}] 调用 LLM 生成最终精准答案...")

            # ========== 步骤1: 分类收集数据 ==========
            # 分别收集结构化信息和常规内容
            all_raw_pages = {}  # {page_num: {"title": str, "content": str}}
            structured_info_items = []  # 结构化信息列表

            for item in formatted_data:
                # 检查是否是结构化信息
                if item.get("type") == "structured_info":
                    # 收集结构化信息（文档结构、标题列表等）
                    structured_info_items.append(item)
                    continue

                title = item.get("title", "未知章节")
                raw_data = item.get("raw_data", {})
                pages = item.get("pages", [])
                content = item.get("content", "")

                # 优先使用 raw_data，如果没有则 fallback 到 content
                if isinstance(raw_data, dict) and raw_data:
                    # 遍历每一页的原始数据
                    for page_num, page_content in raw_data.items():
                        # 去重：同一页只保留第一次出现的内容
                        if page_num not in all_raw_pages:
                            all_raw_pages[page_num] = {
                                "title": title,
                                "content": page_content
                            }
                elif content:
                    # Fallback: 如果没有 raw_data，使用 content（refactor_data）
                    # 使用第一个页码作为 key（或使用 "unknown" 如果没有页码）
                    page_key = pages[0] if pages else f"unknown_{title}"
                    if page_key not in all_raw_pages:
                        all_raw_pages[page_key] = {
                            "title": title,
                            "content": content
                        }

            logger.info(f"🎯 [Format|{self._doc_tag()}] 去重后共 {len(all_raw_pages)} 页原始内容")
            logger.info(f"🎯 [Format|{self._doc_tag()}] 收集到 {len(structured_info_items)} 条结构化信息")

            # ========== 步骤2: 构建检索内容详情 ==========
            content_parts = []

            # 2.1 先添加结构化信息（如果有）
            if structured_info_items:
                for idx, struct_item in enumerate(structured_info_items, 1):
                    tool_name = struct_item.get("tool", "unknown")
                    data = struct_item.get("data", [])
                    content = struct_item.get("content", "")

                    # 构建结构化信息展示
                    if isinstance(data, list) and data:
                        struct_content = "\n".join([f"- {item}" for item in data])
                    else:
                        struct_content = content or str(data)

                    content_block = f"""
## 结构化信息 {idx}: {tool_name}

{struct_content}
"""
                    content_parts.append(content_block.strip())

            # 2.2 再添加常规内容（按页码排序）
            if all_raw_pages:
                sorted_pages = sorted(all_raw_pages.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)

                for idx, page_num in enumerate(sorted_pages, 1):
                    page_data = all_raw_pages[page_num]
                    title = page_data["title"]
                    content = page_data["content"]

                    content_block = f"""
## 内容 {idx}: {title} (页码: {page_num})

{content}
"""
                    content_parts.append(content_block.strip())

            # 构建完整的 prompt
            if not content_parts:
                # 没有任何可用内容（既没有结构化信息也没有常规内容）
                logger.warning(f"⚠️  [Format|{self._doc_tag()}] 没有可用内容生成答案，返回提示信息")
                state["final_summary"] = "未能检索到相关内容。请尝试调整查询或检查文档是否已正确索引。"
                self._save_persistent_state(state)
                return state

            all_content = "\n\n".join(content_parts)

            prompt = f"""# 用户查询

{original_query}

# 检索到的内容

{all_content}

---

# 任务

基于以上检索内容，生成精准、完整的答案来回答用户查询。

要求：
1. 直接回答用户的问题，聚焦于查询的核心
2. 基于检索内容的事实和数据，不要编造信息
3. 保留重要的细节、数据、公式等关键信息
4. 使用清晰的 Markdown 格式组织答案
5. **页码标注**: 在答案正文中不要频繁标注页码，只在答案末尾简要提及主要来源页码即可
6. 如果检索内容不足以完全回答问题，明确说明
7. **结构化信息**: 如果检索到文档结构、标题列表等结构化信息，请清晰地展示出来
"""

            total_items = len(structured_info_items) + len(all_raw_pages)
            logger.info(f"🎯 [Format|{self._doc_tag()}] 准备生成最终答案，总数据项: {total_items}（结构化: {len(structured_info_items)}, 内容: {len(all_raw_pages)}），总长度: {len(all_content)} 字符")

            session_id = f"format_{state.get('doc_name', 'default')}"
            final_summary = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.CONTEXT_SUMMARIZER,
                input_prompt=prompt,
                session_id=session_id
            )

            state["final_summary"] = final_summary
            logger.info(f"✅ [Format|{self._doc_tag()}] 最终答案生成完成")
            logger.info(f"🎯 [Format|{self._doc_tag()}]   - 答案长度: {len(final_summary)} 字符")
            logger.info(f"🎯 [Format|{self._doc_tag()}]   - 答案预览: {final_summary[:200]}...")

            # ============ 状态持久化：保存当前状态供下一轮使用 ============
            self._save_persistent_state(state)

            return state

        except Exception as e:
            logger.error(f"❌ [Format|{self._doc_tag()}] 失败: {e}", exc_info=True)
            #intermediate_summary = state.get("intermediate_summary", "")
            #state["final_summary"] = intermediate_summary
            #logger.info(f"⚠️  [Format|{self._doc_tag()}] 错误回退: 使用中间总结 (长度: {len(intermediate_summary)})")

            # ============ 状态持久化：即使失败也保存状态 ============
            self._save_persistent_state(state)

            return state

    def should_continue(self, state: RetrievalState) -> str:
        """判断是否继续检索"""
        current_iter = state.get("current_iteration", 0)
        max_iter = state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS)

        # 添加详细日志以便调试
        logger.info(f"🔍 [ShouldContinue] 检查迭代状态: current={current_iter}, max={max_iter}, is_complete={state.get('is_complete', False)}")

        if state.get("is_complete", False):
            logger.info(f"✅ [ShouldContinue] 检索完成，结束循环")
            return "finish"

        if current_iter >= max_iter:
            logger.warning(f"⚠️  [ShouldContinue] 达到最大迭代次数 ({max_iter})，结束循环")
            return "finish"

        logger.info(f"🔄 [ShouldContinue] 继续下一轮检索 (第 {current_iter + 1}/{max_iter} 轮)")
        return "continue"
