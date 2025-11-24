"""
Base provider handler interface for vendor-specific LLM behavior.

This module defines the abstract base class for provider-specific handlers
that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class BaseProviderHandler(ABC):
    """
    Abstract base class for provider-specific LLM handlers.

    Each vendor (Claude, OpenAI, Gemini, etc.) can have its own handler
    that customizes request preparation, system prompt formatting, and
    response parsing to work optimally with that vendor's API.

    Handler Selection:
        The ProviderHandlerRegistry selects handlers based on the 'vendor'
        field from the LLM provider registration (extracted via LiteLLM).

    Extensibility:
        New handlers can be added by:
        1. Subclassing BaseProviderHandler
        2. Implementing required methods
        3. Registering in ProviderHandlerRegistry
        4. Optionally: Adding as Python entry point for auto-discovery
    """

    def __init__(self, vendor: str):
        """
        Initialize provider handler.

        Args:
            vendor: Vendor name (e.g., "anthropic", "openai", "google")
        """
        self.vendor = vendor

    @abstractmethod
    def prepare_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        output_type: type[BaseModel],
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Prepare vendor-specific request parameters.

        This method allows customization of the request sent to the LLM provider.
        For example:
        - OpenAI: Add response_format parameter for structured output
        - Claude: Use native tool calling format
        - Gemini: Add generation config

        Args:
            messages: List of message dicts (role, content)
            tools: Optional list of tool schemas (OpenAI format)
            output_type: Pydantic model for expected response
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters to pass to litellm.completion()
            Must include at minimum: messages, tools (if provided)
            May include vendor-specific params like response_format, temperature, etc.
        """
        pass

    @abstractmethod
    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[List[Dict[str, Any]]],
        output_type: type[BaseModel]
    ) -> str:
        """
        Format system prompt for vendor-specific requirements.

        Different vendors have different best practices for system prompts:
        - Claude: Prefers detailed instructions, handles XML well
        - OpenAI: Structured output mode makes JSON instructions optional
        - Gemini: System instructions separate from messages

        Args:
            base_prompt: Base system prompt (from template or config)
            tool_schemas: Optional list of tool schemas (if tools available)
            output_type: Pydantic model for response validation

        Returns:
            Formatted system prompt string optimized for this vendor
        """
        pass

    def get_vendor_capabilities(self) -> Dict[str, bool]:
        """
        Return vendor-specific capability flags.

        Override this to indicate which features the vendor supports:
        - native_tool_calling: Vendor has native function calling
        - structured_output: Vendor supports structured output (response_format)
        - streaming: Vendor supports streaming responses
        - vision: Vendor supports image inputs
        - json_mode: Vendor has JSON response mode

        Returns:
            Dictionary of capability flags
        """
        return {
            "native_tool_calling": True,
            "structured_output": False,
            "streaming": False,
            "vision": False,
            "json_mode": False,
        }

    def __repr__(self) -> str:
        """String representation of handler."""
        return f"{self.__class__.__name__}(vendor='{self.vendor}')"
