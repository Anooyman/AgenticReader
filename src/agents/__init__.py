"""
Agent系统

基于LangGraph的多Agent架构：
- AnswerAgent: 用户对话接口
- RetrievalAgent: 智能检索
- IndexingAgent: 文档索引构建

工具方法直接在各Agent类中实现，通过config/tools/配置文件管理

使用：
    from src.agents import AnswerAgent, RetrievalAgent, IndexingAgent
"""

# 导入Agent基类和具体Agent
from .base import AgentBase
from .answer import AnswerAgent, AnswerState
from .retrieval import RetrievalAgent, RetrievalState
from .indexing import IndexingAgent, IndexingState, DocumentRegistry

__all__ = [
    # 基类
    "AgentBase",
    # Answer Agent
    "AnswerAgent",
    "AnswerState",
    # Retrieval Agent
    "RetrievalAgent",
    "RetrievalState",
    # Indexing Agent
    "IndexingAgent",
    "IndexingState",
    "DocumentRegistry",
]
