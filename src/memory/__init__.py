"""AgenticReader 专属的长期记忆子系统（论文/文章摘要 + research chat 对话
历史），改自 LLM-Memory 项目，独立的 LanceDB 数据库（data/memory_db/），
不与 LLM-Memory 共享同一个库。

对外的两个主要入口：
    from src.memory.ingest import ingest_source
    from src.memory.search import agentic_search
"""
