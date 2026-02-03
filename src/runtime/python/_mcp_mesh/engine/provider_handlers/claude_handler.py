"""
Claude/Anthropic provider handler.

Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
using Anthropic's best practices for tool calling and JSON responses.

Supports three output modes for performance/reliability tradeoffs:
- strict: Use response_format for guaranteed schema compliance (slowest, 100% reliable)
- hint: Use prompt-based JSON instructions (medium speed, ~95% reliable)
- text: Plain text output for str return types (fastest)

Features:
- Automatic prompt caching for system messages (up to 90% cost reduction)
- Anti-XML tool calling instructions
- Output mode optimization based on return type
"""

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BASE_TOOL_INSTRUCTIONS,
    BaseProviderHandler,
    CLAUDE_ANTI_XML_INSTRUCTION,
    is_simple_schema,
    make_schema_strict,
    sanitize_schema_for_structured_output,
)

logger = logging.getLogger(__name__)

# Output mode constants
OUTPUT_MODE_STRICT = "strict"
OUTPUT_MODE_HINT = "hint"
OUTPUT_MODE_TEXT = "text"


class ClaudeHandler(BaseProviderHandler):
    """
    Provider handler for Claude/Anthropic models.

    Claude Characteristics:
    - Excellent at following detailed instructions
    - Native structured output via response_format (requires strict schema)
    - Native tool calling (via Anthropic messages API)
    - Performs best with anti-XML tool calling instructions
    - Automatic prompt caching for cost optimization

    Output Modes:
    - strict: response_format with JSON schema (slowest, guaranteed valid JSON)
    - hint: JSON schema in prompt (medium speed, usually valid JSON)
    - text: Plain text output for str return types (fastest)

    Best Practices (from Anthropic docs):
    - Use response_format for guaranteed JSON schema compliance
    - Schema must have additionalProperties: false on all objects
    - Add anti-XML instructions to prevent <invoke> style tool calls
    - Use one tool call at a time for better reliability
    - Use cache_control for system prompts to reduce costs
    """

    def __init__(self):
        """Initialize Claude handler."""
        super().__init__(vendor="anthropic")

    def _is_simple_schema(self, model_class: type[BaseModel]) -> bool:
        """
        Check if a Pydantic model has a simple schema.

        Simple schema criteria:
        - Less than 5 fields
        - All fields are basic types (str, int, float, bool, list, Optional)
        - No nested Pydantic models

        Args:
            model_class: Pydantic model class

        Returns:
            True if schema is simple, False otherwise
        """
        try:
            schema = model_class.model_json_schema()
            properties = schema.get("properties", {})

            # Check field count
            if len(properties) >= 5:
                return False

            # Check for nested objects or complex types
            for field_name, field_schema in properties.items():
                field_type = field_schema.get("type")

                # Check for nested objects (indicates nested Pydantic model)
                if field_type == "object" and "properties" in field_schema:
                    return False

                # Check for $ref (nested model reference)
                if "$ref" in field_schema:
                    return False

                # Check array items for complex types
                if field_type == "array":
                    items = field_schema.get("items", {})
                    if items.get("type") == "object" or "$ref" in items:
                        return False

            return True
        except Exception:
            return False

    def determine_output_mode(
        self, output_type: type, override_mode: Optional[str] = None
    ) -> str:
        """
        Determine the output mode based on return type.

        Logic:
        - If override_mode specified, use it
        - If return type is str, use "text" mode
        - If return type is simple schema (<5 fields, basic types), use "hint" mode
        - Otherwise, use "strict" mode

        Args:
            output_type: Return type (str or BaseModel subclass)
            override_mode: Optional override ("strict", "hint", or "text")

        Returns:
            Output mode string
        """
        # Allow explicit override
        if override_mode:
            return override_mode

        # String return type -> text mode
        if output_type is str:
            return OUTPUT_MODE_TEXT

        # Check if it's a Pydantic model
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            if self._is_simple_schema(output_type):
                return OUTPUT_MODE_HINT
            else:
                return OUTPUT_MODE_STRICT

        # Default to strict for unknown types
        return OUTPUT_MODE_STRICT

    def _apply_prompt_caching(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Apply prompt caching to system messages for Claude.

        Claude's prompt caching feature caches the system prompt prefix,
        reducing costs by up to 90% and improving latency for repeated calls.

        The cache_control with type "ephemeral" tells Claude to cache
        this content for the duration of the session (typically 5 minutes).

        Args:
            messages: List of message dicts

        Returns:
            Messages with cache_control applied to system messages

        Reference:
            https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
        """
        cached_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")

                # Convert string content to cached content block format
                if isinstance(content, str):
                    cached_msg = {
                        "role": "system",
                        "content": [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                    cached_messages.append(cached_msg)
                    logger.debug(
                        f"🗄️ Applied prompt caching to system message ({len(content)} chars)"
                    )
                elif isinstance(content, list):
                    # Already in content block format - add cache_control to last block
                    cached_content = []
                    for i, block in enumerate(content):
                        if isinstance(block, dict):
                            block_copy = block.copy()
                            # Add cache_control to the last text block
                            if i == len(content) - 1 and block.get("type") == "text":
                                block_copy["cache_control"] = {"type": "ephemeral"}
                            cached_content.append(block_copy)
                        else:
                            cached_content.append(block)
                    cached_messages.append(
                        {"role": "system", "content": cached_content}
                    )
                    logger.debug("🗄️ Applied prompt caching to system content blocks")
                else:
                    # Unknown format - pass through unchanged
                    cached_messages.append(msg)
            else:
                # Non-system messages pass through unchanged
                cached_messages.append(msg)

        return cached_messages

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        output_type: type,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request parameters for Claude API with output mode support.

        Output Mode Strategy:
        - strict: Use response_format for guaranteed JSON schema compliance (slowest)
        - hint: No response_format, rely on prompt instructions (medium speed)
        - text: No response_format, plain text output (fastest)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Return type (str or Pydantic model)
            **kwargs: Additional model parameters (may include output_mode override)

        Returns:
            Dictionary of parameters for litellm.completion()
        """
        # Extract output_mode from kwargs if provided
        output_mode = kwargs.pop("output_mode", None)
        determined_mode = self.determine_output_mode(output_type, output_mode)

        # Remove response_format from kwargs - we control this based on output mode
        # The decorator's response_format="json" is just a hint for parsing, not API param
        kwargs.pop("response_format", None)

        # Apply prompt caching to system messages for cost optimization
        cached_messages = self._apply_prompt_caching(messages)

        request_params = {
            "messages": cached_messages,
            **kwargs,  # Pass through temperature, max_tokens, etc.
        }

        # Add tools if provided
        # LiteLLM will convert OpenAI tool format to Anthropic's format
        if tools:
            request_params["tools"] = tools

        # Only add response_format in "strict" mode
        if determined_mode == OUTPUT_MODE_STRICT:
            # Claude requires additionalProperties: false on all object types
            # Unlike OpenAI/Gemini, Claude doesn't require all properties in 'required'
            if isinstance(output_type, type) and issubclass(output_type, BaseModel):
                schema = output_type.model_json_schema()
                strict_schema = make_schema_strict(schema, add_all_required=False)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_type.__name__,
                        "schema": strict_schema,
                        "strict": False,  # Allow optional fields with defaults
                    },
                }

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[list[dict[str, Any]]],
        output_type: type,
        output_mode: Optional[str] = None,
    ) -> str:
        """
        Format system prompt for Claude with output mode support.

        Output Mode Strategy:
        - strict: Minimal JSON instructions (response_format handles schema)
        - hint: Add detailed JSON schema instructions in prompt
        - text: No JSON instructions (plain text output)

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type
            output_mode: Optional override for output mode

        Returns:
            Formatted system prompt optimized for Claude
        """
        system_content = base_prompt
        determined_mode = self.determine_output_mode(output_type, output_mode)

        # Add tool calling instructions if tools available
        # These prevent Claude from using XML-style <invoke> syntax
        if tool_schemas:
            # Use base instructions but insert anti-XML rule for Claude
            instructions = BASE_TOOL_INSTRUCTIONS.replace(
                "- Make ONE tool call at a time",
                f"- Make ONE tool call at a time\n{CLAUDE_ANTI_XML_INSTRUCTION}",
            )
            system_content += instructions

        # Add output format instructions based on mode
        if determined_mode == OUTPUT_MODE_TEXT:
            # Text mode: No JSON instructions
            pass

        elif determined_mode == OUTPUT_MODE_STRICT:
            # Strict mode: Minimal instructions (response_format handles schema)
            if isinstance(output_type, type) and issubclass(output_type, BaseModel):
                system_content += f"\n\nYour final response will be structured as JSON matching the {output_type.__name__} format."

        elif determined_mode == OUTPUT_MODE_HINT:
            # Hint mode: Add detailed JSON schema instructions
            if isinstance(output_type, type) and issubclass(output_type, BaseModel):
                schema = output_type.model_json_schema()
                properties = schema.get("properties", {})
                required = schema.get("required", [])

                # Build human-readable schema description
                field_descriptions = []
                for field_name, field_schema in properties.items():
                    field_type = field_schema.get("type", "any")
                    is_required = field_name in required
                    req_marker = " (required)" if is_required else " (optional)"
                    desc = field_schema.get("description", "")
                    desc_text = f" - {desc}" if desc else ""
                    field_descriptions.append(
                        f"  - {field_name}: {field_type}{req_marker}{desc_text}"
                    )

                fields_text = "\n".join(field_descriptions)
                system_content += f"""

RESPONSE FORMAT:
You MUST respond with valid JSON matching this schema:
{{
{fields_text}
}}

Example format:
{json.dumps({k: f"<{v.get('type', 'value')}>" for k, v in properties.items()}, indent=2)}

IMPORTANT: Respond ONLY with valid JSON. No markdown code fences, no preamble text."""

        return system_content

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return Claude-specific capabilities.

        Returns:
            Capability flags for Claude
        """
        return {
            "native_tool_calling": True,  # Claude has native function calling
            "structured_output": True,  # Native response_format support via LiteLLM
            "streaming": True,  # Supports streaming
            "vision": True,  # Claude 3+ supports vision
            "json_mode": True,  # Native JSON mode via response_format
            "prompt_caching": True,  # Automatic system prompt caching for cost savings
        }

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: Optional[str],
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Claude-specific structured output handling for mesh delegation.

        When called via mesh delegation (output_schema passed from consumer), we always
        use strict mode with response_format to guarantee JSON output. Hint mode is only
        suitable for local consumers who control their own system prompts and can inject
        JSON instructions there.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "AnalysisResult")
            model_params: Current model parameters dict (will be modified)

        Returns:
            Modified model_params with structured output settings applied
        """
        # For mesh delegation, always use strict mode with response_format
        # This guarantees JSON output regardless of consumer's system prompt
        # Sanitize schema first to remove unsupported validation keywords (minimum, maximum, etc.)
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)
        strict_schema = make_schema_strict(sanitized_schema, add_all_required=False)
        model_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_type_name or "Response",
                "schema": strict_schema,
                "strict": False,  # Claude doesn't require all properties in 'required'
            },
        }
        logger.info(
            f"🎯 Claude strict mode for '{output_type_name}' "
            f"(mesh delegation, using response_format)"
        )
        return model_params
