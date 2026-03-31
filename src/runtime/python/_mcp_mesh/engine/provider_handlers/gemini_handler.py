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

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
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

        Delegates to Rust core for prompt construction.

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt optimized for Gemini
        """
        import mcp_mesh_core

        # Use pending schema if set (from apply_structured_output or prepare_request)
        output_schema = self._pending_output_schema
        output_type_name = self._pending_output_type_name

        if output_schema is None:
            if output_type is str:
                # No schema and str return type — text mode
                is_string = True
                schema_json = None
                schema_name = None
            elif isinstance(output_type, type) and issubclass(output_type, BaseModel):
                is_string = False
                output_schema = sanitize_schema_for_structured_output(
                    output_type.model_json_schema()
                )
                output_type_name = output_type.__name__
                schema_json = json.dumps(output_schema)
                schema_name = output_type_name
            else:
                is_string = False
                schema_json = None
                schema_name = None
        else:
            is_string = False
            schema_json = json.dumps(output_schema)
            schema_name = output_type_name

        # Determine mode: strict when no tools, hint when tools present
        determined_mode = self.determine_output_mode(output_type)
        if determined_mode == "strict" and tool_schemas:
            determined_mode = "hint"

        return mcp_mesh_core.format_system_prompt_py(
            "gemini",
            base_prompt,
            bool(tool_schemas),
            has_media_params(tool_schemas),
            schema_json,
            schema_name,
            determined_mode if not (is_string and output_schema is None) else "text",
        )

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
                properties = sanitized_schema.get("properties", {})
                hint_text += self.build_json_example(properties) + "\n\n"
                hint_text += "Return ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks."

                msg["content"] = base_content + hint_text
                break

        logger.info(
            "Gemini hint mode for '%s' (mesh delegation, schema in prompt)",
            output_type_name or "Response",
        )
        return model_params
