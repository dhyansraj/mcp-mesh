"""
Helper decorators for common mesh patterns.

This module provides convenience decorators that build on top of the core
mesh decorators to simplify common patterns like zero-code LLM providers.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import jsonschema  # type: ignore

from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry
from _mcp_mesh.shared.logging_config import format_log_value

logger = logging.getLogger(__name__)


def _hint_response_parses(content: str, schema: dict[str, Any]) -> bool:
    """Validate that ``content`` is JSON-parseable and conforms to ``schema``.

    Used after Claude HINT mode to decide whether to fall back to native
    response_format. Tolerant of fenced code blocks (Claude HINT can wrap
    JSON in ``\u0060\u0060\u0060json...\u0060\u0060\u0060``) — strip them before parsing.

    If ``jsonschema`` is not installed, only JSON parseability is checked.
    """
    if not content:
        return False
    try:
        cleaned = content.strip()
        # Strip surrounding markdown code fences if present.
        # Handle both ```json\n...\n``` and ```\n...\n``` patterns.
        cleaned = re.sub(
            r"^```(?:json)?\s*\n?", "", cleaned, count=1
        )
        cleaned = re.sub(r"\n?```\s*$", "", cleaned, count=1)
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return False

    try:
        import jsonschema  # type: ignore

        try:
            jsonschema.validate(instance=parsed, schema=schema)
            return True
        except jsonschema.ValidationError:
            return False
    except ImportError:
        # jsonschema not available — JSON parseability is the best we can do.
        return True


# Internal mesh control flags set by provider handlers (e.g., ClaudeHandler
# HINT mode) and consumed by the loop / legacy paths in this module. They MUST
# be stripped from completion_args before any litellm.completion call —
# otherwise providers like Anthropic reject the request with HTTP 400
# ("Extra inputs are not permitted").
_MESH_HINT_KEYS = (
    "_mesh_hint_mode",
    "_mesh_hint_schema",
    "_mesh_hint_fallback_timeout",
    "_mesh_hint_output_type_name",
)

# Single source of truth for the HINT → response_format fallback timeout when
# a handler did not explicitly inject one. ClaudeHandler now defaults to 90s
# (configurable via MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT) — keep this in
# sync so loop paths that bypass the handler don't silently revert to 30.
_DEFAULT_HINT_FALLBACK_TIMEOUT = 90


# Per-vendor dedupe set for the "native dispatch claims unknown vendor" WARN.
# Keyed by vendor name so each unique vendor produces exactly one log line per
# process, even though the dispatch path is hit once per agentic-loop iteration.
_logged_unknown_native_vendors: set[str] = set()


def _warn_native_dispatch_unknown_vendor_once(vendor: str) -> None:
    """Emit a one-time WARN when native dispatch reports a vendor that has no
    formatter in ``mesh.media.resolver._VENDOR_FORMATTERS``.

    Symptom this catches: a new native handler is wired up (advertises
    ``has_native=True`` for some vendor X) but the matching emitter formatter
    in the resolver is never added. The resource_link resolver would then
    silently fall back to OpenAI shape on a path that explicitly asked for
    vendor-native shape — i.e., the very misconfiguration #860 introduced
    upstream emission to surface.
    """
    if vendor in _logged_unknown_native_vendors:
        return
    _logged_unknown_native_vendors.add(vendor)
    logger.warning(
        "Native dispatch reports vendor=%r but %r has no entry in "
        "_VENDOR_FORMATTERS; falling back to OpenAI-shape blocks. "
        "Add a formatter to mesh.media.resolver._VENDOR_FORMATTERS to "
        "emit vendor-native shape on the native path.",
        vendor, vendor,
    )


def _pop_mesh_hint_flags(
    completion_args: dict[str, Any],
    defaults: tuple[bool, dict | None, int, str] = (
        False,
        None,
        _DEFAULT_HINT_FALLBACK_TIMEOUT,
        "Response",
    ),
) -> tuple[bool, dict | None, int, str]:
    """Strip ``_mesh_*`` HINT-mode flags from ``completion_args`` in place.

    Returns the captured ``(hint_mode, hint_schema, hint_fallback_timeout,
    hint_output_type_name)`` so callers can use them to drive the post-call
    fallback. Defaults preserve existing values across loop iterations.
    """
    hint_mode_default, hint_schema_default, hint_timeout_default, hint_name_default = defaults
    hint_mode = bool(completion_args.pop("_mesh_hint_mode", hint_mode_default))
    hint_schema = completion_args.pop("_mesh_hint_schema", hint_schema_default)
    hint_fallback_timeout = completion_args.pop(
        "_mesh_hint_fallback_timeout", hint_timeout_default
    )
    hint_output_type_name = completion_args.pop(
        "_mesh_hint_output_type_name", hint_name_default
    )
    return hint_mode, hint_schema, hint_fallback_timeout, hint_output_type_name


# ---------------------------------------------------------------------------
# Synthetic-format-tool flags (issue #834, native Anthropic SDK path)
# ---------------------------------------------------------------------------
# Set by ClaudeHandler.apply_structured_output when on the native path. Read
# by the agentic loops in this module. Like the HINT keys above, they MUST be
# stripped before any LLM call so they don't leak into the wire request.

_MESH_SYNTHETIC_FORMAT_KEYS = (
    "_mesh_synthetic_format_tool_name",
    "_mesh_synthetic_format_tool",
    "_mesh_synthetic_format_output_type_name",
)


def _pop_mesh_synthetic_format_flags(
    completion_args: dict[str, Any],
    defaults: tuple[str | None, dict | None, str] = (None, None, "Response"),
) -> tuple[str | None, dict | None, str]:
    """Strip ``_mesh_synthetic_format_*`` flags from ``completion_args`` in place.

    Returns ``(synthetic_tool_name, synthetic_tool, output_type_name)``. The
    tool name is the recognition key for the agentic loop ("call to this name
    means the model is signalling its final structured answer"). The tool is
    the OpenAI-shape function dict to splice into the tools list. Defaults
    preserve values across iterations (handlers stamp once per request).
    """
    name_default, tool_default, type_name_default = defaults
    name = completion_args.pop("_mesh_synthetic_format_tool_name", name_default)
    tool = completion_args.pop("_mesh_synthetic_format_tool", tool_default)
    type_name = completion_args.pop(
        "_mesh_synthetic_format_output_type_name", type_name_default
    )
    return name, tool, type_name


# ---------------------------------------------------------------------------
# Native output_config flags (Anthropic Sonnet 4.5+ / Opus 4.1+)
# ---------------------------------------------------------------------------
# Set by ClaudeHandler.apply_structured_output when on the native ``output_config``
# path. Sentinel for "the model is going to return the structured answer as a
# plain TextBlock — do NOT run synthetic-fallback recovery on the no-tool-calls
# branch; the text content IS the answer". Like the other mesh keys above,
# they MUST be stripped before any LLM call so they don't leak into the wire
# request.

_MESH_OUTPUT_CONFIG_KEYS = (
    "_mesh_output_config_mode",
    "_mesh_output_config_schema",
    "_mesh_output_config_output_type_name",
)


def _pop_mesh_output_config_flags(
    completion_args: dict[str, Any],
    defaults: tuple[bool, dict | None, str] = (False, None, "Response"),
) -> tuple[bool, dict | None, str]:
    """Strip ``_mesh_output_config_*`` flags from ``completion_args`` in place.

    Returns ``(output_config_mode, output_config_schema, output_type_name)``.
    The schema is captured for an optional defense-in-depth parse check on
    the returned text (logged WARN-only — no retry, mirroring the framework
    principle of not forcing the model after it has answered).
    """
    mode_default, schema_default, type_name_default = defaults
    mode = bool(completion_args.pop("_mesh_output_config_mode", mode_default))
    schema = completion_args.pop("_mesh_output_config_schema", schema_default)
    type_name = completion_args.pop(
        "_mesh_output_config_output_type_name", type_name_default
    )
    return mode, schema, type_name


def _inject_synthetic_format_tool(
    tools: list[dict[str, Any]] | None,
    synthetic_tool: dict[str, Any],
    completion_args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Append the synthetic format tool to ``tools`` and set ``tool_choice``.

    Returns a NEW list (never mutates the caller's). If user has zero real
    tools (excluding the synthetic), force ``tool_choice`` to the synthetic
    tool — saves one round-trip and is fully deterministic. Otherwise use
    ``"auto"`` so Claude can keep invoking real tools across iterations and
    only pick the synthetic when it's done gathering data (matches TS/Java
    pattern).

    Idempotent. The agentic loops call this helper once per iteration; if
    the caller persists the augmented list across iterations, the synthetic
    is detected and the helper skips both the re-append AND the override
    WARN. Without this guard the WARN spams 5-10 times per request for
    typical multi-turn structured-output runs (the value at
    ``completion_args["tool_choice"]`` on iter 2+ is the value WE set on
    iter 1, not a real caller override).

    If the caller (or upstream) had already set ``tool_choice`` AND the
    synthetic is not yet present (real first-iteration override), it is
    silently taken over — synthetic format injection requires the model to
    be able to invoke our synthetic tool, so we must control this knob. A
    WARN is logged so the override is at least visible in observability.
    """
    real_tools = list(tools or [])
    synthetic_name = synthetic_tool.get("function", {}).get("name")
    already_injected = any(
        isinstance(t, dict)
        and t.get("function", {}).get("name") == synthetic_name
        for t in real_tools
    )
    prior_choice = completion_args.get("tool_choice")
    if prior_choice is not None and not already_injected:
        logger.warning(
            "Synthetic format injection overriding caller-supplied "
            "tool_choice (was: %r). Structured output requires controlling "
            "tool_choice so the synthetic format tool can be invoked.",
            prior_choice,
        )
    # User-supplied real tools = everything except the synthetic. Used for
    # both the no-tools→forced-synthetic decision and to ensure the helper
    # is idempotent when called with an already-augmented list.
    user_real_tools = [
        t for t in real_tools
        if not (isinstance(t, dict)
                and t.get("function", {}).get("name") == synthetic_name)
    ]
    augmented = user_real_tools + [synthetic_tool]
    if not user_real_tools:
        # No real tools — force the synthetic. Single round-trip, deterministic.
        completion_args["tool_choice"] = {
            "type": "function",
            "function": {"name": synthetic_tool["function"]["name"]},
        }
    else:
        completion_args["tool_choice"] = "auto"
    return augmented


def _build_assistant_tool_call_dict(tc: Any) -> dict[str, Any]:
    """Serialize one ``_ToolCall``-shape object into the conversation dict.

    Whitelists the four canonical fields (``id``, ``type``,
    ``function.name``, ``function.arguments``) plus one Gemini-only sidecar:
    ``_gemini_thought_signature`` (base64-encoded bytes) when present on the
    source object. The signature originates from Gemini 2.0+ thinking models
    that emit a Part-level ``thought_signature`` on each functionCall response
    Part — the Gemini API REQUIRES this signature to be echoed back on the
    next-turn functionCall of the same multi-turn conversation, otherwise
    rejecting with HTTP 400 ("Function call is missing a thought_signature").

    The Gemini native adapter (``gemini_native._adapt_response``) lifts the
    signature off the response Part and stores it on the synthesized
    ``_ToolCall._thought_signature`` attribute. We forward it onto the
    serialized dict here so that the next-iteration's
    ``gemini_native._convert_messages_to_gemini`` can recover it and place it
    back on the outbound functionCall Part. Other vendor adapters
    (anthropic_native, openai_native, litellm) never set the attribute; the
    sidecar is simply absent for them — fully backward-compatible.
    """
    out: dict[str, Any] = {
        "id": tc.id,
        "type": tc.type,
        "function": {
            "name": tc.function.name,
            "arguments": tc.function.arguments,
        },
    }
    # Strict ``bytes`` check — only the Gemini native adapter sets this attr
    # and only ever to bytes / None. MagicMock test doubles otherwise
    # auto-generate truthy attributes that aren't bytes-like and would break
    # the b64encode call below.
    sig = getattr(tc, "_thought_signature", None)
    if isinstance(sig, (bytes, bytearray)) and sig:
        import base64

        out["_gemini_thought_signature"] = base64.b64encode(sig).decode("ascii")
    return out


def _build_assistant_tool_call_dict_from_merged(tc: dict[str, Any]) -> dict[str, Any]:
    """Same as :func:`_build_assistant_tool_call_dict` but for the streaming
    merger's pre-coalesced dict shape.

    ``MeshLlmAgent._merge_streamed_tool_calls`` returns a list of dicts (not
    ``_ToolCall`` objects); the Gemini-only thought_signature is forwarded
    onto those dicts as ``_gemini_thought_signature`` (already base64-encoded)
    so this serializer just whitelist-passes-through. Other vendors don't set
    the key so the field is silently absent for them.
    """
    out: dict[str, Any] = {
        "id": tc["id"],
        "type": tc["type"],
        "function": {
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
        },
    }
    sig_b64 = tc.get("_gemini_thought_signature")
    if sig_b64:
        out["_gemini_thought_signature"] = sig_b64
    return out


def _extract_synthetic_format_arguments(
    message: Any,
    synthetic_tool_name: str,
) -> tuple[str | None, str | None]:
    """Return the synthetic tool's ``(args_json_str, tool_call_id)`` pair.

    Walks ``message.tool_calls`` (litellm/_MockMessage shape) looking for a
    call to the synthetic tool. Returns the raw ``function.arguments`` string
    (already JSON per the SDK contract) plus the ``tool_call_id`` that
    callers need for the corrective-retry tool_use round-trip (issue #961).
    When the model called real tools AND the synthetic in the same turn,
    the synthetic still wins — the model signaled "I'm done", and surfacing
    real-tool execution would defeat the point. Tolerant of malformed JSON:
    caller validates downstream. Returns ``(None, None)`` when the synthetic
    tool was not called.
    """
    tool_calls = getattr(message, "tool_calls", None) or []
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        if getattr(fn, "name", None) == synthetic_tool_name:
            args = getattr(fn, "arguments", None)
            tc_id = getattr(tc, "id", None)
            if args is None:
                return "{}", tc_id
            return (
                args if isinstance(args, str) else json.dumps(args),
                tc_id,
            )
    return None, None


async def _maybe_run_hint_fallback(
    *,
    final_content: str,
    message: Any,
    response: Any,
    base_completion_args: dict[str, Any],
    hint_mode: bool,
    hint_schema: dict[str, Any] | None,
    hint_fallback_timeout: int,
    hint_output_type_name: str,
    fallback_logger: logging.Logger | None = None,
    vendor: str | None = None,
) -> tuple[str, Any, Any]:
    """If HINT mode is active and ``final_content`` fails to parse against the
    schema, retry once with native ``response_format`` and a bounded
    ``request_timeout``.

    Returns ``(possibly-replaced final_content, message, response)``.

    Raises whatever the fallback ``litellm.completion`` raises if it fails —
    the caller is responsible for surfacing or wrapping. The original
    (HINT-mode) response is NOT retained on fallback failure: a fallback that
    errors means we couldn't recover, so re-raising is the cleanest signal.

    IMPORTANT: ``base_completion_args`` MUST already be stripped of the
    ``_mesh_*`` HINT keys AND of the ``tools`` key. The helper does NOT strip
    ``tools`` itself — that's the caller's responsibility. Stripping ``tools``
    matters because the fallback only fires AFTER the model returned final
    content with no tool_calls, and re-introducing the ``response_format +
    tools`` combo would re-create the silent-hang vector from issue #820.

    ``vendor`` is forwarded to :func:`_run_response_format_retry` so the
    retry can route directly through the vendor-native handler when the
    caller has the vendor in scope, avoiding brittle string-prefix
    extraction from ``base_completion_args["model"]``.
    """
    if not (hint_mode and hint_schema and final_content):
        return final_content, message, response

    if _hint_response_parses(final_content, hint_schema):
        return final_content, message, response

    if fallback_logger:
        fallback_logger.warning(
            "Claude HINT mode response failed to parse against output schema; "
            "retrying with native response_format (bounded request_timeout=%ss)",
            hint_fallback_timeout,
        )

    fb_content, fb_message, fallback_response = await _run_response_format_retry(
        base_completion_args=base_completion_args,
        schema=hint_schema,
        output_type_name=hint_output_type_name,
        fallback_timeout=hint_fallback_timeout,
        vendor=vendor,
    )

    if fallback_logger:
        fallback_logger.info("Claude HINT fallback to response_format succeeded")

    return (fb_content if fb_content else "", fb_message, fallback_response)


async def _run_response_format_retry(
    *,
    base_completion_args: dict[str, Any],
    schema: dict[str, Any],
    output_type_name: str,
    fallback_timeout: int,
    vendor: str | None = None,
) -> tuple[str, Any, Any]:
    """Single shared LLM retry that injects ``response_format`` + a bounded
    timeout. Used by BOTH the HINT-mode fallback and the native synthetic-tool
    fallback — the recovery shape is identical (rebuild args, strict-ify
    schema, dispatch through native handler or LiteLLM, return content).

    Caller MUST have already stripped ``tools``, ``tool_choice``, and any
    streaming flags from ``base_completion_args``. The helper only adds
    ``response_format`` and ``request_timeout``; it neither pops nor rewrites
    the rest.

    When ``vendor`` is supplied, native-handler resolution uses it directly;
    otherwise the helper falls back to extracting the vendor from
    ``base_completion_args["model"]`` (preserved for legacy callers).
    Explicit vendor plumbing avoids the brittle prefix-extraction path that
    skips native dispatch on bare model strings like ``"claude-haiku-4-5"``.

    Returns ``(content, message, response)``.
    """
    # Anthropic's structured output requires additionalProperties: false on every
    # object type in the schema. Pydantic-generated schemas don't include that by
    # default. The base apply_structured_output path already strict-ifies via
    # make_schema_strict; the legacy HINT fallback was missing the same step,
    # causing Anthropic's "output_format.schema: ... must be explicitly set to
    # false" rejection on complex schemas (nested BaseModels).
    #
    # add_all_required is per-vendor: OpenAI and Gemini require every property
    # in 'required'; Claude does not. Default to False for unknown/legacy
    # callers to preserve prior behavior.
    from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
        make_schema_strict,
    )

    add_all_required = vendor in ("openai", "gemini")
    strict_schema = make_schema_strict(schema, add_all_required=add_all_required)

    # Strip caller's timeout/request_timeout so the fallback's bounded retry
    # timeout actually wins downstream (the native adapter prefers caller's
    # ``timeout`` over ``request_timeout``).
    fallback_args = {
        k: v
        for k, v in base_completion_args.items()
        if k not in ("timeout", "request_timeout")
    }
    fallback_args["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": output_type_name,
            "schema": strict_schema,
            "strict": True,
        },
    }
    fallback_args["request_timeout"] = fallback_timeout
    # Lazy import keeps this module importable in environments without
    # litellm (e.g., during static analysis); both call sites already
    # import litellm before invoking this helper.
    import litellm

    # Native dispatch (issue #834, PR 1): if the vendor handler ships a
    # native SDK adapter and the feature flag is on, route through it.
    # Otherwise, fall back to LiteLLM (current default behavior).
    # ``vendor`` is preferred when the caller plumbed it in — prefix
    # extraction from ``model`` returns None for bare names like
    # ``claude-haiku-4-5`` and silently skips the native path.
    # (``ProviderHandlerRegistry`` is imported at module top.)
    fb_model = fallback_args.get("model")
    fb_vendor = vendor if vendor else (
        _extract_vendor_from_model(fb_model) if fb_model else None
    )
    fb_handler = (
        ProviderHandlerRegistry.get_handler(fb_vendor) if fb_vendor else None
    )
    if fb_handler is not None and fb_handler.has_native():
        fb_native_args = {
            k: v
            for k, v in fallback_args.items()
            if k not in ("model", "api_key", "base_url")
        }
        fallback_response = await fb_handler.complete(
            fb_native_args,
            model=fb_model,
            api_key=fallback_args.get("api_key"),
            base_url=fallback_args.get("base_url"),
        )
    else:
        fallback_response = await asyncio.to_thread(
            litellm.completion, **fallback_args
        )
    fb_message = fallback_response.choices[0].message
    # Native handlers return synthetic-tool args as tool_calls; LiteLLM unpacks
    # them to content. Lift here so callers see structured output regardless of
    # dispatch path. Falls through to text extraction for the LiteLLM shape and
    # the no-tool-call edge case.
    from _mcp_mesh.engine._structured_output_helpers import (
        SYNTHETIC_FORMAT_TOOL_NAME,
    )

    synthetic_args, _ = _extract_synthetic_format_arguments(
        fb_message, SYNTHETIC_FORMAT_TOOL_NAME
    )
    if synthetic_args is not None:
        fb_content = synthetic_args
    else:
        fb_content = _extract_text_from_message_content(fb_message.content)

    return (fb_content if fb_content else "", fb_message, fallback_response)


async def _maybe_run_synthetic_fallback(
    *,
    final_content: str,
    message: Any,
    response: Any,
    base_completion_args: dict[str, Any],
    synthetic_tool_name: str | None,
    synthetic_tool: dict[str, Any] | None,
    fallback_timeout: int,
    fallback_logger: logging.Logger | None = None,
    vendor: str | None = None,
) -> tuple[str, Any, Any]:
    """Recovery for the native synthetic-tool path when the model declines
    to call the synthetic tool and emits plain text instead.

    Mirrors :func:`_maybe_run_hint_fallback`. The native synthetic-tool path
    (issue #834) injects ``__mesh_format_response`` with the Pydantic schema
    as ``input_schema`` and lets the model choose between real tools and the
    synthetic with ``tool_choice="auto"``. On borderline content (long
    character roleplay, conversational turns near alignment ceilings) Haiku
    occasionally refuses the synthetic tool call entirely:
    ``stop_reason="end_turn"``, response is plain text, no ``tool_use``
    block. Without this fallback, the agentic loop would surface the
    model's hedge/refusal text raw to the caller as if it were the
    structured answer — the v2.0.0 native-dispatch refusal regression.

    Returns ``(possibly-replaced final_content, message, response)``.

    If the retry's response ALSO fails to parse against the schema, the
    retry's content is returned anyway — we don't loop. Single-shot
    recovery; further escalation is the caller's problem.

    IMPORTANT: ``base_completion_args`` MUST already be stripped of the
    synthetic-format keys, the ``tools`` key, AND the ``tool_choice`` key.
    The helper does not strip them itself. The retry uses
    ``response_format`` only; re-introducing tools or tool_choice would
    defeat the recovery (we WANT a forced-schema buffered call).
    """
    if not (synthetic_tool_name and synthetic_tool and final_content):
        return final_content, message, response

    # The synthetic tool stores the sanitized Pydantic schema as its
    # ``parameters`` field (OpenAI tool shape — see
    # ClaudeHandler._apply_native_synthetic_format).
    synthetic_schema = synthetic_tool.get("function", {}).get("parameters")
    if not synthetic_schema:
        return final_content, message, response

    if _hint_response_parses(final_content, synthetic_schema):
        if fallback_logger:
            fallback_logger.info(
                "Native synthetic-tool path: text response parses against "
                "schema; skipping fallback"
            )
        return final_content, message, response

    # The retry's output_type_name is best-effort: handlers stash the real
    # one via ``_mesh_synthetic_format_output_type_name``, but the caller
    # has already popped it and we don't strictly need it for behavior —
    # it's only the json_schema "name" field. Default mirrors the handler.
    output_type_name = "Response"

    if fallback_logger:
        fallback_logger.warning(
            "Native synthetic-tool path: model returned plain text without "
            "calling '%s'; retrying with native response_format (bounded "
            "request_timeout=%ss)",
            synthetic_tool_name,
            fallback_timeout,
        )

    fb_content, fb_message, fallback_response = await _run_response_format_retry(
        base_completion_args=base_completion_args,
        schema=synthetic_schema,
        output_type_name=output_type_name,
        fallback_timeout=fallback_timeout,
        vendor=vendor,
    )

    if fallback_logger:
        fallback_logger.info(
            "Native synthetic-tool fallback to response_format succeeded"
        )

    return (fb_content if fb_content else "", fb_message, fallback_response)


# Default cap on synthetic-tool corrective retries (issue #961). Set to 0 to
# disable; values > 1 are accepted but discouraged because the corrective
# prompt is bounded — additional iterations rarely buy more than the first.
_DEFAULT_SYNTHETIC_RETRY_MAX = 1


def _read_synthetic_retry_max(loop_logger: logging.Logger | None) -> int:
    """Parse ``MCP_MESH_LLM_SYNTHETIC_RETRY_MAX`` once with safe defaults.

    Negative or non-integer values fall back to the default (1) and emit a
    single WARN per call so that misconfiguration surfaces in logs without
    masking the retry feature entirely.
    """
    raw = os.environ.get("MCP_MESH_LLM_SYNTHETIC_RETRY_MAX")
    if raw is None or raw == "":
        return _DEFAULT_SYNTHETIC_RETRY_MAX
    try:
        value = int(raw)
    except (TypeError, ValueError):
        if loop_logger:
            loop_logger.warning(
                "Invalid MCP_MESH_LLM_SYNTHETIC_RETRY_MAX=%r (expected int >= 0); "
                "falling back to default %d",
                raw,
                _DEFAULT_SYNTHETIC_RETRY_MAX,
            )
        return _DEFAULT_SYNTHETIC_RETRY_MAX
    if value < 0:
        if loop_logger:
            loop_logger.warning(
                "Invalid MCP_MESH_LLM_SYNTHETIC_RETRY_MAX=%d (must be >= 0); "
                "falling back to default %d",
                value,
                _DEFAULT_SYNTHETIC_RETRY_MAX,
            )
        return _DEFAULT_SYNTHETIC_RETRY_MAX
    return value


def _serialize_assistant_message_for_retry(
    message: Any,
    bad_tool_use_id: str | None = None,
) -> dict[str, Any]:
    """Serialize the bad-attempt assistant turn into the dict shape that the
    LLM client accepts as a prior assistant turn.

    Mirrors the conversation-dict shape built when real tool calls iterate
    (see :func:`_build_assistant_tool_call_dict` and the assistant_msg
    construction in ``_provider_agentic_loop``). Used by the synthetic-tool
    corrective-retry path (issue #961) to thread the failed ``tool_use``
    back to the model so its next turn can reference the same tool_use_id
    via a ``role:tool`` message.

    When ``bad_tool_use_id`` is supplied, the ``tool_calls`` list is filtered
    to the single entry whose ``id`` matches. This preserves Anthropic's 1:1
    ``tool_use``/``tool_result`` correlation invariant: the corrective retry
    only emits one ``tool_result`` (for ``bad_tool_use_id``), so any other
    parallel ``tool_use`` blocks from the same assistant turn would be
    orphaned and rejected by the API. Per
    :func:`_extract_synthetic_format_arguments`, the model may return real
    tool calls AND the synthetic in the same turn; this filter ensures the
    retry payload is protocol-conformant in that case.
    """
    raw_tool_calls = getattr(message, "tool_calls", None) or []
    if bad_tool_use_id:
        raw_tool_calls = [
            tc for tc in raw_tool_calls if getattr(tc, "id", None) == bad_tool_use_id
        ]
    return {
        "role": getattr(message, "role", "assistant"),
        "content": getattr(message, "content", "") or "",
        "tool_calls": [_build_assistant_tool_call_dict(tc) for tc in raw_tool_calls],
    }


async def _maybe_retry_synthetic_on_validation_failure(
    *,
    synthetic_args: str,
    synthetic_tool: dict,
    synthetic_tool_name: str,
    bad_tool_use_id: str,
    assistant_message_dict: dict,
    current_messages: list[dict],
    tools: list[dict],
    completion_args_template: dict,
    native_handler,
    litellm_module,
    effective_model: str,
    vendor: str | None,
    loop_logger: logging.Logger | None,
) -> tuple[str, dict | None]:
    """Validate synthetic-tool args against the schema; retry once on failure.

    Issue #961 — adds a shape-agnostic, schema-driven corrective retry to the
    native-path provider agentic loop. The native synthetic-tool path is
    single-shot: when Claude returns malformed ``tool_use.input`` (for
    example, the well-known ``{"parameter": {<real fields>}}`` envelope
    hallucination), Pydantic validation downstream fails with no recovery.
    This helper runs a provider-side ``jsonschema`` pre-filter on the
    synthetic-tool arguments and, on failure, asks the model to try again
    with the schema and the validation error inlined into the prompt.
    Mirrors the LiteLLM HINT->``response_format`` fallback pattern in
    :func:`_maybe_run_hint_fallback`.

    Returns ``(final_args_str, usage_to_fold_or_None)``. If validation
    passes or the retry feature is disabled (``MCP_MESH_LLM_SYNTHETIC_RETRY_MAX=0``),
    returns the input ``synthetic_args`` unchanged with ``usage=None``. On
    retry, returns the second attempt's args (whether validated or not —
    :class:`_mcp_mesh.engine.response_parser.ResponseParser` is the final
    gate; validation failure on attempt 2 falls through with a WARN so the
    consumer-side parser can apply its own envelope-unwrap heuristic before
    Pydantic raises) plus the retry call's usage dict so callers can fold
    it into their cumulative ``_mesh_usage`` block.

    Tracing: TODO(#961) — when the OpenTelemetry tracer is wired into this
    module the retry call should be wrapped in a span with attributes
    ``mesh.llm.synthetic_retry=true``, ``mesh.llm.vendor``,
    ``mesh.llm.model``, ``mesh.llm.validation_error``. Until then the same
    information is captured at WARN level.
    """
    # Fall back to the module logger when no caller-supplied logger is
    # threaded through — the buffered loop's ``loop_logger`` parameter is
    # ``None`` by default, but observability still needs the WARN trail
    # because the consumer-facing failure mode (Pydantic validation error)
    # is downstream of this helper.
    effective_logger = loop_logger if loop_logger is not None else logger

    retry_max = _read_synthetic_retry_max(effective_logger)
    if retry_max <= 0:
        return synthetic_args, None

    schema = (synthetic_tool or {}).get("function", {}).get("parameters")
    if not schema:
        # No schema to validate against — nothing to retry for.
        return synthetic_args, None

    try:
        parsed_args = json.loads(synthetic_args) if synthetic_args else {}
    except (TypeError, ValueError) as e:
        # Malformed JSON is not what this retry is for — ResponseParser handles
        # the salvage path. Don't mask weird bugs; just log and bail.
        effective_logger.warning(
            "[provider:retry] synthetic args not JSON-parseable (%s); skipping "
            "validation retry",
            e,
        )
        return synthetic_args, None

    try:
        jsonschema.validate(instance=parsed_args, schema=schema)
        return synthetic_args, None
    except jsonschema.ValidationError as ve:
        first_error_msg = str(ve)
    except jsonschema.exceptions.SchemaError as schema_err:
        # Provider-side schema authoring bug; loud WARN, no retry (won't help).
        effective_logger.warning(
            "[provider:retry] synthetic tool schema is malformed (SchemaError: %s) — "
            "skipping retry; this indicates a provider/decorator misconfiguration",
            schema_err,
        )
        return synthetic_args, None
    except Exception as exc:  # noqa: BLE001 - guard against jsonschema oddities
        # jsonschema oddity (corrupt args, decode failure, etc.) — log and skip retry.
        effective_logger.warning(
            "[provider:retry] unexpected error during schema validation pre-check: %s — skipping retry",
            exc,
        )
        return synthetic_args, None

    # Build the corrective conversation: prior turn (with the bad tool_use)
    # + a tool result acknowledging the failure + a user message that inlines
    # the schema and the validation error.
    tool_result_dict = {
        "role": "tool",
        "tool_call_id": bad_tool_use_id,
        "content": json.dumps(
            {"error": "schema validation failed", "is_error": True}
        ),
    }
    corrective_user_dict = {
        "role": "user",
        "content": (
            f"Your previous response to {synthetic_tool_name} failed schema validation:\n"
            f"<error>{first_error_msg[:2000]}</error>\n"
            f"\n"
            f"The required schema is:\n"
            f"<schema>{json.dumps(schema, indent=2)}</schema>\n"
            f"\n"
            f"Call {synthetic_tool_name} again with arguments that exactly match the "
            f"schema. Do NOT wrap the fields in an envelope (e.g., "
            f'{{"parameter": {{...}}}} or {{"input": {{...}}}}). Pass the fields '
            f"directly as the tool arguments."
        ),
    }
    # Invariant: current_messages ends in a USER turn at this point — the
    # loop only invokes this helper after the LLM's first response, which
    # was the assistant turn we're appending below. Anthropic rejects
    # assistant→assistant adjacency.
    new_messages = list(current_messages) + [
        assistant_message_dict,
        tool_result_dict,
        corrective_user_dict,
    ]

    retry_args = {
        **completion_args_template,
        "messages": new_messages,
        "tools": tools,
        # Force the synthetic on retry — the model already chose it once, and
        # we want a deterministic single-call corrective turn rather than
        # risking another tool-call detour. OpenAI-shape tool_choice is what
        # ``_inject_synthetic_format_tool`` and the rest of the loop use; the
        # vendor-native adapters translate as needed.
        # Use OpenAI shape; anthropic_native._convert_tool_choice
        # (anthropic_native.py:800-807) translates to {"type": "tool", "name": ...}.
        "tool_choice": {
            "type": "function",
            "function": {"name": synthetic_tool_name},
        },
    }

    effective_logger.warning(
        "[provider:retry] synthetic-tool schema validation failed (attempt 1) "
        "for vendor=%s model=%s tool=%s: %s; retrying once",
        vendor,
        effective_model,
        synthetic_tool_name,
        first_error_msg[:500],
    )

    # Mirror the dispatch logic of the outer loop: prefer native handler when
    # available, otherwise fall back to LiteLLM via asyncio.to_thread.
    # The retry call itself can fail (rate limits, timeouts, anthropic outages,
    # transient network errors). When it does, fall back to the original (bad)
    # args so ResponseParser's defensive envelope-unwrap (PR #960) still gets
    # a chance to salvage — the documented "ResponseParser is the final salvage
    # gate" design must hold across transient retry failures.
    try:
        if native_handler is not None and native_handler.has_native():
            native_args = {
                k: v
                for k, v in retry_args.items()
                if k not in ("model", "api_key", "base_url")
            }
            retry_response = await native_handler.complete(
                native_args,
                model=effective_model,
                api_key=retry_args.get("api_key"),
                base_url=retry_args.get("base_url"),
            )
        else:
            retry_response = await asyncio.to_thread(
                litellm_module.completion, **retry_args
            )
    except Exception as retry_exc:  # noqa: BLE001 - any retry failure falls back
        effective_logger.warning(
            "[provider:retry] retry call raised %s: %s; falling back to "
            "original (attempt 1) args for downstream salvage",
            type(retry_exc).__name__,
            retry_exc,
        )
        return synthetic_args, None

    retry_message = retry_response.choices[0].message
    retry_args_str, _retry_tc_id = _extract_synthetic_format_arguments(
        retry_message, synthetic_tool_name
    )
    if retry_args_str is None:
        effective_logger.warning(
            "[provider:retry] retry response did not call synthetic tool '%s' — "
            "falling back to original (bad) args; ResponseParser will attempt "
            "envelope-unwrap salvage",
            synthetic_tool_name,
        )
        return synthetic_args, None

    # Log attempt 2's validation outcome too — useful when both attempts fail.
    try:
        retry_parsed = json.loads(retry_args_str) if retry_args_str else {}
        jsonschema.validate(instance=retry_parsed, schema=schema)
    except jsonschema.ValidationError as ve2:
        effective_logger.warning(
            "[provider:retry] synthetic-tool schema validation still failed "
            "(attempt 2) for vendor=%s model=%s tool=%s: %s; returning "
            "second-attempt args anyway (ResponseParser is the final gate)",
            vendor,
            effective_model,
            synthetic_tool_name,
            str(ve2)[:500],
        )
    except Exception:  # noqa: BLE001
        # Non-validation errors on attempt 2 are ignored here — the args are
        # returned regardless and ResponseParser will surface any real failure.
        pass

    retry_usage_dict: dict | None = None
    if hasattr(retry_response, "usage") and retry_response.usage:
        ru = retry_response.usage
        retry_usage_dict = {
            "prompt_tokens": getattr(ru, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(ru, "completion_tokens", 0) or 0,
        }

    return retry_args_str, retry_usage_dict


def _extract_text_from_message_content(content: Any) -> str:
    """Normalize a LiteLLM message ``content`` field to a plain string.

    LiteLLM may return ``content`` as a string (most providers) or as a list
    of content blocks (Anthropic with thinking, mixed text+image, etc.). This
    helper handles both shapes and concatenates text blocks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if block is None:
                continue
            if isinstance(block, dict):
                text_value = block.get("text", "")
                text_parts.append(
                    str(text_value) if text_value is not None else ""
                )
            else:
                try:
                    text_parts.append(str(block))
                except Exception:
                    continue
        return "".join(text_parts)
    return str(content)


# Vendors that do NOT support images in tool/function result messages.
# OpenAI strictly rejects images in role:tool messages.
# For these vendors, images are accumulated and sent as one user message
# after ALL tool results for the iteration.
_TOOL_IMAGE_UNSUPPORTED_VENDORS = {"openai", "gemini", "google"}


async def _execute_tool_calls_for_iteration(
    message: Any,
    tool_endpoints: dict[str, str],
    parallel: bool,
    vendor: str | None,
    loop_logger: logging.Logger | None,
    has_native_dispatch: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Execute one iteration's tool calls (parallel or sequential).

    Encapsulates the per-iteration tool dispatch logic shared by the buffered
    provider agentic loop (``_provider_agentic_loop``) and the streaming
    provider agentic loop (Phase 2 of issue #849). Behavior is intentionally
    identical to the previous inline implementation so that callers can drop
    in this helper without observable changes.

    For each ``tool_call`` in ``message.tool_calls``:
      * Look up the MCP endpoint from ``tool_endpoints`` (returns an error
        tool message if missing).
      * Dispatch via :class:`UnifiedMCPProxy.call_tool`.
      * Resolve resource_link items in the tool result to multimodal content.
        The resolver formats per the destination vendor when known —
        vendor-native shape (issue #860) for the native dispatch path,
        OpenAI-shape (image_url + data URI, the historical default) for the
        LiteLLM fallback path so LiteLLM's vendor adapters handle conversion.
      * For vendors that do not support images in role:tool messages
        (OpenAI / Gemini / Google), strip image parts out of the tool message
        and accumulate them so the caller can synthesize a follow-up user
        message after all tool results.
      * For vendors that do support images in role:tool messages
        (Anthropic / Claude), inline the resolved multimodal content directly
        in the tool message.

    Args:
        message: The ``response.choices[0].message`` from LiteLLM whose
            ``tool_calls`` should be executed. Must have a non-empty
            ``tool_calls`` attribute — callers are expected to gate on
            ``message.tool_calls`` themselves.
        tool_endpoints: Mapping of tool_name -> MCP endpoint URL.
        parallel: When True (and there is more than one tool call), execute
            the tool calls concurrently via :func:`asyncio.gather`. Otherwise
            execute sequentially in declaration order.
        vendor: Vendor name extracted from the model string (e.g.,
            ``"anthropic"``, ``"openai"``, ``"gemini"``). Drives both
            resource_link resolution and image-handling restrictions. May be
            ``None`` for unknown vendors — in that case, resource_link
            resolution is skipped and tool results pass through as JSON.
        loop_logger: Logger used for debug/info/warning output. May be
            ``None`` to suppress logging.
        has_native_dispatch: When True, the surrounding agentic loop is
            dispatching through the vendor's native SDK adapter (e.g.
            ``anthropic_native``) and resource_link resolution should emit
            vendor-native content blocks (issue #860). When False (LiteLLM
            fallback path or unknown vendor), resolution stays on the
            historical OpenAI-shape contract — LiteLLM handles vendor
            translation internally and changing the upstream shape would
            break the LiteLLM adapter chain. Defaults to False so callers
            that don't yet plumb dispatch awareness fall back to the
            pre-#860 behaviour.

    Returns:
        A tuple ``(tool_messages, accumulated_images)`` where:
          * ``tool_messages`` is the ordered list of
            ``{role: "tool", tool_call_id: ..., content: ...}`` dicts to be
            appended to the conversation immediately after the assistant
            message that requested the tools.
          * ``accumulated_images`` is the list of image dicts (vendor-native
            shape on native dispatch path, OpenAI-shape on LiteLLM path) to
            be sent in a follow-up user message after all tool results, for
            vendors that do not support images in role:tool messages. Empty
            for other vendors.
    """
    from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy
    from _mcp_mesh.media.resolver import _has_resource_link, resolve_resource_links

    # Issue #860: pick the resolver vendor argument so that:
    #   * native dispatch (e.g. anthropic_native, gemini_native) receives the
    #     vendor-native content shape directly — no per-adapter translation
    #     needed downstream;
    #   * LiteLLM fallback path keeps the historical OpenAI-shape contract,
    #     because LiteLLM's vendor adapters expect image_url + data URI and
    #     translate to the wire format themselves.
    # Note: ``_format_for_gemini`` is currently aliased to ``_format_for_openai``
    # in the resolver, so for vendor="gemini"/"google"/"vertex_ai" the shape
    # is identical regardless of dispatch path. Only vendor="anthropic" sees
    # an actual shape difference today (image_url → Claude image block).
    if has_native_dispatch and vendor:
        # Validate the vendor has a formatter; if not, fall back to OpenAI
        # shape (safe default — won't crash) but log loudly so the operator
        # learns the native handler was added without a matching emitter.
        from _mcp_mesh.media.resolver import _VENDOR_FORMATTERS

        if vendor in _VENDOR_FORMATTERS:
            resolver_vendor = vendor
        else:
            _warn_native_dispatch_unknown_vendor_once(vendor)
            resolver_vendor = "openai"
    else:
        resolver_vendor = "openai"

    async def _execute_single_tool(tc) -> tuple[dict, list[dict]]:
        """Execute a single tool call and return (tool_message, image_parts)."""
        tool_name = tc.function.name
        endpoint = tool_endpoints.get(tool_name)

        if not endpoint:
            if loop_logger:
                loop_logger.warning(
                    f"No endpoint for tool {tool_name}, returning error"
                )
            return (
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(
                        {"error": f"Tool {tool_name} not available"}
                    ),
                },
                [],
            )

        try:
            args = (
                json.loads(tc.function.arguments)
                if tc.function.arguments
                else {}
            )
            proxy = UnifiedMCPProxy(
                endpoint=endpoint, function_name=tool_name
            )
            result = await proxy.call_tool(tool_name, args)

            # Resolve resource_link items to multimodal content.
            # ``resolver_vendor`` is "openai" on the LiteLLM fallback path
            # (preserves historical contract) and the actual vendor on the
            # native dispatch path (issue #860 — vendor-native shape upstream).
            if vendor and _has_resource_link(result):
                try:
                    resolved_parts = await resolve_resource_links(
                        result, resolver_vendor
                    )
                except Exception as resolve_err:
                    if loop_logger:
                        loop_logger.error(f"Media resolution failed: {resolve_err}")
                    resolved_parts = []

                image_types = ("image", "image_url")
                has_image = any(
                    p.get("type") in image_types
                    for p in resolved_parts
                )

                if has_image:
                    if vendor in _TOOL_IMAGE_UNSUPPORTED_VENDORS:
                        # OpenAI/Gemini: images NOT allowed in tool messages.
                        # Put text-only parts in the tool message, accumulate
                        # images for a single user message after all tool results.
                        text_parts = [
                            p for p in resolved_parts
                            if p.get("type") not in image_types
                        ]
                        image_parts = [
                            p for p in resolved_parts
                            if p.get("type") in image_types
                        ]

                        # Ensure tool message has at least some content
                        if not text_parts:
                            text_parts = [{"type": "text", "text": "[Image from tool result]"}]

                        # OpenAI requires tool message content to be a string
                        if len(text_parts) == 1:
                            tool_content = text_parts[0].get("text", "")
                        else:
                            tool_content = json.dumps(text_parts)

                        if loop_logger:
                            loop_logger.debug(
                                f"Tool {tool_name} result: {len(text_parts)} text parts in tool msg, "
                                f"{len(image_parts)} images accumulated (vendor={vendor})"
                            )
                        return (
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": tool_content,
                            },
                            image_parts,
                        )
                    else:
                        # Claude/Anthropic via LiteLLM: inline images in tool message.
                        # LiteLLM converts image_url data URIs to the provider's native
                        # format (Claude base64 blocks, etc.).
                        if loop_logger:
                            loop_logger.debug(
                                f"Tool {tool_name} result: resolved {len(resolved_parts)} "
                                f"multimodal parts inline (vendor={vendor})"
                            )
                        return (
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": resolved_parts,
                            },
                            [],
                        )
                else:
                    # Non-image resource_links resolved to text — use resolved text
                    text_content = "\n".join(
                        p.get("text", "") for p in resolved_parts if p.get("type") == "text"
                    )
                    if text_content:
                        tool_result = text_content
                    else:
                        tool_result = json.dumps(result)
                    if loop_logger:
                        loop_logger.debug(
                            f"Tool {tool_name} result: resolved non-image resource_link to text "
                            f"({len(text_content)} chars, vendor={vendor})"
                        )
                    # Fall through to normal message append
            elif isinstance(result, (dict, list)):
                tool_result = json.dumps(result)
            elif result is None:
                tool_result = ""
            else:
                tool_result = str(result)

            if loop_logger:
                loop_logger.debug(
                    f"Tool {tool_name} result: {tool_result[:200]}"
                )
        except Exception as e:
            if loop_logger:
                loop_logger.error(f"Tool {tool_name} execution failed: {e}")
            tool_result = json.dumps({"error": str(e)})

        return (
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            },
            [],
        )

    tool_messages: list[dict] = []
    accumulated_images: list[dict] = []

    if parallel and len(message.tool_calls) > 1:
        # Parallel execution via asyncio.gather
        if loop_logger:
            loop_logger.info(
                f"⚡ Provider executing {len(message.tool_calls)} tool calls in parallel"
            )
        results = await asyncio.gather(
            *[_execute_single_tool(tc) for tc in message.tool_calls]
        )
        for tool_msg, images in results:
            tool_messages.append(tool_msg)
            accumulated_images.extend(images)
    else:
        # Sequential execution (original behavior)
        for tc in message.tool_calls:
            tool_msg, images = await _execute_single_tool(tc)
            tool_messages.append(tool_msg)
            accumulated_images.extend(images)

    return tool_messages, accumulated_images


async def _provider_agentic_loop(
    effective_model: str,
    messages: list,
    tools: list,
    tool_endpoints: dict[str, str],
    model_params: dict,
    litellm_kwargs: dict,
    max_iterations: int = 10,
    loop_logger: logging.Logger | None = None,
    vendor: str | None = None,
) -> dict[str, Any]:
    """Execute tools provider-side and return final response.

    Runs a full agentic loop on the provider: calls the LLM, executes any
    tool calls via MCP proxies, feeds results back, and repeats until the
    LLM produces a final text response (no tool calls).

    Args:
        effective_model: LiteLLM model identifier to use.
        messages: Conversation messages (will be copied internally).
        tools: OpenAI-format tool schemas (already cleaned of _mesh_endpoint).
        tool_endpoints: Mapping of tool_name -> MCP endpoint URL.
        model_params: Extra model parameters for litellm.completion().
        litellm_kwargs: Base kwargs captured by the decorator.
        max_iterations: Safety limit on loop iterations.
        loop_logger: Logger instance for debug/info output.
        vendor: Vendor name for media resolution (e.g., "anthropic", "openai").

    Returns:
        Message dict with role, content, and optionally _mesh_usage.
    """
    import litellm

    iteration = 0
    current_messages = list(messages)

    # Pop parallel_tool_calls before it reaches completion_args
    # (Claude handler strips it, but OpenAI would pass it to API)
    parallel = model_params.pop("parallel_tool_calls", False)
    if parallel and loop_logger:
        loop_logger.info("🔀 Provider parallel tool calls enabled — tools will execute concurrently via asyncio.gather()")

    # HINT-mode state (set by ClaudeHandler.apply_structured_output, LiteLLM
    # path). Pop ONCE from ``model_params`` here so subsequent iterations
    # don't re-inject the flags via ``model_params.update(...)``. Captured
    # outside the loop so the post-loop fallback has access.
    (
        hint_mode,
        hint_schema,
        hint_fallback_timeout,
        hint_output_type_name,
    ) = _pop_mesh_hint_flags(model_params)

    # Synthetic-format-tool state (set by ClaudeHandler.apply_structured_output,
    # native path). Pop ONCE here too — same reason. When
    # ``synthetic_tool_name`` is non-None, the loop appends ``synthetic_tool``
    # to the tools list, sets tool_choice (auto if real tools present, forced
    # otherwise), and treats a tool_call to that name as the model's "I'm
    # done — here's the structured answer" signal.
    (
        synthetic_tool_name,
        synthetic_tool,
        synthetic_output_type_name,
    ) = _pop_mesh_synthetic_format_flags(model_params)

    # Native ``output_config`` state (Anthropic Sonnet 4.5+ / Opus 4.1+, set
    # by ClaudeHandler.apply_structured_output's output_config branch). When
    # ``output_config_mode`` is True, the model returns the structured JSON
    # answer as a plain TextBlock (Anthropic enforces the schema server-side
    # via output_config.format) and the "no tool calls" branch below skips
    # the synthetic-fallback recovery — the text content IS the answer.
    (
        output_config_mode,
        output_config_schema,
        output_config_output_type_name,
    ) = _pop_mesh_output_config_flags(model_params)

    while iteration < max_iterations:
        iteration += 1

        completion_args: dict[str, Any] = {
            "model": effective_model,
            "messages": current_messages,
            "tools": tools,
            **litellm_kwargs,
        }
        if model_params:
            completion_args.update(model_params)

        # Native dispatch (issue #834, PR 1): route through the vendor's
        # native SDK adapter by default when the SDK is installed.
        # Set MCP_MESH_NATIVE_LLM=0 to force the LiteLLM fallback path.
        # (``ProviderHandlerRegistry`` is imported at module top.)
        _native_handler = ProviderHandlerRegistry.get_handler(vendor)

        # Inject synthetic format tool when handler signaled it. The helper
        # is idempotent: on iter 2+ the synthetic is already in ``tools``
        # (we persist the augmented list back to the outer ``tools`` below)
        # and the helper skips both the re-append and the override WARN.
        # Tool_choice is set per-iteration because LiteLLM/Anthropic require
        # it alongside the tools list.
        if synthetic_tool_name and synthetic_tool:
            completion_args["tools"] = _inject_synthetic_format_tool(
                completion_args.get("tools"), synthetic_tool, completion_args
            )
            # Persist the augmented list across iterations so the helper's
            # idempotency check (synthetic-already-present) trips on iter 2+.
            # Without this, iter 2 starts from the raw user tools again and
            # ``completion_args["tool_choice"]`` (set by the helper on iter 1)
            # would be misread as a caller override and trigger a spurious WARN.
            tools = completion_args["tools"]

        if _native_handler.has_native():
            _native_args = {
                k: v
                for k, v in completion_args.items()
                if k not in ("model", "api_key", "base_url")
            }
            response = await _native_handler.complete(
                _native_args,
                model=effective_model,
                api_key=completion_args.get("api_key"),
                base_url=completion_args.get("base_url"),
            )
        else:
            response = await asyncio.to_thread(
                litellm.completion, **completion_args
            )
        message = response.choices[0].message

        # Synthetic-format-tool recognition (native path, structured output).
        # When the model called the synthetic tool, its arguments ARE the
        # structured answer — terminate the loop and surface them as content.
        # Real tool calls in the same turn are intentionally dropped: the
        # synthetic call signals "I'm done", and executing additional tools
        # would mean another iteration that the model already opted out of.
        if synthetic_tool_name and hasattr(message, "tool_calls") and message.tool_calls:
            synthetic_args, bad_tc_id = _extract_synthetic_format_arguments(
                message, synthetic_tool_name
            )
            if synthetic_args is not None:
                if loop_logger:
                    loop_logger.info(
                        "Provider-managed loop: synthetic format tool '%s' "
                        "called at iteration %d/%d — returning structured "
                        "content",
                        synthetic_tool_name,
                        iteration,
                        max_iterations,
                    )

                # Schema-validation retry for the synthetic tool (issue #961).
                # Gated to anthropic for v1 — the bad-tool_use_id round-trip
                # follows Anthropic's tool_use/tool_result correlation contract;
                # OpenAI/Gemini equivalents need per-vendor verification before
                # opt-in. See the helper docstring for the corrective-prompt
                # rationale.
                # TODO(#961): enable retry for openai/gemini after per-vendor
                # verification of the corrective-prompt round-trip.
                retry_usage: dict | None = None
                # ``bad_tc_id`` is the synthetic tool_call's id recovered
                # alongside ``synthetic_args`` above — it's the bad
                # ``tool_use_id`` that the corrective ``role:tool`` message
                # must reference for the Anthropic tool_use/tool_result
                # correlation contract.
                if vendor == "anthropic" and synthetic_tool is not None:
                    if bad_tc_id is not None:
                        # Rebuild a fresh template from the current iteration's
                        # completion_args (excluding messages/tools/tool_choice
                        # which the helper sets explicitly, and stream flags
                        # that don't apply on the buffered retry path).
                        retry_template = {
                            k: v
                            for k, v in completion_args.items()
                            if k not in (
                                "messages",
                                "tools",
                                "tool_choice",
                                "stream",
                                "stream_options",
                            )
                        }
                        synthetic_args, retry_usage = (
                            await _maybe_retry_synthetic_on_validation_failure(
                                synthetic_args=synthetic_args,
                                synthetic_tool=synthetic_tool,
                                synthetic_tool_name=synthetic_tool_name,
                                bad_tool_use_id=bad_tc_id,
                                assistant_message_dict=_serialize_assistant_message_for_retry(
                                    message, bad_tool_use_id=bad_tc_id
                                ),
                                current_messages=current_messages,
                                tools=tools,
                                completion_args_template=retry_template,
                                native_handler=_native_handler,
                                litellm_module=litellm,
                                effective_model=effective_model,
                                vendor=vendor,
                                loop_logger=loop_logger,
                            )
                        )

                message_dict: dict[str, Any] = {
                    "role": getattr(message, "role", "assistant"),
                    "content": synthetic_args,
                }
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    message_dict["_mesh_usage"] = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                        "model": effective_model,
                    }
                # Fold retry usage into the cumulative block so observability
                # captures the corrective call's tokens.
                if retry_usage:
                    if "_mesh_usage" not in message_dict:
                        message_dict["_mesh_usage"] = {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "model": effective_model,
                        }
                    bucket = message_dict["_mesh_usage"]
                    bucket["prompt_tokens"] = (
                        bucket.get("prompt_tokens", 0)
                        + retry_usage.get("prompt_tokens", 0)
                    )
                    bucket["completion_tokens"] = (
                        bucket.get("completion_tokens", 0)
                        + retry_usage.get("completion_tokens", 0)
                    )
                return message_dict

        if hasattr(message, "tool_calls") and message.tool_calls:
            if loop_logger:
                loop_logger.debug(
                    f"Provider executing {len(message.tool_calls)} tool calls "
                    f"(iteration {iteration}/{max_iterations})"
                )

            # Add assistant message with tool_calls to conversation.
            #
            # ``_gemini_thought_signature`` (when present, base64-encoded
            # bytes) is a Gemini-only sidecar: Gemini 2.0+ thinking models
            # emit a Part-level ``thought_signature`` on each ``functionCall``
            # response Part that the API REQUIRES to be echoed back on the
            # next-turn ``functionCall`` of a multi-turn tool-calling
            # conversation. Without it Gemini rejects the request with
            # HTTP 400. The native Gemini adapter (gemini_native._adapt_response)
            # lifts the signature off the response Part onto its ``_ToolCall``;
            # we serialize it onto the conversation dict here so that the
            # next iteration's ``_convert_messages_to_gemini`` can recover it
            # and place it back on the outbound functionCall Part. Other
            # vendors never set the attribute, so the field is silently
            # absent for them.
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    _build_assistant_tool_call_dict(tc)
                    for tc in message.tool_calls
                ],
            }
            current_messages.append(assistant_msg)

            tool_messages, accumulated_images = await _execute_tool_calls_for_iteration(
                message,
                tool_endpoints,
                parallel,
                vendor,
                loop_logger,
                has_native_dispatch=_native_handler.has_native(),
            )
            current_messages.extend(tool_messages)

            # After ALL tool results: inject accumulated images as one user message.
            # Sequence: assistant(tool_calls) -> tool -> tool -> ... -> user(images)
            # This is valid because it comes after all tool results and before the
            # next LLM call.
            if accumulated_images:
                current_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Here are the images from the tool results above:"},
                        *accumulated_images,
                    ],
                })
                if loop_logger:
                    loop_logger.info(
                        f"Injected user message with {len(accumulated_images)} accumulated images "
                        f"(vendor={vendor})"
                    )
        else:
            # No tool calls - final response
            final_content = _extract_text_from_message_content(message.content)

            # Native ``output_config`` short-circuit (Anthropic Sonnet 4.5+ /
            # Opus 4.1+). Anthropic enforces the schema server-side via
            # ``output_config.format`` and returns the structured JSON answer
            # as a plain TextBlock — there is no synthetic-tool unwrap, and
            # synthetic-fallback recovery would be both wrong (no synthetic
            # tool was injected) and wasteful. The HINT fallback is also
            # skipped because HINT mode is mutually exclusive with
            # ``output_config`` mode. Defense-in-depth: optionally log a
            # WARN if the returned text doesn't parse against the captured
            # schema — but do NOT retry (the framework principle is "don't
            # force the model after it has answered").
            if output_config_mode:
                if (
                    output_config_schema is not None
                    and final_content
                    and not _hint_response_parses(final_content, output_config_schema)
                ):
                    if loop_logger:
                        loop_logger.warning(
                            "Native output_config mode for '%s': returned text "
                            "did not parse against the schema (Anthropic's "
                            "output_config.format normally enforces this) — "
                            "surfacing the raw text to the caller without retry",
                            output_config_output_type_name,
                        )

                message_dict: dict[str, Any] = {
                    "role": message.role,
                    "content": final_content if final_content else "",
                }
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    message_dict["_mesh_usage"] = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0)
                        or 0,
                        "model": effective_model,
                    }

                if loop_logger:
                    loop_logger.info(
                        f"Provider-managed loop completed in {iteration} "
                        f"iterations (output_config mode)"
                    )

                return message_dict

            # HINT-mode validation + bounded-timeout fallback (issue #820).
            # If a handler (currently only ClaudeHandler) signaled HINT mode,
            # validate the final response against the schema. If it fails to
            # parse, retry once with native response_format and a hard timeout.
            # This recovers from HINT compliance failures without re-introducing
            # the silent 600s+ hang of the unbounded response_format path.
            #
            # Build base args for the fallback — strip ``tools`` AND
            # ``tool_choice`` since the fallback only fires AFTER the model
            # gave a final answer with no tool_calls. Keeping ``tools`` would
            # re-introduce the ``response_format + tools`` combo that caused
            # the original silent hang (issue #820). ``tool_choice`` is
            # stripped because the synthetic-tool path leaves it set to
            # "auto" / forced-synthetic, which has no meaning once tools are
            # gone and would be rejected by some vendors. Bounded timeout is
            # still there as defense-in-depth.
            fallback_base_args = {
                k: v
                for k, v in completion_args.items()
                if k not in ("tools", "tool_choice")
            }
            try:
                final_content, message, response = await _maybe_run_hint_fallback(
                    final_content=final_content,
                    message=message,
                    response=response,
                    base_completion_args=fallback_base_args,
                    hint_mode=hint_mode,
                    hint_schema=hint_schema,
                    hint_fallback_timeout=hint_fallback_timeout,
                    hint_output_type_name=hint_output_type_name,
                    fallback_logger=loop_logger,
                    vendor=vendor,
                )
            except Exception as e:
                if loop_logger:
                    loop_logger.error(
                        "Claude HINT fallback to response_format failed: %s",
                        e,
                    )
                raise

            # Native synthetic-tool fallback (synthetic-tool decline regression, v2.0.0). When
            # the native synthetic-tool path is active and the model
            # declined to call ``__mesh_format_response`` (returning plain
            # text instead), recover by retrying once with native
            # response_format. The two fallbacks are mutually exclusive in
            # practice — HINT mode and synthetic-tool mode are alternative
            # dispatch shapes — so the early-returns gate each correctly.
            try:
                final_content, message, response = await _maybe_run_synthetic_fallback(
                    final_content=final_content,
                    message=message,
                    response=response,
                    base_completion_args=fallback_base_args,
                    synthetic_tool_name=synthetic_tool_name,
                    synthetic_tool=synthetic_tool,
                    fallback_timeout=hint_fallback_timeout,
                    fallback_logger=loop_logger,
                    vendor=vendor,
                )
            except Exception as e:
                if loop_logger:
                    loop_logger.error(
                        "Native synthetic-tool fallback to response_format "
                        "failed: %s",
                        e,
                    )
                raise

            message_dict: dict[str, Any] = {
                "role": message.role,
                "content": final_content,
            }

            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                message_dict["_mesh_usage"] = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "model": effective_model,
                }

            if loop_logger:
                loop_logger.info(
                    f"Provider-managed loop completed in {iteration} iterations"
                )

            return message_dict

    # Safety: max iterations reached
    if loop_logger:
        loop_logger.warning(
            f"Provider-managed loop hit max iterations ({max_iterations})"
        )
    return {
        "role": "assistant",
        "content": "Maximum tool call iterations reached",
    }


async def _provider_agentic_loop_stream(
    effective_model: str,
    messages: list,
    tools: list,
    tool_endpoints: dict[str, str],
    model_params: dict,
    litellm_kwargs: dict,
    max_iterations: int = 10,
    loop_logger: logging.Logger | None = None,
    vendor: str | None = None,
) -> AsyncIterator[str]:
    """Streaming counterpart to :func:`_provider_agentic_loop`.

    Mirrors the buffered provider agentic loop one-for-one, but yields text
    chunks as they arrive from ``litellm.acompletion(stream=True, ...)``.
    Intermediate iterations whose assistant turn requests tool_calls are
    handled internally (tools execute on the provider, results feed back
    into the loop). The final iteration's text streams chunk-by-chunk to
    the consumer — except in HINT mode (see below).

    Mid-stream tool_call detection (Option B):
        Within each iteration we open one ``acompletion(stream=True)`` call
        and consume chunks live. Text deltas yield to the consumer as they
        arrive UNTIL we see the first ``tool_calls`` delta — at that point
        we stop yielding and continue draining the stream so we collect all
        ``tool_call`` argument fragments and the trailing ``usage`` block.
        Once the stream exhausts, we reassemble the tool_calls (via
        :meth:`MeshLlmAgent._merge_streamed_tool_calls`), execute them via
        :func:`_execute_tool_calls_for_iteration`, append assistant + tool
        messages to the conversation, and continue the outer while-loop. An
        iteration that produces no tool_calls IS the final answer — its
        text was already yielded live, so we just publish usage metadata
        and return.

    HINT mode caveat (Claude HINT):
        When :class:`ClaudeHandler` signaled HINT mode (i.e. the provider
        is expected to return JSON conforming to a schema), we cannot
        stream the final iteration's text live because the validation
        + bounded-timeout fallback (issue #820) needs the complete content
        to decide whether to re-issue the call with native
        ``response_format``. In that case we BUFFER the final iteration's
        text, run :func:`_maybe_run_hint_fallback`, and yield the
        validated (or fallback) text as a single chunk. This is a known
        UX limitation — HINT + streaming becomes effectively non-streaming
        for the final response — and is logged at INFO when entered.

    Cancellation:
        If the consumer breaks out of the ``async for`` early, we close
        the underlying ``litellm.acompletion`` async iterator via
        ``aclose()`` to release server resources promptly.

    Token-usage publication:
        Cumulative ``input``/``output`` tokens across iterations are
        published via :func:`set_llm_metadata` after each stream
        completion (LiteLLM emits ``usage`` in the final chunk when
        ``stream_options={"include_usage": True}`` is requested). This
        mirrors the direct-mode streaming agent so ExecutionTracer's
        post-call read sees accurate counts.

    Args:
        effective_model: LiteLLM model identifier to use (e.g.
            ``"anthropic/claude-sonnet-4-5"``).
        messages: Conversation messages (will be copied internally).
        tools: OpenAI-format tool schemas (already cleaned of
            ``_mesh_endpoint``).
        tool_endpoints: Mapping of tool_name -> MCP endpoint URL.
        model_params: Extra model parameters for ``litellm.acompletion``.
            ``parallel_tool_calls`` is popped early because Claude's
            handler strips it; OpenAI would otherwise pass it to the API.
        litellm_kwargs: Base kwargs captured by the decorator (api_key,
            base_url, etc.).
        max_iterations: Safety limit on loop iterations.
        loop_logger: Logger for debug/info/warning output. May be
            ``None`` to suppress logging.
        vendor: Vendor name extracted from the model (e.g.
            ``"anthropic"``, ``"openai"``). Drives image handling in
            tool-result messages — see
            :func:`_execute_tool_calls_for_iteration`.

    Yields:
        ``str`` text chunks. The empty stream is valid (e.g. tool-call
        iterations followed by a final iteration that returns empty
        content).
    """
    # TODO(#961): synthetic-tool validation retry is not implemented for the
    # streaming path. The buffered loop performs a one-shot corrective retry
    # via :func:`_maybe_retry_synthetic_on_validation_failure` when Claude
    # returns malformed ``tool_use.input`` against the synthetic tool schema;
    # the streaming path needs an equivalent path that handles mid-stream
    # tool_use accumulation, abandons the in-flight stream cleanly, and
    # re-issues the corrective call without breaking partial-text yields.
    # Tracking issue: https://github.com/dhyanraj/mcp-mesh/issues/961.
    import litellm

    # Imported here to avoid a circular import: ``_mcp_mesh.engine`` imports
    # this module via the @mesh.llm_provider decorator path.
    from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
    from _mcp_mesh.tracing.context import set_llm_metadata

    iteration = 0
    current_messages = list(messages)

    parallel = model_params.pop("parallel_tool_calls", False)
    if parallel and loop_logger:
        loop_logger.info(
            "🔀 Provider parallel tool calls enabled — tools will execute "
            "concurrently via asyncio.gather()"
        )

    # Pop mesh control flags ONCE here so subsequent iterations don't
    # re-inject them via ``model_params.update(...)``. Mirrors the buffered
    # loop (``_provider_agentic_loop``) — see comment there.
    (
        hint_mode,
        hint_schema,
        hint_fallback_timeout,
        hint_output_type_name,
    ) = _pop_mesh_hint_flags(model_params)

    # Synthetic-format-tool state (mirrors the buffered loop, native path).
    (
        synthetic_tool_name,
        synthetic_tool,
        synthetic_output_type_name,
    ) = _pop_mesh_synthetic_format_flags(model_params)

    # Native ``output_config`` state — defense-in-depth strip. Streaming +
    # structured output intentionally routes away from ``output_config``
    # (Phase C), so these sentinels should never be set on this path. Pop
    # them anyway so a future misconfiguration can't leak the sentinel keys
    # into the wire request.
    _pop_mesh_output_config_flags(model_params)

    total_input_tokens = 0
    total_output_tokens = 0

    while iteration < max_iterations:
        iteration += 1

        completion_args: dict[str, Any] = {
            "model": effective_model,
            "messages": current_messages,
            "tools": tools,
            **litellm_kwargs,
        }
        if model_params:
            completion_args.update(model_params)

        existing_stream_opts = completion_args.get("stream_options") or {}
        completion_args["stream"] = True
        completion_args["stream_options"] = {
            **existing_stream_opts,
            "include_usage": True,
        }

        # Native dispatch (issue #834, PR 1): route through the vendor's
        # native SDK streaming adapter by default when the SDK is installed.
        # Set MCP_MESH_NATIVE_LLM=0 to force the LiteLLM fallback path.
        # (``ProviderHandlerRegistry`` is imported at module top.)
        _native_handler = ProviderHandlerRegistry.get_handler(vendor)

        # Inject synthetic format tool when handler signaled it. Same logic
        # as the buffered loop — append the tool, set tool_choice. The
        # adapter emits tool_use deltas the same way for synthetic and real
        # tools; the loop disambiguates AFTER merge by tool name. Helper is
        # idempotent — see ``_inject_synthetic_format_tool``. We persist the
        # augmented list back to the outer ``tools`` so iter 2+ sees the
        # synthetic-already-present state and the override WARN doesn't
        # spam once per iteration.
        if synthetic_tool_name and synthetic_tool:
            completion_args["tools"] = _inject_synthetic_format_tool(
                completion_args.get("tools"), synthetic_tool, completion_args
            )
            tools = completion_args["tools"]

        if _native_handler.has_native():
            _native_args = {
                k: v
                for k, v in completion_args.items()
                if k
                not in (
                    "model",
                    "api_key",
                    "base_url",
                    "stream",
                    "stream_options",
                )
            }
            stream_iter = await _native_handler.complete_stream(
                _native_args,
                model=effective_model,
                api_key=completion_args.get("api_key"),
                base_url=completion_args.get("base_url"),
            )
        else:
            stream_iter = await litellm.acompletion(**completion_args)

        chunks: list[Any] = []
        saw_tool_call = False
        stream_completed = False

        # When HINT mode is active we cannot yield the final iteration's
        # text live: the bounded-timeout fallback (issue #820) needs the
        # complete content for schema validation. Buffer instead.
        buffer_for_hint = bool(hint_mode and hint_schema)
        if buffer_for_hint and loop_logger:
            loop_logger.info(
                "HINT mode active — buffering final iteration for validation "
                "(streaming UX degrades to single-chunk for this response)"
            )

        try:
            async for chunk in stream_iter:
                chunks.append(chunk)

                if MeshLlmAgent._chunk_has_tool_call(chunk):
                    saw_tool_call = True
                    continue

                if saw_tool_call:
                    continue

                if buffer_for_hint:
                    # Drain without yielding; we need the full content to
                    # validate against the schema before emitting anything.
                    continue

                text = MeshLlmAgent._extract_text_from_chunk(chunk)
                if text:
                    yield text
            stream_completed = True

            iter_usage = MeshLlmAgent._extract_usage_from_chunks(chunks)
            if iter_usage:
                total_input_tokens += iter_usage.get("prompt_tokens", 0) or 0
                total_output_tokens += (
                    iter_usage.get("completion_tokens", 0) or 0
                )
            iter_model = MeshLlmAgent._extract_model_from_chunks(chunks)
            if iter_model:
                effective_model = iter_model

            if saw_tool_call:
                merged_tool_calls = MeshLlmAgent._merge_streamed_tool_calls(chunks)
                if not merged_tool_calls:
                    raise RuntimeError(
                        "provider stream produced tool_call deltas but no "
                        "complete tool_call could be merged"
                    )

                # Synthetic-format-tool recognition (native path, structured
                # output). If any merged tool call targets the synthetic name,
                # its arguments ARE the structured answer — emit ONE final
                # content chunk and terminate the loop. Real tool calls in
                # the same iteration are dropped (the model signaled "I'm
                # done" by calling the synthetic; executing real tools would
                # imply another iteration the model already opted out of).
                if synthetic_tool_name:
                    synthetic_args: str | None = None
                    for tc in merged_tool_calls:
                        if tc["function"]["name"] == synthetic_tool_name:
                            synthetic_args = tc["function"]["arguments"] or "{}"
                            break
                    if synthetic_args is not None:
                        if loop_logger:
                            loop_logger.info(
                                "Provider stream loop: synthetic format tool "
                                "'%s' called at iteration %d/%d — emitting "
                                "structured content as one chunk",
                                synthetic_tool_name,
                                iteration,
                                max_iterations,
                            )
                        yield synthetic_args
                        set_llm_metadata(
                            model=effective_model,
                            provider=vendor or "",
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                        )
                        return

                preamble_text = MeshLlmAgent._join_text_from_chunks(chunks)
                if loop_logger:
                    loop_logger.debug(
                        f"Provider executing {len(merged_tool_calls)} tool calls "
                        f"(iteration {iteration}/{max_iterations})"
                    )

                # See ``_build_assistant_tool_call_dict`` for the
                # ``_gemini_thought_signature`` rationale — the merged dict
                # may carry that Gemini-only sidecar (the streaming merger
                # forwards it from ``_StreamToolCallDelta._thought_signature``)
                # and we propagate it onto the conversation dict so the
                # next iteration's Gemini Part-conversion can echo it back.
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": preamble_text or "",
                    "tool_calls": [
                        _build_assistant_tool_call_dict_from_merged(tc)
                        for tc in merged_tool_calls
                    ],
                }
                current_messages.append(assistant_msg)

                # Synthesize a litellm-shaped message so the Phase 1 helper
                # (which reads ``message.tool_calls``) works unchanged.
                from _mcp_mesh.engine.mesh_llm_agent import _MockMessage

                mock_message = _MockMessage(
                    {
                        "role": "assistant",
                        "content": preamble_text or "",
                        "tool_calls": merged_tool_calls,
                    }
                )

                tool_messages, accumulated_images = (
                    await _execute_tool_calls_for_iteration(
                        mock_message,
                        tool_endpoints,
                        parallel,
                        vendor,
                        loop_logger,
                        has_native_dispatch=_native_handler.has_native(),
                    )
                )
                current_messages.extend(tool_messages)

                if accumulated_images:
                    current_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Here are the images from the tool results above:",
                                },
                                *accumulated_images,
                            ],
                        }
                    )
                    if loop_logger:
                        loop_logger.info(
                            f"Injected user message with {len(accumulated_images)} "
                            f"accumulated images (vendor={vendor})"
                        )

                # Continue the outer loop for the next iteration.
                continue

            # No tool_calls observed this iteration → final answer.
            final_content = MeshLlmAgent._join_text_from_chunks(chunks)

            if buffer_for_hint:
                # Run HINT validation + bounded-timeout fallback. The
                # fallback uses ``litellm.completion`` (sync) so it
                # returns a buffered response; we yield its content as
                # one chunk regardless of whether it ran.
                fallback_base_args = {
                    k: v
                    for k, v in completion_args.items()
                    if k not in ("tools", "tool_choice", "stream", "stream_options")
                }
                try:
                    final_content, _msg, _resp = await _maybe_run_hint_fallback(
                        final_content=final_content,
                        message=None,
                        response=None,
                        base_completion_args=fallback_base_args,
                        hint_mode=hint_mode,
                        hint_schema=hint_schema,
                        hint_fallback_timeout=hint_fallback_timeout,
                        hint_output_type_name=hint_output_type_name,
                        fallback_logger=loop_logger,
                        vendor=vendor,
                    )
                except Exception as e:
                    if loop_logger:
                        loop_logger.error(
                            "Claude HINT fallback to response_format failed: %s",
                            e,
                        )
                    raise

                if final_content:
                    yield final_content

                # If the HINT fallback actually fired (_resp is not None),
                # its tokens/model belong in observability metadata. The
                # streamed attempt's totals already reflect the failed first
                # try; add the fallback's usage so the trace shows the
                # true work performed.
                if _resp is not None and hasattr(_resp, "usage") and _resp.usage:
                    _fb_usage = _resp.usage
                    total_input_tokens += (
                        getattr(_fb_usage, "prompt_tokens", 0) or 0
                    )
                    total_output_tokens += (
                        getattr(_fb_usage, "completion_tokens", 0) or 0
                    )
                    _fb_model = getattr(_resp, "model", None)
                    if _fb_model:
                        effective_model = _fb_model

            set_llm_metadata(
                model=effective_model,
                provider=vendor or "",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

            if loop_logger:
                loop_logger.info(
                    f"Provider-managed stream loop completed in {iteration} iterations"
                )
            return
        finally:
            if not stream_completed:
                aclose = getattr(stream_iter, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception as e:
                        if loop_logger:
                            loop_logger.debug(
                                f"provider stream: aclose() failed during teardown: {e}"
                            )

    # Safety: max iterations reached. Emit a textual indicator so consumers
    # iterating ``async for`` always see at least one chunk in this edge.
    if loop_logger:
        loop_logger.warning(
            f"Provider-managed stream loop hit max iterations ({max_iterations})"
        )
    yield "Maximum tool call iterations reached"


def _extract_vendor_from_model(model: str) -> str | None:
    """
    Extract vendor name from LiteLLM model string.

    LiteLLM uses vendor/model format (e.g., "anthropic/claude-sonnet-4-5").
    This extracts the vendor for provider handler selection.

    Args:
        model: LiteLLM model string

    Returns:
        Vendor name (e.g., "anthropic", "openai") or None if not extractable

    Examples:
        "anthropic/claude-sonnet-4-5" -> "anthropic"
        "openai/gpt-4o" -> "openai"
        "gpt-4" -> None (no vendor prefix)
    """
    if not model:
        return None

    if "/" in model:
        vendor = model.split("/")[0].lower().strip()
        return vendor

    return None


# Canonical LiteLLM-style prefix for each big-3 vendor. Used to normalize an
# inferred bare model name to ``vendor/<name>`` at the routing boundary so the
# native clients' ``supports_model`` / ``_strip_prefix`` work unchanged (they
# require the prefix) and the wire model name is identical to the
# already-prefixed input case (``_strip_prefix`` reverses the normalization).
_BIG3_VENDOR_PREFIX: dict[str, str] = {
    "openai": "openai/",
    "anthropic": "anthropic/",
    # Bare ``gemini-*`` implies Google AI Studio (GOOGLE_API_KEY) — the safe
    # default. Vertex AI requires the explicit ``vertex_ai/`` prefix and is
    # never inferred from a bare name.
    "gemini": "gemini/",
}


def _infer_big3_vendor_from_bare_name(model: str) -> str | None:
    """Infer a big-3 vendor from an UNPREFIXED model name, conservatively.

    LiteLLM's ``get_llm_provider`` resolves some bare names (those in its
    model DB) to a vendor, but raises for others (e.g. ``claude-3-haiku``,
    ``gemini-3-pro``) — those then fall to ``vendor="unknown"`` →
    ``GenericHandler`` → LiteLLM, even though the matching native SDK is
    bundled and native dispatch is default-ON. This helper closes that gap
    for the three vendors that ship native adapters, using only unambiguous
    name prefixes:

      * ``gpt-*``, ``o1*``/``o3*``/``o4*``, ``chatgpt-*`` → ``openai``
      * ``claude-*``                                      → ``anthropic``
      * ``gemini-*``                                      → ``gemini``

    Anything else — including any string that already contains ``/`` (it has
    an explicit prefix; do not second-guess it) and any unknown bare name —
    returns ``None`` so the caller keeps the existing GenericHandler/LiteLLM
    tail behavior.

    Args:
        model: A model identifier (bare or prefixed).

    Returns:
        ``"openai"`` / ``"anthropic"`` / ``"gemini"`` for an unambiguous bare
        big-3 name, else ``None``.
    """
    if not model or "/" in model:
        return None

    name = model.lower().strip()

    # ``o1``/``o3``/``o4`` reasoning families: match only when the prefix is
    # the whole name or is followed by ``-`` (e.g. ``o3``, ``o3-mini``), so a
    # hypothetical unrelated ``o3xyz`` does NOT misroute to openai. Mirrors the
    # trailing-dash discipline of the ``gpt-``/``chatgpt-`` prefixes.
    _openai_reasoning = name in ("o1", "o3", "o4") or name.startswith(
        ("o1-", "o3-", "o4-")
    )

    if (
        name.startswith("gpt-")
        or _openai_reasoning
        or name.startswith("chatgpt-")
    ):
        return "openai"
    if name.startswith("claude-"):
        return "anthropic"
    if name.startswith("gemini-"):
        return "gemini"

    return None


def llm_provider(
    model: str,
    capability: str = "llm",
    tags: list[str] | None = None,
    version: str = "1.0.0",
    **litellm_kwargs: Any,
):
    """
    Zero-code LLM provider decorator.

    Creates a mesh-registered LLM provider that automatically:
    - Registers as MCP tool (@app.tool) for direct MCP calls
    - Registers in mesh network (@mesh.tool) for dependency injection
    - Wraps LiteLLM with standard MeshLlmRequest interface
    - Returns raw string response (caller handles parsing)

    The decorated function becomes a placeholder - the decorator generates
    a process_chat(request: MeshLlmRequest) -> str function that handles
    all LLM provider logic.

    Args:
        model: LiteLLM model name (e.g., "anthropic/claude-sonnet-4-5")
        capability: Capability name for mesh registration (default: "llm")
        tags: Tags for mesh registration (e.g., ["claude", "fast", "+budget"])
        version: Version string for mesh registration (default: "1.0.0")
        **litellm_kwargs: Additional kwargs to pass to litellm.completion()

    Usage:
        from fastmcp import FastMCP
        import mesh

        app = FastMCP("LLM Provider")

        @mesh.llm_provider(
            model="anthropic/claude-sonnet-4-5",
            capability="llm",
            tags=["claude", "test"],
            version="1.0.0",
        )
        def claude_provider():
            '''Zero-code Claude provider.'''
            pass  # Implementation is in the decorator

        @mesh.agent(name="my-provider", auto_run=True)
        class MyProviderAgent:
            pass

    The generated process_chat function signature:
        def process_chat(request: MeshLlmRequest) -> str:
            '''
            Auto-generated LLM handler.

            Args:
                request: MeshLlmRequest with messages, tools, model_params

            Returns:
                Raw LLM response content as string
            '''

    Testing:
        # Direct MCP call
        curl -X POST http://localhost:9019/mcp \\
          -H "Content-Type: application/json" \\
          -d '{
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
              "name": "process_chat",
              "arguments": {
                "request": {
                  "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Say hello."}
                  ]
                }
              }
            }
          }'

    Raises:
        RuntimeError: If FastMCP 'app' not found in module
        ImportError: If litellm not installed
    """

    def decorator(func):
        # Import here to avoid circular imports
        import sys

        from mesh import tool
        from mesh.types import MeshLlmRequest, Stream

        # Find FastMCP app in current module
        current_module = sys.modules.get(func.__module__)
        if not current_module or not hasattr(current_module, "app"):
            raise RuntimeError(
                f"@mesh.llm_provider requires FastMCP 'app' in module {func.__module__}. "
                f"Example: app = FastMCP('LLM Provider')"
            )

        app = current_module.app

        # Extract vendor from model name using LiteLLM
        vendor = "unknown"
        try:
            import litellm

            _, vendor, _, _ = litellm.get_llm_provider(model=model)
            logger.info(
                f"✅ Extracted vendor '{vendor}' from model '{model}' "
                f"using LiteLLM detection"
            )
        except (ImportError, AttributeError, ValueError, KeyError) as e:
            # Fallback: try to extract from model prefix
            # ImportError: litellm not installed
            # AttributeError: get_llm_provider doesn't exist
            # ValueError: invalid model format
            # KeyError: model not in provider mapping
            if "/" in model:
                vendor = model.split("/")[0]
                logger.warning(
                    f"⚠️  Could not extract vendor using LiteLLM ({e}), "
                    f"falling back to prefix extraction: '{vendor}'"
                )
            else:
                logger.warning(
                    f"⚠️  Could not extract vendor from model '{model}', "
                    f"using 'unknown'"
                )

        # Gap #1 (RFC #1100): route UNPREFIXED big-3 names to the native
        # handler. LiteLLM's get_llm_provider only resolves bare names that
        # are in its model DB; novel/uncommon ones (e.g. ``claude-3-haiku``,
        # ``gemini-3-pro``) fall through to ``vendor="unknown"`` →
        # GenericHandler → LiteLLM, bypassing the bundled native SDK. When the
        # vendor is still unresolved AND the model has no explicit ``vendor/``
        # prefix, conservatively infer the big-3 vendor from an unambiguous
        # bare-name prefix and normalize ``model`` to the canonical
        # ``vendor/<name>`` form. Normalizing here (the single vendor-
        # resolution chokepoint) means the native clients' supports_model /
        # _strip_prefix work unchanged and the outbound wire model name is
        # identical to the already-prefixed-input case. Already-prefixed
        # models and non-big-3 bare names are untouched (stay on the
        # GenericHandler/LiteLLM tail).
        #
        # ``provider_model`` holds the (possibly-normalized) model string used
        # for all downstream dispatch (it seeds ``effective_model``). The
        # original ``model`` closure parameter is left untouched so reassigning
        # it here cannot turn it into a function-local and trip an
        # UnboundLocalError on the LiteLLM-detection read above.
        provider_model = model
        if vendor == "unknown" and "/" not in model:
            inferred = _infer_big3_vendor_from_bare_name(model)
            if inferred is not None:
                vendor = inferred
                provider_model = f"{_BIG3_VENDOR_PREFIX[inferred]}{model}"
                logger.info(
                    f"🔀 Inferred big-3 vendor '{vendor}' from bare model "
                    f"name; normalized to '{provider_model}' for native "
                    f"dispatch (RFC #1100 Gap #1)"
                )

        def _prepare_provider_request(
            request: MeshLlmRequest,
            *,
            streaming: bool = False,
        ) -> tuple[
            str,
            list[dict[str, Any]],
            list[dict[str, Any]] | None,
            dict[str, str],
            dict[str, Any],
        ]:
            """Shared setup for ``process_chat`` and ``process_chat_stream``.

            Both the buffered and streaming auto-generated handlers need the
            same preamble: resolve the effective model (with consumer
            override), apply vendor-specific structured-output handling
            (issue #459), extract mesh tool endpoints from
            ``request.tools`` (mutating each tool dict to strip
            ``_mesh_endpoint`` — same as the original inline code), and
            format the system prompt via the vendor handler when tools are
            present. Centralizing keeps both paths in lock-step so a future
            change to one cannot drift from the other.

            The ``streaming`` flag is plumbed through to
            ``handler.apply_structured_output`` so vendors that have
            synthetic-tool injection (Claude native) route to HINT mode for
            streaming — synthetic-tool produces a single discrete tool call
            that doesn't actually stream as chunks.

            Returns a 5-tuple:
                ``(effective_model, messages, clean_tools, tool_endpoints,
                model_params_copy)``
            where ``clean_tools`` is ``None`` when ``request.tools`` is
            None / empty (preserving the legacy buffered path's existing
            behavior of omitting ``tools`` from ``completion_args``).
            """
            # Determine effective model (check for consumer override - issue #308)
            effective_model = provider_model  # Default to provider's (normalized) model
            model_params_copy = (
                dict(request.model_params) if request.model_params else {}
            )

            if "model" in model_params_copy:
                override_model = model_params_copy.pop(
                    "model"
                )  # Remove to avoid duplication

                if override_model:
                    # Validate vendor compatibility
                    override_vendor = _extract_vendor_from_model(override_model)

                    if override_vendor and override_vendor != vendor:
                        # Vendor mismatch - log warning and fall back to provider's model
                        logger.warning(
                            f"⚠️ Model override '{override_model}' ignored - vendor mismatch "
                            f"(override vendor: '{override_vendor}', provider vendor: '{vendor}'). "
                            f"Using provider's default model: '{provider_model}'"
                        )
                    else:
                        # Vendor matches or can't be determined - use override
                        effective_model = override_model
                        logger.info(
                            f"🔄 Using model override '{effective_model}' "
                            f"(requested by consumer)"
                        )

            # Get vendor handler once - used for both structured output and system prompt formatting
            # (``ProviderHandlerRegistry`` is imported at module top.)
            handler = ProviderHandlerRegistry.get_handler(vendor)

            # Issue #459: Handle output_schema for vendor-specific structured output
            # Use provider handler pattern for vendor-specific behavior
            output_schema = model_params_copy.pop("output_schema", None)
            output_type_name = model_params_copy.pop("output_type_name", None)

            # Source-of-truth for messages downstream. Defaults to the
            # request's messages; ``apply_structured_output`` may swap in a
            # NEW list (Claude native synthetic-format path builds an
            # augmented list to avoid mutating the caller's reference). We
            # read it back from ``model_params_copy`` so that augmentation
            # flows through to the agentic loop.
            effective_messages = request.messages
            if output_schema:
                # Include messages so handler can modify system prompt (e.g., HINT mode injection)
                model_params_copy["messages"] = request.messages
                handler.apply_structured_output(
                    output_schema,
                    output_type_name,
                    model_params_copy,
                    streaming=streaming,
                    model=effective_model,
                )
                # Pull back the (possibly-replaced) messages list before
                # popping the key off the model_params dict — the native
                # synthetic-format path returns a NEW list rather than
                # mutating the original.
                effective_messages = model_params_copy.get(
                    "messages", request.messages
                )
                # Remove messages to avoid duplication in completion_args
                model_params_copy.pop("messages", None)
                logger.debug(
                    f"🎯 Applied {vendor} structured output via handler: "
                    f"{output_type_name}"
                )

            # Check if tools have mesh endpoints for provider-side execution
            tool_endpoints: dict[str, str] = {}
            clean_tools: list[dict[str, Any]] | None = None
            if request.tools:
                clean_tools = []
                for req_tool in request.tools:
                    func_def = req_tool.get("function", {})
                    endpoint = func_def.pop("_mesh_endpoint", None)
                    if endpoint:
                        tool_endpoints[func_def.get("name", "")] = endpoint
                    clean_tools.append(req_tool)

            # Use vendor handler to format system prompt when tools are present
            effective_tools = clean_tools if clean_tools is not None else request.tools
            # Use the messages list returned by ``apply_structured_output``
            # (may be the request's original list OR a new augmented list
            # built by the Claude native synthetic-format path).
            messages = effective_messages
            if effective_tools:

                # Find and format system message
                formatted_messages = []
                for msg in messages:
                    if msg.get("role") == "system":
                        # Format system prompt with vendor-specific instructions
                        base_prompt = msg.get("content", "")
                        formatted_content = handler.format_system_prompt(
                            base_prompt=base_prompt,
                            tool_schemas=effective_tools,
                            output_type=str,  # Provider returns raw string
                        )
                        formatted_messages.append(
                            {"role": "system", "content": formatted_content}
                        )
                    else:
                        formatted_messages.append(msg)
                messages = formatted_messages

            return (
                effective_model,
                messages,
                clean_tools,
                tool_endpoints,
                model_params_copy,
            )

        # Generate the LLM handler function
        async def process_chat(request: MeshLlmRequest) -> dict[str, Any]:
            """
            Auto-generated LLM handler.

            Args:
                request: MeshLlmRequest with messages, tools, model_params

            Returns:
                Full message dict with content, role, and tool_calls (if present)
            """
            import litellm

            (
                effective_model,
                messages,
                clean_tools,
                tool_endpoints,
                model_params_copy,
            ) = _prepare_provider_request(request, streaming=False)
            effective_tools = clean_tools if clean_tools is not None else request.tools

            if tool_endpoints:
                # Provider-managed agentic loop: execute tools internally
                logger.info(
                    f"Provider-managed loop: {len(tool_endpoints)} tools with endpoints"
                )
                message_dict = await _provider_agentic_loop(
                    effective_model=effective_model,
                    messages=messages,
                    tools=clean_tools or [],
                    tool_endpoints=tool_endpoints,
                    model_params=model_params_copy,
                    litellm_kwargs=litellm_kwargs,
                    max_iterations=10,
                    loop_logger=logger,
                    vendor=vendor,
                )

                logger.info(
                    f"LLM provider {func.__name__} processed request via provider loop "
                    f"(model={effective_model}, messages={len(request.messages)})"
                )

                return message_dict

            # Legacy path: single LLM call, return tool_calls to consumer
            completion_args: dict[str, Any] = {
                "model": effective_model,
                "messages": messages,
                **litellm_kwargs,
            }

            if effective_tools:
                completion_args["tools"] = effective_tools

            if model_params_copy:
                completion_args.update(model_params_copy)

            # Strip internal mesh control flags before they reach LiteLLM.
            # These are set by handlers (e.g., ClaudeHandler HINT mode) and
            # would otherwise cause provider APIs to reject the request with
            # HTTP 400 ("Extra inputs are not permitted"). The HINT fallback
            # below uses the captured values.
            # NOTE: The provider-managed loop above does the SAME strip —
            # see ``_provider_agentic_loop`` for the multi-iteration path.
            (
                hint_mode,
                hint_schema,
                hint_fallback_timeout,
                hint_output_type_name,
            ) = _pop_mesh_hint_flags(completion_args)

            (
                synthetic_tool_name,
                synthetic_tool,
                synthetic_output_type_name,
            ) = _pop_mesh_synthetic_format_flags(completion_args)

            # Native ``output_config`` state (mirrors the agentic loop).
            # Pop the sentinels so they never leak into the wire request;
            # ``output_config_mode`` gates the synthetic-fallback skip below.
            (
                output_config_mode,
                output_config_schema,
                output_config_output_type_name,
            ) = _pop_mesh_output_config_flags(completion_args)

            # Inject synthetic format tool when handler signaled it. Same
            # logic as the agentic loop. Mirrors the no-tools→one-iteration
            # case there: when there are zero real user tools, ``tool_choice``
            # is forced to the synthetic for a deterministic single round-trip.
            if synthetic_tool_name and synthetic_tool:
                completion_args["tools"] = _inject_synthetic_format_tool(
                    completion_args.get("tools"), synthetic_tool, completion_args
                )

            try:
                logger.debug(
                    f"📤 LLM provider request: {format_log_value(completion_args)}"
                )

                # Native dispatch (issue #834, PR 1): route through the
                # vendor's native SDK adapter by default when the SDK is
                # installed. Set MCP_MESH_NATIVE_LLM=0 to force LiteLLM.
                # (``ProviderHandlerRegistry`` is imported at module top.)
                _native_handler = ProviderHandlerRegistry.get_handler(vendor)
                if _native_handler.has_native():
                    _native_args = {
                        k: v
                        for k, v in completion_args.items()
                        if k not in ("model", "api_key", "base_url")
                    }
                    response = await _native_handler.complete(
                        _native_args,
                        model=effective_model,
                        api_key=completion_args.get("api_key"),
                        base_url=completion_args.get("base_url"),
                    )
                else:
                    response = await asyncio.to_thread(
                        litellm.completion, **completion_args
                    )

                logger.debug(f"📥 LLM provider response: {format_log_value(response)}")

                message = response.choices[0].message

                # Synthetic-format-tool recognition: the model's call to the
                # synthetic tool IS the structured answer. Surface its args as
                # ``content`` and DROP tool_calls so downstream consumers don't
                # try to "execute" a synthetic tool that has no MCP endpoint.
                synthetic_args: str | None = None
                if synthetic_tool_name:
                    synthetic_args, _ = _extract_synthetic_format_arguments(
                        message, synthetic_tool_name
                    )

                if synthetic_args is not None:
                    if logger:
                        logger.info(
                            "LLM provider %s: synthetic format tool '%s' called "
                            "— returning structured content (legacy single-call path)",
                            func.__name__,
                            synthetic_tool_name,
                        )
                    message_dict = {
                        "role": getattr(message, "role", "assistant"),
                        "content": synthetic_args,
                    }
                    if hasattr(response, "usage") and response.usage:
                        usage = response.usage
                        message_dict["_mesh_usage"] = {
                            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                            "model": effective_model,
                        }
                    return message_dict

                # Handle content - it can be a string or list of content blocks
                final_content = _extract_text_from_message_content(message.content)

                # HINT-mode validation + bounded-timeout fallback (issue #820).
                # Mirrors the same logic in ``_provider_agentic_loop``. Without
                # this, a HINT compliance failure here would surface as a
                # ResponseParseError to the consumer.
                # NOTE: only run when there are no tool_calls — if the model
                # returned tools, structured output is not yet expected.
                no_tool_calls = not (
                    hasattr(message, "tool_calls") and message.tool_calls
                )
                if no_tool_calls:
                    # Native ``output_config`` short-circuit (Anthropic Sonnet
                    # 4.5+ / Opus 4.1+). Anthropic enforces the schema via
                    # ``output_config.format`` and returns the structured JSON
                    # answer as a plain TextBlock — synthetic-fallback would
                    # be wrong (no synthetic tool injected) and HINT-fallback
                    # is mutually exclusive with output_config mode. Defense-
                    # in-depth: WARN if the text doesn't parse against the
                    # schema, but don't retry.
                    if output_config_mode:
                        if (
                            output_config_schema is not None
                            and final_content
                            and not _hint_response_parses(
                                final_content, output_config_schema
                            )
                        ):
                            logger.warning(
                                "Native output_config mode for '%s': returned "
                                "text did not parse against the schema "
                                "(Anthropic's output_config.format normally "
                                "enforces this) — surfacing the raw text to "
                                "the caller without retry",
                                output_config_output_type_name,
                            )
                        # Fall through to the message_dict construction below
                        # (skip both HINT and synthetic fallbacks).
                    else:
                        # Build base args for the fallback — strip ``tools`` AND
                        # ``tool_choice`` since the fallback only fires AFTER the
                        # model gave a final answer with no tool_calls. Keeping
                        # ``tools`` would re-introduce the ``response_format +
                        # tools`` combo that caused the original silent hang
                        # (issue #820); ``tool_choice`` has no meaning once tools
                        # are gone and would be rejected by some vendors. Mirrors
                        # the agentic-loop fallback site.
                        fallback_base_args = {
                            k: v
                            for k, v in completion_args.items()
                            if k not in ("tools", "tool_choice")
                        }
                        if hint_mode:
                            try:
                                final_content, message, response = await _maybe_run_hint_fallback(
                                    final_content=final_content,
                                    message=message,
                                    response=response,
                                    base_completion_args=fallback_base_args,
                                    hint_mode=hint_mode,
                                    hint_schema=hint_schema,
                                    hint_fallback_timeout=hint_fallback_timeout,
                                    hint_output_type_name=hint_output_type_name,
                                    fallback_logger=logger,
                                    vendor=vendor,
                                )
                            except Exception as fallback_err:
                                logger.error(
                                    "Claude HINT fallback to response_format failed: %s",
                                    fallback_err,
                                )
                                raise

                        # Native synthetic-tool fallback (mirrors the agentic loop
                        # post-HINT block). Fires when the native synthetic-tool
                        # path is active and the model declined to call
                        # ``__mesh_format_response`` (returning plain text). The
                        # two fallbacks are mutually exclusive in practice — HINT
                        # mode and synthetic-tool mode are alternative dispatch
                        # shapes — so the early-returns in each helper gate this
                        # correctly.
                        try:
                            final_content, message, response = await _maybe_run_synthetic_fallback(
                                final_content=final_content,
                                message=message,
                                response=response,
                                base_completion_args=fallback_base_args,
                                synthetic_tool_name=synthetic_tool_name,
                                synthetic_tool=synthetic_tool,
                                fallback_timeout=hint_fallback_timeout,
                                fallback_logger=logger,
                                vendor=vendor,
                            )
                        except Exception as fallback_err:
                            logger.error(
                                "Native synthetic-tool fallback to response_format "
                                "failed: %s",
                                fallback_err,
                            )
                            raise

                message_dict: dict[str, Any] = {
                    "role": message.role,
                    "content": final_content if final_content else "",
                }

                # Include tool_calls if present (critical for agentic loop support!)
                #
                # Use the shared ``_build_assistant_tool_call_dict`` helper so
                # the Gemini-only ``_gemini_thought_signature`` sidecar is
                # forwarded onto the conversation dict. Inline construction
                # would silently drop the signature, breaking the next-iteration
                # request to thinking Gemini models with HTTP 400 ("Function
                # call is missing a thought_signature"). This single-call
                # branch fires for callers who hit ``process_chat`` directly
                # (no agentic-loop path) — the loop branch (~line 849) already
                # uses the helper.
                if hasattr(message, "tool_calls") and message.tool_calls:
                    message_dict["tool_calls"] = [
                        _build_assistant_tool_call_dict(tc)
                        for tc in message.tool_calls
                    ]

                # Issue #311: Include usage metadata for cost tracking
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    message_dict["_mesh_usage"] = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0)
                        or 0,
                        "model": effective_model,
                    }

                logger.info(
                    f"LLM provider {func.__name__} processed request "
                    f"(model={effective_model}, messages={len(request.messages)}, "
                    f"tool_calls={len(message_dict.get('tool_calls', []))})"
                )

                return message_dict

            except Exception as e:
                logger.error(f"LLM provider {func.__name__} failed: {e}")
                raise

        # Auto-generated streaming counterpart: yields text chunks from the
        # provider's agentic loop. Co-exists with ``process_chat`` and shares
        # the same capability + tags so consumers can soft-fall-back to the
        # buffered tool when no streaming variant is registered. The
        # ``Stream[str]`` return annotation triggers
        # :func:`detect_stream_type` in the ``@mesh.tool`` layer, which
        # stamps ``metadata["stream_type"] = "text"`` and switches FastMCP
        # to the streaming runtime wrapper (chunks → progress notifications).
        async def process_chat_stream(request: MeshLlmRequest) -> Stream[str]:
            """Auto-generated streaming LLM handler.

            Yields text chunks from the provider's agentic loop. Intermediate
            iterations whose assistant turn requests tool_calls execute the
            tools internally on the provider; the final iteration's text
            streams chunk-by-chunk to the consumer via FastMCP progress
            notifications. HINT-mode requests buffer the final iteration to
            run the schema-validation fallback (see
            ``_provider_agentic_loop_stream``).
            """
            (
                effective_model,
                messages,
                clean_tools,
                tool_endpoints,
                model_params_copy,
            ) = _prepare_provider_request(request, streaming=True)
            effective_tools = (
                clean_tools if clean_tools is not None else request.tools
            )

            if tool_endpoints:
                logger.info(
                    f"Provider-managed stream loop: {len(tool_endpoints)} tools with endpoints"
                )
                async for chunk in _provider_agentic_loop_stream(
                    effective_model=effective_model,
                    messages=messages,
                    tools=clean_tools or [],
                    tool_endpoints=tool_endpoints,
                    model_params=model_params_copy,
                    litellm_kwargs=litellm_kwargs,
                    max_iterations=10,
                    loop_logger=logger,
                    vendor=vendor,
                ):
                    yield chunk
                logger.info(
                    f"LLM provider {func.__name__}_stream completed "
                    f"(model={effective_model}, messages={len(request.messages)})"
                )
                return

            # Legacy no-tools path: single ``litellm.acompletion(stream=True)``
            # passthrough. Mirrors the no-tools branch of ``process_chat`` but
            # streams chunks instead of buffering. We do NOT run the HINT
            # fallback here because the no-tools path does not pre-inject the
            # HINT-mode flags (those come from ``handler.apply_structured_output``
            # which only runs when ``output_schema`` is set in
            # ``model_params``); the buffered legacy path's HINT branch is
            # preserved exactly as-is in ``process_chat``.
            import litellm

            completion_args: dict[str, Any] = {
                "model": effective_model,
                "messages": messages,
                **litellm_kwargs,
            }
            if effective_tools:
                completion_args["tools"] = effective_tools
            if model_params_copy:
                completion_args.update(model_params_copy)

            # Strip internal mesh control flags before they reach LiteLLM
            # (mirrors the buffered legacy path). Captured values are not
            # used here for HINT mode — HINT validation cannot be applied
            # to a live stream without buffering. Synthetic-format flags are
            # also stripped: per Phase C, streaming + structured output
            # routes to HINT mode in ClaudeHandler (synthetic-tool injection
            # is buffered-only), so these flags should not be set on this
            # path; the strip is defense-in-depth against misconfiguration.
            _pop_mesh_hint_flags(completion_args)
            _pop_mesh_synthetic_format_flags(completion_args)
            _pop_mesh_output_config_flags(completion_args)

            existing_stream_opts = completion_args.get("stream_options") or {}
            completion_args["stream"] = True
            completion_args["stream_options"] = {
                **existing_stream_opts,
                "include_usage": True,
            }

            from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
            from _mcp_mesh.tracing.context import set_llm_metadata

            # Native dispatch (issue #834, PR 1): route through the
            # vendor's native SDK streaming adapter by default when the
            # SDK is installed. Set MCP_MESH_NATIVE_LLM=0 to force the
            # LiteLLM fallback path. (``ProviderHandlerRegistry`` is
            # imported at module top.)
            _native_handler = ProviderHandlerRegistry.get_handler(vendor)
            if _native_handler.has_native():
                _native_args = {
                    k: v
                    for k, v in completion_args.items()
                    if k
                    not in (
                        "model",
                        "api_key",
                        "base_url",
                        "stream",
                        "stream_options",
                    )
                }
                stream_iter = await _native_handler.complete_stream(
                    _native_args,
                    model=effective_model,
                    api_key=completion_args.get("api_key"),
                    base_url=completion_args.get("base_url"),
                )
            else:
                stream_iter = await litellm.acompletion(**completion_args)
            chunks: list[Any] = []
            stream_completed = False
            saw_tool_call = False
            try:
                async for chunk in stream_iter:
                    chunks.append(chunk)
                    if MeshLlmAgent._chunk_has_tool_call(chunk):
                        saw_tool_call = True
                        continue
                    if saw_tool_call:
                        # Tool-call deltas continue arriving; suppress text
                        # to avoid interleaving partial text with the JSON
                        # we'll emit at end-of-stream.
                        continue
                    text = MeshLlmAgent._extract_text_from_chunk(chunk)
                    if text:
                        yield text
                stream_completed = True
            finally:
                if not stream_completed:
                    aclose = getattr(stream_iter, "aclose", None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception as e:
                            logger.debug(
                                f"provider stream (no-tools): aclose() failed: {e}"
                            )

            usage = MeshLlmAgent._extract_usage_from_chunks(chunks)
            iter_model = MeshLlmAgent._extract_model_from_chunks(chunks)
            set_llm_metadata(
                model=iter_model or effective_model,
                provider=vendor or "",
                input_tokens=(usage or {}).get("prompt_tokens", 0) or 0,
                output_tokens=(usage or {}).get("completion_tokens", 0) or 0,
            )

            logger.info(
                f"LLM provider {func.__name__}_stream completed "
                f"(model={effective_model}, messages={len(request.messages)}, "
                f"no-tools-path)"
            )

        # Preserve original function's docstring metadata
        if func.__doc__:
            process_chat.__doc__ = func.__doc__ + "\n\n" + (process_chat.__doc__ or "")

        # FIX for issue #227: Preserve original function name to avoid conflicts
        # when multiple @mesh.llm_provider decorators are used in the same agent.
        # FastMCP uses __name__ as the tool name, so without this fix all providers
        # would be registered as "process_chat" and overwrite each other.
        process_chat.__name__ = func.__name__
        process_chat.__qualname__ = func.__qualname__

        # Streaming variant follows the same pattern but with a ``_stream``
        # suffix so the consumer can call ``proxy.stream(name=f"{fn}_stream")``
        # and fall back to ``proxy(...)`` when the suffix tool is absent.
        process_chat_stream.__name__ = f"{func.__name__}_stream"
        process_chat_stream.__qualname__ = f"{func.__qualname__}_stream"

        # CRITICAL: Apply @mesh.tool() FIRST (before FastMCP caches the function)
        # This ensures mesh DI wrapper is in place when FastMCP caches the function
        # Decorators are applied bottom-up, so mesh wrapper must be innermost
        process_chat = tool(
            capability=capability,
            tags=tags,
            version=version,
            vendor=vendor,  # Pass vendor to registry for provider handler selection
        )(process_chat)

        # Then apply @app.tool() for MCP registration (caches the wrapped version)
        process_chat = app.tool()(process_chat)

        # Same decorator order for the streaming variant. Same capability /
        # tags / vendor — soft-fallback to the buffered tool is keyed off the
        # ``_stream`` suffix on the tool NAME, not on a separate capability.
        #
        # The ``ai.mcpmesh.stream`` tag is the producer half of a contract with
        # ``@mesh.llm``: the consumer-side decorator augments its provider tags
        # filter with ``ai.mcpmesh.stream`` (required) when the consumer returns
        # ``Stream[str]`` and ``-ai.mcpmesh.stream`` (excluded) otherwise. This
        # lets the registry resolver pick the right variant deterministically
        # via existing tag-operator semantics — no resolver special-casing.
        stream_tags = list(tags or []) + ["ai.mcpmesh.stream"]
        process_chat_stream = tool(
            capability=capability,
            tags=stream_tags,
            version=version,
            vendor=vendor,
        )(process_chat_stream)
        process_chat_stream = app.tool()(process_chat_stream)

        logger.info(
            f"✅ Created LLM provider '{func.__name__}' "
            f"(+ streaming variant '{func.__name__}_stream'; "
            f"model={model}, capability={capability}, tags={tags}, vendor={vendor})"
        )

        # Return the generated function (replaces the placeholder).
        # The streaming variant is registered via @app.tool() and @tool()
        # side effects above; it does not need to be returned to the caller.
        return process_chat

    return decorator
