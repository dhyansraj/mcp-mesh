"""
Helper decorators for common mesh patterns.

This module provides convenience decorators that build on top of the core
mesh decorators to simplify common patterns like zero-code LLM providers.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

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


def _pop_mesh_hint_flags(
    completion_args: dict[str, Any],
    defaults: tuple[bool, dict | None, int, str] = (False, None, 30, "Response"),
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

    # Anthropic's structured output requires additionalProperties: false on every
    # object type in the schema. Pydantic-generated schemas don't include that by
    # default. The base apply_structured_output path already strict-ifies via
    # make_schema_strict; the HINT fallback was missing the same step, causing
    # Anthropic's "output_format.schema: ... must be explicitly set to false"
    # rejection on complex schemas (nested BaseModels). add_all_required=False
    # because Claude — unlike OpenAI/Gemini — does not require every property
    # to be in 'required'.
    from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
        make_schema_strict,
    )

    strict_hint_schema = make_schema_strict(hint_schema, add_all_required=False)

    fallback_args = {
        **base_completion_args,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": hint_output_type_name,
                "schema": strict_hint_schema,
                "strict": True,
            },
        },
        "request_timeout": hint_fallback_timeout,
    }
    # Lazy import keeps this module importable in environments without
    # litellm (e.g., during static analysis); both call sites already
    # import litellm before invoking this helper.
    import litellm

    fallback_response = await asyncio.to_thread(
        litellm.completion, **fallback_args
    )
    fb_message = fallback_response.choices[0].message
    fb_content = _extract_text_from_message_content(fb_message.content)

    if fallback_logger:
        fallback_logger.info("Claude HINT fallback to response_format succeeded")

    return (fb_content if fb_content else "", fb_message, fallback_response)


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
      * Resolve resource_link items in the tool result to multimodal content
        using the OpenAI-compatible image_url format (LiteLLM converts to the
        provider-native format).
      * For vendors that do not support images in role:tool messages
        (OpenAI / Gemini / Google), strip image parts out of the tool message
        and accumulate them so the caller can synthesize a follow-up user
        message after all tool results.
      * For vendors that do support images in role:tool messages
        (Anthropic / Claude via LiteLLM), inline the resolved multimodal
        content directly in the tool message.

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

    Returns:
        A tuple ``(tool_messages, accumulated_images)`` where:
          * ``tool_messages`` is the ordered list of
            ``{role: "tool", tool_call_id: ..., content: ...}`` dicts to be
            appended to the conversation immediately after the assistant
            message that requested the tools.
          * ``accumulated_images`` is the list of image dicts (in
            OpenAI-compatible format) to be sent in a follow-up user message
            after all tool results, for vendors that do not support images
            in role:tool messages. Empty for other vendors.
    """
    from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy
    from _mcp_mesh.media.resolver import _has_resource_link, resolve_resource_links

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
            # Always use OpenAI-compatible format (image_url with
            # data URIs) — LiteLLM converts to provider-native.
            if vendor and _has_resource_link(result):
                try:
                    # Always use OpenAI format — LiteLLM converts to
                    # provider-native format internally.
                    resolved_parts = await resolve_resource_links(
                        result, "openai"
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

    # HINT-mode state (set by ClaudeHandler.apply_structured_output).
    # Captured outside the loop so the fallback after the loop has access.
    hint_mode = False
    hint_schema: dict[str, Any] | None = None
    hint_fallback_timeout = 30
    hint_output_type_name = "Response"

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

        # Strip internal mesh control flags before they reach LiteLLM.
        # These are set by handlers (e.g., ClaudeHandler HINT mode) to
        # signal post-processing to the loop. Must run every iteration
        # because model_params is unconditionally re-applied above.
        # NOTE: The legacy single-call path below (in ``llm_provider``) does
        # the SAME strip — keep both in sync.
        (
            hint_mode,
            hint_schema,
            hint_fallback_timeout,
            hint_output_type_name,
        ) = _pop_mesh_hint_flags(
            completion_args,
            defaults=(
                hint_mode,
                hint_schema,
                hint_fallback_timeout,
                hint_output_type_name,
            ),
        )

        response = await asyncio.to_thread(litellm.completion, **completion_args)
        message = response.choices[0].message

        if hasattr(message, "tool_calls") and message.tool_calls:
            if loop_logger:
                loop_logger.debug(
                    f"Provider executing {len(message.tool_calls)} tool calls "
                    f"(iteration {iteration}/{max_iterations})"
                )

            # Add assistant message with tool_calls to conversation
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            current_messages.append(assistant_msg)

            tool_messages, accumulated_images = await _execute_tool_calls_for_iteration(
                message, tool_endpoints, parallel, vendor, loop_logger
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

            # HINT-mode validation + bounded-timeout fallback (issue #820).
            # If a handler (currently only ClaudeHandler) signaled HINT mode,
            # validate the final response against the schema. If it fails to
            # parse, retry once with native response_format and a hard timeout.
            # This recovers from HINT compliance failures without re-introducing
            # the silent 600s+ hang of the unbounded response_format path.
            #
            # Build base args for the fallback — strip ``tools`` since the
            # fallback only fires AFTER the model gave a final answer with no
            # tool_calls. Keeping ``tools`` would re-introduce the
            # ``response_format + tools`` combo that caused the original
            # silent hang (issue #820). Bounded timeout is still there as
            # defense-in-depth, but stripping tools removes the deadlock
            # vector entirely.
            fallback_base_args = {
                k: v for k, v in completion_args.items() if k != "tools"
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
                )
            except Exception as e:
                if loop_logger:
                    loop_logger.error(
                        "Claude HINT fallback to response_format failed: %s",
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

    hint_mode = False
    hint_schema: dict[str, Any] | None = None
    hint_fallback_timeout = 30
    hint_output_type_name = "Response"

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

        # Strip internal mesh control flags before they reach LiteLLM
        # (mirrors the buffered loop and the legacy single-call path).
        (
            hint_mode,
            hint_schema,
            hint_fallback_timeout,
            hint_output_type_name,
        ) = _pop_mesh_hint_flags(
            completion_args,
            defaults=(
                hint_mode,
                hint_schema,
                hint_fallback_timeout,
                hint_output_type_name,
            ),
        )

        existing_stream_opts = completion_args.get("stream_options") or {}
        completion_args["stream"] = True
        completion_args["stream_options"] = {
            **existing_stream_opts,
            "include_usage": True,
        }

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

                preamble_text = MeshLlmAgent._join_text_from_chunks(chunks)
                if loop_logger:
                    loop_logger.debug(
                        f"Provider executing {len(merged_tool_calls)} tool calls "
                        f"(iteration {iteration}/{max_iterations})"
                    )

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": preamble_text or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": tc["type"],
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
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
                    if k not in ("tools", "stream", "stream_options")
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

        def _prepare_provider_request(
            request: MeshLlmRequest,
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

            Returns a 5-tuple:
                ``(effective_model, messages, clean_tools, tool_endpoints,
                model_params_copy)``
            where ``clean_tools`` is ``None`` when ``request.tools`` is
            None / empty (preserving the legacy buffered path's existing
            behavior of omitting ``tools`` from ``completion_args``).
            """
            # Determine effective model (check for consumer override - issue #308)
            effective_model = model  # Default to provider's model
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
                            f"Using provider's default model: '{model}'"
                        )
                    else:
                        # Vendor matches or can't be determined - use override
                        effective_model = override_model
                        logger.info(
                            f"🔄 Using model override '{effective_model}' "
                            f"(requested by consumer)"
                        )

            # Get vendor handler once - used for both structured output and system prompt formatting
            from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

            handler = ProviderHandlerRegistry.get_handler(vendor)

            # Issue #459: Handle output_schema for vendor-specific structured output
            # Use provider handler pattern for vendor-specific behavior
            output_schema = model_params_copy.pop("output_schema", None)
            output_type_name = model_params_copy.pop("output_type_name", None)

            if output_schema:
                # Include messages so handler can modify system prompt (e.g., HINT mode injection)
                model_params_copy["messages"] = request.messages
                handler.apply_structured_output(
                    output_schema, output_type_name, model_params_copy
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
            messages = request.messages
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
            ) = _prepare_provider_request(request)
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

            try:
                logger.debug(
                    f"📤 LLM provider request: {format_log_value(completion_args)}"
                )

                response = await asyncio.to_thread(
                    litellm.completion, **completion_args
                )

                logger.debug(f"📥 LLM provider response: {format_log_value(response)}")

                message = response.choices[0].message

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
                if hint_mode and no_tool_calls:
                    # Build base args for the fallback — strip ``tools`` since
                    # the fallback only fires AFTER the model gave a final
                    # answer with no tool_calls. Keeping ``tools`` would
                    # re-introduce the ``response_format + tools`` combo that
                    # caused the original silent hang (issue #820). Bounded
                    # timeout is still there as defense-in-depth, but stripping
                    # tools removes the deadlock vector entirely.
                    fallback_base_args = {
                        k: v for k, v in completion_args.items() if k != "tools"
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
                            fallback_logger=logger,
                        )
                    except Exception as fallback_err:
                        logger.error(
                            "Claude HINT fallback to response_format failed: %s",
                            fallback_err,
                        )
                        raise

                message_dict: dict[str, Any] = {
                    "role": message.role,
                    "content": final_content if final_content else "",
                }

                # Include tool_calls if present (critical for agentic loop support!)
                if hasattr(message, "tool_calls") and message.tool_calls:
                    message_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
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
            ) = _prepare_provider_request(request)
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
            # used here — HINT validation cannot be applied to a live
            # stream without buffering, and this no-tools branch never
            # runs ``apply_structured_output``. Future work could buffer
            # if HINT mode is later signaled by another route.
            _pop_mesh_hint_flags(completion_args)

            existing_stream_opts = completion_args.get("stream_options") or {}
            completion_args["stream"] = True
            completion_args["stream_options"] = {
                **existing_stream_opts,
                "include_usage": True,
            }

            from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
            from _mcp_mesh.tracing.context import set_llm_metadata

            stream_iter = await litellm.acompletion(**completion_args)
            chunks: list[Any] = []
            stream_completed = False
            try:
                async for chunk in stream_iter:
                    chunks.append(chunk)
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
