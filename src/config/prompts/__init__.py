"""
Prompts configuration package.

This package contains all system prompts organized by agent functionality:
- common_prompts.py: Common prompts used across multiple components
- indexing_prompts.py: Prompts for IndexingAgent (document parsing, extraction)
- retrieval_prompts.py: Prompts for RetrievalAgent (intelligent retrieval)
- answer_prompts.py: Prompts for AnswerAgent (intent analysis, conversational QA)
- agent_prompts.py: Prompts for multi-agent coordination (PlanAgent, ExecutorAgent, MemoryAgent)

Usage:
    # Import from specific modules
    from src.config.prompts.indexing_prompts import INDEXING_PROMPTS, IndexingRole
    from src.config.prompts.retrieval_prompts import RETRIEVAL_PROMPTS, RetrievalRole
    from src.config.prompts.answer_prompts import ANSWER_PROMPTS, AnswerRole
    from src.config.prompts.common_prompts import COMMON_PROMPTS, CommonRole
    from src.config.prompts.agent_prompts import AGENT_PROMPTS, AgentType
"""

# Import from modular structure
from .common_prompts import COMMON_PROMPTS, CommonRole
from .indexing_prompts import INDEXING_PROMPTS, IndexingRole
from .retrieval_prompts import RETRIEVAL_PROMPTS, RetrievalRole
from .answer_prompts import ANSWER_PROMPTS, AnswerRole
from .agent_prompts import AGENT_PROMPTS, AgentType, ExecutorRole, MemoryRole

# Combine all prompts into a single dictionary
SYSTEM_PROMPT_CONFIG = {
    **COMMON_PROMPTS,
    **INDEXING_PROMPTS,
    **RETRIEVAL_PROMPTS,
    **ANSWER_PROMPTS,
    **AGENT_PROMPTS,
}

__all__ = [
    # Unified config
    'SYSTEM_PROMPT_CONFIG',

    # Modular prompts
    'COMMON_PROMPTS',
    'INDEXING_PROMPTS',
    'RETRIEVAL_PROMPTS',
    'ANSWER_PROMPTS',
    'AGENT_PROMPTS',

    # Role classes
    'CommonRole',
    'IndexingRole',
    'RetrievalRole',
    'AnswerRole',
    'AgentType',
    'ExecutorRole',
    'MemoryRole',
]
