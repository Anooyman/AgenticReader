"""
Indexing Agent状态定义
"""

from typing import TypedDict, Literal, Optional, List, Dict


class IndexingState(TypedDict, total=False):
    """
    Indexing Agent的状态

    工作流程：
    parse → chunk → summarize → tag → build_index → register
    """

    # ============ 输入 ============
    doc_name: str  # 文档名称
    doc_path: str  # 文档路径
    doc_type: Literal["pdf", "url"]  # 文档类型
    manual_tags: Optional[List[str]]  # 手动指定的标签

    # ============ 中间状态 ============
    raw_data: Optional[str]  # 原始提取的内容
    chunks: Optional[List[Dict]]  # 文本分块 [{"data": str, "page": str}, ...]
    brief_summary: Optional[str]  # 简要摘要
    detailed_summaries: Optional[Dict[str, str]]  # 详细摘要 {chapter: summary}
    auto_tags: Optional[List[str]]  # LLM自动生成的标签
    tags: Optional[List[str]]  # 最终标签（auto + manual）

    # ============ 输出 ============
    index_path: Optional[str]  # 索引存储路径
    doc_id: Optional[str]  # 文档ID
    status: str  # 当前状态：pending, parsed, chunked, summarized, tagged, indexed, completed
    error: Optional[str]  # 错误信息
