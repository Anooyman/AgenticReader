"""
Answer Agent状态定义

工具调用架构：plan → execute → evaluate → (循环或结束) → generate
用户通过 enabled_tools 和 selected_docs 控制工具使用。
"""

from typing import TypedDict, Optional, List, Dict, Any


class AnswerState(TypedDict, total=False):
    """
    Answer Agent的状态（工具调用架构）

    工作流程：
    plan → execute_tools → evaluate → (continue → plan / finish → generate) → END

    工具选择由用户控制：
    - enabled_tools: 用户启用的工具列表（空=纯对话）
    - selected_docs: 用户选择的文档列表（PDF检索时使用）
    plan节点根据用户选择确定性地构造工具调用，仅做寒暄过滤。
    """

    # ============ 输入 ============
    user_query: str  # 用户查询
    enabled_tools: List[str]  # 用户启用的工具 ["retrieve_documents", "search_web"]
    selected_docs: Optional[List[str]]  # 用户选择的文档列表（PDF检索时）

    # ============ ReAct循环 ============
    thoughts: List[str]  # 推理过程记录
    tool_calls: List[Dict[str, Any]]  # 所有工具调用记录 [{tool, args, iteration}, ...]
    tool_results: List[Dict[str, Any]]  # 所有工具返回结果 [{tool, args, result, success}, ...]
    current_iteration: int  # 当前迭代轮次
    max_iterations: int  # 最大迭代次数（默认3）

    # ============ 输出 ============
    final_answer: str  # 最终回答
    is_complete: bool  # 是否完成
    error: Optional[str]  # 错误信息
