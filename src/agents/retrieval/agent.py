"""
Retrieval Agent - 智能检索Agent

使用ReAct（Reasoning + Acting）模式进行智能检索
"""

from langgraph.graph import StateGraph, END
from typing import Dict, List, Any, Optional
import logging

from src.config.constants import ProcessingLimits

from ..base import AgentBase
from .state import RetrievalState
from .tools import RetrievalTools
from .nodes import RetrievalNodes
from .utils import RetrievalUtils

logger = logging.getLogger(__name__)


class RetrievalAgent(AgentBase):
    """
    检索Agent（ReAct模式）

    工作流程（循环）：
    1. initialize - 初始化环境
    2. rewrite - 查询优化（第2轮开始）
    3. think - 思考下一步使用哪个工具
    4. act - 执行工具调用
    5. summary - 累积并总结数据（可选）
    6. evaluate - 评估是否完成
    7. format - 生成最终精准答案

    支持：
    - 单文档检索：指定doc_name
    - 多文档检索：doc_name=None
    """

    def __init__(self, doc_name: str = None, provider: str = 'openai', progress_callback=None):
        super().__init__(name="RetrievalAgent", provider=provider)

        # 当前文档上下文
        self.current_doc = doc_name

        # 进度回调函数（用于实时上报处理进度）
        self.progress_callback = progress_callback

        # 初始化 VectorDBClient（复用实例，避免重复加载）
        self.vector_db_client = None

        # 检索缓存字典（提升性能，避免重复检索）
        self.retrieval_data_dict: Dict[str, Any] = {}

        # 当前对话轮次（由 initialize 节点从 state 同步，用于检索去重窗口）
        # None 表示尚未获知轮次，此时不会向向量库下发轮次
        self.current_conversation_turn = None

        # 内部对话轮次账本（{doc_name: turn_count}）
        # 仅在调用方未提供外部账本时使用（见 retrieve(conversation_turns=...)）
        self.conversation_turns: Dict[str, int] = {}

        # 持久化状态（跨多轮检索保留 ReAct 历史）
        # 保留：thoughts, actions, observations, retrieved_content 等
        # 用于：基于历史优化查询、避免重复检索
        self.persistent_state: Optional[RetrievalState] = None

        # 初始化功能模块（使用依赖注入）
        self.utils = RetrievalUtils(self)
        self.tools = RetrievalTools(self)
        self.nodes = RetrievalNodes(self)

        # 如果指定了文档，创建VectorDBClient
        if doc_name:
            self.vector_db_client = self.utils.create_vector_db_client(doc_name)

        # 构建workflow
        self.graph = self.build_graph()

    # ==================== Graph构建 ====================

    def build_graph(self) -> StateGraph:
        """构建ReAct workflow"""
        workflow = StateGraph(RetrievalState)

        # 添加节点
        workflow.add_node("initialize", self.nodes.initialize)
        workflow.add_node("rewrite", self.nodes.rewrite)
        workflow.add_node("think", self.nodes.think)
        workflow.add_node("act", self.nodes.act)
        workflow.add_node("summary", self.nodes.summary)
        workflow.add_node("evaluate", self.nodes.evaluate)
        workflow.add_node("format", self.nodes.format)

        # 添加边
        workflow.add_edge("initialize", "rewrite")
        workflow.add_edge("rewrite", "think")
        workflow.add_edge("think", "act")

        # 始终执行 summary 节点（负责数据累积，并根据需要生成总结）
        workflow.add_edge("act", "summary")
        workflow.add_edge("summary", "evaluate")

        # 条件边：根据评估结果决定继续或结束
        workflow.add_conditional_edges(
            "evaluate",
            self.nodes.should_continue,
            {
                "continue": "rewrite",
                "finish": "format"
            }
        )

        workflow.add_edge("format", END)

        # 设置入口
        workflow.set_entry_point("initialize")

        return workflow.compile()

    # ==================== 公开检索接口 ====================

    async def retrieve(
        self,
        query: str,
        *,
        doc_name: Optional[str] = None,
        rewritten_query: Optional[str] = None,
        max_iterations: Optional[int] = None,
        progress_callback=None,
        conversation_turns: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        执行一次检索（推荐的调用入口，替代外部手拼 state 调 graph.ainvoke）

        职责：
        - 构造完整的 RetrievalState 初始状态（含 ReAct 历史字段清零）
        - 计算 recursion_limit（max_iterations * 5 + 10）
        - 复用已编译的 graph（未编译时按 build_graph 懒加载）
        - 对话轮次记账：读取当前轮次并在检索成功后自增

        Args:
            query: 用户查询
            doc_name: 目标文档名；None 表示多文档模式
                （此时沿用实例自身的 current_doc 上下文，与图内 initialize 节点语义一致）
            rewritten_query: 预置的改写查询（可选）。图内 rewrite 节点会覆盖它，
                仅在需要给外部工具留痕时使用
            max_iterations: 最大迭代次数，默认 ProcessingLimits.MAX_RETRIEVAL_ITERATIONS
            progress_callback: 本次调用的进度回调（可选）。给定时临时覆盖实例的
                progress_callback，调用结束后恢复；并发复用自己的实例时以最后一次设置为准
            conversation_turns: 对话轮次账本 {doc_name: turn_count}（可选）。
                给定时（推荐，AnswerAgent.conversation_turns 即为此账本）在其上读轮次并自增，
                从而与 AnswerAgent.reset_history() / clear_all_retrieval_agents() 共享生命周期；
                未给定时退化为实例内部账本 self.conversation_turns

        Returns:
            {
                "final_summary": str,        # format 节点产出的最终摘要
                "retrieved_content": List,   # 检索到的内容块
                "selected_pages": List,      # format 节点选中的页码
                "is_complete": bool,         # 检索是否完成
                "error": Optional[str],      # 图内写入的 error（通常为空）
            }

        Raises:
            异常（graph 内部抛出、超过 recursion_limit 等）原样向上抛出，
            由调用方决定如何转成自己的错误结果；抛出时**不会**自增轮次。
        """
        if doc_name is None:
            doc_name = self.current_doc

        if max_iterations is None:
            max_iterations = ProcessingLimits.MAX_RETRIEVAL_ITERATIONS

        recursion_limit = max_iterations * 5 + 10
        turn_key = doc_name if doc_name is not None else "__multi_doc__"
        tag = doc_name or "多文档"

        ledger = conversation_turns if conversation_turns is not None else self.conversation_turns
        if turn_key not in ledger:
            ledger[turn_key] = 0
        current_turn = ledger[turn_key]
        logger.info(f"🔢 [RetrievalAgent|{tag}] 对话轮次: {current_turn}")

        initial_state: RetrievalState = {
            "query": query,
            "doc_name": doc_name,
            "max_iterations": max_iterations,
            "conversation_turn": current_turn,
            "current_iteration": 0,
            "is_complete": False,
            "thoughts": [],
            "actions": [],
            "observations": [],
            "retrieved_content": []
        }
        if rewritten_query is not None:
            initial_state["rewritten_query"] = rewritten_query

        previous_callback = self.progress_callback
        if progress_callback is not None:
            self.progress_callback = progress_callback

        try:
            if self.graph is None:
                self.graph = self.build_graph()

            logger.info(
                f"🚀 [RetrievalAgent|{tag}] 开始检索: {query[:50]}... "
                f"(max_iterations={max_iterations}, recursion_limit={recursion_limit})"
            )

            final_state = await self.graph.ainvoke(
                initial_state,
                config={"recursion_limit": recursion_limit}
            )
        except Exception as e:
            # 保持原有语义：异常交给调用方处理，且不计入轮次
            logger.error(f"❌ [RetrievalAgent|{tag}] 检索失败: {e}", exc_info=True)
            raise
        finally:
            self.progress_callback = previous_callback

        # 轮次记账：仅在检索成功后自增
        ledger[turn_key] = current_turn + 1
        logger.info(f"🔢 [RetrievalAgent|{tag}] 对话轮次递增至: {ledger[turn_key]}")

        return {
            "final_summary": final_state.get("final_summary", ""),
            "retrieved_content": final_state.get("retrieved_content", []),
            "selected_pages": final_state.get("selected_pages", []),
            "is_complete": final_state.get("is_complete", False),
            "error": final_state.get("error"),
        }
