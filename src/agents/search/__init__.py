"""
SearchAgent - 网络搜索与URL内容分析Agent

支持两种主要使用场景：
1. 搜索引擎检索：通过搜索引擎获取最新信息
2. 指定URL分析：分析特定网页内容，支持智能索引决策
"""

from .agent import SearchAgent
from .state import SearchState

__all__ = ["SearchAgent", "SearchState"]
