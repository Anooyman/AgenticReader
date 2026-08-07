"""Adapter 注册表：source_type 字符串 -> adapter 实例。"""
from .ai_research import AIResearchAdapter
from .base import Chunk, SourceAdapter, UpdatePlan
from .webapp_chat import WebappChatAdapter

_REGISTRY = {
    AIResearchAdapter.source_type: AIResearchAdapter,
    WebappChatAdapter.source_type: WebappChatAdapter,
}


def get_adapter(source_type: str) -> SourceAdapter:
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(f"Unknown source type '{source_type}'. Available: {sorted(_REGISTRY)}")
    return cls()
