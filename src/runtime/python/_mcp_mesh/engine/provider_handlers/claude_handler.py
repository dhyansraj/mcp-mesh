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
    make_schema_strict,
    normalize_output_mode_override,
    render_dispatch_status_log,
    sanitize_schema_for_structured_output,
)

logger = logging.getLogger(__name__)

# Output mode constants
OUTPUT_MODE_STRICT = (
    "strict"  # Unused for Claude (kept for override_mode compatibility)
)
OUTPUT_MODE_HINT = "hint"
OUTPUT_MODE_TEXT = "text"

# Re-exported from .._structured_output_helpers for backwards compatibility
# with any external imports (e.g. tests/test_claude_handler_native.py). The
# single source of truth lives in the shared module so adapter-side
# response_format translation (anthropic_native._build_create_kwargs) and
# this handler stay byte-identical on the wire.
from .._structured_output_helpers import (  # noqa: F401
    SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION,
    SYNTHETIC_FORMAT_TOOL_DESCRIPTION,
    SYNTHETIC_FORMAT_TOOL_NAME,
    append_synthetic_system_instruction,
    filter_anthropic_output_schema,
    schema_to_synthetic_tool,
)

# Single source of truth for every ``_mesh_*`` structured-output sentinel that
# the three Claude modes (HINT / synthetic-tool / output_config) may stamp on
# ``model_params``. Each mode clears ALL sentinels EXCEPT its own before
# stamping — this cross-mode defense-in-depth prevents a stale sentinel from a
# prior code path leaking into another mode and confusing the agentic loop's
# recognition logic. Centralizing the list keeps the clear-scopes in lockstep.
_HINT_SENTINELS = (
    "_mesh_hint_mode",
    "_mesh_hint_schema",
    "_mesh_hint_fallback_timeout",
    "_mesh_hint_output_type_name",
)
_SYNTHETIC_SENTINELS = (
    "_mesh_synthetic_format_tool_name",
    "_mesh_synthetic_format_tool",
    "_mesh_synthetic_format_output_type_name",
)
_OUTPUT_CONFIG_SENTINELS = (
    "_mesh_output_config_mode",
    "_mesh_output_config_schema",
    "_mesh_output_config_output_type_name",
)
def _clear_structured_output_sentinels(
    model_params: dict[str, Any], *keys: str
) -> None:
    """Pop the given structured-output sentinels from ``model_params``.

    Call sites pass the sentinel tuples (``_HINT_SENTINELS`` /
    ``_SYNTHETIC_SENTINELS`` / ``_OUTPUT_CONFIG_SENTINELS``) so the exact
    cross-mode clear-scope each mode had before centralization is preserved —
    the only change is that the key lists now have a single source of truth.
    """
    for key in keys:
        model_params.pop(key, None)


# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in anthropic_native. The
# registry caches a singleton handler per vendor
# (``ProviderHandlerRegistry._instances``), so an instance-level flag would
# already dedupe across requests — we keep the state at module level so the
# dedupe survives even if the singleton is ever rebuilt, and to match the
# native-client modules' module-level fallback flag.
_DISPATCH_STATUS_LOGGED = False


def is_dispatch_status_logged() -> bool:
    """Return True once the one-time dispatch-status log has fired.

    Exposed so ``has_native()`` can skip the call frame for
    ``_log_dispatch_status_once`` on every dispatch decision after the
    first — the function dedupes internally, but on the hot path
    avoiding the call entirely is cheaper. Mirrors ``is_fallback_logged``
    on the native-client modules.
    """
    return _DISPATCH_STATUS_LOGGED


def _anthropic_sdk_version() -> str:
    """Probe the installed anthropic SDK version for the dispatch-status log."""
    try:
        import anthropic
        return getattr(anthropic, "__version__", "<unknown>")
    except Exception:
        return "<import-failed>"


def _log_dispatch_status_once() -> None:
    """Log the resolved native-dispatch status once per process at DEBUG level.

    Designed so users running with ``meshctl ... --debug`` can confirm whether
    a Claude provider agent is using the native anthropic SDK or falling back
    to LiteLLM. Fires on first call only; subsequent invocations are no-ops.

    The rendered text is delegated to the shared base helper but the latch +
    logger stay module-local so the DEBUG record is attributed to this module
    and tests can re-arm the once-guard.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    from _mcp_mesh.engine.native_clients import anthropic_native

    render_dispatch_status_log(
        logger,
        vendor_label="Claude",
        sdk_display="anthropic",
        install_extra="anthropic",
        native_module=anthropic_native,
        version_probe=_anthropic_sdk_version,
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

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
        *,
        streaming: bool = False,
        model: str | None = None,
        output_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Apply Claude-specific structured output for mesh delegation.

        Three paths, selected by model + ``has_native()`` + ``streaming``:

        - Native ``output_config`` path (Sonnet 4.5+ / Opus 4.1+, buffered,
          ``has_native()``): Set ``response_format`` directly in
          ``model_params``; the native adapter's
          ``_build_create_kwargs`` translates it to Anthropic's first-class
          ``output_config.format`` primitive. No synthetic-tool injection,
          no extra tool slot, no system-prompt addendum — the API enforces
          the schema directly. Stamps ``_mesh_output_config_mode = True``
          so the agentic loop knows to skip synthetic-fallback recovery
          (the returned TextBlock IS the structured JSON).

        - Native synthetic-tool path (issue #834, older Claude models
          buffered, or any model when ``output_config`` is unavailable):
          Append a synthetic ``__mesh_format_response`` tool with the
          schema as ``input_schema`` and let Claude pick between real
          tools and the synthetic tool with ``tool_choice="auto"``. The
          agentic loop terminates when the synthetic tool is called.
          Mirrors the TS (Vercel AI SDK) and Java (Spring AI) runtimes.

        - LiteLLM path (set ``MCP_MESH_NATIVE_LLM=0`` to force, or used
          automatically when the SDK is missing, OR for streaming on any
          model): HINT mode (prompt injection). Claude's native
          ``response_format`` path silently hangs (600s+) on certain
          content + tools combinations (issue #820), so we inject schema
          instructions into the system prompt and let the agentic loop
          validate the final response. If validation fails, the loop
          falls back to a bounded-timeout ``response_format`` call.

        Set ``MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT=true`` to revert the
        LiteLLM path to native response_format-first (delegates to base
        impl). The flag is a no-op on the native paths — synthetic-tool
        and ``output_config`` modes are the canonical native behavior.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "TripPlan")
            model_params: Current model parameters dict (will be modified)
            streaming: When True, route capable models (Sonnet 4.5+ /
                Opus 4.1+) to native ``output_config`` (it streams as
                ``text_delta`` chunks) and older models to HINT (synthetic-tool
                doesn't chunk). See note below.
            model: Effective LiteLLM-style model id (e.g.
                ``anthropic/claude-sonnet-4-6``). Used to gate the native
                ``output_config`` branch — Sonnet 4.5+ / Opus 4.1+ accept the
                primitive; older models route to synthetic-tool injection.
            output_mode: Consumer-supplied structured-output mode override
                (finding #6). When set and valid it fully replaces the
                capability resolver's auto-selection, mapping onto Claude's
                EXISTING mode branches:

                - ``"strict"`` → Claude's native server-enforced
                  ``output_config.format`` branch (Sonnet 4.5+ / Opus 4.1+ on
                  the native SDK). When the model/SDK cannot server-enforce a
                  schema (older model, no native SDK), Claude has no
                  server-side primitive, so it falls back to its safe auto
                  default (synthetic-tool / HINT) with a warning — mirroring
                  Gemini's strict-fallback.
                - ``"hint"`` → prose HINT (schema embedded in the system
                  prompt). This is Claude's usual auto choice on the LiteLLM /
                  older-model paths.
                - ``"text"`` → no schema enforcement (no ``response_format``,
                  no synthetic tool, no HINT; all structured-output sentinels
                  cleared).

                Invalid override → ignored (warning logged) + auto-selection.
                None/unset → identical to today's resolver-driven auto behavior
                (no regression).

        Returns:
            Modified model_params with mode-specific flags + injected
            system prompt
        """
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)

        normalized = normalize_output_mode_override(
            output_mode, vendor_label="Claude", handler_logger=logger
        )

        if normalized == "text":
            # No schema enforcement: emit plain text. Drop response_format and
            # clear every structured-output sentinel so neither the HINT path,
            # the synthetic-tool path, nor output_config is engaged.
            model_params.pop("response_format", None)
            _clear_structured_output_sentinels(
                model_params,
                *_HINT_SENTINELS,
                *_SYNTHETIC_SENTINELS,
                *_OUTPUT_CONFIG_SENTINELS,
            )
            logger.info(
                "Claude TEXT mode for '%s' (output_mode='text' override; "
                "no schema enforcement)",
                output_type_name or "Response",
            )
            return model_params

        if normalized == "hint":
            # Prose HINT: schema in prompt, response_format dropped. The shared
            # base helper performs the inject/synthesize/stamp work and pops
            # response_format; Claude uses ``support_content_blocks=True`` so the
            # post-prompt-cache content-block list shape is tolerated.
            self.apply_prose_hint(
                model_params,
                sanitized_schema,
                output_type_name,
                support_content_blocks=True,
                logger=logger,
            )
            logger.info(
                "Claude HINT mode for '%s' (output_mode='hint' override; "
                "schema in prompt, response_format dropped)",
                output_type_name or "Response",
            )
            return model_params

        # Centralized mode selection (RFC #1100). The resolver owns the full
        # decision:
        #   - BaseModel + native + capable model (Sonnet 4.5+ / Opus 4.1+) →
        #     OUTPUT_CONFIG, for BOTH buffered and streaming. On streaming,
        #     ``client.messages.stream`` accepts ``output_config`` and the
        #     structured JSON arrives as ordinary ``text_delta`` chunks that
        #     accumulate into the final ``TextBlock`` (RFC #1100 follow-up).
        #   - BaseModel + native + older model, buffered → SYNTHETIC_TOOL.
        #   - BaseModel + native + older model, streaming → PROSE_HINT
        #     (synthetic-tool injection produces a single forced tool call that
        #     arrives discrete, not chunked — it doesn't actually stream).
        #   - no-native (LiteLLM) → PROSE_HINT.
        # HINT mode emits JSON as plain text which flows naturally through
        # stream chunks; the existing HINT-fallback machinery handles parse
        # failures. The mode-implementation bodies are unchanged — we only
        # switch on the resolved mode here.
        from .capabilities import StructuredOutputMode, resolve_capabilities

        caps = resolve_capabilities(
            self.vendor,
            model,
            output_is_basemodel=True,
            has_native=self.has_native(),
            streaming=streaming,
        )

        if normalized == "strict" and (
            caps.structured_output != StructuredOutputMode.OUTPUT_CONFIG
        ):
            # OUTPUT_CONFIG is Claude's only server-enforced ("strict")
            # structured-output primitive, and the resolver only selects it for
            # capable models (Sonnet 4.5+ / Opus 4.1+) on the native SDK. When
            # it is unavailable (older model, no native SDK), Claude cannot
            # server-enforce a schema, so fall back to its safe auto default
            # (synthetic-tool / HINT) with a warning rather than hard-failing —
            # mirroring Gemini's strict-fallback.
            logger.warning(
                "Claude: output_mode='strict' requested for '%s' but the "
                "model/SDK do not support server-enforced output_config "
                "(requires Sonnet 4.5+ / Opus 4.1+ on the native anthropic "
                "SDK); falling back to the safe default (%s).",
                output_type_name or "Response",
                caps.structured_output,
            )

        if caps.structured_output == StructuredOutputMode.OUTPUT_CONFIG:
            # Sonnet 4.5+ / Opus 4.1+ accept Anthropic's first-class
            # ``output_config.format`` primitive. Cheaper than the synthetic-
            # tool path (no extra tool slot, no system-prompt addendum, no
            # agentic-loop tool_use→JSON unwrap) and enforced by the API
            # rather than by a tool/prompt hint. The native adapter's
            # ``_build_create_kwargs`` translates ``response_format`` →
            # ``output_config`` for allow-listed models; we stamp
            # ``_mesh_output_config_mode`` so the agentic loop knows the
            # returned TextBlock IS the structured JSON answer (no
            # synthetic-tool unwrap, no synthetic-fallback recovery).
            return self._apply_native_output_config(
                sanitized_schema, output_type_name, model_params
            )
        if caps.structured_output == StructuredOutputMode.SYNTHETIC_TOOL:
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
                output_schema, output_type_name, model_params, streaming=streaming
            )

        # Inject HINT instructions into the first system message.
        # Mesh delegation always involves tools, and Claude's response_format
        # path silently hangs on certain content+tools combos (issue #820),
        # so we cannot use it here. The shared base helper performs the
        # inject/synthesize/stamp work and pops response_format; Claude uses
        # ``support_content_blocks=True`` so the system message's post-prompt-
        # cache content-block list shape is tolerated (a NEW text block is
        # appended, preserving the original blocks' cache_control).
        # Fallback timeout (stamped by the helper): configurable via
        # MCP_MESH_HINT_FALLBACK_TIMEOUT (seconds); the legacy
        # MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT remains as a back-compat alias
        # with a deprecation warning.
        self.apply_prose_hint(
            model_params,
            sanitized_schema,
            output_type_name,
            support_content_blocks=True,
            logger=logger,
        )

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
        #
        # IMPORTANT: build a NEW messages list and a NEW system message dict
        # rather than mutating the caller's. The caller's reference to the
        # list is shared across iterations / requests; in-place reassignment
        # via ``messages[idx] = new_msg`` or ``messages.insert(0, ...)``
        # would surface to the caller and could re-inject the instruction
        # on subsequent reuse (see issue #834 review-round-2). The new list
        # is wired back through ``model_params["messages"]`` so the agentic
        # loop sees the augmented version.
        original_messages = model_params.get("messages", [])
        new_messages: list[dict[str, Any]] = list(original_messages)
        instruction_inserted = False
        for idx, msg in enumerate(new_messages):
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                new_msg: dict[str, Any] = {**msg}
                # Tolerate string OR content-block list (post-prompt-cache).
                if isinstance(base_content, str):
                    new_msg["content"] = append_synthetic_system_instruction(
                        base_content
                    )
                elif isinstance(base_content, list):
                    # Build a NEW list (don't mutate the caller's). Original
                    # block dicts pass through by reference — that's fine,
                    # we're not modifying their cache_control.
                    new_msg["content"] = list(base_content) + [
                        {
                            "type": "text",
                            "text": SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n"),
                        }
                    ]
                else:
                    # Unknown content shape — leave the dict as-is (best effort).
                    new_msg["content"] = base_content
                new_messages[idx] = new_msg
                instruction_inserted = True
                break

        if not instruction_inserted:
            # No system message — synthesize one. Without it the model would
            # never see the "must call this tool" rule and structured output
            # would silently degrade to plain-text answers.
            new_messages.insert(
                0,
                {
                    "role": "system",
                    "content": SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n"),
                },
            )

        # Wire the new list back into model_params so the agentic loop sees
        # the augmented messages. The caller's original list reference is
        # left untouched.
        model_params["messages"] = new_messages

        # Build the synthetic tool. Stored as the OpenAI/litellm tool shape
        # so the upstream `_convert_tools` translator in anthropic_native
        # picks it up uniformly with user tools — no special-casing.
        synthetic_tool = schema_to_synthetic_tool(sanitized_schema)

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
        _clear_structured_output_sentinels(model_params, *_HINT_SENTINELS)

        logger.info(
            "Claude native synthetic-tool mode for '%s' (mesh delegation; "
            "tool_choice=auto when real tools present, forced otherwise)",
            output_type_name or "Response",
        )
        return model_params

    def _apply_native_output_config(
        self,
        sanitized_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply structured output via Anthropic's native ``output_config``.

        Sonnet 4.5+ / Opus 4.1+ accept ``output_config.format`` as a first-
        class structured-output primitive. We forward the schema by setting
        ``response_format`` (LiteLLM shape); the native Anthropic adapter's
        ``_build_create_kwargs`` translates it to the ``output_config`` wire
        shape for allow-listed models. No synthetic tool is injected, no
        ``__mesh_format_response`` system addendum is added, and no extra
        tool slot is consumed. The API enforces the schema directly and
        returns the structured answer as a plain ``TextBlock``.

        Stamps ``_mesh_output_config_mode = True`` (and the schema) as
        sentinels so ``_provider_agentic_loop``:
          1. Pops them before reaching ``messages.create``.
          2. Skips synthetic-fallback recovery on the "no tool calls"
             branch — the text content IS the structured answer.

        Schema must be strict-ified: Anthropic's ``output_config`` endpoint
        requires ``additionalProperties: false`` on every object-typed schema
        node (unlike the synthetic-tool path, where tool ``input_schema`` is
        more lenient). ``add_all_required=False`` matches Anthropic's
        looser ``required`` semantics — only the ``additionalProperties``
        injection is needed.

        ``maxItems`` / ``minItems`` are then stripped via
        ``filter_anthropic_output_schema`` — Anthropic's native
        ``output_config.format`` rejects those keys (issue #19444). The
        adapter applies the same filter before placing the schema on the
        wire; running it here too means ``_mesh_output_config_schema``
        matches the on-wire shape exactly, so the loop's defense-in-depth
        parse check doesn't WARN about responses that violate maxItems /
        minItems constraints Anthropic never enforced.
        """
        strict_schema = make_schema_strict(sanitized_schema, add_all_required=False)
        wire_schema = filter_anthropic_output_schema(strict_schema)
        model_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_type_name or "Response",
                "schema": wire_schema,
                "strict": True,
            },
        }
        model_params["_mesh_output_config_mode"] = True
        model_params["_mesh_output_config_schema"] = wire_schema
        model_params["_mesh_output_config_output_type_name"] = (
            output_type_name or "Response"
        )

        # Defense-in-depth: ``output_config`` mode is mutually exclusive with
        # HINT and synthetic-tool modes. Clear any leftover sentinels from a
        # prior code path so the loop's recognition logic stays deterministic.
        _clear_structured_output_sentinels(
            model_params, *_HINT_SENTINELS, *_SYNTHETIC_SENTINELS
        )

        logger.info(
            "Claude native output_config mode for '%s' (mesh delegation; "
            "Anthropic enforces schema via output_config.format)",
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
    #
    # ``has_native()`` / ``complete()`` / ``complete_stream()`` are inherited
    # from BaseProviderHandler, driven by the one-line ``_native_module()`` hook
    # below (plus label/version for the dispatch-status log).

    def _native_module(self):
        # Lazy import inside the method so module import does not fail when the
        # SDK is absent; this mirrors what the call sites do.
        from _mcp_mesh.engine.native_clients import anthropic_native

        return anthropic_native

    def _native_label(self) -> str:
        return "Claude"

    def _log_dispatch_status(self) -> None:
        # Skip the call entirely once the log has fired — the function dedupes
        # internally, but avoiding the call frame on the hot path is cheaper.
        if not is_dispatch_status_logged():
            _log_dispatch_status_once()
