"""
Answer Agent状态定义
"""

from typing import TypedDict, Optional, List, Dict


class AnswerState(TypedDict, total=False):
    """
    Answer Agent的状态

    工作流程：
    analyze_intent → (retrieve/direct) → generate_answer
    """

    # ============ 输入 ============
    user_query: str  # 用户查询
    current_doc: Optional[str]  # 当前文档名（None=多文档模式）
    conversation_history: Optional[List[Dict]]  # 对话历史

    # ============ 中间状态 ============
    needs_retrieval: bool  # 是否需要检索
    analysis_reason: Optional[str]  # 意图分析的理由
    context: Optional[str]  # 检索到的上下文

    # ============ 输出 ============
    final_answer: str  # 最终回答
    is_complete: bool  # 是否完成
