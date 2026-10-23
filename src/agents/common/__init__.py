"""
Common Agent Module

Contains common prompts and utilities shared across multiple agents.
"""

from .json_utils import PARSE_FAILED, parse_llm_json
from .progress import build_progress_payload, emit_progress
from .prompts import COMMON_PROMPTS, CommonRole
from .tool_response_format import (
    ToolResponse,
    create_content_response,
    create_metadata_response,
    create_structure_response,
)

__all__ = [
    'COMMON_PROMPTS',
    'CommonRole',
    'ToolResponse',
    'create_content_response',
    'create_metadata_response',
    'create_structure_response',
    'PARSE_FAILED',
    'parse_llm_json',
    'build_progress_payload',
    'emit_progress',
]
