"""
SearchAgent 状态定义

支持两种 Use Case：
1. 搜索引擎检索模式 (search)
2. URL内容分析模式 (url_analysis)
"""

from typing import TypedDict, Optional, List, Dict, Any


class SearchState(TypedDict, total=False):
    """
    SearchAgent 的状态定义

    双模式工作流：
    - search: 搜索引擎检索 → URL筛选 → 内容爬取 → 汇总答案
    - url_analysis: 指定URL爬取 → 内容量判断 → 索引/直接对话
    """

    # ============ 输入参数 ============
    query: str  # 用户查询/问题
    use_case: str  # 使用场景："search" 或 "url_analysis"
    target_urls: Optional[List[str]]  # Use Case 2: 用户指定的URL列表
    max_iterations: int  # 最大迭代次数（默认3）

    # ============ Use Case 判断 ============
    detected_use_case: str  # Agent自动判断的use case
    use_case_reason: str  # 判断理由

    # ============ Use Case 1: 搜索引擎检索 ============
    search_query: str  # 优化后的搜索查询
    search_engine_results: List[Dict]  # 搜索引擎返回的结果
    # 格式: [{"title": str, "url": str, "snippet": str}, ...]
    selected_urls: List[str]  # LLM筛选后的相关URL（用于爬取）
    selection_reason: str  # URL筛选理由

    # ============ Use Case 2: URL内容分析 ============
    content_size: int  # 提取内容的总字符数
    processing_strategy: str  # 处理策略: "direct_chat" 或 "index_then_chat"
    strategy_reason: str  # 策略选择理由
    should_call_indexing: bool  # 是否需要调用 IndexingAgent
    indexing_result: Optional[Dict]  # IndexingAgent 的返回结果
    web_content_json: Optional[str]  # 保存的 JSON 文件路径（data/web_content/）
    generated_doc_name: Optional[str]  # 生成的文档名（用于 IndexingAgent）

    # ============ 爬取过程 ============
    scraping_tasks: List[Dict]  # 待爬取的任务列表
    # 格式: [{"url": str, "content_types": List[str]}, ...]
    scraped_results: List[Dict]  # 爬取结果
    # 格式: [{"url": str, "success": bool, "content": {...}, "files": [...], "error": str}, ...]

    # ============ 内容提取 ============
    extracted_content: List[Dict]  # 提取的内容片段
    # 格式: [{"url": str, "title": str, "text": str, "html": str, "json": dict}, ...]
    merged_text: str  # 合并后的文本内容（用于直接对话）

    # ============ ReAct Loop（可选，用于复杂场景）============
    thoughts: List[str]  # 思考过程
    actions: List[Dict]  # 执行的动作
    observations: List[str]  # 观察结果
    current_iteration: int  # 当前迭代次数

    # ============ 当前步骤状态 ============
    current_tool: Optional[str]  # 当前使用的工具
    current_params: Optional[Dict]  # 当前工具参数
    last_result: Optional[Any]  # 上一步的结果

    # ============ 输出 ============
    final_answer: str  # 最终答案
    sources: List[str]  # 信息来源URL列表
    is_complete: bool  # 是否完成

    # ============ 错误处理 ============
    error: Optional[str]  # 错误信息
    warnings: List[str]  # 警告信息列表
