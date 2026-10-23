"""
Answer Agent状态定义

确定性工具架构：rewrite_query → plan → execute → generate
用户通过 enabled_tools 和 selected_docs 控制工具使用。
"""

from typing import TypedDict, Optional, List, Dict, Any


class AnswerState(TypedDict, total=False):
    """
    Answer Agent的状态（确定性工具架构 / 单轮流水线）

    工作流程：
    rewrite_query → plan → (execute → generate | generate) → END

    工具选择由用户控制：
    - enabled_tools: 用户启用的工具列表（空=纯对话）
    - selected_docs: 用户选择的文档列表（PDF检索时使用）
    - rewrite_query节点根据历史对话重写用户查询（补全上下文）
    - plan节点根据用户选择确定性地构造工具调用，仅做寒暄过滤
    - 单轮架构：execute 之后直接进入 generate，不再回环到 plan

    说明：
    - current_iteration / max_iterations 字段保留以兼容旧代码引用，
      当前单轮架构下不再驱动多轮规划（无回环边）。
    """

    # ============ 输入 ============
    user_query: str  # 用户原始查询
    rewritten_query: str  # LLM改写后的查询（补全上下文）
    enabled_tools: List[str]  # 用户启用的工具 ["retrieve_documents", "search_web"]
    selected_docs: Optional[List[str]]  # 用户选择的文档列表（PDF检索时）

    # ============ 工具调用记录 ============
    tool_calls: List[Dict[str, Any]]  # 所有工具调用记录 [{tool, args, iteration}, ...]
    tool_results: List[Dict[str, Any]]  # 所有工具返回结果 [{tool, args, result, success}, ...]
    current_iteration: int  # 工具执行批次计数（保留字段；单轮架构下最多 +1）
    max_iterations: int  # 保留字段，当前无实际多轮驱动逻辑

    # ============ 输出 ============
    final_answer: str  # 最终回答
    is_complete: bool  # 是否完成
    error: Optional[str]  # 错误信息
