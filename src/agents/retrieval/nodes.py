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
        from src.config.prompts.retrieval_prompts import RetrievalRole

        current_iteration = state.get("current_iteration", 0)
        intermediate_summary = state.get("intermediate_summary", "")
        original_query = state["query"]

        logger.info(f"🔄 [Rewrite] 查询重写 - 迭代 {current_iteration + 1}")

        try:
            if current_iteration == 0 or not intermediate_summary:
                state["rewritten_query"] = original_query
                return state

            # 构建prompt（省略具体实现）
            session_id = f"rewrite_{state.get('doc_name', 'default')}"
            rewritten = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.QUERY_REWRITE,
                input_prompt=f"原始查询: {original_query}\n优化该查询",
                session_id=session_id
            )

            state["rewritten_query"] = rewritten.strip().strip('"').strip("'").strip()
            return state

        except Exception as e:
            logger.error(f"❌ [Rewrite] 失败: {e}")
            state["rewritten_query"] = original_query
            return state

    async def think(self, state: RetrievalState) -> Dict:
        """思考节点：选择工具"""
        from src.config.prompts.retrieval_prompts import RetrievalRole
        from src.config.tools.retrieval_tools import format_all_tools_for_llm

        current_iteration = state.get("current_iteration", 0)
        logger.info(f"🤔 [Think] ========== 步骤1: 思考工具选择 ==========")

        try:
            tools_description = format_all_tools_for_llm()
            current_query = state.get("rewritten_query", state["query"])

            prompt = f"""当前查询: {current_query}
迭代: {current_iteration + 1}/{state['max_iterations']}

请选择下一步使用的工具。返回JSON：
{{"thought": "...", "action": "工具名称", "action_input": "参数"}}
"""

            session_id = f"think_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL,
                input_prompt=prompt,
                session_id=session_id,
                system_format_dict={"tool_info_dict": tools_description}
            )

            # 解析JSON
            decision = json.loads(response.strip()) if response.strip().startswith('{') else None
            if decision:
                action = decision.get("action", "search_by_context")
                action_input = decision.get("action_input", current_query)
            else:
                action = "search_by_context"
                action_input = current_query

            state["current_tool"] = action
            state["action_input"] = action_input
            state["current_iteration"] = current_iteration + 1

            return state

        except Exception as e:
            logger.error(f"❌ [Think] 失败: {e}")
            state["current_tool"] = "search_by_context"
            state["action_input"] = state.get("rewritten_query", state["query"])
            state["current_iteration"] = current_iteration + 1
            return state

    async def act(self, state: RetrievalState) -> Dict:
        """执行工具调用"""
        from src.config.tools.retrieval_tools import get_tool_by_name
        import inspect

        tool_name = state["current_tool"]
        current_query = state.get("rewritten_query", state["query"])

        logger.info(f"🔧 [Act] ========== 执行工具: {tool_name} ==========")

        try:
            # 构建可用工具
            available_tools = self.agent.utils.build_retrieval_tools()

            if tool_name in available_tools:
                tool_func = available_tools[tool_name]["function"]
                
                # 调用工具（传入current_query）
                result = await tool_func(current_query)
            else:
                result = await self.agent.tools.search_by_context(current_query)

            # 获取工具配置
            tool_config = get_tool_by_name(tool_name)
            requires_summary = tool_config.get("requires_summary", True) if tool_config else True

            state["last_result"] = result
            state["requires_summary"] = requires_summary
            state["actions"] = state.get("actions", []) + [{"tool": tool_name}]

            return state

        except Exception as e:
            logger.error(f"❌ [Act] 失败: {e}")
            state["last_result"] = []
            state["requires_summary"] = True
            return state

    async def summary(self, state: RetrievalState) -> Dict:
        """累积并总结数据"""
        from src.config.prompts.retrieval_prompts import RetrievalRole

        logger.info(f"📝 [Summary] ========== 累积并总结数据 ==========")

        try:
            last_result = state.get("last_result", [])
            retrieved_content = state.get("retrieved_content", [])

            # 累积结果
            if isinstance(last_result, list):
                for item in last_result:
                    if isinstance(item, dict):
                        retrieved_content.append(item)

            state["retrieved_content"] = retrieved_content

            if not retrieved_content:
                state["intermediate_summary"] = "未检索到相关内容"
                return state

            # 构建格式化数据
            formatted_data = []
            for idx, item in enumerate(retrieved_content, 1):
                formatted_data.append({
                    "index": idx,
                    "title": item.get("title", ""),
                    "pages": item.get("pages", []),
                    "content": item.get("content", "")
                })

            # 生成总结
            prompt = f"对以下{len(formatted_data)}条检索内容进行总结：\n..."
            session_id = f"summary_{state.get('doc_name', 'default')}"
            summary = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.CONTEXT_SUMMARIZER,
                input_prompt=prompt,
                session_id=session_id
            )

            state["intermediate_summary"] = summary
            state["formatted_data"] = formatted_data

            return state

        except Exception as e:
            logger.error(f"❌ [Summary] 失败: {e}")
            state["intermediate_summary"] = "总结失败"
            return state

    async def evaluate(self, state: RetrievalState) -> Dict:
        """评估检索结果"""
        from src.config.prompts.retrieval_prompts import RetrievalRole

        logger.info(f"⚖️ [Evaluate] ========== 评估检索结果 ==========")

        try:
            intermediate_summary = state.get("intermediate_summary", "")
            current_iteration = state.get("current_iteration", 0)

            if not intermediate_summary:
                state["is_complete"] = False
                state["reason"] = "无总结内容，继续检索"
                return state

            prompt = f"""用户查询: {state['query']}
检索总结: {intermediate_summary}

评估是否足以回答问题。返回JSON：
{{"is_complete": true/false, "reason": "..."}}
"""

            session_id = f"evaluate_{state.get('doc_name', 'default')}"
            response = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.RETRIEVAL_EVALUATOR,
                input_prompt=prompt,
                session_id=session_id
            )

            evaluation = json.loads(response.strip()) if response.strip().startswith('{') else {}
            is_complete = evaluation.get("is_complete", False)
            reason = evaluation.get("reason", "")

            state["is_complete"] = is_complete
            state["reason"] = reason

            return state

        except Exception as e:
            logger.error(f"❌ [Evaluate] 失败: {e}")
            state["is_complete"] = current_iteration >= state["max_iterations"]
            return state

    async def format(self, state: RetrievalState) -> Dict:
        """生成最终精准总结"""
        from src.config.prompts.retrieval_prompts import RetrievalRole

        logger.info(f"🎯 [Format] ========== 生成最终总结 ==========")

        try:
            formatted_data = state.get("formatted_data", [])
            if not formatted_data:
                state["final_summary"] = state.get("intermediate_summary", "")
                return state

            # 构建最终总结
            prompt = f"""用户查询: {state['query']}
检索内容: {...}

生成精准回答。
"""

            session_id = f"format_{state.get('doc_name', 'default')}"
            final_summary = await self.agent.llm.async_call_llm_chain(
                role=RetrievalRole.CONTEXT_SUMMARIZER,
                input_prompt=prompt,
                session_id=session_id
            )

            state["final_summary"] = final_summary
            return state

        except Exception as e:
            logger.error(f"❌ [Format] 失败: {e}")
            state["final_summary"] = state.get("intermediate_summary", "")
            return state

    def should_summarize(self, state: RetrievalState) -> str:
        """判断是否需要总结"""
        return "summary" if state.get("requires_summary", True) else "evaluate"

    def should_continue(self, state: RetrievalState) -> str:
        """判断是否继续检索"""
        if state.get("is_complete", False):
            return "finish"
        if state.get("current_iteration", 0) >= state.get("max_iterations", 5):
            return "finish"
        return "continue"
