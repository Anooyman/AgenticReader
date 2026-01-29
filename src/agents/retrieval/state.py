"""
Retrieval Agent状态定义
"""

from typing import TypedDict, Optional, List, Dict, Any


class RetrievalState(TypedDict, total=False):
    """
    Retrieval Agent的状态（ReAct模式）

    工作流程（ReAct Loop）：
    think → act → observe → evaluate → (continue/finish)
    """

    # ============ 输入 ============
    query: str  # 用户原始查询
    rewritten_query: Optional[str]  # 基于历史优化后的查询
    doc_name: Optional[str]  # 指定文档名（None=多文档检索）
    max_iterations: int  # 最大迭代次数
    conversation_turn: int  # 对话轮次（用于判断是否需要 rewrite）

    # ============ ReAct Loop 状态 ============
    thoughts: List[str]  # 思考过程
    actions: List[Dict]  # 执行的动作 [{"tool": str, "params": dict}, ...]
    observations: List[str]  # 观察结果
    current_iteration: int  # 当前迭代次数（内部轮数，用于ReAct循环控制和query重写判断）

    # ============ 当前步骤 ============
    current_tool: Optional[str]  # 当前选择的工具
    action_input: Optional[str]  # think 节点输出的原始输入（字符串）
    current_params: Optional[Dict]  # act 节点构建的工具参数（用于记录）
    last_result: Optional[Any]  # 上一步的结果

    # ============ 输出 ============
    retrieved_content: List[Dict]  # 检索到的内容列表 [{"content": str, "title": str, "pages": List}, ...]
    formatted_data: List[Dict]  # 格式化的原始数据 [{"index": int, "title": str, "pages": List, "content": str}, ...]
    intermediate_summary: str  # 中间总结（循环内，每次检索后生成）
    reason: str  # evaluate 的评估原因
    final_summary: str  # 最终精准总结（format 节点生成）
    selected_pages: List  # format 节点选择的页码
    is_complete: bool  # 是否完成检索
