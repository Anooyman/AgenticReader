"""
Prompts configuration package.

This package contains all system prompts organized by functionality:
- reader_prompts.py: Prompts for document readers (PDF, Web) with ReaderRole constants
- agent_prompts.py: Prompts for multi-agent system with AgentType, ExecutorRole, MemoryRole constants

Usage:
    # Import specific prompts (recommended)
    from src.config.prompts.reader_prompts import READER_PROMPTS, ReaderRole
    from src.config.prompts.agent_prompts import AGENT_PROMPTS, AgentType

    # Or import from prompts package
    from src.config.prompts import SYSTEM_PROMPT_CONFIG, ReaderRole, AgentType
"""

from .reader_prompts import READER_PROMPTS, ReaderRole
from .agent_prompts import AGENT_PROMPTS, AgentType, ExecutorRole, MemoryRole

# Combine all prompts into a single dictionary for backward compatibility
SYSTEM_PROMPT_CONFIG = {
    **READER_PROMPTS,
    **AGENT_PROMPTS,
}

__all__ = [
    'SYSTEM_PROMPT_CONFIG',
    'READER_PROMPTS',
    'AGENT_PROMPTS',
    'ReaderRole',
    'AgentType',
    'ExecutorRole',
    'MemoryRole',
]
