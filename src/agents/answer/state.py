"""
Answer Agent状态定义
"""

from typing import TypedDict, Optional, List, Dict, Any


class AnswerState(TypedDict, total=False):
    """
    Answer Agent的状态

    支持三种模式：
    1. 单文档模式：current_doc 指定 → retrieve_single
    2. 跨文档自动选择模式：current_doc=None, manual_selected_docs=None → select_docs → retrieve_multi → synthesize
    3. 跨文档手动选择模式：manual_selected_docs 指定 → retrieve_multi → synthesize

    工作流程：
    analyze_intent → (direct / single_doc / cross_doc_auto / cross_doc_manual) → generate_answer
    """

    # ============ 输入 ============
    user_query: str  # 用户查询
    current_doc: Optional[str]  # 当前文档名（None=跨文档模式）
    conversation_history: Optional[List[Dict]]  # 对话历史
    manual_selected_docs: Optional[List[str]]  # 手动选择的文档名列表（用于手动选择模式）

    # ============ 模式标识 ============
    retrieval_mode: str  # "single_doc" | "cross_doc_auto" | "cross_doc_manual"

    # ============ 单文档模式字段 ============
    needs_retrieval: bool  # 是否需要检索
    analysis_reason: Optional[str]  # 意图分析的理由
    context: Optional[str]  # 检索到的上下文（单文档）

    # ============ 跨文档模式字段 ============
    selected_documents: List[Dict[str, Any]]  # DocumentSelector返回的文档列表
    doc_specific_queries: Dict[str, str]  # 每个文档的针对性改写查询 {doc_name: rewritten_query}
    multi_doc_results: Dict[str, Any]  # 并行检索结果 {doc_name: result}

    # ============ 输出 ============
    final_answer: str  # 最终回答
    is_complete: bool  # 是否完成
