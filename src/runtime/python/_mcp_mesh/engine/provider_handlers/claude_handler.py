"""
Claude/Anthropic provider handler.

Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
using Anthropic's best practices for tool calling and JSON responses.

Supports two output modes:
- hint: Use prompt-based JSON instructions with DECISION GUIDE (~95% reliable)
- text: Plain text output for str return types (fastest)

Native response_format (strict mode) is NOT used due to cross-runtime
incompatibilities when tools are present, and grammar compilation overhead.

Features:
- Automatic prompt caching for system messages (up to 90% cost reduction)
- Anti-XML tool calling instructions
- DECISION GUIDE for tool vs. direct JSON response decisions
"""

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BASE_TOOL_INSTRUCTIONS,
    CLAUDE_ANTI_XML_INSTRUCTION,
    BaseProviderHandler,
)

logger = logging.getLogger(__name__)

# Output mode constants
OUTPUT_MODE_STRICT = (
    "strict"  # Unused for Claude (kept for override_mode compatibility)
)
OUTPUT_MODE_HINT = "hint"
OUTPUT_MODE_TEXT = "text"


class ClaudeHandler(BaseProviderHandler):
    """
    Provider handler for Claude/Anthropic models.

    Claude Characteristics:
    - Excellent at following detailed instructions
    - Native tool calling (via Anthropic messages API)
    - Performs best with anti-XML tool calling instructions
    - Automatic prompt caching for cost optimization

    Output Modes (TEXT + HINT only):
    - hint: JSON schema in prompt with DECISION GUIDE (~95% reliable)
    - text: Plain text output for str return types (fastest)

    Native response_format (strict mode) is not used. HINT mode with
    detailed prompt instructions provides sufficient reliability (~95%)
    without the cross-runtime incompatibilities and grammar compilation
    overhead of native structured output.

    Best Practices (from Anthropic docs):
    - Add anti-XML instructions to prevent <invoke> style tool calls
    - Use one tool call at a time for better reliability
    - Use cache_control for system prompts to reduce costs
    """

    def __init__(self):
        """Initialize Claude handler."""
        super().__init__(vendor="anthropic")

    def determine_output_mode(
        self, output_type: type, override_mode: Optional[str] = None
    ) -> str:
        """
        Determine the output mode based on return type.

        Strategy: TEXT + HINT only. No STRICT mode for Claude.

        Logic:
        - If override_mode specified, use it
        - If return type is str, use "text" mode
        - All schema types use "hint" mode (prompt-based JSON instructions)

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

        # All schema types use HINT mode -- no STRICT for Claude
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            return OUTPUT_MODE_HINT

        return OUTPUT_MODE_HINT

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

        Output Mode Strategy (TEXT + HINT only):
        - hint: No response_format, rely on prompt instructions (~95% reliable)
        - text: No response_format, plain text output (fastest)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Return type (str or Pydantic model)
            **kwargs: Additional model parameters (may include output_mode override)

        Returns:
            Dictionary of parameters for litellm.completion()
        """
        # Extract output_mode from kwargs to prevent it leaking into request params
        kwargs.pop("output_mode", None)

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

        Output Mode Strategy (TEXT + HINT only):
        - hint: Add detailed JSON schema instructions with DECISION GUIDE in prompt
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

        elif determined_mode == OUTPUT_MODE_HINT:
            # Hint mode: Add detailed JSON schema instructions with DECISION GUIDE
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

                # Add DECISION GUIDE when tools are present
                decision_guide = ""
                if tool_schemas:
                    decision_guide = """
DECISION GUIDE:
- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.
- After calling a tool and receiving results, STOP calling tools and return your final JSON response.
"""

                system_content += f"""
{decision_guide}
RESPONSE FORMAT:
You MUST respond with valid JSON matching this schema:
{{
{fields_text}
}}

Example format:
{json.dumps({k: f"<{v.get('type', 'value')}>" for k, v in properties.items()}, indent=2)}

CRITICAL: Your response must be ONLY the raw JSON object.
- DO NOT wrap in markdown code fences (```json or ```)
- DO NOT include any text before or after the JSON
- Start directly with {{ and end with }}"""

        return system_content

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return Claude-specific capabilities.

        Returns:
            Capability flags for Claude
        """
        return {
            "native_tool_calling": True,  # Claude has native function calling
            "structured_output": False,  # Uses HINT mode (prompt-based), not native response_format
            "streaming": True,  # Supports streaming
            "vision": True,  # Claude 3+ supports vision
            "json_mode": False,  # No native JSON mode used
            "prompt_caching": True,  # Automatic system prompt caching for cost savings
        }

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: Optional[str],
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Claude-specific structured output for mesh delegation using HINT mode.

        Instead of using response_format (strict mode), injects detailed JSON schema
        instructions into the system message. This is consistent with the TEXT + HINT
        only strategy and avoids cross-runtime incompatibilities.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "AnalysisResult")
            model_params: Current model parameters dict (will be modified)

        Returns:
            Modified model_params with HINT-mode instructions in system prompt
        """
        # Build HINT mode instructions from the schema
        properties = output_schema.get("properties", {})
        required = output_schema.get("required", [])

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
        type_name = output_type_name or "Response"

        hint_instructions = f"""

DECISION GUIDE:
- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.
- If your answer is general knowledge, directly return your response as JSON WITHOUT calling tools.
- After calling a tool and receiving results, STOP calling tools and return your final JSON response.

RESPONSE FORMAT:
You MUST respond with valid JSON matching this schema:
{{
{fields_text}
}}

Example format:
{json.dumps({k: f"<{v.get('type', 'value')}>" for k, v in properties.items()}, indent=2)}

CRITICAL: Your response must be ONLY the raw JSON object.
- DO NOT wrap in markdown code fences (```json or ```)
- DO NOT include any text before or after the JSON
- Start directly with {{ and end with }}"""

        # Inject into system message
        messages = model_params.get("messages", [])
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    msg["content"] = content + hint_instructions
                elif isinstance(content, list):
                    # Content block format -- append to last text block
                    for block in reversed(content):
                        if isinstance(block, dict) and block.get("type") == "text":
                            block["text"] = block["text"] + hint_instructions
                            break
                break

        logger.info(
            f"Claude hint mode for '{type_name}' "
            f"(mesh delegation, schema in prompt)"
        )
        return model_params
