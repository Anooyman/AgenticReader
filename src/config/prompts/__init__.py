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

# Import all agent prompts for unified access
from src.agents.common.prompts import COMMON_PROMPTS
from src.agents.indexing.prompts import INDEXING_PROMPTS
from src.agents.retrieval.prompts import RETRIEVAL_PROMPTS
from src.agents.answer.prompts import ANSWER_PROMPTS
from .metadata_prompts import METADATA_PROMPTS  # Metadata extraction prompts

# Create unified SYSTEM_PROMPT_CONFIG for backward compatibility
# This combines all prompts from different agents into a single dictionary
SYSTEM_PROMPT_CONFIG = {
    **COMMON_PROMPTS,      # Common prompts used across agents
    **INDEXING_PROMPTS,    # IndexingAgent prompts
    **RETRIEVAL_PROMPTS,   # RetrievalAgent prompts
    **ANSWER_PROMPTS,      # AnswerAgent prompts
    **METADATA_PROMPTS,    # Metadata extraction prompts
}

__all__ = [
    # Unified prompt config (backward compatibility)
    'SYSTEM_PROMPT_CONFIG',
]
