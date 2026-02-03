"""
Gemini/Google provider handler.

Optimized for Gemini models (Gemini 2.0 Flash, Gemini 1.5 Pro, etc.)
using Google's best practices for tool calling and structured output.

Features:
- Prompt-based JSON hints for structured output (NOT response_format)
- Native function calling support
- Support for Gemini 2.x and 3.x models
- Large context windows (up to 2M tokens)

Note:
- Gemini 2.0 Flash + tools + response_format causes infinite tool loops
- We use prompt-based hints instead of response_format when tools are involved

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
    sanitize_schema_for_structured_output,
)

logger = logging.getLogger(__name__)


class GeminiHandler(BaseProviderHandler):
    """
    Provider handler for Google Gemini models.

    Gemini Characteristics:
    - Prompt-based JSON hints for structured output (NOT response_format)
    - Native function calling support
    - Large context windows (1M-2M tokens)
    - Multimodal support (text, images, video, audio)
    - Works well with concise, focused prompts

    Important:
    - Gemini 2.0 Flash + tools + response_format causes the model to keep calling tools
    - We use prompt-based hints instead of response_format when tools are involved

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
        # Store output schema for use in format_system_prompt (set by apply_structured_output)
        self._pending_output_schema: dict[str, Any] | None = None
        self._pending_output_type_name: str | None = None

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        output_type: type,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request parameters for Gemini API via LiteLLM.

        Gemini Strategy:
        - Do NOT use response_format (causes infinite tool loops with Gemini 2.0)
        - Store schema for prompt-based hints in format_system_prompt
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
            self._pending_output_schema = None
            self._pending_output_type_name = None
            return request_params

        # Only store schema for Pydantic models (used in format_system_prompt)
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
            # Sanitize schema to remove unsupported validation keywords
            self._pending_output_schema = sanitize_schema_for_structured_output(schema)
            self._pending_output_type_name = output_type.__name__
            logger.debug(
                "Gemini: Stored output schema for prompt-based hints (not using response_format)"
            )
        else:
            self._pending_output_schema = None
            self._pending_output_type_name = None

        # NOTE: We do NOT add response_format here!
        # Gemini 2.0 Flash + tools + response_format causes infinite tool loops.
        # Structured output is handled via prompt-based hints in format_system_prompt().

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: list[dict[str, Any]] | None,
        output_type: type,
    ) -> str:
        """
        Format system prompt for Gemini with prompt-based JSON hints.

        Gemini Strategy:
        1. Use base prompt as-is
        2. Add tool calling instructions if tools present
        3. Add detailed JSON output instructions with example structure
        4. Use prompt-based hints (NOT response_format) to avoid tool loops

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

        # Get the output schema (may have been set by apply_structured_output or prepare_request)
        # Check pending schema FIRST - it may be set even when output_type is str (delegate path)
        output_schema = self._pending_output_schema
        output_type_name = self._pending_output_type_name

        # Fall back to output_type if no pending schema AND output_type is Pydantic model
        if output_schema is None:
            if output_type is str:
                # No schema and str return type - skip JSON instructions
                return system_content
            elif isinstance(output_type, type) and issubclass(output_type, BaseModel):
                output_schema = sanitize_schema_for_structured_output(
                    output_type.model_json_schema()
                )
                output_type_name = output_type.__name__

        # Add detailed JSON output instructions (like Java handler)
        if output_schema is not None:
            system_content += "\n\nOUTPUT FORMAT:\n"

            # Add DECISION GUIDE if tools are available
            if tool_schemas:
                system_content += "DECISION GUIDE:\n"
                system_content += "- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.\n"
                system_content += "- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.\n\n"

            system_content += "Your FINAL response must be ONLY valid JSON (no markdown, no code blocks) with this exact structure:\n"
            system_content += "{\n"

            # Build example showing expected structure with descriptions
            properties = output_schema.get("properties", {})
            prop_items = list(properties.items())
            for i, (prop_name, prop_schema) in enumerate(prop_items):
                prop_type = prop_schema.get("type", "string")
                prop_desc = prop_schema.get("description", "")

                # Show example value based on type
                if prop_type == "string":
                    example_value = f'"<your {prop_name} here>"'
                elif prop_type in ("number", "integer"):
                    example_value = "0"
                elif prop_type == "array":
                    example_value = '["item1", "item2"]'
                elif prop_type == "boolean":
                    example_value = "true"
                elif prop_type == "object":
                    example_value = "{}"
                else:
                    example_value = "..."

                # Add comma for all but last property
                comma = "," if i < len(prop_items) - 1 else ""
                # Include description as comment if available
                if prop_desc:
                    system_content += (
                        f'  "{prop_name}": {example_value}{comma}  // {prop_desc}\n'
                    )
                else:
                    system_content += f'  "{prop_name}": {example_value}{comma}\n'

            system_content += "}\n\n"
            system_content += "Return ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks."

        return system_content

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return Gemini-specific capabilities.

        Returns:
            Capability flags for Gemini
        """
        return {
            "native_tool_calling": True,  # Gemini has native function calling
            "structured_output": True,  # Supports structured output via prompt hints
            "streaming": True,  # Supports streaming
            "vision": True,  # Gemini supports multimodal (images, video, audio)
            "json_mode": True,  # JSON mode via prompt-based hints
            "large_context": True,  # Up to 2M tokens context window
        }

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Gemini-specific structured output handling (prompt-based hints).

        Gemini Strategy:
        - Do NOT add response_format to model_params (causes tool loops with Gemini 2.0)
        - Store the schema so format_system_prompt can add JSON instructions
        - Let prompt-based hints guide the model to output valid JSON

        This is called by LLM providers (via mesh) when they receive an output_schema
        from a consumer.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "AnalysisResult")
            model_params: Current model parameters dict (will NOT be modified with response_format)

        Returns:
            model_params unchanged (no response_format added)
        """
        # Store the schema for use in format_system_prompt
        self._pending_output_schema = sanitize_schema_for_structured_output(
            output_schema
        )
        self._pending_output_type_name = output_type_name

        logger.debug(
            "Gemini: Using prompt-based JSON hints for structured output (not response_format). "
            "Schema stored for output type: %s",
            output_type_name or "Response",
        )

        # NOTE: We do NOT add response_format to model_params!
        # Gemini 2.0 Flash + tools + response_format causes the model to keep calling tools.
        # Structured output is handled via prompt-based hints in format_system_prompt().

        return model_params
