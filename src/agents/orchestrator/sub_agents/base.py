"""SubAgent 接口——Orchestrator 调用的两个工具（deep_dive_document /
search_memory）都实现这个接口。改自 ai-research-pipeline 的
webapp/agents/base.py，去掉了 subprocess 相关的内容（合并进 AgenticReader
后两者都是同进程直接调用）。
"""
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional

ProgressCallback = Optional[Callable[[str, str], Awaitable[None]]]


class SubAgent(ABC):
    """Orchestrator 可调用的子 agent。"""

    name: str = "base"

    @abstractmethod
    def tool_schema(self) -> Dict[str, Any]:
        """OpenAI/LangChain 兼容的 function-calling 工具定义。"""

    @abstractmethod
    async def invoke(self, on_progress: ProgressCallback = None, **kwargs) -> Dict[str, Any]:
        """执行一次调用，返回结构化结果字典。约定：任何失败都返回
        {"error": ...} 而不是抛异常——调用方（Orchestrator）的 LLM 需要
        看到失败本身作为一次正常的工具结果，而不是让整个循环崩掉。"""
