"""
Claude/Anthropic provider handler.

Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
using Anthropic's best practices for tool calling and JSON responses.

Output strategy:
- format_system_prompt (direct calls): Uses HINT mode — prompt-based JSON
  instructions with DECISION GUIDE (~95% reliable). This avoids cross-runtime
  incompatibilities when the caller is a non-Python SDK.
- apply_structured_output (mesh delegation): Uses HINT mode (prompt injection)
  by default to avoid the Anthropic response_format + tools silent-hang bug
  (issue #820). The agentic loop validates the final response against the
  schema and falls back to a bounded-timeout response_format call if the HINT
  output fails to parse. Set MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT=true to
  revert to the previous response_format-first behavior.

Features:
- Automatic prompt caching for system messages (up to 90% cost reduction)
- Anti-XML tool calling instructions
- DECISION GUIDE for tool vs. direct JSON response decisions (direct calls)
"""

import json
import logging
import os
from typing import Any

import mcp_mesh_core
from pydantic import BaseModel

from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
    sanitize_schema_for_structured_output,
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

    Output Modes:
    - format_system_prompt (direct calls): TEXT + HINT only.
      HINT adds JSON schema instructions with DECISION GUIDE in prompt (~95%).
    - apply_structured_output (mesh delegation): Uses native response_format
      with json_schema strict mode (100% enforcement, inherited from base class).

    Best Practices (from Anthropic docs):
    - Add anti-XML instructions to prevent <invoke> style tool calls
    - Use one tool call at a time for better reliability
    - Use cache_control for system prompts to reduce costs
    """

    def __init__(self):
        """Initialize Claude handler."""
        super().__init__(vendor="anthropic")

    def determine_output_mode(
        self, output_type: type, override_mode: str | None = None
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
        tools: list[dict[str, Any]] | None,
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

        # Claude doesn't support parallel_tool_calls API param
        # (it naturally supports multiple tool_use blocks)
        kwargs.pop("parallel_tool_calls", None)

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
        tool_schemas: list[dict[str, Any]] | None,
        output_type: type,
        output_mode: str | None = None,
    ) -> str:
        """
        Format system prompt for Claude with output mode support.

        Delegates to Rust core for prompt construction.

        When called via the mesh delegation path, ``apply_structured_output``
        will have already injected an ``OUTPUT FORMAT:`` HINT block into the
        system message. In that case the Rust formatter is invoked with
        ``output_type=str`` (text mode) so the only additions are tool/media
        instructions — the HINT block is not duplicated.

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type
            output_mode: Optional override for output mode

        Returns:
            Formatted system prompt optimized for Claude
        """
        determined_mode = self.determine_output_mode(output_type, output_mode)

        schema_json = None
        schema_name = None
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema_json = json.dumps(output_type.model_json_schema())
            schema_name = output_type.__name__

        return mcp_mesh_core.format_system_prompt_py(
            "anthropic",
            base_prompt,
            bool(tool_schemas),
            has_media_params(tool_schemas),
            schema_json,
            schema_name,
            determined_mode,
        )

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Claude-specific structured output for mesh delegation.

        Claude's native ``response_format`` path silently hangs (600s+) on
        certain content + tools combinations (issue #820). To avoid this,
        we use HINT mode by default: inject schema instructions into the
        system prompt and let the agentic loop validate the final response.
        If validation fails, the loop falls back to a bounded-timeout
        ``response_format`` call (see ``_provider_agentic_loop``).

        Set ``MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT=true`` to revert to the
        previous response_format-first behavior (delegates to base impl).

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "TripPlan")
            model_params: Current model parameters dict (will be modified)

        Returns:
            Modified model_params with HINT-mode flags + injected system prompt
        """
        # Backwards-compat env flag: revert to base response_format behavior.
        if os.environ.get("MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            logger.info(
                "Claude: MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT set, using "
                "native response_format (base behavior)"
            )
            return super().apply_structured_output(
                output_schema, output_type_name, model_params
            )

        sanitized_schema = sanitize_schema_for_structured_output(output_schema)

        # Inject HINT instructions into the first system message.
        # Mesh delegation always involves tools, and Claude's response_format
        # path silently hangs on certain content+tools combos (issue #820),
        # so we cannot use it here.
        messages = model_params.get("messages", [])
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                hint_text = "\n\nOUTPUT FORMAT:\n"
                hint_text += (
                    "Your FINAL response must be ONLY valid JSON (no markdown, "
                    "no code blocks) with this exact structure:\n"
                )
                properties = sanitized_schema.get("properties", {})
                hint_text += self.build_json_example(properties) + "\n\n"
                hint_text += (
                    "Return ONLY the JSON object with actual values. Do not "
                    "include the schema definition, markdown formatting, or "
                    "code blocks."
                )

                msg["content"] = base_content + hint_text
                break

        # Internal flags read by _provider_agentic_loop. Prefixed with
        # "_mesh_" so the loop strips them before calling LiteLLM (these
        # are NOT API params).
        model_params["_mesh_hint_mode"] = True
        model_params["_mesh_hint_schema"] = sanitized_schema
        model_params["_mesh_hint_fallback_timeout"] = 30
        model_params["_mesh_hint_output_type_name"] = output_type_name or "Response"

        # Explicitly DO NOT set response_format — that's the bug we're avoiding.
        model_params.pop("response_format", None)

        logger.info(
            "Claude HINT mode for '%s' (mesh delegation, schema in prompt; "
            "loop will fall back to response_format if parse fails)",
            output_type_name or "Response",
        )
        return model_params

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
