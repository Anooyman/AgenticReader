"""
LLM Core Module - Unified LLM provider interface and message history management

This module provides:
- LLMBase: Main client for managing LLM conversations
- LimitedChatMessageHistory: Smart message history with truncation and LLM summarization
- Provider classes: Azure, OpenAI, and Ollama implementations
- Embedding utilities: get_embeddings() function

Module Structure:
    - client.py: Main LLMBase class and embeddings utilities
    - history.py: Message history management
    - providers.py: Provider implementations (Azure, OpenAI, Ollama)
"""

# Import from submodules for backward compatibility
from src.core.llm.client import LLMBase, get_embeddings
from src.core.llm.history import LimitedChatMessageHistory
from src.core.llm.providers import (
    LLMProviderBase,
    AzureLLMProvider,
    OpenAILLMProvider,
    OllamaLLMProvider
)

__all__ = [
    # Main classes
    'LLMBase',
    'LimitedChatMessageHistory',

    # Providers
    'LLMProviderBase',
    'AzureLLMProvider',
    'OpenAILLMProvider',
    'OllamaLLMProvider',

    # Utilities
    'get_embeddings',
]
