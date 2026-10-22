"""
Retrieval Agent - 智能检索Agent

使用ReAct（Reasoning + Acting）模式进行智能检索
"""

from langgraph.graph import StateGraph, END
from typing import Dict, List, Any, Optional
import logging

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

    # ==================== 状态持久化管理 ====================

    def clear_state(self):
        """
        清除持久化状态

        清除所有历史信息：
        - thoughts, actions, observations
        - retrieved_content
        - 等等
        """
        self.persistent_state = None
        logger.info(f"🗑️  [{self.current_doc or 'MultiDoc'}] 已清除 RetrievalAgent 持久化状态")
