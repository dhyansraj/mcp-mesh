"""
Provider-specific handlers for LLM vendors.

This package provides vendor-specific customization for different LLM providers
(Claude, OpenAI, Gemini, etc.) to optimize API calls and response handling.
"""

from .base_provider_handler import (
    BASE_TOOL_INSTRUCTIONS,
    CLAUDE_ANTI_XML_INSTRUCTION,
    BaseProviderHandler,
    is_simple_schema,
    make_schema_strict,
)
from .claude_handler import ClaudeHandler
from .gemini_handler import GeminiHandler
from .generic_handler import GenericHandler
from .openai_handler import OpenAIHandler
from .provider_handler_registry import ProviderHandlerRegistry

__all__ = [
    # Constants
    "BASE_TOOL_INSTRUCTIONS",
    "CLAUDE_ANTI_XML_INSTRUCTION",
    # Utilities
    "is_simple_schema",
    "make_schema_strict",
    # Handlers
    "BaseProviderHandler",
    "ClaudeHandler",
    "GeminiHandler",
    "OpenAIHandler",
    "GenericHandler",
    "ProviderHandlerRegistry",
]
