"""
Answer Agent - 用户对话接口Agent

负责：
1. 分析用户意图
2. 决定是否需要检索
3. 调用Retrieval Agent获取上下文
4. 生成最终回答
"""

from langgraph.graph import StateGraph, END
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

    def __init__(self, doc_name: str = None):
        super().__init__(name="AnswerAgent")

        # 当前文档上下文
        self.current_doc = doc_name

        # 对话轮次追踪（用于传递给 Retrieval Agent）
        self.conversation_turn = 0

        # 延迟加载Retrieval Agent
        self.retrieval_agent = None

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

        工作流程：
        1. analyze - 分析意图
        2. retrieve (可选) - 调用检索
        3. generate - 生成回答
        """
        workflow = StateGraph(AnswerState)

        # 添加节点（委托给 nodes 模块）
        workflow.add_node("analyze", self.nodes.analyze_intent)
        workflow.add_node("retrieve", self.nodes.call_retrieval)
        workflow.add_node("generate", self.nodes.generate_answer)

        # 添加条件边：根据是否需要检索选择路径
        workflow.add_conditional_edges(
            "analyze",
            self.nodes.route_by_intent,
            {
                "retrieve": "retrieve",  # 需要检索
                "direct": "generate"  # 直接回答
            }
        )

        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)

        # 设置入口
        workflow.set_entry_point("analyze")

        return workflow.compile()
