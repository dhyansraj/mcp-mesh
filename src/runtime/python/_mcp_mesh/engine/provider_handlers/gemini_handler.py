"""
Gemini/Google provider handler.

Optimized for Gemini models (Gemini 3 Flash, Gemini 3 Pro, Gemini 2.0 Flash, etc.)
using Google's best practices for tool calling and structured output.

Features:
- Mixed structured output strategy based on tool presence:
  - STRICT mode (response_format) when NO tools are present
  - HINT mode (prompt-based JSON hints) when tools ARE present
- Native function calling support
- Support for Gemini 2.x and 3.x models
- Large context windows (up to 2M tokens)

Note:
- Gemini 3 + response_format + tools causes non-deterministic infinite tool loops,
  so we avoid response_format when tools are present and use HINT mode instead.
- STRICT mode (response_format) is only used for tool-free requests.

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
    sanitize_schema_for_structured_output,
)

OUTPUT_MODE_TEXT = "text"
OUTPUT_MODE_STRICT = "strict"
OUTPUT_MODE_HINT = "hint"

logger = logging.getLogger(__name__)


class GeminiHandler(BaseProviderHandler):
    """
    Provider handler for Google Gemini models.

    Gemini Characteristics:
    - Mixed structured output strategy:
      - STRICT mode (response_format) when NO tools are present
      - HINT mode (prompt-based JSON hints) when tools ARE present
    - Gemini 3 + response_format + tools causes non-deterministic infinite tool loops,
      so we avoid combining them.
    - Native function calling support
    - Large context windows (1M-2M tokens)
    - Multimodal support (text, images, video, audio)
    - Works well with concise, focused prompts

    Supported Models (via LiteLLM):
    - gemini/gemini-3-flash-preview (reasoning support)
    - gemini/gemini-3-pro-preview (advanced reasoning)
    - gemini/gemini-2.0-flash (fast, efficient)
    - gemini/gemini-2.0-flash-lite (fastest, most efficient)
    - gemini/gemini-1.5-pro (high capability)
    - gemini/gemini-1.5-flash (balanced)

    Reference:
    https://docs.litellm.ai/docs/providers/gemini
    """

    def __init__(self):
        """Initialize Gemini handler."""
        super().__init__(vendor="gemini")
        # Store output schema for use in format_system_prompt (set by apply_structured_output)
        self._pending_output_schema: dict[str, Any] | None = None
        self._pending_output_type_name: str | None = None

    def determine_output_mode(self, output_type, override_mode=None):
        """Determine output mode for Gemini.

        Gemini 3 supports native response_format with tools.
        Uses STRICT mode (response_format) for all schema types.
        TEXT mode for string return types.
        """
        if override_mode:
            return override_mode
        if output_type is str:
            return OUTPUT_MODE_TEXT
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            return OUTPUT_MODE_STRICT
        return OUTPUT_MODE_STRICT

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
        - Use native response_format with strict schema (Gemini 3+)
        - Store schema for HINT fallback in format_system_prompt
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

        # Only store schema for Pydantic models
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
            schema = sanitize_schema_for_structured_output(schema)

            # Store for HINT mode in format_system_prompt (always needed as fallback)
            self._pending_output_schema = schema
            self._pending_output_type_name = output_type.__name__

            # Only use response_format when NO tools present
            # Gemini 3 + response_format + tools causes non-deterministic infinite tool loops
            if not tools:
                strict_schema = make_schema_strict(schema, add_all_required=True)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_type.__name__,
                        "schema": strict_schema,
                        "strict": True,
                    },
                }
                logger.debug(
                    "Gemini: Using response_format with strict schema for '%s' (no tools)",
                    output_type.__name__,
                )
            else:
                logger.debug(
                    "Gemini: Using HINT mode for '%s' (tools present, response_format skipped)",
                    output_type.__name__,
                )
        else:
            self._pending_output_schema = None
            self._pending_output_type_name = None

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: list[dict[str, Any]] | None,
        output_type: type,
    ) -> str:
        """
        Format system prompt for Gemini with structured output support.

        Gemini Strategy:
        1. Use base prompt as-is
        2. Add tool calling instructions if tools present
        3. STRICT mode: Brief note (response_format handles enforcement)
        4. HINT mode fallback: Detailed JSON output instructions with example structure

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

        # Determine output mode
        determined_mode = self.determine_output_mode(output_type)

        # STRICT mode: Brief note (response_format handles enforcement)
        # But only when no tools - with tools we use HINT mode
        if determined_mode == OUTPUT_MODE_STRICT and not tool_schemas:
            system_content += f"\n\nYour final response will be structured as JSON matching the {output_type_name} format."
            return system_content

        # HINT mode fallback: Detailed JSON instructions
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
            "native_tool_calling": True,
            "structured_output": True,  # Via native response_format (Gemini 3+)
            "streaming": True,
            "vision": True,
            "json_mode": True,  # Native JSON mode via response_format
            "large_context": True,
        }

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Gemini-specific structured output for mesh delegation.

        Uses HINT mode (prompt injection) because mesh delegation always involves
        tools, and Gemini 3 + response_format + tools causes infinite tool loops.
        """
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)

        # Store for format_system_prompt
        self._pending_output_schema = sanitized_schema
        self._pending_output_type_name = output_type_name

        # Inject HINT instructions into system messages
        # (mesh delegation always has tools, so we can't use response_format)
        messages = model_params.get("messages", [])
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                # Build hint instructions
                hint_text = "\n\nOUTPUT FORMAT:\n"
                hint_text += "Your FINAL response must be ONLY valid JSON (no markdown, no code blocks) with this exact structure:\n"
                hint_text += "{\n"
                properties = sanitized_schema.get("properties", {})
                prop_items = list(properties.items())
                for i, (prop_name, prop_schema) in enumerate(prop_items):
                    prop_type = prop_schema.get("type", "string")
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
                    comma = "," if i < len(prop_items) - 1 else ""
                    prop_desc = prop_schema.get("description", "")
                    if prop_desc:
                        hint_text += (
                            f'  "{prop_name}": {example_value}{comma}  // {prop_desc}\n'
                        )
                    else:
                        hint_text += f'  "{prop_name}": {example_value}{comma}\n'
                hint_text += "}\n\n"
                hint_text += "Return ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks."

                msg["content"] = base_content + hint_text
                break

        logger.info(
            "Gemini hint mode for '%s' (mesh delegation, schema in prompt)",
            output_type_name or "Response",
        )
        return model_params
