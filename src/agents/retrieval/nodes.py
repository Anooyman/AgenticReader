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

    async def initialize(self, state: RetrievalState) -> Dict:
        """初始化节点：设置Agent的上下文环境"""
        logger.info(f"🔧 [Initialize] ========== RetrievalAgent 初始化 ==========")

        try:
            # 验证state
            self.agent.utils.validate_state(state)

            # 从state中读取并设置文档上下文
            doc_name_from_state = state.get('doc_name')
            self.agent.current_doc = doc_name_from_state or self.agent.current_doc

            logger.info(f"🔧 [Initialize] 配置信息:")
            logger.info(f"🔧 [Initialize]   - 文档名称: {self.agent.current_doc or '多文档模式'}")
            logger.info(f"🔧 [Initialize]   - 查询内容: {state['query']}")
            logger.info(f"🔧 [Initialize]   - 最大迭代: {state['max_iterations']}")

            # 创建或更新 VectorDBClient
            if self.agent.current_doc:
                if self.agent.vector_db_client is None:
                    self.agent.vector_db_client = self.agent.utils.create_vector_db_client(self.agent.current_doc)
                    logger.info(f"✅ [Initialize] VectorDBClient 已创建并加载")
                elif doc_name_from_state and doc_name_from_state != self.agent.current_doc:
                    logger.info(f"🔄 [Initialize] 文档名称变化，重新创建VectorDBClient")
                    self.agent.vector_db_client = self.agent.utils.create_vector_db_client(doc_name_from_state)
                    self.agent.current_doc = doc_name_from_state

            # 初始化state字段
            for field in ['retrieved_content', 'formatted_data', 'thoughts', 'actions', 'observations']:
                if field not in state:
                    state[field] = []
            if 'current_iteration' not in state:
                state['current_iteration'] = 0

            logger.info(f"✅ [Initialize] 初始化完成")
            return state

        except Exception as e:
            logger.error(f"❌ [Initialize] 初始化失败: {e}", exc_info=True)
            raise

    async def rewrite(self, state: RetrievalState) -> Dict:
        """查询重写节点"""

        conversation_turn = state.get("conversation_turn", 0)
        intermediate_summary = state.get("intermediate_summary", "")
        original_query = state["query"]

        logger.info(f"🔄 [Rewrite] ========== 步骤0: 查询重写 ==========")
        logger.info(f"🔄 [Rewrite] 对话轮次: {conversation_turn}")
        logger.info(f"🔄 [Rewrite] 原始查询: {original_query}")

        try:
            # 使用对话轮次判断是否需要重写（而不是检索迭代次数）
            if conversation_turn == 0:
                logger.info(f"🔄 [Rewrite] 判断: 首轮对话或无中间总结，跳过查询重写")
                state["rewritten_query"] = original_query
                logger.info(f"✅ [Rewrite] 输出查询: {original_query}")
                return state

            logger.info(f"🔄 [Rewrite] 判断: 非首轮对话且有中间总结，进行查询优化")
            #logger.info(f"🔄 [Rewrite] 中间总结长度: {len(intermediate_summary)} 字符")

            # 构建prompt（省略具体实现）
            #session_id = f"rewrite_{state.get('doc_name', 'default')}"
            rewritten = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.QUERY_REWRITE,
                input_prompt=f"原始查询: {original_query}\n优化该查询",
                session_id="rewrite_query"
            )

            rewritten_clean = rewritten.strip().strip('"').strip("'").strip()
            state["rewritten_query"] = rewritten_clean
            logger.info(f"✅ [Rewrite] 重写后查询: {rewritten_clean}")
            return state

        except Exception as e:
            logger.error(f"❌ [Rewrite] 失败: {e}", exc_info=True)
            state["rewritten_query"] = original_query
            logger.info(f"⚠️  [Rewrite] 回退到原始查询: {original_query}")
            return state

    async def think(self, state: RetrievalState) -> Dict:
        """思考节点：选择工具"""

        current_iteration = state.get("current_iteration", 0)
        logger.info(f"🤔 [Think] ========== 步骤1: 思考工具选择 ==========")
        logger.info(f"🤔 [Think] 迭代进度: 第 {current_iteration + 1}/{state['max_iterations']} 轮")

        try:
            tools_description = format_all_tools_for_llm()
            current_query = state.get("rewritten_query", state["query"])
            original_query = state["query"]

            logger.info(f"🤔 [Think] 输入:")
            logger.info(f"🤔 [Think]   - 原始查询: {original_query}")
            logger.info(f"🤔 [Think]   - 当前查询: {current_query}")

            # 构建历史执行信息
            actions_history = state.get("actions", [])
            executed_tools = [action.get("tool", "") for action in actions_history]

            # 构建已累积内容信息
            retrieved_content = state.get("retrieved_content", [])
            #intermediate_summary = state.get("intermediate_summary", "")

            logger.info(f"🤔 [Think] 上下文:")
            logger.info(f"🤔 [Think]   - 已执行工具: {executed_tools if executed_tools else '无'}")
            logger.info(f"🤔 [Think]   - 已检索内容数: {len(retrieved_content)}")
            #logger.info(f"🤔 [Think]   - 中间总结长度: {len(intermediate_summary)} 字符")

            # ========== 提取结构化信息（get_document_structure 和 extract_titles_from_structure 的结果） ==========
            document_structure = None
            extracted_titles = None
            extraction_reason = None

            # 遍历 retrieved_content，查找结构化信息（新格式：包装在 dict 中）
            for item in retrieved_content:
                if isinstance(item, dict):
                    # 检查是否是结构化信息
                    if item.get("type") == "structured_info":
                        tool_name = item.get("tool", "")
                        data = item.get("data", [])

                        if tool_name == "get_document_structure":
                            document_structure = data
                        elif tool_name == "extract_titles_from_structure":
                            extracted_titles = data
                            extraction_reason = item.get("reason", "")

            logger.info(f"🤔 [Think]   - 文档结构: {'已获取' if document_structure else '未获取'}")
            logger.info(f"🤔 [Think]   - 提取标题: {extracted_titles if extracted_titles else '未提取'}")
            if extraction_reason:
                logger.info(f"🤔 [Think]   - 提取原因: {extraction_reason}")

            # 构建历史信息摘要
            history_info = ""
            if executed_tools:
                history_parts = [f"## 已执行的工具\n{', '.join(executed_tools)}"]

                # 如果有文档结构，显示它
                if document_structure:
                    structure_preview = "\n".join(document_structure[:10])  # 只显示前10行
                    if len(document_structure) > 10:
                        structure_preview += "\n... (还有更多章节)"
                    history_parts.append(f"""
## 已获取的文档结构
{structure_preview}
""")

                # 如果有提取的标题，显示它
                if extracted_titles:
                    title_info = f"""
## 已提取的标题列表
{extracted_titles}
"""
                    if extraction_reason:
                        title_info += f"""
**提取原因**: {extraction_reason}
"""
                    history_parts.append(title_info)

                # 显示累积内容（章节标题和页码）
                if retrieved_content:
                    content_items = []
                    for idx, item in enumerate(retrieved_content, 1):
                        if isinstance(item, dict):
                            if item.get("type") == "structured_info":
                                # 结构化信息已经在上面显示过了，跳过
                                continue
                            else:
                                # 实际检索内容
                                title = item.get("title", "未知章节")
                                pages = item.get("pages", [])
                                content_len = len(item.get("content", ""))
                                page_info = f"页码: {pages}" if pages else "无页码"
                                content_items.append(f"{idx}. {title} ({page_info}, {content_len} 字符)")

                    if content_items:
                        content_summary = "已检索的章节:\n" + "\n".join(content_items)
                        history_parts.append(f"""
## 当前累积内容
{content_summary}
""")
                    else:
                        history_parts.append(f"""
## 当前累积内容
已累积 {len(retrieved_content)} 条信息（主要为结构化信息）
""")

                history_info = "\n".join(history_parts)
            else:
                history_info = "## 首次检索\n这是第一轮检索，暂无历史执行记录。"

            # 构建简洁的 prompt（工具选择策略和参数格式由系统提示引导）
            prompt = f"""# 当前任务信息

**用户原始查询**: {original_query}
**当前优化查询**: {current_query}
**迭代进度**: 第 {current_iteration + 1}/{state['max_iterations']} 轮

{history_info}

# 请选择下一步工具

请仔细阅读每个工具的描述（特别是"使用场景"、"前置条件"、"后续步骤"、"参数"），基于当前上下文选择最合适的工具。

**重要提示**:
- 严格按照工具描述中的"参数"要求填写 action_input
- 特别注意 search_by_title 工具需要 JSON 数组格式的参数，不是字符串

返回严格的 JSON 格式：
{{
  "thought": "你的思考过程",
  "action": "工具名称",
  "action_input": "工具参数（严格遵循工具的参数格式要求）"
}}
"""

            logger.info(f"🤔 [Think] 调用 LLM 进行工具选择...")
            session_id = f"think_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL,
                input_prompt=prompt,
                session_id=session_id,
                system_format_dict={"tool_info_dict": tools_description}
            )

            # 解析JSON
            logger.info(f"🤔 [Think] LLM 响应: {response[:200]}...")
            decision = json.loads(response.strip()) if response.strip().startswith('{') else None

            if decision:
                thought = decision.get("thought", "")
                action = decision.get("action", "search_by_context")
                action_input = decision.get("action_input", current_query)

                logger.info(f"🤔 [Think] 决策结果:")
                logger.info(f"🤔 [Think]   - 思考: {thought}")
                logger.info(f"🤔 [Think]   - 选择工具: {action}")
                logger.info(f"🤔 [Think]   - 工具参数: {action_input}")
            else:
                logger.warning(f"⚠️  [Think] JSON 解析失败，使用默认工具")
                action = "search_by_context"
                action_input = current_query
                logger.info(f"🤔 [Think]   - 默认工具: {action}")
                logger.info(f"🤔 [Think]   - 默认参数: {action_input}")

            state["current_tool"] = action
            state["action_input"] = action_input
            state["current_iteration"] = current_iteration + 1

            # 安全地显示参数（可能是字符串或列表）
            if isinstance(action_input, str):
                param_preview = action_input[:50] + "..." if len(action_input) > 50 else action_input
            elif isinstance(action_input, list):
                param_preview = str(action_input)[:100] + "..." if len(str(action_input)) > 100 else str(action_input)
            else:
                param_preview = str(action_input)

            logger.info(f"✅ [Think] 输出: 工具={action}, 参数类型={type(action_input).__name__}, 参数={param_preview}")
            return state

        except Exception as e:
            logger.error(f"❌ [Think] 失败: {e}", exc_info=True)
            state["current_tool"] = "search_by_context"
            state["action_input"] = state.get("rewritten_query", state["query"])
            state["current_iteration"] = current_iteration + 1
            logger.info(f"⚠️  [Think] 错误回退: 使用 search_by_context")
            return state

    async def act(self, state: RetrievalState) -> Dict:
        """执行工具调用"""

        tool_name = state["current_tool"]
        action_input = state.get("action_input", state.get("rewritten_query", state["query"]))

        logger.info(f"🔧 [Act] ========== 步骤2: 执行工具 ==========")
        logger.info(f"🔧 [Act] 工具名称: {tool_name}")
        logger.info(f"🔧 [Act] 工具参数: {action_input}")

        try:
            # 构建可用工具
            available_tools = self.agent.utils.build_retrieval_tools()
            logger.info(f"🔧 [Act] 可用工具列表: {list(available_tools.keys())}")

            if tool_name in available_tools:
                logger.info(f"🔧 [Act] 调用工具: {tool_name}")
                tool_func = available_tools[tool_name]["function"]

                # 调用工具（传入action_input）
                result = await tool_func(action_input)
            else:
                logger.warning(f"⚠️  [Act] 工具 '{tool_name}' 不在可用列表中，使用默认工具")
                result = await self.agent.tools.search_by_context(action_input)

            # 统计结果
            if isinstance(result, dict):
                # extract_titles_from_structure 的新格式
                result_count = len(result.get("titles", []))
                logger.info(f"🔧 [Act] 工具执行完成，提取到 {result_count} 个标题")
                if result.get("titles"):
                    logger.info(f"🔧 [Act]   标题列表: {result.get('titles')}")
                if result.get("reason"):
                    logger.info(f"🔧 [Act]   选择原因: {result.get('reason')}")
            elif isinstance(result, list):
                result_count = len(result)
                logger.info(f"🔧 [Act] 工具执行完成，返回 {result_count} 条结果")

                if result_count > 0:
                    # 区分结构化工具和内容检索工具
                    if tool_name == "get_document_structure":
                        # get_document_structure：显示结果预览
                        preview_items = result[:5] if len(result) > 5 else result
                        logger.info(f"🔧 [Act]   结果预览（前{len(preview_items)}项）:")
                        for idx, item in enumerate(preview_items, 1):
                            logger.info(f"🔧 [Act]     {idx}. {item}")
                        if len(result) > 5:
                            logger.info(f"🔧 [Act]     ... (还有 {len(result) - 5} 项)")
                    else:
                        # 内容检索工具：显示章节信息（注意：title 是检索的目标，不是检索结果的标题）
                        logger.info(f"🔧 [Act]   检索到的内容:")
                        for idx, item in enumerate(result[:3], 1):
                            if isinstance(item, dict):
                                title = item.get("title", "无标题")
                                pages = item.get("pages", [])
                                content_preview = item.get("content", "")[:50] + "..." if item.get("content", "") else ""
                                logger.info(f"🔧 [Act]     {idx}. 章节: {title} (页码: {pages})")
                                logger.info(f"🔧 [Act]        内容预览: {content_preview}")
                        if len(result) > 3:
                            logger.info(f"🔧 [Act]     ... (还有 {len(result) - 3} 条)")
            else:
                result_count = 0
                logger.info(f"🔧 [Act] 工具执行完成，返回结果类型: {type(result)}")

            # 获取工具配置
            tool_config = get_tool_by_name(tool_name)
            requires_summary = tool_config.get("requires_summary", True) if tool_config else True
            logger.info(f"🔧 [Act] 是否需要总结: {requires_summary}")

            state["last_result"] = result
            state["requires_summary"] = requires_summary
            state["actions"] = state.get("actions", []) + [{"tool": tool_name}]

            logger.info(f"✅ [Act] 输出: {result_count} 条结果，requires_summary={requires_summary}")
            return state

        except Exception as e:
            logger.error(f"❌ [Act] 失败: {e}", exc_info=True)
            state["last_result"] = []
            state["requires_summary"] = True
            logger.info(f"⚠️  [Act] 错误回退: 返回空结果")
            return state

    async def summary(self, state: RetrievalState) -> Dict:
        """累积并总结数据（始终累积，按需总结）"""

        logger.info(f"📝 [Summary] ========== 步骤3: 累积并总结数据 ==========")

        try:
            last_result = state.get("last_result", [])
            retrieved_content = state.get("retrieved_content", [])
            requires_summary = state.get("requires_summary", True)

            logger.info(f"📝 [Summary] 输入:")
            logger.info(f"📝 [Summary]   - 本轮结果数: {len(last_result) if isinstance(last_result, list) else 0}")
            logger.info(f"📝 [Summary]   - 累积结果数: {len(retrieved_content)}")
            logger.info(f"📝 [Summary]   - 需要生成总结: {requires_summary}")

            # ========== 第一步：始终累积数据 ==========
            new_items = 0
            current_tool = state.get("current_tool", "unknown")

            if isinstance(last_result, dict):
                # 检查是否是 extract_titles_from_structure 的新格式
                if current_tool == "extract_titles_from_structure" and "titles" in last_result:
                    # 新格式：{"titles": [...], "reason": "..."}
                    special_data = {
                        "type": "structured_info",
                        "tool": current_tool,
                        "data": last_result.get("titles", []),
                        "reason": last_result.get("reason", "")
                    }
                    retrieved_content.append(special_data)
                    new_items = 1
                    logger.info(f"📝 [Summary] 累积结构化信息: {current_tool}")
                    logger.info(f"📝 [Summary]   - 标题数: {len(last_result.get('titles', []))}")
                    logger.info(f"📝 [Summary]   - 原因: {last_result.get('reason', '')}")
                else:
                    # 常规内容检索工具返回的 dict
                    retrieved_content.append(last_result)
                    new_items = 1
            elif isinstance(last_result, list):
                # 检查是否是 get_document_structure 的结果（返回 List[str]）
                if current_tool == "get_document_structure":
                    # 这个工具返回的是字符串列表，需要包装成特殊格式
                    if all(isinstance(x, str) for x in last_result) and len(last_result) > 0:
                        # 包装成特殊标记的 dict
                        special_data = {
                            "type": "structured_info",
                            "tool": current_tool,
                            "data": last_result
                        }
                        retrieved_content.append(special_data)
                        new_items = 1
                        logger.info(f"📝 [Summary] 累积结构化信息: {current_tool}, {len(last_result)} 项")
                else:
                    # 常规工具返回的是 List[dict]
                    for item in last_result:
                        if isinstance(item, dict):
                            retrieved_content.append(item)
                            new_items += 1

            state["retrieved_content"] = retrieved_content
            logger.info(f"📝 [Summary] 新增 {new_items} 条内容，总计 {len(retrieved_content)} 条")

            if not retrieved_content:
                logger.warning(f"⚠️  [Summary] 无检索内容，跳过总结")
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
                    reason = item.get("reason", "")

                    formatted_item = {
                        "index": idx,
                        "type": "structured_info",
                        "tool": tool_name,
                        "data": data,
                        "title": f"[{tool_name}]",
                        "pages": [],
                        "content": "\n".join(data) if isinstance(data, list) else str(data)
                    }

                    # 如果有原因说明，也加入
                    if reason:
                        formatted_item["reason"] = reason

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
            logger.info(f"📝 [Summary] 格式化 {len(formatted_data)} 条数据")

            return state

            # ========== 以下代码已注释掉 ==========
#            if not requires_summary:
#                # 不需要总结：保留之前的总结，或生成简单描述
#                previous_summary = state.get("intermediate_summary", "")
#                if previous_summary:
#                    logger.info(f"📝 [Summary] 不需要总结，保留之前的总结（长度: {len(previous_summary)}）")
#                else:
#                    # 生成简单描述
#                    simple_summary = f"已累积 {len(retrieved_content)} 条检索结果"
#                    state["intermediate_summary"] = simple_summary
#                    logger.info(f"📝 [Summary] 不需要总结，生成简单描述: {simple_summary}")
#
#                logger.info(f"✅ [Summary] 数据累积完成（跳过LLM总结）")
#                return state
#
#            # 需要总结：调用 LLM 生成总结
#            logger.info(f"📝 [Summary] 调用 LLM 生成总结...")
#
#            # 构建详细的检索内容
#            content_parts = []
#            for idx, item in enumerate(formatted_data, 1):
#                # 跳过结构化信息（它们不需要总结）
#                if item.get("type") == "structured_info":
#                    continue
#
#                # 构建内容块
#                title = item.get("title", "未知章节")
#                pages = item.get("pages", [])
#                content = item.get("content", "")
#
#                if pages:
#                    sorted_pages = sorted(pages, key=lambda x: int(x) if str(x).isdigit() else 0)
#                    page_info = f"页码: {', '.join(map(str, sorted_pages))}"
#                else:
#                    page_info = "页码: 未知"
#
#                content_block = f"""
### 内容 {idx}: {title} ({page_info})
#
#{content}
#"""
#                content_parts.append(content_block.strip())
#
#            # 如果没有实际内容（全是结构化信息），使用简单描述
#            if not content_parts:
#                state["intermediate_summary"] = f"已累积 {len(retrieved_content)} 条检索结果"
#                logger.info(f"📝 [Summary] 无实际内容需要总结，使用简单描述")
#                return state
#
#            # 构建完整的 prompt
#            all_content = "\n\n".join(content_parts)
#            prompt = f"""请对以下 {len(content_parts)} 条检索内容进行总结：
#
#{all_content}
#
#---
#
#请按照以下要求总结：
#1. 保留关键信息、重要数据、核心概念
#2. 按章节组织，标注页码来源
#3. 使用 Markdown 格式，层次清晰
#"""
#
#            logger.info(f"📝 [Summary] 准备总结 {len(content_parts)} 条内容，总长度: {len(all_content)} 字符")
#
#            session_id = f"summary_{state.get('doc_name', 'default')}"
#            summary = await self.agent.llm.async_call_llm_chain(
#                role=RetrievalRole.CONTEXT_SUMMARIZER,
#                input_prompt=prompt,
#                session_id=session_id
#            )
#
#            state["intermediate_summary"] = summary
#
#            logger.info(f"✅ [Summary] 总结完成，长度: {len(summary)} 字符")
#            logger.info(f"📝 [Summary] 总结预览: {summary[:200]}...")
#            return state
#
        except Exception as e:
            logger.error(f"❌ [Summary] 失败: {e}", exc_info=True)
            state["intermediate_summary"] = "总结失败"
            return state

    async def evaluate(self, state: RetrievalState) -> Dict:
        """评估检索结果"""

        logger.info(f"⚖️ [Evaluate] ========== 步骤4: 评估检索结果 ==========")

        try:
            formatted_data = state.get("formatted_data", [])
            current_iteration = state.get("current_iteration", 0)
            max_iterations = state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS)
            original_query = state["query"]

            logger.info(f"⚖️ [Evaluate] 输入:")
            logger.info(f"⚖️ [Evaluate]   - 用户查询: {original_query}")
            logger.info(f"⚖️ [Evaluate]   - 格式化数据数: {len(formatted_data)}")
            logger.info(f"⚖️ [Evaluate]   - 当前迭代: {current_iteration}/{max_iterations}")

            if not formatted_data:
                logger.warning(f"⚠️  [Evaluate] 无检索内容，判断为不完整")
                state["is_complete"] = False
                state["reason"] = "无检索内容，继续检索"
                logger.info(f"⚖️ [Evaluate] 输出: is_complete=False, reason='{state['reason']}'")
                return state

            # 构建检索内容摘要（章节标题 + 页码，不包含完整内容）
            content_summary_parts = []
            for idx, item in enumerate(formatted_data, 1):
                if item.get("type") == "structured_info":
                    # 结构化信息
                    tool_name = item.get("tool", "unknown")
                    data = item.get("data", [])
                    if tool_name == "extract_titles_from_structure":
                        reason = item.get("reason", "")
                        content_summary_parts.append(f"{idx}. 已提取标题: {data} ({reason})")
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

            logger.info(f"⚖️ [Evaluate] 构建检索内容摘要:")
            logger.info(f"{content_summary}")

            logger.info(f"⚖️ [Evaluate] 调用 LLM 评估检索完整性...")
            prompt = f"""用户查询: {original_query}

已检索的内容摘要:
{content_summary}

评估这些检索内容是否足以回答用户的问题。返回JSON：
{{"is_complete": true/false, "reason": "..."}}

判断标准：
- 如果检索到的章节/内容能够回答问题的核心，返回 true
- 如果还缺少关键信息，返回 false 并说明缺少什么
"""

            session_id = f"evaluate_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL_EVALUATOR,
                input_prompt=prompt,
                session_id=session_id
            )

            logger.info(f"⚖️ [Evaluate] LLM 响应: {response[:200]}...")

            evaluation = json.loads(response.strip()) if response.strip().startswith('{') else {}
            is_complete = evaluation.get("is_complete", False)
            reason = evaluation.get("reason", "")

            state["is_complete"] = is_complete
            state["reason"] = reason

            logger.info(f"⚖️ [Evaluate] 评估结果:")
            logger.info(f"⚖️ [Evaluate]   - 是否完整: {is_complete}")
            logger.info(f"⚖️ [Evaluate]   - 判断理由: {reason}")

            if is_complete:
                logger.info(f"✅ [Evaluate] 检索完成，准备生成最终答案")
            else:
                logger.info(f"🔄 [Evaluate] 检索未完成，将继续下一轮")

            return state

        except Exception as e:
            logger.error(f"❌ [Evaluate] 失败: {e}", exc_info=True)
            is_complete_fallback = current_iteration >= state.get("max_iterations", ProcessingLimits.MAX_RETRIEVAL_ITERATIONS)
            state["is_complete"] = is_complete_fallback
            state["reason"] = f"评估失败，基于迭代次数判断: {is_complete_fallback}"
            logger.info(f"⚠️  [Evaluate] 错误回退: is_complete={is_complete_fallback}")
            return state

    async def format(self, state: RetrievalState) -> Dict:
        """生成最终精准总结"""

        logger.info(f"🎯 [Format] ========== 步骤5: 生成最终总结 ==========")

        try:
            formatted_data = state.get("formatted_data", [])
            intermediate_summary = state.get("intermediate_summary", "")
            original_query = state["query"]

            logger.info(f"🎯 [Format] 输入:")
            logger.info(f"🎯 [Format]   - 用户查询: {original_query}")
            logger.info(f"🎯 [Format]   - 格式化数据数: {len(formatted_data)}")
            #logger.info(f"🎯 [Format]   - 中间总结长度: {len(intermediate_summary)} 字符")

            if not formatted_data:
                logger.warning(f"⚠️  [Format] 无格式化数据，使用中间总结作为最终答案")
                #state["final_summary"] = intermediate_summary
                #logger.info(f"🎯 [Format] 输出: 使用中间总结 (长度: {len(intermediate_summary)})")
                return state

            # 构建最终总结
            logger.info(f"🎯 [Format] 调用 LLM 生成最终精准答案...")

            # ========== 步骤1: 去重和合并 raw_data ==========
            # 使用 raw_data 而不是 content（refactor_data）
            # 按页码去重：同一页只保留一次
            all_raw_pages = {}  # {page_num: {"title": str, "content": str}}

            for item in formatted_data:
                # 跳过结构化信息（它们不是实际内容）
                if item.get("type") == "structured_info":
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

            logger.info(f"🎯 [Format] 去重后共 {len(all_raw_pages)} 页原始内容")

            # ========== 步骤2: 构建检索内容详情 ==========
            content_parts = []

            # 按页码排序
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

            # 如果没有实际内容，使用中间总结
            if not content_parts:
                logger.warning(f"⚠️  [Format] 无实际内容，使用中间总结作为最终答案")
                #state["final_summary"] = intermediate_summary
                #logger.info(f"🎯 [Format] 输出: 使用中间总结 (长度: {len(intermediate_summary)})")
                return state

            # 构建完整的 prompt
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
4. 标注信息来源（章节和页码）
5. 使用清晰的 Markdown 格式组织答案
6. 如果检索内容不足以完全回答问题，明确说明
"""

            logger.info(f"🎯 [Format] 准备生成最终答案，内容数: {len(content_parts)}，总长度: {len(all_content)} 字符")

            session_id = f"format_{state.get('doc_name', 'default')}"
            final_summary = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.CONTEXT_SUMMARIZER,
                input_prompt=prompt,
                session_id=session_id
            )

            state["final_summary"] = final_summary
            logger.info(f"✅ [Format] 最终答案生成完成")
            logger.info(f"🎯 [Format]   - 答案长度: {len(final_summary)} 字符")
            logger.info(f"🎯 [Format]   - 答案预览: {final_summary[:200]}...")
            return state

        except Exception as e:
            logger.error(f"❌ [Format] 失败: {e}", exc_info=True)
            #intermediate_summary = state.get("intermediate_summary", "")
            #state["final_summary"] = intermediate_summary
            #logger.info(f"⚠️  [Format] 错误回退: 使用中间总结 (长度: {len(intermediate_summary)})")
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
