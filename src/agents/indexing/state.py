"""
Indexing Agent状态定义
"""

from typing import TypedDict, Literal, Optional, List, Dict, Any


class IndexingState(TypedDict, total=False):
    """
    Indexing Agent的状态

    工作流程：
    parse → chunk → summarize → build_index → register
    """

    # ============ 输入 ============
    doc_name: str  # 文档名称
    doc_path: str  # 文档路径
    doc_type: Literal["pdf", "url"]  # 文档类型

    # ============ 中间状态 ============
    raw_data: Optional[str]  # 原始提取的内容
    pdf_data_list: Optional[List[Dict]]  # PDF每页原始数据 [{"page": str, "data": str}, ...]
    json_data_dict: Optional[Dict[str, str]]  # 页码为key的数据字典 {page: content}
    agenda_dict: Optional[Dict[str, List]]  # 文档目录结构 {title: [page_numbers]}
    has_toc: Optional[bool]  # 是否检测到目录结构

    # ============ 阶段缓存控制 ============
    stage_status: Optional[Dict[str, Dict[str, Any]]]  # 各阶段的缓存状态
    # {
    #     "parse": {"skip": bool, "files": List[str]},
    #     "extract_structure": {"skip": bool, "files": List[str]},
    #     "chunk_text": {"skip": bool, "files": List[str]},
    #     "process_chapters": {"skip": bool, "files": List[str]},
    #     "build_index": {"skip": bool, "files": List[str]},
    #     "generate_summary": {"skip": bool, "files": List[str]},
    # }

    # 章节处理
    agenda_data_list: Optional[List[Dict]]  # 章节数据列表 [{"title": str, "data": dict, "pages": list}, ...]
    chapter_summaries: Optional[Dict[str, str]]  # 章节摘要 {title: summary}
    chapter_refactors: Optional[Dict[str, str]]  # 章节重构内容 {title: refactor}
    raw_data_dict: Optional[Dict[str, Any]]  # 原始数据字典 {title: data}

    # 向量数据库文档
    vector_db_docs: Optional[List[Any]]  # 用于构建向量数据库的Document列表

    brief_summary: Optional[str]  # 简要摘要（基于所有章节摘要生成）

    # ============ 生成的文件追踪 ============
    generated_files: Optional[Dict[str, Any]]  # 生成的文件路径
    # {
    #     "images": List[str],      # PDF转图片文件列表
    #     "json_data": str,         # JSON数据文件路径
    #     "vector_db": str,         # 向量数据库路径
    #     "summaries": List[str],   # 摘要文件路径列表
    # }

    # ============ 输出 ============
    index_path: Optional[str]  # 索引存储路径
    doc_id: Optional[str]  # 文档ID
    status: str  # 当前状态：pending, parsed, chunked, summarized, indexed, completed
    is_complete: bool  # 是否完成整个索引流程
    error: Optional[str]  # 错误信息
