"""
Claude/Anthropic provider handler.

Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
using Anthropic's best practices for tool calling and JSON responses.

Output strategy:
- format_system_prompt (direct calls): Uses HINT mode — prompt-based JSON
  instructions with DECISION GUIDE (~95% reliable). This avoids cross-runtime
  incompatibilities when the caller is a non-Python SDK.
- apply_structured_output (mesh delegation, LiteLLM path): Uses HINT mode
  (prompt injection) by default to avoid the Anthropic response_format + tools
  silent-hang bug (issue #820). The agentic loop validates the final response
  against the schema and falls back to a bounded-timeout response_format call
  if the HINT output fails to parse. Set MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT
  =true to revert to the previous response_format-first behavior.
- apply_structured_output (mesh delegation, NATIVE path, issue #834): Uses the
  synthetic-tool pattern that mirrors the TS (Vercel AI SDK) and Java (Spring
  AI) runtimes: append a synthetic ``__mesh_format_response`` tool whose
  ``input_schema`` IS the desired JSON schema, and let Claude pick between
  real user tools and the synthetic tool with ``tool_choice="auto"``. The
  agentic loop in mesh.helpers terminates as soon as Claude calls the
  synthetic tool. This unblocks the broken combo "native + tools + structured
  output" (the previous force-tool_choice approach suppressed real tool calls).

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

# Stable name for the synthetic tool that backs structured output on the
# native Anthropic SDK path (issue #834). Double-underscore prefix marks it
# as internal — agents must not register a tool with this name. The agentic
# loop in ``mesh.helpers`` recognizes a call to this name as the model's
# "I'm done — here's the structured answer" signal and terminates.
SYNTHETIC_FORMAT_TOOL_NAME = "__mesh_format_response"
SYNTHETIC_FORMAT_TOOL_DESCRIPTION = (
    "Use this tool to return your final structured answer matching the "
    "schema. Call this tool only after gathering all needed data via other "
    "available tools."
)
# System prompt augmentation that goes into the system message when the
# synthetic tool is in play. Keeps Claude from emitting plain text as the
# final answer (which would skip the synthetic tool entirely and break
# downstream Pydantic parsing).
SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION = (
    "\n\nIMPORTANT: When you have all the information needed to answer, "
    "you MUST call the `__mesh_format_response` tool to return your final "
    "answer in the required structured format. Do NOT respond with plain "
    "text — always use this tool to format your final answer."
)

# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in anthropic_native — we
# deliberately keep the state at module level (not on the handler instance)
# because mesh constructs a fresh handler per request in some paths.
_DISPATCH_STATUS_LOGGED = False


def _log_dispatch_status_once() -> None:
    """Log the resolved native-dispatch status once per process at DEBUG level.

    Designed so users running with ``meshctl ... --debug`` can confirm whether
    a Claude provider agent is using the native anthropic SDK or falling back
    to LiteLLM. Fires on first call only; subsequent invocations are no-ops.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    env_value = os.getenv("MCP_MESH_NATIVE_LLM", "").strip().lower()

    if env_value in ("0", "false", "no", "off"):
        logger.debug(
            "Claude native dispatch: disabled "
            "(MCP_MESH_NATIVE_LLM=%s explicitly set; using LiteLLM)",
            env_value or "<unset>",
        )
        return

    from _mcp_mesh.engine.native_clients import anthropic_native

    if anthropic_native.is_available():
        try:
            import anthropic
            version = getattr(anthropic, "__version__", "<unknown>")
        except Exception:
            version = "<import-failed>"
        logger.debug(
            "Claude native dispatch: enabled (anthropic SDK %s)",
            version,
        )
    else:
        logger.debug(
            "Claude native dispatch: disabled "
            "(anthropic SDK not installed; install mcp-mesh[anthropic] to enable)"
        )


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

    def _build_hint_text(self, sanitized_schema: dict[str, Any]) -> str:
        """Build the ``OUTPUT FORMAT:`` HINT block for ``apply_structured_output``.

        Returned text starts with leading blank lines so it can be appended
        directly to existing system message content. Callers that synthesize
        a fresh system message should ``.strip()`` the result.
        """
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
        return hint_text

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply Claude-specific structured output for mesh delegation.

        Two paths, selected by ``has_native()``:

        - Native Anthropic SDK path (issue #834, default when the
          ``anthropic`` SDK is importable): Append a synthetic
          ``__mesh_format_response`` tool with the schema as
          ``input_schema`` and let Claude pick between real tools and the
          synthetic tool with ``tool_choice="auto"``. The agentic loop
          terminates when the synthetic tool is called. Mirrors the TS
          (Vercel AI SDK) and Java (Spring AI) runtimes.

        - LiteLLM path (set ``MCP_MESH_NATIVE_LLM=0`` to force, or used
          automatically when the SDK is missing): HINT mode (prompt
          injection). Claude's native ``response_format`` path silently
          hangs (600s+) on certain content + tools combinations (issue
          #820), so we inject schema instructions into the system prompt
          and let the agentic loop validate the final response. If
          validation fails, the loop falls back to a bounded-timeout
          ``response_format`` call.

        Set ``MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT=true`` to revert the
        LiteLLM path to native response_format-first (delegates to base
        impl). The flag is a no-op on the native path — synthetic-tool
        mode is always used there.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "TripPlan")
            model_params: Current model parameters dict (will be modified)

        Returns:
            Modified model_params with mode-specific flags + injected
            system prompt
        """
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)

        # Native path: use synthetic-tool injection (matches TS/Java).
        # Decided here so the loop doesn't have to re-check the env flag
        # on every iteration; one resolution at request-prep time.
        if self.has_native():
            return self._apply_native_synthetic_format(
                sanitized_schema, output_type_name, model_params
            )

        # Backwards-compat env flag: revert LiteLLM path to base response_format.
        # Intentionally only honored on the LiteLLM path — on native, synthetic
        # tool injection is always used (the env flag predates native and was a
        # workaround for HINT-mode failures).
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

        # Inject HINT instructions into the first system message.
        # Mesh delegation always involves tools, and Claude's response_format
        # path silently hangs on certain content+tools combos (issue #820),
        # so we cannot use it here.
        messages = model_params.get("messages", [])
        hint_block_inserted = False
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                msg["content"] = base_content + self._build_hint_text(sanitized_schema)
                hint_block_inserted = True
                break

        if not hint_block_inserted:
            # No system message found — synthesize one containing just the
            # HINT block. Without this, the _mesh_hint_* flags below would
            # still be set but the model would never see the schema, every
            # response would fail validation, and the 30s fallback timeout
            # would fire on every request.
            hint_text = self._build_hint_text(sanitized_schema)
            messages.insert(0, {"role": "system", "content": hint_text.strip()})
            logger.debug(
                "Claude HINT mode for '%s': no system message found, "
                "synthesized one with HINT block",
                output_type_name or "Response",
            )
            # Keep model_params["messages"] in sync — messages may be a
            # fresh list reference if the caller passed an empty/missing list.
            model_params["messages"] = messages

        # Internal flags read by _provider_agentic_loop. Prefixed with
        # "_mesh_" so the loop strips them before calling LiteLLM (these
        # are NOT API params).
        # Fallback timeout: 30s was too tight for complex nested schemas
        # (e.g. list[NestedModel] where Claude generates multi-day itineraries).
        # Configurable via MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT (seconds).
        # Fail-open on a malformed env value so a typo can't break the
        # provider mid-request — log a warning and use the default.
        _raw_timeout = os.environ.get("MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT")
        if _raw_timeout is None:
            fallback_timeout = 90
        else:
            try:
                fallback_timeout = int(_raw_timeout)
            except ValueError:
                logger.warning(
                    "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT=%r is not an integer; "
                    "using default 90s",
                    _raw_timeout,
                )
                fallback_timeout = 90
            else:
                if fallback_timeout <= 0:
                    logger.warning(
                        "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT=%r must be positive; "
                        "using default 90s",
                        _raw_timeout,
                    )
                    fallback_timeout = 90
        model_params["_mesh_hint_mode"] = True
        model_params["_mesh_hint_schema"] = sanitized_schema
        model_params["_mesh_hint_fallback_timeout"] = fallback_timeout
        model_params["_mesh_hint_output_type_name"] = output_type_name or "Response"

        # Explicitly DO NOT set response_format — that's the bug we're avoiding.
        model_params.pop("response_format", None)

        logger.info(
            "Claude HINT mode for '%s' (mesh delegation, schema in prompt; "
            "loop will fall back to response_format if parse fails)",
            output_type_name or "Response",
        )
        return model_params

    def _apply_native_synthetic_format(
        self,
        sanitized_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply structured output via the synthetic-tool pattern (native SDK).

        Stashes the synthetic tool definition + name in ``model_params`` as
        ``_mesh_synthetic_format_*`` sentinels (mirrors the existing
        ``_mesh_hint_*`` flag pattern). The agentic loop in
        ``mesh.helpers._provider_agentic_loop`` reads these sentinels and:

          1. Appends the synthetic tool to the user's tool list.
          2. Sets ``tool_choice="auto"`` when there are real user tools, or
             forces the synthetic tool when there are none (small perf win,
             deterministic single call).
          3. Recognizes a tool_call with this name as the final structured
             answer and terminates the loop, surfacing the JSON arguments
             as ``message.content``.

        This mirrors the TS (Vercel AI SDK) and Java (Spring AI) patterns:
        single LLM call per iteration, both real tools AND synthetic format
        tool in the tools list, ``tool_choice="auto"``, model decides which
        to call.
        """
        # Augment the first system message with the "must call this tool"
        # instruction. Without this, Claude often returns a plain text final
        # answer and skips the synthetic tool entirely (especially on simple
        # questions where the model thinks tool_use is unnecessary).
        messages = model_params.get("messages", [])
        instruction_inserted = False
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                # Tolerate string OR content-block list (post-prompt-cache).
                if isinstance(base_content, str):
                    msg["content"] = base_content + SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION
                elif isinstance(base_content, list):
                    # Append a text block with the instruction; cache_control
                    # on the original blocks is preserved (we don't touch them).
                    msg["content"] = base_content + [
                        {
                            "type": "text",
                            "text": SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n"),
                        }
                    ]
                instruction_inserted = True
                break

        if not instruction_inserted:
            # No system message — synthesize one. Without it the model would
            # never see the "must call this tool" rule and structured output
            # would silently degrade to plain-text answers.
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n"),
                },
            )
            model_params["messages"] = messages

        # Build the synthetic tool. Stored as the OpenAI/litellm tool shape
        # so the upstream `_convert_tools` translator in anthropic_native
        # picks it up uniformly with user tools — no special-casing.
        synthetic_tool = {
            "type": "function",
            "function": {
                "name": SYNTHETIC_FORMAT_TOOL_NAME,
                "description": SYNTHETIC_FORMAT_TOOL_DESCRIPTION,
                "parameters": sanitized_schema,
            },
        }

        # Stash sentinels for the agentic loop. Prefixed ``_mesh_`` so the
        # adapter's WARN-filter and ``_pop_mesh_*`` helpers know to strip
        # them before reaching anthropic.messages.create.
        model_params["_mesh_synthetic_format_tool_name"] = SYNTHETIC_FORMAT_TOOL_NAME
        model_params["_mesh_synthetic_format_tool"] = synthetic_tool
        model_params["_mesh_synthetic_format_output_type_name"] = (
            output_type_name or "Response"
        )

        # Native path uses synthetic tool — make sure no LiteLLM-only knobs
        # leak through (defense-in-depth; both response_format and HINT flags
        # would confuse the loop).
        model_params.pop("response_format", None)
        for hint_key in (
            "_mesh_hint_mode",
            "_mesh_hint_schema",
            "_mesh_hint_fallback_timeout",
            "_mesh_hint_output_type_name",
        ):
            model_params.pop(hint_key, None)

        logger.info(
            "Claude native synthetic-tool mode for '%s' (mesh delegation; "
            "tool_choice=auto when real tools present, forced otherwise)",
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

    # ------------------------------------------------------------------
    # Native Anthropic SDK dispatch (issue #834, PR 1)
    # ------------------------------------------------------------------
    # Default ON when the anthropic SDK is importable. Set
    # ``MCP_MESH_NATIVE_LLM=0`` (or false/no/off) to force the LiteLLM
    # fallback path. When the SDK is missing, ``has_native()`` returns
    # False and the call sites in mesh.helpers fall back to LiteLLM with
    # a one-time INFO log nudging the user toward
    # ``pip install mcp-mesh[anthropic]``.

    def has_native(self) -> bool:
        """Native dispatch is enabled by default when the anthropic SDK is
        importable. Set ``MCP_MESH_NATIVE_LLM=0`` (or ``false``/``no``/``off``)
        to disable and force the LiteLLM fallback path. Setting the flag to
        ``1``/``true``/``yes``/``on`` is accepted as an explicit-enable
        (same behavior as the default).
        """
        # Emit the one-time dispatch-status DEBUG log. Lazy here (vs. at
        # module/handler init) so it fires when the first dispatch decision
        # is actually made — the most useful signal for ``--debug`` runs.
        _log_dispatch_status_once()

        flag = os.environ.get("MCP_MESH_NATIVE_LLM", "").strip().lower()
        # Explicit opt-out wins over SDK availability.
        if flag in ("0", "false", "no", "off"):
            return False

        # Lazy import inside the function so module import does not fail
        # when the SDK is absent; this mirrors what the call sites do.
        from _mcp_mesh.engine.native_clients import anthropic_native

        if not anthropic_native.is_available():
            anthropic_native.log_fallback_once()
            return False

        return True

    async def complete(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a buffered completion to the native Anthropic SDK adapter."""
        from _mcp_mesh.engine.native_clients import anthropic_native

        return await anthropic_native.complete(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )

    async def complete_stream(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ):
        """Dispatch a streaming completion to the native Anthropic SDK adapter."""
        from _mcp_mesh.engine.native_clients import anthropic_native

        return anthropic_native.complete_stream(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )
