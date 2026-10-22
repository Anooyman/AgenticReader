"""
Prompts configuration package.

All agent prompts live in their respective agent directories:
- Common prompts: src/agents/common/prompts.py
- IndexingAgent prompts: src/agents/indexing/prompts.py
- RetrievalAgent prompts: src/agents/retrieval/prompts.py
- AnswerAgent prompts: src/agents/answer/prompts.py

Usage:
    # Import agent prompts directly from agents
    from src.agents.common.prompts import COMMON_PROMPTS, CommonRole
    from src.agents.indexing.prompts import INDEXING_PROMPTS, IndexingRole
    from src.agents.retrieval.prompts import RETRIEVAL_PROMPTS, RetrievalRole
    from src.agents.answer.prompts import ANSWER_PROMPTS, AnswerRole

    # Import unified SYSTEM_PROMPT_CONFIG for backward compatibility
    from src.config.prompts import SYSTEM_PROMPT_CONFIG
"""

# Metadata extraction prompts (本包内模块，不依赖 agents)
from .metadata_prompts import METADATA_PROMPTS

# SYSTEM_PROMPT_CONFIG 采用惰性构建：本模块 import 期不再 import 任何 agent prompts，
# 从而断开 config -> agents 的模块级 import 边（agent prompts 会拉起完整 agent 图，
# 包括 langgraph）。首次访问 SYSTEM_PROMPT_CONFIG 时才组装，结果缓存复用，
# 语义与原先的模块级 dict 一致（同一个对象、内容相同）。
_SYSTEM_PROMPT_CONFIG = None


def _build_system_prompt_config() -> dict:
    """首次访问时聚合各 agent 的 prompts（延迟 import）"""
    global _SYSTEM_PROMPT_CONFIG
    if _SYSTEM_PROMPT_CONFIG is None:
        from src.agents.common.prompts import COMMON_PROMPTS
        from src.agents.indexing.prompts import INDEXING_PROMPTS
        from src.agents.retrieval.prompts import RETRIEVAL_PROMPTS
        from src.agents.answer.prompts import ANSWER_PROMPTS
        _SYSTEM_PROMPT_CONFIG = {
            **COMMON_PROMPTS,      # Common prompts used across agents
            **INDEXING_PROMPTS,    # IndexingAgent prompts
            **RETRIEVAL_PROMPTS,   # RetrievalAgent prompts
            **ANSWER_PROMPTS,      # AnswerAgent prompts
            **METADATA_PROMPTS,    # Metadata extraction prompts
        }
    return _SYSTEM_PROMPT_CONFIG


def __getattr__(name: str):
    """模块级属性钩子：保持 from src.config.prompts import SYSTEM_PROMPT_CONFIG 可用"""
    if name == 'SYSTEM_PROMPT_CONFIG':
        return _build_system_prompt_config()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Unified prompt config (backward compatibility)
    'SYSTEM_PROMPT_CONFIG',
]
