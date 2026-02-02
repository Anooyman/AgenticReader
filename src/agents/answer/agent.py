"""
Answer Agent - 用户对话接口Agent

负责：
1. 分析用户意图
2. 决定是否需要检索
3. 调用Retrieval Agent获取上下文
4. 生成最终回答
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
    对话Agent

    工作流程：
    1. analyze_intent - 分析用户意图（判断是否需要检索）
    2. retrieve (可选) - 调用Retrieval Agent检索文档上下文
    3. generate_answer - 结合检索上下文（如有）和历史对话生成最终回答

    注意：
    - 历史对话由LLM Client自动管理，无需手动处理
    - 检索结果作为文档上下文，而非最终答案
    - 所有回答都结合历史对话上下文生成
    """

    def __init__(self, doc_name: str = None, provider: str = 'openai', progress_callback=None):
        super().__init__(name="AnswerAgent", provider=provider)

        # 当前文档上下文
        self.current_doc = doc_name

        # 进度回调函数（用于实时上报处理进度）
        self.progress_callback = progress_callback

        # 对话轮次追踪（用于传递给 Retrieval Agent）
        # 每个文档独立追踪对话轮次
        self.conversation_turns = {}  # {doc_name: turn_count}

        # Retrieval Agent 实例池（每个文档一个实例，保留检索缓存）
        # 这样可以：
        # 1. 避免重复检索相同内容（例如文档结构）
        # 2. 保留检索缓存（retrieval_data_dict）
        # 3. 支持多 PDF 联合回答
        self.retrieval_agents = {}  # {doc_name: RetrievalAgent}

        # 文档注册表（用于跨文档检索）
        from src.core.document_management import DocumentRegistry
        self.registry = DocumentRegistry()

        # 持久化状态（跨多轮对话保留）
        self.persistent_state: Optional[AnswerState] = None

        # 初始化功能模块（使用依赖注入）
        self.utils = AnswerUtils(self)
        self.tools = AnswerTools(self)
        self.nodes = AnswerNodes(self)

        # 构建workflow
        self.graph = self.build_graph()

    # ==================== Graph构建 ====================

    def build_graph(self) -> StateGraph:
        """
        构建workflow

        支持三种模式：
        1. 单文档模式：analyze → retrieve_single → generate
        2. 跨文档自动选择模式：analyze → select_docs → rewrite_queries → retrieve_multi → synthesize → generate
        3. 跨文档手动选择模式：analyze → rewrite_queries → retrieve_multi → synthesize → generate
        4. 直接回答：analyze → generate

        工作流程：
        1. analyze - 分析意图和模式
        2. select_docs (跨文档自动模式) - 自动选择相关文档
        3. rewrite_queries (跨文档模式) - 为每个文档改写查询
        4. retrieve_single (单文档模式) - 单文档检索
        5. retrieve_multi (跨文档模式) - 多文档并行检索
        6. synthesize (跨文档模式) - 综合多文档结果
        7. generate - 生成最终回答
        """
        workflow = StateGraph(AnswerState)

        # 添加节点（委托给 nodes 模块）
        workflow.add_node("analyze", self.nodes.analyze_intent)
        workflow.add_node("select_docs", self.nodes.select_documents)
        workflow.add_node("rewrite_queries", self.nodes.rewrite_queries_for_docs)
        workflow.add_node("retrieve_single", self.nodes.call_retrieval)
        workflow.add_node("retrieve_multi", self.nodes.call_multi_retrieval)
        workflow.add_node("synthesize", self.nodes.synthesize_multi_docs)
        workflow.add_node("generate", self.nodes.generate_answer)

        # 条件边1: 根据意图和模式路由
        workflow.add_conditional_edges(
            "analyze",
            self.nodes.route_by_intent,
            {
                "direct": "generate",              # 直接回答
                "single_doc": "retrieve_single",   # 单文档检索
                "cross_doc_auto": "select_docs",   # 跨文档自动选择
                "cross_doc_manual": "rewrite_queries"  # 跨文档手动选择（跳过select_docs）
            }
        )

        # 条件边2: 根据文档选择结果路由
        workflow.add_conditional_edges(
            "select_docs",
            self.nodes.route_after_selection,
            {
                "no_docs": "generate",          # 未找到相关文档，直接回答
                "retrieve": "rewrite_queries"   # 找到相关文档，先改写查询
            }
        )

        # 单文档流程
        workflow.add_edge("retrieve_single", "generate")

        # 跨文档流程（自动选择和手动选择都走这个流程）
        workflow.add_edge("rewrite_queries", "retrieve_multi")  # 改写查询 → 并行检索
        workflow.add_edge("retrieve_multi", "synthesize")
        workflow.add_edge("synthesize", "generate")

        workflow.add_edge("generate", END)

        # 设置入口
        workflow.set_entry_point("analyze")

        return workflow.compile()

    # ==================== Retrieval Agent 管理方法 ====================

    def get_retrieval_agent(self, doc_name: str):
        """
        获取指定文档的 Retrieval Agent 实例

        Args:
            doc_name: 文档名称

        Returns:
            RetrievalAgent 实例，如果不存在则返回 None
        """
        return self.retrieval_agents.get(doc_name)

    def get_managed_documents(self):
        """
        获取当前管理的所有文档列表

        Returns:
            文档名称列表
        """
        return list(self.retrieval_agents.keys())

    def get_retrieval_cache_stats(self, doc_name: str = None):
        """
        获取检索缓存统计信息

        Args:
            doc_name: 文档名称，如果为 None 则返回所有文档的统计

        Returns:
            缓存统计字典
        """
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
            # 返回所有文档的统计
            stats = {}
            for doc, agent in self.retrieval_agents.items():
                if hasattr(agent, 'retrieval_data_dict'):
                    stats[doc] = {
                        "cached_chapters": len(agent.retrieval_data_dict),
                        "chapter_list": list(agent.retrieval_data_dict.keys())
                    }
            return stats

    def clear_retrieval_agent(self, doc_name: str):
        """
        清除指定文档的 Retrieval Agent 实例及其缓存

        Args:
            doc_name: 文档名称
        """
        if doc_name in self.retrieval_agents:
            del self.retrieval_agents[doc_name]
            logger.info(f"🗑️  已清除文档 '{doc_name}' 的 Retrieval Agent")

        if doc_name in self.conversation_turns:
            del self.conversation_turns[doc_name]
            logger.info(f"🗑️  已清除文档 '{doc_name}' 的对话轮次记录")

    def clear_all_retrieval_agents(self):
        """
        清除所有 Retrieval Agent 实例及其缓存
        """
        count = len(self.retrieval_agents)
        self.retrieval_agents.clear()
        self.conversation_turns.clear()
        logger.info(f"🗑️  已清除所有 {count} 个 Retrieval Agent 实例")

    # ==================== 手动选择模式辅助方法 ====================

    def validate_manual_selected_docs(self, doc_names: list) -> tuple:
        """
        验证手动选择的文档列表

        Args:
            doc_names: 文档名列表

        Returns:
            (valid_docs, invalid_docs): 有效和无效的文档名列表
        """
        valid_docs = []
        invalid_docs = []

        for doc_name in doc_names:
            doc_info = self.registry.get_by_name(doc_name)  # 使用 get_by_name 而不是 get
            if doc_info:
                valid_docs.append(doc_name)
            else:
                invalid_docs.append(doc_name)

        return valid_docs, invalid_docs

    def get_available_documents(self) -> list:
        """
        获取所有可用的文档列表

        Returns:
            文档信息列表，每个元素包含 doc_name 和 brief_summary
        """
        all_docs = self.registry.list_all()
        return [
            {
                "doc_name": doc.get("doc_name"),
                "brief_summary": doc.get("brief_summary", ""),
                "doc_type": doc.get("doc_type", "unknown")
            }
            for doc in all_docs
        ]

    # ==================== 历史管理方法 ====================

    def load_history(self, messages: list, selected_docs: Optional[list] = None):
        """
        加载历史对话到 LLM

        Args:
            messages: 历史消息列表，格式: [{"role": "user", "content": "..."}, ...]
            selected_docs: 跨文档模式下的文档列表（用于预设 conversation_turns）
        """
        if not messages or len(messages) == 0:
            logger.info("无历史消息需要加载")
            return

        logger.info(f"正在加载 {len(messages)} 条历史消息到 LLM...")

        # 转换为 LangChain 消息格式
        from langchain_core.messages import HumanMessage, AIMessage

        langchain_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))
            else:
                logger.warning(f"未知的消息角色: {role}，跳过")

        # 并行加载到所有需要的 session（使用线程池）
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        start_time = time.time()

        def load_to_session(agent_llm, session_id, agent_name=""):
            """加载历史到单个session"""
            try:
                agent_llm.add_messages_to_history(session_id, langchain_messages)
                return (session_id, agent_name, True, None)
            except Exception as e:
                logger.error(f"加载到 {agent_name} session '{session_id}' 时出错: {e}")
                return (session_id, agent_name, False, str(e))

        # 准备所有需要加载的任务
        tasks = []

        # 1. Answer Agent 的 analyze_intent session
        tasks.append((self.llm, "analyze_intent", "Answer Agent"))

        # 2. 所有 Retrieval Agent 的 rewrite_query session
        for doc_name, retrieval_agent in self.retrieval_agents.items():
            tasks.append((retrieval_agent.llm, "rewrite_query", f"Retrieval Agent ({doc_name})"))

        # 使用线程池并行加载
        with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as executor:
            # 提交所有任务
            futures = {executor.submit(load_to_session, llm, sid, name): (sid, name) for llm, sid, name in tasks}

            # 等待所有任务完成并收集结果
            success_count = 0
            for future in as_completed(futures):
                session_id, agent_name, success, error = future.result()
                if success:
                    logger.info(f"✅ 已加载 {len(langchain_messages)} 条历史消息到 {agent_name} 的 '{session_id}' session")
                    success_count += 1
                else:
                    logger.error(f"❌ 加载到 {agent_name} 的 '{session_id}' session 失败: {error}")

        elapsed = time.time() - start_time
        logger.info(f"⚡ 并行加载完成: {success_count}/{len(tasks)} 个session，耗时: {elapsed:.3f}秒")

        # 根据历史消息数量计算对话轮次（每个user-assistant对算一轮）
        # 计算用户消息的数量作为对话轮次
        user_message_count = sum(1 for msg in messages if msg.get("role") == "user")

        if user_message_count > 0:
            # 为所有已创建的 Retrieval Agent 设置对话轮次
            for doc_name in self.retrieval_agents.keys():
                self.conversation_turns[doc_name] = user_message_count
                logger.info(f"🔢 [LoadHistory] 设置文档 '{doc_name}' 的对话轮次为: {user_message_count}")

            # 如果当前是单文档模式，也为当前文档设置轮次（即使 Retrieval Agent 还未创建）
            if self.current_doc and self.current_doc not in self.conversation_turns:
                self.conversation_turns[self.current_doc] = user_message_count
                logger.info(f"🔢 [LoadHistory] 预设单文档模式文档 '{self.current_doc}' 的对话轮次为: {user_message_count}")

            # 如果是跨文档模式（manual），为所有选中的文档预设轮次
            if selected_docs:
                for doc_name in selected_docs:
                    if doc_name not in self.conversation_turns:
                        self.conversation_turns[doc_name] = user_message_count
                        logger.info(f"🔢 [LoadHistory] 预设跨文档模式文档 '{doc_name}' 的对话轮次为: {user_message_count}")

            logger.info(f"📊 [LoadHistory] 对话轮次统计: 共 {user_message_count} 轮对话已加载")

    def reset_history(self):
        """
        重置 LLM 历史（清空对话历史，并行处理）
        """
        logger.info("正在重置 LLM 对话历史...")

        # 并行清空所有需要的 session
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        start_time = time.time()

        def clear_session(agent_llm, session_id, agent_name=""):
            """清空单个session"""
            try:
                agent_llm.clear_session_history(session_id)
                return (session_id, agent_name, True, None)
            except Exception as e:
                logger.error(f"清空 {agent_name} session '{session_id}' 时出错: {e}")
                return (session_id, agent_name, False, str(e))

        # 准备所有需要清空的任务
        tasks = []

        # 1. Answer Agent 的 analyze_intent session
        tasks.append((self.llm, "analyze_intent", "Answer Agent"))

        # 2. 所有 Retrieval Agent 的 rewrite_query session
        for doc_name, retrieval_agent in self.retrieval_agents.items():
            tasks.append((retrieval_agent.llm, "rewrite_query", f"Retrieval Agent ({doc_name})"))

        # 使用线程池并行清空
        with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as executor:
            futures = {executor.submit(clear_session, llm, sid, name): (sid, name) for llm, sid, name in tasks}

            success_count = 0
            for future in as_completed(futures):
                session_id, agent_name, success, error = future.result()
                if success:
                    logger.info(f"✅ 已清空 {agent_name} 的 '{session_id}' session 历史")
                    success_count += 1
                else:
                    logger.error(f"❌ 清空 {agent_name} 的 '{session_id}' session 失败: {error}")

        elapsed = time.time() - start_time
        logger.info(f"✅ LLM 对话历史已重置: {success_count}/{len(tasks)} 个session，耗时: {elapsed:.3f}秒")

        # 重置对话轮次
        self.conversation_turns.clear()
        logger.info("🔄 已重置所有文档的对话轮次")

    # ==================== 状态持久化方法 ====================

    def create_or_update_state(
        self,
        user_query: str,
        current_doc: Optional[str] = None,
        manual_selected_docs: Optional[list] = None,
        needs_retrieval: bool = True
    ) -> AnswerState:
        """
        创建或更新状态（支持多轮对话）

        如果存在持久化状态，会保留以下信息：
        - selected_documents（跨文档模式的文档选择结果）
        - doc_specific_queries（为每个文档改写的查询）
        - retrieval_mode（检索模式）

        Args:
            user_query: 用户查询
            current_doc: 当前文档名（单文档模式）
            manual_selected_docs: 手动选择的文档列表（手动选择模式）
            needs_retrieval: 是否需要检索（默认 True，由 analyze_intent 节点决定）

        Returns:
            AnswerState: 新的或更新后的状态
        """
        # 创建基础状态
        new_state: AnswerState = {
            "user_query": user_query,
            "current_doc": current_doc,
            "needs_retrieval": needs_retrieval,
            "is_complete": False
        }

        # 如果有手动选择的文档，添加到状态
        if manual_selected_docs:
            new_state["manual_selected_docs"] = manual_selected_docs

        # 如果存在持久化状态，合并重要信息
        if self.persistent_state:
            logger.info("🔄 检测到持久化状态，保留以下信息:")

            # 保留文档选择结果（跨文档模式）
            if "selected_documents" in self.persistent_state:
                selected_docs = self.persistent_state["selected_documents"]
                # 只在模式相同时保留
                persistent_mode = self.persistent_state.get("retrieval_mode", "")
                current_mode = "cross_doc_manual" if manual_selected_docs else (
                    "single_doc" if current_doc else "cross_doc_auto"
                )

                if persistent_mode == current_mode:
                    new_state["selected_documents"] = selected_docs
                    logger.info(f"   - selected_documents: {len(selected_docs)} 个文档")

            # 保留文档改写查询（跨文档模式）
            if "doc_specific_queries" in self.persistent_state:
                new_state["doc_specific_queries"] = self.persistent_state["doc_specific_queries"]
                logger.info(f"   - doc_specific_queries: {len(new_state['doc_specific_queries'])} 个")

            # 保留检索模式
            if "retrieval_mode" in self.persistent_state:
                # 只在非手动选择模式时保留（手动选择每次都要重新设置）
                if not manual_selected_docs:
                    new_state["retrieval_mode"] = self.persistent_state["retrieval_mode"]
                    logger.info(f"   - retrieval_mode: {new_state['retrieval_mode']}")

        return new_state

    def save_state(self, state: AnswerState):
        """
        保存状态（供下一轮对话使用）

        保存以下信息：
        - selected_documents: 文档选择结果
        - doc_specific_queries: 文档改写查询
        - retrieval_mode: 检索模式
        - multi_doc_results: 多文档检索结果（可选）

        Args:
            state: 当前状态
        """
        # 创建持久化状态副本，只保留需要的字段
        self.persistent_state = {}

        # 保留文档选择结果
        if "selected_documents" in state:
            self.persistent_state["selected_documents"] = state["selected_documents"]

        # 保留文档改写查询
        if "doc_specific_queries" in state:
            self.persistent_state["doc_specific_queries"] = state["doc_specific_queries"]

        # 保留检索模式
        if "retrieval_mode" in state:
            self.persistent_state["retrieval_mode"] = state["retrieval_mode"]

        # 可选：保留多文档检索结果（如果需要）
        if "multi_doc_results" in state:
            self.persistent_state["multi_doc_results"] = state["multi_doc_results"]

        logger.debug(f"💾 已保存持久化状态: {list(self.persistent_state.keys())}")

    def clear_state(self):
        """
        清除持久化状态（切换模式或重置时使用）

        清除：
        - AnswerAgent 的 persistent_state（文档选择、查询改写等）
        - conversation_turns（对话轮次）
        - 所有 RetrievalAgent 的 persistent_state（检索历史）
        """
        # 清除 AnswerState 持久化状态
        self.persistent_state = None

        # 清除对话轮次
        self.conversation_turns.clear()

        # 清除所有 RetrievalAgent 的持久化状态
        for retrieval_agent in self.retrieval_agents.values():
            retrieval_agent.clear_state()

        logger.info("🗑️  已清除所有持久化状态（AnswerState + conversation_turns + RetrievalStates）")

    async def query(
        self,
        user_query: str,
        current_doc: Optional[str] = None,
        manual_selected_docs: Optional[list] = None,
        needs_retrieval: bool = True
    ) -> AnswerState:
        """
        执行查询（推荐使用此方法，自动管理状态）

        Args:
            user_query: 用户查询
            current_doc: 当前文档名（单文档模式）
            manual_selected_docs: 手动选择的文档列表（手动选择模式）
            needs_retrieval: 是否需要检索

        Returns:
            AnswerState: 执行结果
        """
        # 创建或更新状态
        state = self.create_or_update_state(
            user_query=user_query,
            current_doc=current_doc,
            manual_selected_docs=manual_selected_docs,
            needs_retrieval=needs_retrieval
        )

        # 执行查询
        result = await self.graph.ainvoke(state)

        # 保存状态
        self.save_state(result)

        return result
