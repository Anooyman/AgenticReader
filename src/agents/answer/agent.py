"""
Answer Agent - 用户对话接口Agent（确定性工具规划架构）

工作流程（单轮确定性流水线，非 ReAct）：
0. rewrite_query - 根据对话历史改写查询，补全上下文
1. plan - 按用户启用的工具确定性构造工具调用（无 LLM 决策）
2. execute - 执行工具调用
3. evaluate - 判断内容是否足够（仅作终止标记，不再回环到 plan）
4. generate - 生成最终答案

图结构：
    rewrite_query → plan → (execute → evaluate → generate | generate) → END

工具：
- retrieve_documents: 统一文档检索（单文档/多文档/自动选择）
- search_web: 网络搜索（使用 SearchAgent）
"""

from langgraph.graph import StateGraph, END
from typing import Optional
import logging

from ..base import AgentBase
from .state import AnswerState
from .tools import AnswerTools
from .nodes import AnswerNodes
from .utils import AnswerUtils

logger = logging.getLogger(__name__)


class AnswerAgent(AgentBase):
    """
    对话Agent（确定性工具规划架构）

    工作流程：
    rewrite_query → plan → execute_tools → evaluate → generate → END
    （plan 若判无需工具则直接 → generate）

    特点：
    - 上下文查询改写：根据历史对话补全省略、指代
    - plan 节点按 enabled_tools 确定性构造工具调用，不再依赖 LLM 动态规划
    - 单轮架构：evaluate 之后直接进入 generate，不再回环到 plan 做二次规划
    - 新工具通过注册即可接入
    - current_doc/manual_selected_docs 作为上下文提示传给 generate
    """

    def __init__(self, doc_name: str = None, provider: str = 'openai', progress_callback=None):
        super().__init__(name="AnswerAgent", provider=provider)

        # 当前文档上下文
        self.current_doc = doc_name

        # 进度回调函数
        self.progress_callback = progress_callback

        # 对话轮次追踪（每个文档独立追踪）
        self.conversation_turns = {}  # {doc_name: turn_count}

        # Retrieval Agent 实例池（每个文档一个实例，保留检索缓存）
        self.retrieval_agents = {}  # {doc_name: RetrievalAgent}

        # Search Agent 实例（单例，用于网络搜索）
        self.search_agent = None  # SearchAgent (lazy initialization)

        # 文档注册表
        from src.core.document_management import DocumentRegistry
        self.registry = DocumentRegistry()

        # 初始化功能模块（依赖注入）
        self.utils = AnswerUtils(self)
        self.tools = AnswerTools(self)
        self.nodes = AnswerNodes(self)

        # 构建workflow
        self.graph = self.build_graph()

    # ==================== Graph构建 ====================

    def build_graph(self) -> StateGraph:
        """
        构建单轮确定性工作流

        rewrite_query → plan → (execute → evaluate → generate | generate) → END

        - rewrite_query: 根据对话历史改写查询，补全上下文
        - plan: 按 enabled_tools 确定性构造工具调用（无 LLM 决策）
        - execute: 并行执行工具调用
        - evaluate: 判断内容是否充分，仅作终止标记
        - generate: 生成最终答案
        """
        workflow = StateGraph(AnswerState)

        # 添加节点
        workflow.add_node("rewrite_query", self.nodes.rewrite_query)
        workflow.add_node("plan", self.nodes.plan)
        workflow.add_node("execute", self.nodes.execute_tools)
        workflow.add_node("evaluate", self.nodes.evaluate)
        workflow.add_node("generate", self.nodes.generate_answer)

        # 设置入口
        workflow.set_entry_point("rewrite_query")

        # rewrite_query → plan
        workflow.add_edge("rewrite_query", "plan")

        # plan → execute（有工具调用）或 generate（无需工具）
        workflow.add_conditional_edges(
            "plan",
            self.nodes.route_after_plan,
            {
                "execute": "execute",
                "direct": "generate"
            }
        )

        # execute → evaluate
        workflow.add_edge("execute", "evaluate")

        # evaluate → generate（单轮架构：评估完成后直接进入生成，不再回环到 plan）
        workflow.add_edge("evaluate", "generate")

        # generate → END
        workflow.add_edge("generate", END)

        return workflow.compile()

    # ==================== Retrieval Agent 管理 ====================

    def get_retrieval_agent(self, doc_name: str):
        """获取指定文档的 Retrieval Agent 实例"""
        return self.retrieval_agents.get(doc_name)

    def get_managed_documents(self):
        """获取当前管理的所有文档列表"""
        return list(self.retrieval_agents.keys())

    def get_retrieval_cache_stats(self, doc_name: str = None):
        """获取检索缓存统计信息"""
        if doc_name:
            agent = self.retrieval_agents.get(doc_name)
            if agent and hasattr(agent, 'retrieval_data_dict'):
                return {
                    "doc_name": doc_name,
                    "cached_chapters": len(agent.retrieval_data_dict),
                    "chapter_list": list(agent.retrieval_data_dict.keys())
                }
            return {"doc_name": doc_name, "cached_chapters": 0, "chapter_list": []}
        else:
            stats = {}
            for doc, agent in self.retrieval_agents.items():
                if hasattr(agent, 'retrieval_data_dict'):
                    stats[doc] = {
                        "cached_chapters": len(agent.retrieval_data_dict),
                        "chapter_list": list(agent.retrieval_data_dict.keys())
                    }
            return stats

    def clear_retrieval_agent(self, doc_name: str):
        """清除指定文档的 Retrieval Agent"""
        if doc_name in self.retrieval_agents:
            del self.retrieval_agents[doc_name]
            logger.info(f"🗑️  已清除文档 '{doc_name}' 的 Retrieval Agent")
        if doc_name in self.conversation_turns:
            del self.conversation_turns[doc_name]

    def clear_all_retrieval_agents(self):
        """清除所有 Retrieval Agent"""
        count = len(self.retrieval_agents)
        self.retrieval_agents.clear()
        self.conversation_turns.clear()
        logger.info(f"🗑️  已清除所有 {count} 个 Retrieval Agent 实例")

    # ==================== 文档验证辅助方法 ====================

    def validate_manual_selected_docs(self, doc_names: list) -> tuple:
        """验证手动选择的文档列表"""
        valid_docs = []
        invalid_docs = []
        for doc_name in doc_names:
            doc_info = self.registry.get_by_name(doc_name)
            if doc_info:
                valid_docs.append(doc_name)
            else:
                invalid_docs.append(doc_name)
        return valid_docs, invalid_docs

    def get_available_documents(self) -> list:
        """获取所有可用的文档列表"""
        all_docs = self.registry.list_all()
        return [
            {
                "doc_name": doc.get("doc_name"),
                "brief_summary": doc.get("brief_summary", ""),
                "doc_type": doc.get("doc_type", "unknown")
            }
            for doc in all_docs
        ]

    # ==================== 历史管理 ====================

    def load_history(self, messages: list, selected_docs: Optional[list] = None):
        """
        加载历史对话到 LLM

        Args:
            messages: 历史消息列表 [{"role": "user", "content": "..."}, ...]
            selected_docs: 跨文档模式下的文档列表
        """
        if not messages or len(messages) == 0:
            logger.info("无历史消息需要加载")
            return

        logger.info(f"正在加载 {len(messages)} 条历史消息到 LLM...")

        from langchain_core.messages import HumanMessage, AIMessage

        langchain_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))

        # 并行加载到所有 session
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        start_time = time.time()

        def load_to_session(agent_llm, session_id, agent_name=""):
            try:
                agent_llm.add_messages_to_history(session_id, langchain_messages)
                return (session_id, agent_name, True, None)
            except Exception as e:
                logger.error(f"加载到 {agent_name} session '{session_id}' 时出错: {e}")
                return (session_id, agent_name, False, str(e))

        tasks = []
        # Answer Agent 的 tool_planning session
        tasks.append((self.llm, "tool_planning", "Answer Agent"))
        # 所有 Retrieval Agent 的 rewrite_query session
        for doc_name, retrieval_agent in self.retrieval_agents.items():
            tasks.append((retrieval_agent.llm, "rewrite_query", f"Retrieval Agent ({doc_name})"))

        with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as executor:
            futures = {executor.submit(load_to_session, llm, sid, name): (sid, name) for llm, sid, name in tasks}
            success_count = 0
            for future in as_completed(futures):
                session_id, agent_name, success, error = future.result()
                if success:
                    logger.info(f"✅ 已加载历史到 {agent_name} 的 '{session_id}' session")
                    success_count += 1

        elapsed = time.time() - start_time
        logger.info(f"⚡ 并行加载完成: {success_count}/{len(tasks)} 个session，耗时: {elapsed:.3f}秒")

        # 设置对话轮次
        user_message_count = sum(1 for msg in messages if msg.get("role") == "user")
        if user_message_count > 0:
            for doc_name in self.retrieval_agents.keys():
                self.conversation_turns[doc_name] = user_message_count

            if self.current_doc and self.current_doc not in self.conversation_turns:
                self.conversation_turns[self.current_doc] = user_message_count

            if selected_docs:
                for doc_name in selected_docs:
                    if doc_name not in self.conversation_turns:
                        self.conversation_turns[doc_name] = user_message_count

    def reset_history(self):
        """重置 LLM 历史"""
        logger.info("正在重置 LLM 对话历史...")

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        start_time = time.time()

        def clear_session(agent_llm, session_id, agent_name=""):
            try:
                agent_llm.clear_session_history(session_id)
                return (session_id, agent_name, True, None)
            except Exception as e:
                return (session_id, agent_name, False, str(e))

        tasks = []
        tasks.append((self.llm, "tool_planning", "Answer Agent"))
        for doc_name, retrieval_agent in self.retrieval_agents.items():
            tasks.append((retrieval_agent.llm, "rewrite_query", f"Retrieval Agent ({doc_name})"))

        with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as executor:
            futures = {executor.submit(clear_session, llm, sid, name): (sid, name) for llm, sid, name in tasks}
            success_count = 0
            for future in as_completed(futures):
                session_id, agent_name, success, error = future.result()
                if success:
                    success_count += 1

        elapsed = time.time() - start_time
        logger.info(f"✅ 历史已重置: {success_count}/{len(tasks)} 个session，耗时: {elapsed:.3f}秒")
        self.conversation_turns.clear()

        # 同步清空检索去重历史（含轮次计数），让新会话可以重新检索同一批文档
        for retrieval_agent in self.retrieval_agents.values():
            vdb_client = getattr(retrieval_agent, "vector_db_client", None)
            if vdb_client is not None:
                vdb_client.reset_retrieval_history()
            if hasattr(retrieval_agent, "current_conversation_turn"):
                retrieval_agent.current_conversation_turn = 0

    # ==================== 查询接口 ====================

    async def query(
        self,
        user_query: str,
        enabled_tools: Optional[list] = None,
        selected_docs: Optional[list] = None,
        **kwargs
    ) -> AnswerState:
        """
        执行查询（推荐使用此方法）

        Args:
            user_query: 用户查询
            enabled_tools: 用户启用的工具列表 ["retrieve_documents", "search_web"]
            selected_docs: 用户选择的文档列表（PDF检索时）
            **kwargs: 额外参数（向后兼容）

        Returns:
            AnswerState: 执行结果
        """
        # 更新当前文档上下文（取第一个文档用于 progress 显示）
        if selected_docs and len(selected_docs) == 1:
            self.current_doc = selected_docs[0]
        elif not selected_docs:
            self.current_doc = None

        # 创建初始状态
        state: AnswerState = {
            "user_query": user_query,
            "enabled_tools": enabled_tools or [],
        }

        if selected_docs:
            state["selected_docs"] = selected_docs

        # 执行查询
        result = await self.graph.ainvoke(state)

        return result
