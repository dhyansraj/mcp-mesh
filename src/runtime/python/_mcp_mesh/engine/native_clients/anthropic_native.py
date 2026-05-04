"""Native Anthropic SDK adapter for the provider-side LLM dispatch path.

Adapts ``anthropic.AsyncAnthropic`` (and ``AsyncAnthropicBedrock``) to the
litellm.completion() / litellm.acompletion() response shapes that the rest
of the provider-side code in ``mesh/helpers.py`` already consumes.

Design notes:
  * Module-level functions, not a class — keeps the adapter functional and
    avoids state that could leak across requests.
  * Lazy import of ``anthropic`` inside every function so importing this
    module never fails when the SDK is absent.
  * Lazy ``AsyncAnthropic`` wrapper construction per-call (the wrapper
    itself is NOT cached) — required for K8s secret rotation: the api_key
    is re-read every time we build a client. The underlying ``httpx``
    connection pool IS cached process-wide via ``_get_shared_httpx_client``
    so TLS handshakes and HTTP/2 sessions are reused across calls.
  * Backend selection by model prefix: anthropic/* → AsyncAnthropic,
    bedrock/anthropic.claude-* → AsyncAnthropicBedrock,
    databricks/anthropic.claude-* → AsyncAnthropic with workspace base_url.
  * Response shape: returns objects mirroring the ``_MockResponse`` family
    in ``_mcp_mesh.engine.mesh_llm_agent`` (choices[0].message.content/.role/
    .tool_calls + usage.prompt_tokens/.completion_tokens + .model). Stream
    chunks mirror the litellm streaming shape consumed by helpers.py
    (chunk.choices[0].delta.content / .tool_calls and chunk.usage / .model).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Matches: data:<mime>;base64,<data>
_DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)

# Model prefixes that route through this adapter.
_ANTHROPIC_PREFIXES = ("anthropic/",)
_BEDROCK_ANTHROPIC_PREFIX = "bedrock/anthropic."
_DATABRICKS_ANTHROPIC_PREFIX = "databricks/anthropic."


# ---------------------------------------------------------------------------
# Shared httpx connection pool (issue #834 perf fix)
# ---------------------------------------------------------------------------
# A single ``httpx.AsyncClient`` is reused across all native Anthropic calls
# in this process. ``anthropic.AsyncAnthropic`` accepts ``http_client=`` and
# uses the supplied client (and its connection pool) instead of constructing
# a fresh one per call. This eliminates ~150-300ms per-call TLS+H2 setup
# overhead measured against LiteLLM (which does its own pool reuse).
#
# K8s secret rotation still works because the api_key is still read fresh
# per call by callers and forwarded to the per-call ``AsyncAnthropic``
# wrapper — the pool itself carries no credential state, only TCP/TLS
# connections.
_CACHED_HTTPX_CLIENT: httpx.AsyncClient | None = None


def _get_shared_httpx_client() -> httpx.AsyncClient:
    """Lazily construct (or rebuild if closed) the shared httpx client.

    Single connection pool shared across all native Anthropic calls in this
    process. Per-call ``AsyncAnthropic`` wrappers reuse this pool —
    eliminating ~150-300ms per-call TLS+H2 setup overhead. K8s secret
    rotation still works: ``api_key`` is read fresh per call; the pool
    carries no credential state.
    """
    global _CACHED_HTTPX_CLIENT
    if _CACHED_HTTPX_CLIENT is None or _CACHED_HTTPX_CLIENT.is_closed:
        _CACHED_HTTPX_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,  # connection establishment
                read=600.0,    # body read — LLM responses can be slow
                write=30.0,    # request body write
                pool=5.0,      # waiting for free connection from pool
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
        )
    return _CACHED_HTTPX_CLIENT


def _reset_shared_httpx_client() -> None:
    """For tests — reset the cached client. NOT for production use."""
    global _CACHED_HTTPX_CLIENT
    _CACHED_HTTPX_CLIENT = None


# ---------------------------------------------------------------------------
# litellm-shaped response objects
# ---------------------------------------------------------------------------
# These mirror _MockResponse / _MockMessage / _MockChoice / _MockUsage in
# ``_mcp_mesh.engine.mesh_llm_agent``. Kept independent here so this module
# does not import from mesh_llm_agent (avoids circular imports through the
# provider_handlers package).


class _Function:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    __slots__ = ("id", "type", "function")

    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = _Function(name=name, arguments=arguments)


class _Message:
    __slots__ = ("content", "role", "tool_calls")

    def __init__(
        self,
        content: str | None,
        role: str = "assistant",
        tool_calls: list[_ToolCall] | None = None,
    ):
        self.content = content
        self.role = role
        self.tool_calls = tool_calls or None


class _Choice:
    __slots__ = ("message", "finish_reason", "index")

    def __init__(self, message: _Message, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason
        self.index = 0


class _Usage:
    __slots__ = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens or 0
        self.completion_tokens = completion_tokens or 0
        self.total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)


class _Response:
    __slots__ = ("choices", "usage", "model")

    def __init__(
        self,
        message: _Message,
        usage: _Usage | None,
        model: str | None,
    ):
        self.choices = [_Choice(message)]
        self.usage = usage
        self.model = model


# ---------------------------------------------------------------------------
# litellm-shaped streaming chunk objects
# ---------------------------------------------------------------------------


class _Delta:
    __slots__ = ("content", "tool_calls", "role")

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[Any] | None = None,
        role: str | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls
        self.role = role


class _StreamChoice:
    __slots__ = ("delta", "index", "finish_reason")

    def __init__(
        self,
        delta: _Delta,
        index: int = 0,
        finish_reason: str | None = None,
    ):
        self.delta = delta
        self.index = index
        self.finish_reason = finish_reason


class _StreamChunk:
    __slots__ = ("choices", "usage", "model")

    def __init__(
        self,
        delta: _Delta,
        usage: _Usage | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
    ):
        self.choices = [_StreamChoice(delta, finish_reason=finish_reason)]
        self.usage = usage
        self.model = model


class _StreamToolCallDelta:
    """Tool-call fragment matching litellm's streamed tool_call shape.

    ``MeshLlmAgent._merge_streamed_tool_calls`` reads ``index``, ``id``,
    ``type``, and ``function.name`` / ``function.arguments`` off these
    deltas. Anthropic emits the full tool name + id once at start and
    accumulates JSON arguments in subsequent ``input_json_delta`` events;
    we surface those as separate fragment chunks at the same ``index``.
    """

    __slots__ = ("index", "id", "type", "function")

    def __init__(
        self,
        index: int,
        id: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
    ):
        self.index = index
        self.id = id
        self.type = "function" if id is not None else None
        self.function = _StreamFunctionDelta(name=name, arguments=arguments)


class _StreamFunctionDelta:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str | None = None, arguments: str | None = None):
        self.name = name
        self.arguments = arguments


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """True if the ``anthropic`` SDK is importable in this process."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def supports_model(model: str) -> bool:
    """True if ``model`` routes to the Anthropic SDK.

    Matches:
      * ``anthropic/<name>`` (Anthropic API direct)
      * ``bedrock/anthropic.claude-*`` (AWS Bedrock)
      * ``databricks/anthropic.claude-*`` (Databricks workspace)
    """
    if not model:
        return False
    if model.startswith(_ANTHROPIC_PREFIXES):
        return True
    if model.startswith(_BEDROCK_ANTHROPIC_PREFIX):
        return True
    if model.startswith(_DATABRICKS_ANTHROPIC_PREFIX):
        return True
    return False


def _strip_prefix(model: str) -> str:
    """Return the bare Anthropic model id for the SDK call.

    ``anthropic/claude-sonnet-4-5`` → ``claude-sonnet-4-5``
    ``bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`` →
        ``anthropic.claude-3-5-sonnet-20241022-v2:0`` (Bedrock keeps the
        ``anthropic.`` prefix as part of the model id)
    ``databricks/anthropic.claude-...`` → ``anthropic.claude-...``
    """
    if model.startswith(_ANTHROPIC_PREFIXES):
        return model.split("/", 1)[1]
    if model.startswith("bedrock/"):
        return model.split("/", 1)[1]
    if model.startswith("databricks/"):
        return model.split("/", 1)[1]
    return model


def _build_client(
    model: str,
    api_key: str | None,
    base_url: str | None,
):
    """Construct the appropriate async Anthropic client per model prefix.

    The ``AsyncAnthropic`` wrapper is built fresh on every call (no caching
    of the wrapper itself) so K8s secret rotation works: callers re-read
    the api_key from env each request. The wrapper, however, is given the
    process-wide shared ``httpx.AsyncClient`` so the underlying connection
    pool (and its already-established TLS sessions) is reused across calls.
    """
    import anthropic

    if model.startswith(_BEDROCK_ANTHROPIC_PREFIX):
        # AsyncAnthropicBedrock takes AWS credentials from the standard
        # boto3 chain (env, ~/.aws/credentials, IAM role). base_url is
        # ignored for Bedrock; we don't pass it.
        # TODO(#834): wire the shared httpx client for Bedrock too.
        # AsyncAnthropicBedrock does accept ``http_client=`` (verified
        # against anthropic SDK), but the auth path uses boto3/botocore
        # for SigV4 signing, which has its own connection pooling. Reusing
        # the same httpx client is feasible but needs a separate validation
        # pass to ensure SigV4 signing isn't broken by the swap.
        return anthropic.AsyncAnthropicBedrock()

    # Anthropic direct OR Databricks (same SDK class, different base_url).
    kwargs: dict[str, Any] = {"http_client": _get_shared_httpx_client()}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.AsyncAnthropic(**kwargs)


def _split_system_messages(
    messages: list[dict[str, Any]],
) -> tuple[Any | None, list[dict[str, Any]]]:
    """Split out system message(s) from a litellm-style messages list.

    Anthropic's ``messages.create`` takes ``system=`` as a separate top-level
    parameter; system messages must NOT appear in the ``messages`` array.
    Returns ``(system_value, non_system_messages)``. ``system_value`` is:
      * a plain string when there's exactly one system message with string
        content (the most common case),
      * a list of content blocks when multiple system messages exist or
        when a single system message already uses content-block form (e.g.
        ClaudeHandler's prompt-cache decoration),
      * None when no system message is present.
    """
    system_blocks: list[Any] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, list):
                system_blocks.extend(content)
            elif content is not None:
                system_blocks.append({"type": "text", "text": str(content)})
        else:
            rest.append(msg)

    if not system_blocks:
        return None, rest
    if (
        len(system_blocks) == 1
        and isinstance(system_blocks[0], dict)
        and system_blocks[0].get("type") == "text"
        and "cache_control" not in system_blocks[0]
    ):
        # Plain single string system → unwrap to a bare string for clarity.
        return system_blocks[0].get("text", ""), rest
    return system_blocks, rest


def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Translate OpenAI/litellm tool schema → Anthropic tool schema.

    OpenAI shape (what mesh / litellm uses):
        {"type": "function", "function": {"name": ..., "description": ...,
                                          "parameters": {...}}}

    Anthropic shape:
        {"name": ..., "description": ..., "input_schema": {...}}

    Tools already in Anthropic shape (``input_schema`` present at top level)
    pass through unchanged.
    """
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if "input_schema" in tool and "function" not in tool:
            converted.append(tool)
            continue
        fn = tool.get("function") or {}
        out: dict[str, Any] = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        }
        converted.append(out)
    return converted


def _translate_content_block_to_anthropic(block: Any) -> dict | list[dict]:
    """Translate one OpenAI-shape content block to Anthropic-native shape.

    Returns a single block dict, or a LIST of blocks if a single input block
    expands to multiple natives (rare; reserved for future input_audio etc).

    Supported translations (defensive fix for #834 multimedia regression):
      * ``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<data>"}}``
        → ``{"type": "image", "source": {"type": "base64", "media_type": <mime>, "data": <data>}}``
      * ``{"type": "image_url", "image_url": {"url": "https://..."}}``
        → ``{"type": "image", "source": {"type": "url", "url": <url>}}``
        (Anthropic supports url-source images.)

    Non-image-url blocks (text, image already in native shape, tool_use,
    tool_result, etc.) pass through unchanged. A non-dict input is returned
    unchanged.

    Upstream callers (``mesh/helpers.py``, ``mesh_llm_agent._resolve_media_inputs``)
    currently emit OpenAI-shape image blocks regardless of vendor. This adapter-
    side translator is the safety net so the native Anthropic dispatch path
    accepts those blocks until the upstream emitters are made vendor-aware.
    """
    if not isinstance(block, dict):
        return block

    btype = block.get("type")

    # Already in Anthropic-native image shape — passthrough (idempotent).
    if btype == "image":
        return block

    # Translate image_url → image
    if btype == "image_url":
        image_url_field = block.get("image_url", {})
        # OpenAI typically uses ``image_url: {"url": "..."}``; some clients
        # pass a bare string. Accept both.
        if isinstance(image_url_field, str):
            url = image_url_field
        elif isinstance(image_url_field, dict):
            url = image_url_field.get("url", "")
        else:
            url = ""

        if not url:
            logger.warning(
                "image_url block missing url; passing through (will likely error)"
            )
            return block

        # data: URI — extract mime + base64 payload.
        m = _DATA_URI_RE.match(url)
        if m:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": m.group("mime"),
                    "data": m.group("data"),
                },
            }

        # http(s) URL — Anthropic supports url-source for images.
        if url.startswith(("http://", "https://")):
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": url,
                },
            }

        # Unknown URL scheme — log + passthrough (will error at API level).
        logger.warning(
            "image_url block has unrecognized url scheme: %s; passing through",
            url[:50],
        )
        return block

    # Other content block types — passthrough.
    return block


def _translate_content_list_to_anthropic(content: Any) -> Any:
    """Apply ``_translate_content_block_to_anthropic`` to a content list.

    If ``content`` is a string or non-list, returns it unchanged.
    If ``content`` is a list, returns a NEW list with each block translated.
    A single-block translator may return a list (future-proofing for blocks
    that expand to multiple natives); those are flattened into the output.
    """
    if not isinstance(content, list):
        return content

    out: list = []
    for block in content:
        translated = _translate_content_block_to_anthropic(block)
        if isinstance(translated, list):
            out.extend(translated)
        else:
            out.append(translated)
    return out


def _convert_messages_to_anthropic(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate litellm-shape messages → Anthropic-shape messages.

    Key transforms:
      * ``role: tool`` (litellm) → ``role: user`` with a ``tool_result``
        content block (Anthropic).
      * Assistant turns with ``tool_calls`` → assistant message with
        ``tool_use`` content blocks (id/name/input parsed from the
        litellm tool_call dict).
      * String content stays as a string (Anthropic accepts string OR
        content blocks for user/assistant roles).
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")

        if role == "tool":
            # litellm: {"role": "tool", "tool_call_id": "...", "content": "..."}
            # Anthropic: user message containing a tool_result block. Note the
            # provider-side loop emits one role:tool message per tool call,
            # which Anthropic accepts as separate user turns; the SDK does
            # not require coalescing.
            #
            # Anthropic's tool_result.content accepts EITHER a string OR a
            # typed content list (text + image blocks). Strings stay as
            # strings; lists are translated block-by-block (image_url →
            # image) and forwarded as a typed list. We MUST NOT json.dumps a
            # content list — base64 image payloads serialized as text blow
            # the 200k input-token limit (the original #834 multimedia
            # regression).
            content = msg.get("content", "")
            tool_use_id = msg.get("tool_call_id", "")
            if isinstance(content, str):
                tool_result_content: Any = content
            elif isinstance(content, list):
                tool_result_content = _translate_content_list_to_anthropic(content)
            else:
                # Non-string, non-list (dict, etc.) — fall back to JSON
                # encoding so the call doesn't fail with a type error.
                # Image payloads should never reach this branch because
                # callers emit lists for multipart content.
                tool_result_content = json.dumps(content)

            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": tool_result_content,
            }
            out.append({"role": "user", "content": [block]})
            continue

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            elif isinstance(text, list):
                blocks.extend(_translate_content_list_to_anthropic(text))
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args_raw = fn.get("arguments", "{}")
                try:
                    parsed_input = (
                        json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    )
                except (json.JSONDecodeError, ValueError):
                    parsed_input = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": parsed_input,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
            continue

        # Default passthrough for user/assistant text. Content may be a
        # string OR a list of typed blocks (multimodal). Translate
        # image_url → image defensively so OpenAI-shape callers work.
        out.append(
            {
                "role": role,
                "content": _translate_content_list_to_anthropic(
                    msg.get("content", "")
                ),
            }
        )
    return out


# Anthropic's messages.create takes a fixed set of top-level kwargs; anything
# else (including litellm-specific knobs like response_format, parallel_tool_calls,
# stream_options, request_timeout, etc.) must NOT be forwarded.
_ANTHROPIC_PASSTHROUGH_KWARGS = frozenset(
    [
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "extra_headers",
        "extra_query",
        "extra_body",
        "timeout",
    ]
)

# Keys explicitly handled (translated, consumed, or routed) inside this adapter
# — the WARN filter must not flag these as "dropped". Everything in
# _ANTHROPIC_PASSTHROUGH_KWARGS is also handled, but listed below are the keys
# that are NOT forwarded as-is (they are translated to Anthropic semantics
# elsewhere or intentionally swallowed).
#
# ``response_format`` is intentionally NOT in this set anymore. On the native
# path, structured output is implemented upstream in
# ``ClaudeHandler._apply_native_synthetic_format`` via the synthetic-tool
# pattern (issue #834); the adapter just forwards tools + tool_choice
# unchanged. If response_format ever leaks here it will be WARN-logged so the
# regression is visible.
_ANTHROPIC_HANDLED_KWARGS = frozenset(
    [
        "messages",
        "model",
        "tools",
        "tool_choice",
        "stream",
    ]
)


def _build_create_kwargs(
    request_params: dict[str, Any],
    *,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    """Translate litellm-shape request_params → anthropic.messages.create kwargs.

    Tools (real and synthetic) are forwarded verbatim through ``_convert_tools``
    — this adapter no longer special-cases the synthetic format tool. The
    upstream ``ClaudeHandler`` injects it at handler time and the agentic loop
    in ``mesh.helpers`` recognizes the synthetic tool_call after the response
    arrives.
    """
    raw_messages = request_params.get("messages") or []
    system_value, non_system = _split_system_messages(raw_messages)
    converted_messages = _convert_messages_to_anthropic(non_system)
    converted_tools = _convert_tools(request_params.get("tools")) or []

    # Anthropic requires max_tokens; litellm/mesh callers may omit it. Pick
    # a generous default (Claude 3.5 Sonnet ceiling) so this isn't the
    # surprising-hard-fail layer.
    max_tokens = request_params.get("max_tokens", 8192)

    create_kwargs: dict[str, Any] = {
        "model": _strip_prefix(model),
        "messages": converted_messages,
        "max_tokens": max_tokens,
    }
    if system_value is not None:
        create_kwargs["system"] = system_value

    for key in _ANTHROPIC_PASSTHROUGH_KWARGS:
        if key == "max_tokens":
            continue  # handled above
        if key in request_params and request_params[key] is not None:
            create_kwargs[key] = request_params[key]

    # Tool choice: litellm uses {"type": "function", "function": {"name": "..."}}
    # or "auto" / "none"; Anthropic uses {"type": "auto" | "any" | "tool",
    # "name": "..."}. We translate both string and dict forms.
    tool_choice = request_params.get("tool_choice")
    if tool_choice == "auto":
        create_kwargs["tool_choice"] = {"type": "auto"}
    elif tool_choice == "any":
        create_kwargs["tool_choice"] = {"type": "any"}
    elif isinstance(tool_choice, dict):
        # OpenAI/litellm shape: {"type": "function", "function": {"name": "..."}}
        # → Anthropic shape: {"type": "tool", "name": "..."}
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function") or {}
            name = fn.get("name")
            if name:
                create_kwargs["tool_choice"] = {"type": "tool", "name": name}
        elif "type" in tool_choice:
            # Best-effort: already Anthropic-shaped, pass through.
            create_kwargs["tool_choice"] = tool_choice

    if converted_tools:
        create_kwargs["tools"] = converted_tools

    # WARN-log any kwargs the adapter is silently dropping. This catches the
    # next litellm-only knob we forget to translate (e.g. parallel_tool_calls,
    # stream_options, request_timeout) before it silently regresses behavior.
    # Internal mesh markers (``_mesh_*``) are not forwarded but should also
    # not warn — they're handled upstream in helpers._pop_mesh_*_flags.
    for k in request_params:
        if k.startswith("_mesh_"):
            continue
        if k in _ANTHROPIC_PASSTHROUGH_KWARGS:
            continue
        if k in _ANTHROPIC_HANDLED_KWARGS:
            continue
        logger.warning(
            "Native Anthropic adapter dropping unsupported kwarg: '%s' "
            "(LiteLLM-only — not forwarded to anthropic.messages.create)",
            k,
        )

    return create_kwargs


async def complete(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> _Response:
    """Run a buffered Anthropic completion and adapt to litellm-shape response.

    The synthetic-format-tool used to live here (and special-cased the
    response content), but that approach forced ``tool_choice`` to the
    synthetic which suppressed real user tool calls — broken for the
    "tools + structured output" combo (issue #834). Synthetic-tool
    injection now happens upstream in
    ``ClaudeHandler._apply_native_synthetic_format`` and the agentic loop
    in ``mesh.helpers`` recognizes the synthetic tool_call after this
    function returns. The adapter just forwards everything verbatim.
    """
    client = _build_client(model, api_key, base_url)
    create_kwargs = _build_create_kwargs(request_params, model=model, stream=False)

    api_response = await client.messages.create(**create_kwargs)

    # Walk content blocks, collecting text and tool_use blocks separately
    # (litellm contract: text → message.content (str), tool_use →
    # message.tool_calls). Synthetic and real tool_use blocks are emitted
    # uniformly — the loop disambiguates by name.
    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    for block in getattr(api_response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", "") or "")
        elif block_type == "tool_use":
            tc_id = getattr(block, "id", "") or ""
            tc_name = getattr(block, "name", "") or ""
            tc_input = getattr(block, "input", {}) or {}
            try:
                args_str = json.dumps(tc_input)
            except (TypeError, ValueError):
                args_str = "{}"
            tool_calls.append(_ToolCall(id=tc_id, name=tc_name, arguments=args_str))

    message = _Message(
        content="".join(text_parts) if text_parts else None,
        role="assistant",
        tool_calls=tool_calls or None,
    )

    usage_obj = getattr(api_response, "usage", None)
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
            completion_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
        )
    else:
        usage = None

    return _Response(
        message=message,
        usage=usage,
        model=getattr(api_response, "model", None) or _strip_prefix(model),
    )


async def complete_stream(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[Any]:
    """Stream an Anthropic completion as litellm-shape chunks.

    Anthropic's SDK exposes streaming via ``client.messages.stream(...)``
    which is an async context manager yielding typed events. We translate
    each event into the chunk shape consumed by ``mesh.helpers``:

      * ``content_block_start`` (text)        → no chunk yielded (start
        markers carry no delta text).
      * ``content_block_delta`` (text_delta)  → chunk with delta.content.
      * ``content_block_start`` (tool_use)    → chunk with delta.tool_calls
        carrying id+name (one fragment).
      * ``content_block_delta`` (input_json_delta) → chunk with
        delta.tool_calls carrying argument fragment at same index.
      * ``message_delta`` (with usage)        → chunk carrying usage.
      * ``message_start`` (with model id)     → chunk carrying model.
    """
    client = _build_client(model, api_key, base_url)
    create_kwargs = _build_create_kwargs(request_params, model=model, stream=True)

    # Track which content_block_index belongs to which tool_use so
    # subsequent input_json_delta fragments can be tagged with the
    # right index in the merged tool_call shape. Both real and synthetic
    # (``__mesh_format_response``) tool_use blocks flow through the same
    # path — the agentic loop in mesh.helpers disambiguates by name after
    # merging the streamed deltas.
    tool_use_indices: dict[int, int] = {}  # anthropic block index → tc index
    next_tc_index = 0

    async with client.messages.stream(**create_kwargs) as stream:
        async for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "message_start":
                msg_obj = getattr(event, "message", None)
                model_id = getattr(msg_obj, "model", None) if msg_obj else None
                if model_id:
                    yield _StreamChunk(delta=_Delta(), model=model_id)
                continue

            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                idx = getattr(event, "index", 0)
                block_type = getattr(block, "type", None) if block else None
                if block_type == "tool_use":
                    block_name = getattr(block, "name", "")
                    tc_index = next_tc_index
                    next_tc_index += 1
                    tool_use_indices[idx] = tc_index
                    tc_delta = _StreamToolCallDelta(
                        index=tc_index,
                        id=getattr(block, "id", ""),
                        name=block_name,
                    )
                    yield _StreamChunk(delta=_Delta(tool_calls=[tc_delta]))
                continue

            if event_type == "content_block_delta":
                delta_obj = getattr(event, "delta", None)
                idx = getattr(event, "index", 0)
                delta_type = getattr(delta_obj, "type", None) if delta_obj else None
                if delta_type == "text_delta":
                    text = getattr(delta_obj, "text", "") or ""
                    if text:
                        yield _StreamChunk(delta=_Delta(content=text))
                elif delta_type == "input_json_delta":
                    tc_index = tool_use_indices.get(idx)
                    if tc_index is None:
                        # Fragment for an unknown block — skip rather than
                        # raise; merger drops malformed entries anyway.
                        continue
                    json_fragment = getattr(delta_obj, "partial_json", "") or ""
                    tc_delta = _StreamToolCallDelta(
                        index=tc_index,
                        arguments=json_fragment,
                    )
                    yield _StreamChunk(delta=_Delta(tool_calls=[tc_delta]))
                continue

            if event_type == "message_delta":
                usage_obj = getattr(event, "usage", None)
                if usage_obj is not None:
                    # Anthropic emits cumulative output_tokens in message_delta;
                    # input_tokens lives on the original message_start. The
                    # SDK exposes the final tally on get_final_message().usage,
                    # but we yield what's available now and rely on a final
                    # MessageStopEvent (handled below) to publish the totals.
                    pass
                continue

            if event_type == "message_stop":
                # Pull the final aggregated message + usage so we can emit
                # one definitive usage chunk (matches litellm's "usage in
                # final chunk when stream_options.include_usage=True").
                final_msg = await stream.get_final_message()
                final_usage = getattr(final_msg, "usage", None)
                if final_usage is not None:
                    usage = _Usage(
                        prompt_tokens=getattr(final_usage, "input_tokens", 0) or 0,
                        completion_tokens=getattr(final_usage, "output_tokens", 0) or 0,
                    )
                    yield _StreamChunk(
                        delta=_Delta(),
                        usage=usage,
                        model=getattr(final_msg, "model", None),
                        finish_reason=getattr(final_msg, "stop_reason", None),
                    )
                continue


# ---------------------------------------------------------------------------
# Fallback-logging helpers
# ---------------------------------------------------------------------------

_logged_fallback_once = False


def log_fallback_once() -> None:
    """Emit the LiteLLM-fallback notice exactly once per process.

    Called from the dispatch sites in helpers.py / claude_handler.py when
    native dispatch was attempted (the default) but the ``anthropic`` SDK
    is not importable.
    """
    global _logged_fallback_once
    if _logged_fallback_once:
        return
    _logged_fallback_once = True
    logger.info(
        "Install `mcp-mesh[anthropic]` for native SDK with full feature "
        "support — falling back to LiteLLM"
    )
