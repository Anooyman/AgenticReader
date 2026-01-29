"""
Parallel Processing Module

并行处理核心模块，提供索引和检索阶段的并行处理功能。

主要组件：
- indexing: 索引阶段的并行处理（ChapterProcessor, PageExtractor）
- retrieval: 检索阶段的并行处理（ParallelRetrievalCoordinator）

使用示例：
    # 索引阶段
    from src.core.parallel import ChapterProcessor, PageExtractor

    processor = ChapterProcessor(llm_client, max_concurrent=5)
    results = await processor.process_chapters_summary_and_refactor(chapters)

    # 检索阶段
    from src.core.parallel import ParallelRetrievalCoordinator

    coordinator = ParallelRetrievalCoordinator(answer_agent)
    results = await coordinator.retrieve_from_multiple_docs(query, doc_list)
"""

from .indexing import (
    ChapterProcessor,
    PageExtractor,
    run_parallel_chapter_processing,
    run_parallel_detail_summaries,
    run_parallel_page_extraction,
)
from .retrieval import ParallelRetrievalCoordinator

__all__ = [
    # 索引并行处理
    'ChapterProcessor',
    'PageExtractor',
    'run_parallel_chapter_processing',
    'run_parallel_detail_summaries',
    'run_parallel_page_extraction',
    # 检索并行处理
    'ParallelRetrievalCoordinator',
]

__version__ = '1.0.0'
__author__ = 'AgenticReader Team'
