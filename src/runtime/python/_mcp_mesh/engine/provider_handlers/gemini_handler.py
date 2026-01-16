"""
Gemini/Google provider handler.

Optimized for Gemini models (Gemini 2.0 Flash, Gemini 1.5 Pro, etc.)
using Google's best practices for tool calling and structured output.

Features:
- Native structured output via response_format (similar to OpenAI)
- Native function calling support
- Support for Gemini 2.x and 3.x models
- Large context windows (up to 2M tokens)

Reference:
- https://docs.litellm.ai/docs/providers/gemini
- https://ai.google.dev/gemini-api/docs
"""

import logging
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BASE_TOOL_INSTRUCTIONS,
    BaseProviderHandler,
    make_schema_strict,
)

logger = logging.getLogger(__name__)


class GeminiHandler(BaseProviderHandler):
    """
    Provider handler for Google Gemini models.

    Gemini Characteristics:
    - Native structured output via response_format parameter (LiteLLM translates)
    - Native function calling support
    - Large context windows (1M-2M tokens)
    - Multimodal support (text, images, video, audio)
    - Works well with concise, focused prompts

    Key Similarities with OpenAI:
    - Uses response_format for structured output (via LiteLLM translation)
    - Native function calling format
    - Similar schema enforcement requirements

    Supported Models (via LiteLLM):
    - gemini/gemini-2.0-flash (fast, efficient)
    - gemini/gemini-2.0-flash-lite (fastest, most efficient)
    - gemini/gemini-1.5-pro (high capability)
    - gemini/gemini-1.5-flash (balanced)
    - gemini/gemini-3-flash-preview (reasoning support)
    - gemini/gemini-3-pro-preview (advanced reasoning)

    Reference:
    https://docs.litellm.ai/docs/providers/gemini
    """

    def __init__(self):
        """Initialize Gemini handler."""
        super().__init__(vendor="gemini")

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        output_type: type,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request parameters for Gemini API via LiteLLM.

        Gemini Strategy:
        - Use response_format parameter for structured JSON output
        - LiteLLM handles translation to Gemini's native format
        - Skip structured output for str return types (text mode)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Return type (str or Pydantic model)
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters for litellm.completion()
        """
        # Build base request
        request_params = {
            "messages": messages,
            **kwargs,  # Pass through temperature, max_tokens, etc.
        }

        # Add tools if provided
        # LiteLLM will convert OpenAI tool format to Gemini's function_declarations
        if tools:
            request_params["tools"] = tools

        # Skip structured output for str return type (text mode)
        if output_type is str:
            return request_params

        # Only add response_format for Pydantic models
        if not (isinstance(output_type, type) and issubclass(output_type, BaseModel)):
            return request_params

        # Add response_format for structured output
        # LiteLLM translates this to Gemini's native format
        schema = output_type.model_json_schema()

        # Transform schema for strict mode compliance
        # Gemini requires additionalProperties: false and all properties in required
        schema = make_schema_strict(schema, add_all_required=True)

        # Gemini structured output format (via LiteLLM)
        request_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_type.__name__,
                "schema": schema,
                "strict": True,  # Enforce schema compliance
            },
        }

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[list[dict[str, Any]]],
        output_type: type,
    ) -> str:
        """
        Format system prompt for Gemini (concise approach).

        Gemini Strategy:
        1. Use base prompt as-is
        2. Add tool calling instructions if tools present
        3. Minimal JSON instructions (response_format handles structure)
        4. Keep prompt concise - Gemini works well with clear, direct prompts

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt optimized for Gemini
        """
        system_content = base_prompt

        # Add tool calling instructions if tools available
        if tool_schemas:
            system_content += BASE_TOOL_INSTRUCTIONS

        # Skip JSON note for str return type (text mode)
        if output_type is str:
            return system_content

        # Add brief JSON note (response_format handles enforcement)
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            system_content += f"\n\nYour final response will be structured as JSON matching the {output_type.__name__} format."

        return system_content

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return Gemini-specific capabilities.

        Returns:
            Capability flags for Gemini
        """
        return {
            "native_tool_calling": True,  # Gemini has native function calling
            "structured_output": True,  # Supports structured output via response_format
            "streaming": True,  # Supports streaming
            "vision": True,  # Gemini supports multimodal (images, video, audio)
            "json_mode": True,  # Native JSON mode via response_format
            "large_context": True,  # Up to 2M tokens context window
        }

