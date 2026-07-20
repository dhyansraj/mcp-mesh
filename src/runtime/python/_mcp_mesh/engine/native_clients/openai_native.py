"""Native OpenAI SDK adapter for the @mesh.llm_provider invocation layer.

Adapts ``openai.AsyncOpenAI`` to the same _Response/_StreamChunk shape
contract that mesh's agentic loop in helpers.py expects (mirrors
litellm.completion()'s shape via mesh_llm_agent._MockResponse, and matches
the anthropic_native adapter introduced in PR 1 of issue #834).

Design notes:
  * Module-level functions, not a class — keeps the adapter functional and
    avoids state that could leak across requests.
  * Lazy import of ``openai`` inside every function so importing this
    module never fails when the SDK is absent.
  * Lazy ``AsyncOpenAI`` wrapper construction per-call (the wrapper itself
    is NOT cached) — required for K8s secret rotation: ``api_key`` is
    re-read every time we build a client. The underlying ``httpx``
    connection pool IS cached process-wide via ``_get_shared_httpx_client``
    so TLS handshakes and HTTP/2 sessions are reused across calls.
  * Backend selection by model prefix: ``openai/*`` → ``AsyncOpenAI`` (with
    optional custom base_url for OpenAI-compatible providers like Databricks).
    Future ``azure/*`` and explicit ``databricks/openai-*`` prefixes are
    out of scope for this PR.
  * Translation overhead is minimal vs. the Anthropic adapter — OpenAI's
    wire shape IS what mesh emits internally (litellm uses OpenAI shape
    too). Mostly passthrough.

Out of scope (PR 2 of issue #834):
  * AsyncAzureOpenAI backend (different ctor: azure_endpoint, api_version).
  * Reasoning-token breakdown for o1/o3 models (passthrough only here).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ._native_client_helpers import (
    is_openai_reasoning_model,
    make_fallback_logger,
    make_is_available,
    reset_unsupported_kwargs_dedupe,
    resolve_request_timeout,
    restricts_openai_sampling_params,
    translate_max_tokens_for_restricted,
    warn_unsupported_kwarg_once,
)

logger = logging.getLogger(__name__)

# Model prefixes that route through this adapter.
_OPENAI_PREFIX = "openai/"


# ---------------------------------------------------------------------------
# Per-event-loop httpx connection pool (issue #834 perf fix + #866 cross-loop fix)
# ---------------------------------------------------------------------------
# An ``httpx.AsyncClient`` is reused across all native OpenAI calls in this
# process — but the cache is keyed by the *running asyncio event loop* rather
# than process-globally. ``openai.AsyncOpenAI`` accepts ``http_client=`` and
# uses the supplied client (and its connection pool) instead of constructing
# a fresh one per call. This eliminates ~150-300ms per-call TLS+H2 setup
# overhead vs. LiteLLM (which does its own pool reuse).
#
# WHY PER-LOOP (preventive fix mirroring gemini_native — issue #866):
# ``httpx.AsyncClient`` (via httpcore) lazily constructs anyio synchronization
# primitives — ``Lock`` / ``Semaphore`` / ``Event`` for the connection pool
# — on first I/O. Those primitives bind to the *event loop that issues the
# first request* and CANNOT be reused from a different loop ("bound to a
# different event loop" RuntimeError).
#
# In mesh, ``shared/tool_executor.py`` runs an N-worker thread pool, each
# thread owning its own long-lived asyncio event loop. Tool calls are
# round-robin dispatched across workers. A single process-wide ``httpx``
# pool would bind to the first worker's loop and then break the moment a
# call lands on a different worker. OpenAI's current integration tests
# happen not to surface this on their current test mix, but the same
# mechanism trips reliably in Gemini's uc10_toolcalls suite — applying the
# fix uniformly so future test patterns can't trip the same regression.
#
# Per-loop caching keeps the connection-reuse win within a single loop
# (tool calls scheduled to the same worker share its pool) while
# guaranteeing each loop owns its own anyio primitives. ``id(loop)`` is the
# cache key.
#
# ASSUMPTION: mesh's worker loops live for the process lifetime — loop ids
# are stable per worker. If short-lived loops were ever introduced (e.g.,
# ad-hoc ``asyncio.run()`` outside a worker), id() reuse could surface a
# stale-but-not-closed cached client bound to the original (now-dead) loop.
# The current code does NOT detect this — ``is_closed`` only flips on
# explicit ``aclose()``, not on owning-loop closure. A weakref-keyed cache
# would handle this; deferred per #860.
#
# K8s secret rotation still works because the api_key is read fresh per call
# by callers and forwarded to the per-call ``AsyncOpenAI`` wrapper — the
# pool itself carries no credential state, only TCP/TLS connections.
_CACHED_HTTPX_CLIENT_BY_LOOP: dict[int, httpx.AsyncClient] = {}
# Guards lazy-init / rebuild of the per-loop httpx client cache. The pool
# instances themselves are safe for concurrent use within their owning loop;
# the lock only protects the check-then-create race at construction. Cheap
# (uncontended after first call per loop).
_CACHED_HTTPX_CLIENT_LOCK = threading.Lock()


def _build_httpx_client() -> httpx.AsyncClient:
    """Construct a fresh httpx.AsyncClient with the standard mesh tuning."""
    return httpx.AsyncClient(
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


def _get_shared_httpx_client() -> httpx.AsyncClient:
    """Return an httpx.AsyncClient bound to the current event loop.

    Cached per-loop (NOT process-globally) — see the module-level comment
    for the rationale. Falls back to constructing a fresh client when no
    loop is currently running (sync test paths); that client is NOT cached
    so it gets garbage-collected promptly.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — caller is in sync code (most likely test setup).
        # Return an uncached client; the caller is responsible for cleanup.
        return _build_httpx_client()

    loop_id = id(loop)
    # Fast path — no lock when the cached client for this loop is healthy.
    cached = _CACHED_HTTPX_CLIENT_BY_LOOP.get(loop_id)
    if cached is not None and not cached.is_closed:
        return cached
    with _CACHED_HTTPX_CLIENT_LOCK:
        cached = _CACHED_HTTPX_CLIENT_BY_LOOP.get(loop_id)
        if cached is None or cached.is_closed:
            cached = _build_httpx_client()
            _CACHED_HTTPX_CLIENT_BY_LOOP[loop_id] = cached
        return cached


def _reset_shared_httpx_client() -> None:
    """For tests — drop all cached per-loop clients. NOT for production use."""
    with _CACHED_HTTPX_CLIENT_LOCK:
        _CACHED_HTTPX_CLIENT_BY_LOOP.clear()


# ---------------------------------------------------------------------------
# litellm-shaped response objects
# ---------------------------------------------------------------------------
# These mirror _MockResponse / _MockMessage / _MockChoice / _MockUsage in
# ``_mcp_mesh.engine.mesh_llm_agent`` (and the corresponding shapes in
# ``anthropic_native``). Kept independent here so this module does not
# import from mesh_llm_agent (avoids circular imports through the
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
        finish_reason: str = "stop",
    ):
        self.choices = [_Choice(message, finish_reason=finish_reason)]
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


class _StreamFunctionDelta:
    __slots__ = ("name", "arguments")

    def __init__(self, name: str | None = None, arguments: str | None = None):
        self.name = name
        self.arguments = arguments


class _StreamToolCallDelta:
    """Tool-call fragment matching litellm's streamed tool_call shape.

    ``MeshLlmAgent._merge_streamed_tool_calls`` reads ``index``, ``id``,
    ``type``, and ``function.name`` / ``function.arguments`` off these
    deltas. OpenAI's wire shape already mirrors this; the adapter just
    extracts the fields and re-emits them through this slot-based wrapper
    so the merger sees identical attribute access on every backend.
    """

    __slots__ = ("index", "id", "type", "function")

    def __init__(
        self,
        index: int,
        id: str | None = None,
        type: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
    ):
        self.index = index
        self.id = id
        # OpenAI populates ``type`` only on the first chunk (along with id).
        # Subsequent argument fragments carry id=None and type=None — match
        # that pattern so the merger's "set if non-None" logic works
        # correctly.
        self.type = type if type is not None else ("function" if id is not None else None)
        self.function = _StreamFunctionDelta(name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# is_available() probes whether the ``openai`` SDK is importable, caching
# the result after the first probe (SDK presence is fixed for the process).
# Built from the shared factory so all three adapters share one
# implementation; the cache lives in the factory's closure.
is_available, _reset_is_available_cache = make_is_available("openai")


def supports_model(model: str) -> bool:
    """True if ``model`` routes to the OpenAI SDK.

    Matches:
      * ``openai/<name>`` (OpenAI direct, or OpenAI-compatible via base_url).

    Future prefixes (``azure/*``, explicit ``databricks/openai-*``) are
    deferred to a follow-up PR.
    """
    if not model:
        return False
    if model.startswith(_OPENAI_PREFIX):
        return True
    return False


def _strip_prefix(model: str) -> str:
    """Return the bare OpenAI model id for the SDK call.

    ``openai/gpt-4o`` → ``gpt-4o``
    ``openai/gpt-4o-mini`` → ``gpt-4o-mini``
    """
    if model.startswith(_OPENAI_PREFIX):
        return model[len(_OPENAI_PREFIX):]
    return model


def _build_client(
    model: str,
    api_key: str | None,
    base_url: str | None,
):
    """Construct the AsyncOpenAI client with the shared httpx pool.

    The ``AsyncOpenAI`` wrapper is built fresh on every call (no caching of
    the wrapper itself) so K8s secret rotation works: callers re-read the
    api_key from env each request. The wrapper, however, is given the
    process-wide shared ``httpx.AsyncClient`` so the underlying connection
    pool (and its already-established TLS sessions) is reused across calls.

    Validates credentials upfront — without this, a missing key surfaces as
    an opaque late 401 from openai.chat.completions.create which is harder
    to debug.
    """
    # Validate credentials upfront. ``model`` is unused by the validator
    # today but keeps the signature symmetric with anthropic_native and
    # leaves room for backend-specific routing (Azure, Databricks) later.
    if not api_key and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError(
            "Native OpenAI dispatch requires OPENAI_API_KEY env var or "
            "explicit api_key argument. Set OPENAI_API_KEY or pass api_key= "
            "to @mesh.llm_provider, or set MCP_MESH_NATIVE_LLM=0 to fall "
            "back to LiteLLM."
        )

    import openai

    kwargs: dict[str, Any] = {"http_client": _get_shared_httpx_client()}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return openai.AsyncOpenAI(**kwargs)


# OpenAI's chat.completions.create accepts a wide kwarg set; passthrough
# most things. Anything not in this set (and not in _OPENAI_HANDLED_KWARGS)
# triggers the once-per-key WARN so the next litellm-only knob we forget
# to translate is visible early.
# Note on ``tool_choice``: OpenAI natively supports tool_choice values
# "auto", "none", "required", and {"type": "function", "function": {"name":
# "..."}}. We pass through unchanged — no translation needed (unlike
# Anthropic, which lacks a native "none" semantics and requires us to
# translate "auto"/"any"/"none" + the {"type": "function", ...} dict shape;
# see anthropic_native._build_create_kwargs for that mapping).
_OPENAI_PASSTHROUGH_KWARGS = frozenset({
    "messages",
    "tools",
    "tool_choice",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "n",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "user",
    "seed",
    "response_format",
    "logprobs",
    "top_logprobs",
    "parallel_tool_calls",
    "extra_headers",
    "extra_query",
    "extra_body",
    "timeout",
    # o1/o3 reasoning models:
    "reasoning_effort",
    # Streaming options (the adapter sets include_usage itself but a
    # caller-provided stream_options is also forwarded after merge):
    "stream_options",
})

# Keys explicitly handled (consumed or routed) inside this adapter — the
# WARN filter must not flag these as "dropped".
_OPENAI_HANDLED_KWARGS = frozenset({
    "model",
    "api_key",
    "base_url",
    "stream",
})


def _build_create_kwargs(
    request_params: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Translate mesh/litellm-shape request_params → openai SDK kwargs.

    For OpenAI this is mostly passthrough — the wire shape is identical
    (litellm uses OpenAI shape internally). The adapter:
      * Strips the ``openai/`` model prefix.
      * Forwards every kwarg in :data:`_OPENAI_PASSTHROUGH_KWARGS` whose
        value is not None.
      * WARN-once on any kwarg that is neither in the passthrough set nor
        explicitly handled (mirrors anthropic_native — catches the next
        litellm-only knob we forget).

    OpenAI does NOT require ``max_tokens`` (unlike Anthropic), so an
    explicit ``max_tokens=None`` simply omits the kwarg. ``max_completion_tokens``
    is the newer field for o1/o3 reasoning models — both are accepted by
    the OpenAI SDK; the adapter forwards whichever the caller supplied.
    """
    # Shallow-copy so we don't mutate the caller's dict (we ``pop`` below).
    request_params = dict(request_params)

    # --- request_timeout → timeout rename -----------------------------------
    # Shared helper resolves caller's ``timeout`` / ``request_timeout`` into
    # a single value the OpenAI SDK accepts under ``timeout=`` (seconds, no
    # unit conversion).
    resolved_timeout = resolve_request_timeout(
        request_params,
        adapter_label="Native OpenAI adapter",
        logger=logger,
    )
    if resolved_timeout is not None:
        request_params["timeout"] = resolved_timeout

    create_kwargs: dict[str, Any] = {"model": _strip_prefix(model)}

    # gpt-5 (non-chat) and o-series reasoning models reject any explicit
    # ``temperature``/``top_p`` (HTTP 400) — only the default is accepted.
    # Omit those two params for the restricted models (everything else,
    # including ``max_completion_tokens``, is forwarded normally). Soft-fail
    # with a WARN per omitted param rather than letting the request 400.
    restricted = restricts_openai_sampling_params(model)

    for key in _OPENAI_PASSTHROUGH_KWARGS:
        value = request_params.get(key)
        # Drop None values — OpenAI rejects ``max_tokens=None`` etc., and
        # leaving them out matches the "unset → SDK default" semantics that
        # callers expect. (``request_params.get`` already returns None for
        # missing keys, so the absence check collapses into the value check.)
        if value is None:
            continue
        if restricted and key in ("temperature", "top_p"):
            logger.warning(
                "OpenAI model %s rejects %s; omitting %s=%s "
                "(only the default is supported)",
                model,
                key,
                key,
                value,
            )
            continue
        create_kwargs[key] = value

    # Restricted models reject the raw ``max_tokens`` (HTTP 400) — they require
    # ``max_completion_tokens``. Translate any forwarded ``max_tokens`` into
    # ``max_completion_tokens`` (unless one is already present, which wins) and
    # never emit ``max_tokens`` on the wire. Shared with the LiteLLM path so
    # the two cannot drift.
    translate_max_tokens_for_restricted(create_kwargs, model, logger)

    # WARN once when ``n>1`` is observed. OpenAI's SDK accepts ``n=k>1`` and
    # returns k candidates in ``choices[0..k-1]``, but ``_adapt_response``
    # only reads ``choices[0]`` — caller is billed for k completions and
    # silently gets just one back. WARN flags the narrowing rather than
    # hard-rejecting (callers may pass ``n>1`` intentionally as a server-
    # side optimization the adapter can't see).
    n_value = create_kwargs.get("n")
    if isinstance(n_value, int) and n_value > 1:
        _warn_unsupported_kwarg_once("n_greater_than_1")

    # WARN-log any kwargs the adapter is silently dropping. This catches the
    # next litellm-only knob we forget to allow-list. Internal mesh markers
    # (``_mesh_*``) are not forwarded but should also not warn — they're
    # handled upstream in helpers._pop_mesh_*_flags. Dedupe per-key so
    # high-volume providers receiving the same litellm-only kwarg every
    # request don't flood the log.
    for k in request_params:
        if k.startswith("_mesh_"):
            continue
        if k in _OPENAI_PASSTHROUGH_KWARGS:
            continue
        if k in _OPENAI_HANDLED_KWARGS:
            continue
        _warn_unsupported_kwarg_once(k)

    return create_kwargs


# ---------------------------------------------------------------------------
# Responses API path (issue #1334)
# ---------------------------------------------------------------------------
# OpenAI gpt-5-family / o-series REASONING models reason by default. On
# ``/v1/chat/completions`` OpenAI returns HTTP 400 when such a model is asked
# to reason AND is given function tools ("use /v1/responses or set
# reasoning_effort='none'"). Routing those requests to the Responses API lets
# reasoning + tools coexist. gpt-4o and gpt-5 *chat* variants — which do not
# restrict sampling params — stay on chat.completions; no-tools reasoning
# calls also stay on chat.completions (no 400 there). ``tools`` is constant
# across an agentic loop so the endpoint never flips mid-conversation.


def _openai_wants_responses_api(model: str, request_params: dict[str, Any]) -> bool:
    """True when this request must route to the OpenAI Responses API.

    Trigger: a reasoning model (o-series / gpt-5 non-chat) *and* the request
    carries function tools. See the section comment for the rationale.

    Exception: ``reasoning_effort="none"`` is OpenAI's documented way to keep a
    reasoning model on ``/v1/chat/completions`` with tools (no reasoning, no
    400). Those requests stay on chat.completions — routing them to Responses
    would emit ``reasoning={"effort": "none"}``, which Responses rejects.
    """
    if request_params.get("reasoning_effort") == "none":
        return False
    return is_openai_reasoning_model(model) and bool(request_params.get("tools"))


# Chat-completions kwargs the Responses builder consumes/translates itself —
# the leftover-kwarg WARN must not flag these as "dropped".
_OPENAI_RESPONSES_HANDLED_KWARGS = frozenset({
    "messages",
    "tools",
    "tool_choice",
    "reasoning_effort",
    "response_format",
    "max_completion_tokens",
    "max_tokens",
    "temperature",
    "top_p",
    "model",
    "api_key",
    "base_url",
    "stream",
    "stream_options",
})

# Kwargs forwarded verbatim to responses.create (shapes are identical on both
# endpoints).
_OPENAI_RESPONSES_PASSTHROUGH_KWARGS = frozenset({
    "parallel_tool_calls",
    "user",
    "metadata",
    "extra_headers",
    "extra_query",
    "extra_body",
})


def _stringify_tool_output(content: Any) -> str:
    """Coerce a chat ``role:tool`` message ``content`` into the Responses
    ``function_call_output.output`` string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


def _translate_response_format_to_text(response_format: Any) -> dict[str, Any]:
    """chat ``response_format`` → Responses ``text`` block.

    ``{type:json_schema, json_schema:{name,schema,strict}}`` becomes
    ``{format:{type:json_schema, name, schema, strict}}`` (flattened). Other
    shapes (``{type:json_object}``, ``{type:text}``) pass through under
    ``format`` unchanged.
    """
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        js = response_format.get("json_schema") or {}
        fmt: dict[str, Any] = {"type": "json_schema"}
        if js.get("name") is not None:
            fmt["name"] = js.get("name")
        if js.get("schema") is not None:
            fmt["schema"] = js.get("schema")
        if "strict" in js:
            fmt["strict"] = js.get("strict")
        return {"format": fmt}
    return {"format": response_format}


def _translate_message_content(content: Any, role: str) -> Any:
    """Translate chat-style message ``content`` into the Responses input shape.

    Plain-string content passes through unchanged (the common case). A
    content-part ARRAY is translated part-by-part: text parts
    ``{"type":"text","text":...}`` become ``input_text`` (user/system) or
    ``output_text`` (assistant), matching the part types Responses expects.

    Any image or other non-text part raises a clear ``ValueError`` rather than
    forwarding an untranslated chat-shape part that would yield a cryptic
    OpenAI 400. Image translation is deliberately NOT attempted here (the
    Responses image-part shape differs and is unverified for this path).
    """
    if not isinstance(content, list):
        return content
    text_type = "output_text" if role == "assistant" else "input_text"
    translated: list[dict[str, Any]] = []
    for part in content:
        ptype = part.get("type") if isinstance(part, dict) else None
        if ptype == "text":
            translated.append({"type": text_type, "text": part.get("text")})
        else:
            raise ValueError(
                "OpenAI Responses path (reasoning model + tools) does not yet "
                "support multimodal image content; use string/text content, "
                "drop tools, or use a non-reasoning model "
                f"(unsupported content part type={ptype!r})"
            )
    return translated


def _build_responses_kwargs(
    request_params: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Translate mesh/chat.completions-shape request_params → Responses kwargs.

    Parallel to :func:`_build_create_kwargs` but targets ``responses.create``:

      * ``messages`` → ``input`` items (+ ``instructions`` from system turns).
        The multi-turn history remap is the critical part — prior assistant
        ``tool_calls`` become ``function_call`` items and ``role:tool`` results
        become ``function_call_output`` items, preserving ``call_id`` exactly
        so calls and outputs pair correctly on iteration 2+.
      * flat tool schema / tool_choice.
      * ``reasoning_effort`` → ``reasoning={"effort": ...}``.
      * ``response_format`` → ``text={"format": ...}``.
      * ``max_completion_tokens`` / ``max_tokens`` → ``max_output_tokens``.

    ``store`` is explicitly set to ``False`` to match the chat path's
    no-persistence behavior — ``responses.create`` defaults ``store=true``
    (persisting prompt + output on OpenAI's servers for 30 days) whereas
    ``chat.completions.create`` defaults ``false``. ``temperature`` / ``top_p``
    are omitted (reasoning models reject them) with a soft-fail WARN, mirroring
    the chat path.
    """
    # Shallow-copy so we don't mutate the caller's dict (we ``pop`` below).
    request_params = dict(request_params)

    resolved_timeout = resolve_request_timeout(
        request_params,
        adapter_label="Native OpenAI adapter (Responses)",
        logger=logger,
    )

    responses_kwargs: dict[str, Any] = {"model": _strip_prefix(model)}
    # ``responses.create`` defaults ``store=true`` (persists prompt + output on
    # OpenAI servers for 30 days); ``chat.completions.create`` defaults false.
    # Set it explicitly so the Responses path matches the chat path's
    # no-persistence behavior.
    responses_kwargs["store"] = False
    if resolved_timeout is not None:
        responses_kwargs["timeout"] = resolved_timeout

    # --- messages → input items (+ instructions) ----------------------------
    input_items: list[dict[str, Any]] = []
    instructions_parts: list[str] = []
    for msg in request_params.get("messages") or []:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            # Collect string system prompts into ``instructions``; non-string
            # (multimodal) system content falls back to an input item.
            if isinstance(content, str):
                instructions_parts.append(content)
            else:
                input_items.append({
                    "role": "system",
                    "content": _translate_message_content(content, "system"),
                })
            continue
        if role == "assistant":
            # A text turn and tool calls can co-occur — emit both.
            if content:
                input_items.append({
                    "role": "assistant",
                    "content": _translate_message_content(content, "assistant"),
                })
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                input_items.append({
                    "type": "function_call",
                    # chat ``tool_call.id`` → Responses ``call_id`` (exact).
                    "call_id": tc.get("id"),
                    "name": fn.get("name"),
                    # Responses expects a string; coerce an explicit None → "".
                    "arguments": fn.get("arguments") or "",
                })
            continue
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                # chat ``tool_call_id`` → Responses ``call_id`` (exact).
                "call_id": msg.get("tool_call_id"),
                "output": _stringify_tool_output(content),
            })
            continue
        # user / any other role → passthrough input item.
        input_items.append(
            {"role": role, "content": _translate_message_content(content, role)}
        )

    responses_kwargs["input"] = input_items
    if instructions_parts:
        responses_kwargs["instructions"] = "\n\n".join(instructions_parts)

    # --- tools: nested {type:function, function:{...}} → flat ---------------
    tools = request_params.get("tools")
    if tools:
        flat_tools: list[dict[str, Any]] = []
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
                fn = t["function"] or {}
                flat_tools.append({
                    "type": "function",
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "parameters": fn.get("parameters"),
                })
            else:
                flat_tools.append(t)
        responses_kwargs["tools"] = flat_tools

    # --- tool_choice: flatten the {type:function, function:{name}} dict ------
    tool_choice = request_params.get("tool_choice")
    if tool_choice is not None:
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            fn = tool_choice.get("function") or {}
            responses_kwargs["tool_choice"] = {
                "type": "function",
                "name": fn.get("name"),
            }
        else:
            # "auto" / "none" / "required" pass through unchanged.
            responses_kwargs["tool_choice"] = tool_choice

    # --- reasoning_effort → reasoning={"effort": ...} ----------------------
    reasoning_effort = request_params.get("reasoning_effort")
    if reasoning_effort is not None:
        responses_kwargs["reasoning"] = {"effort": reasoning_effort}

    # --- response_format → text={"format": ...} ----------------------------
    response_format = request_params.get("response_format")
    if response_format is not None:
        responses_kwargs["text"] = _translate_response_format_to_text(response_format)

    # --- max_completion_tokens / max_tokens → max_output_tokens ------------
    max_output = request_params.get("max_completion_tokens")
    if max_output is None:
        max_output = request_params.get("max_tokens")
    if max_output is not None:
        responses_kwargs["max_output_tokens"] = max_output

    # --- sampling-param gating (reasoning models reject temperature/top_p) --
    for key in ("temperature", "top_p"):
        if request_params.get(key) is not None:
            logger.warning(
                "OpenAI model %s rejects %s; omitting %s=%s "
                "(only the default is supported)",
                model,
                key,
                key,
                request_params.get(key),
            )

    # --- verbatim passthrough kwargs ---------------------------------------
    for key in _OPENAI_RESPONSES_PASSTHROUGH_KWARGS:
        value = request_params.get(key)
        if value is not None:
            responses_kwargs[key] = value

    # --- WARN on leftover unhandled kwargs (mirrors the chat path) ----------
    # ``timeout`` / ``request_timeout`` were already popped by
    # resolve_request_timeout, so they won't surface here.
    for k in request_params:
        if k.startswith("_mesh_"):
            continue
        if k in _OPENAI_RESPONSES_HANDLED_KWARGS:
            continue
        if k in _OPENAI_RESPONSES_PASSTHROUGH_KWARGS:
            continue
        _warn_unsupported_kwarg_once(k, sdk_call_label="openai.responses.create")

    return responses_kwargs


def _rget(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-key getter so adapters accept both SDK Pydantic objects
    and plain dicts (keeps the Responses adapter test-friendly)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _adapt_responses_response(raw: Any) -> _Response:
    """Translate an openai Responses ``Response`` → litellm-shape ``_Response``.

    Maps ``raw.output[]`` items:
      * ``type=="function_call"`` → :class:`_ToolCall` (``call_id`` → ``id``).
      * ``type=="message"`` ``output_text`` parts → joined ``_Message.content``.
        Structured output has no ``message.parsed`` analog on Responses — it
        arrives as ``output_text`` JSON and is recovered here as the content
        string.
      * ``type=="reasoning"`` items are ignored for content.
    Refusals surface as a ``refusal`` content part (or ``status``) and are
    raised as the same :class:`LLMRefusedError` the chat path raises.
    ``raw.usage.input_tokens``/``output_tokens`` → :class:`_Usage`.
    """
    output = _rget(raw, "output", None) or []

    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    refusal_text: str | None = None

    for item in output:
        itype = _rget(item, "type", None)
        if itype == "function_call":
            call_id = _rget(item, "call_id", None) or _rget(item, "id", "") or ""
            name = _rget(item, "name", "") or ""
            arguments = _rget(item, "arguments", "")
            if not isinstance(arguments, str):
                try:
                    arguments = json.dumps(arguments)
                except (TypeError, ValueError):
                    arguments = "{}"
            tool_calls.append(
                _ToolCall(id=call_id, name=name, arguments=arguments or "")
            )
        elif itype == "message":
            for part in _rget(item, "content", None) or []:
                ptype = _rget(part, "type", None)
                if ptype == "refusal":
                    refusal_text = _rget(part, "refusal", None) or refusal_text
                elif ptype == "output_text":
                    text_parts.append(_rget(part, "text", "") or "")
        # ``reasoning`` (and any other) items contribute no content.

    # Preserve the chat path's refusal behavior: surface a typed exception so
    # the model's articulated reason reaches the @mesh.llm consumer rather than
    # collapsing into an opaque empty-response / Pydantic validation error.
    if refusal_text:
        from _mcp_mesh.engine.llm_errors import LLMRefusedError

        model_name = _rget(raw, "model", None)
        logger.info(
            "Native OpenAI adapter (Responses): model refused structured "
            "output (model=%s, refusal=%r)",
            model_name,
            refusal_text,
        )
        raise LLMRefusedError(
            refusal_text,
            vendor="openai",
            model=model_name,
        )

    content: str | None = "".join(text_parts) if text_parts else None

    message = _Message(
        content=content,
        role="assistant",
        tool_calls=tool_calls or None,
    )

    usage_obj = _rget(raw, "usage", None)
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=_rget(usage_obj, "input_tokens", 0) or 0,
            completion_tokens=_rget(usage_obj, "output_tokens", 0) or 0,
        )
    else:
        usage = None

    # Preserve a truthful finish_reason (the chat path forwards the real one).
    # Responses carries the signal on ``status`` / ``incomplete_details`` rather
    # than a ``finish_reason`` field: map truncation / content-filter /
    # incomplete outcomes instead of collapsing everything into stop/tool_calls.
    finish_reason = "tool_calls" if tool_calls else "stop"
    status = _rget(raw, "status", None)
    incomplete = _rget(raw, "incomplete_details", None)
    if status == "incomplete":
        reason = _rget(incomplete, "reason", None) if incomplete is not None else None
        if reason == "max_output_tokens":
            finish_reason = "length"
        elif reason == "content_filter":
            finish_reason = "content_filter"
        else:
            # An incomplete response with an unmapped (or empty) reason must not
            # look like a clean stop — surface it for debugging.
            logger.debug(
                "Native OpenAI adapter (Responses): incomplete response with "
                "unmapped reason (status=%r, incomplete_details=%r); keeping "
                "finish_reason=%r",
                status,
                incomplete,
                finish_reason,
            )
    elif status not in (None, "completed"):
        # "failed" / any other terminal status — keep stop/tool_calls but log so
        # an empty-output failure isn't a silent clean stop.
        logger.debug(
            "Native OpenAI adapter (Responses): non-completed status "
            "(status=%r, incomplete_details=%r); keeping finish_reason=%r",
            status,
            incomplete,
            finish_reason,
        )

    return _Response(
        message=message,
        usage=usage,
        model=_rget(raw, "model", None),
        finish_reason=finish_reason,
    )


def _responses_result_to_stream_chunk(resp: _Response) -> _StreamChunk:
    """Collapse a buffered Responses ``_Response`` into a single terminal
    ``_StreamChunk`` carrying content + tool-call deltas + usage + finish_reason.

    Used by the buffered-fallback streaming path (see ``complete_stream``). The
    provider-side consumer buffers all chunks and merges content / tool_calls /
    usage across them, so one all-in-one chunk reassembles correctly.
    """
    choice = resp.choices[0]
    msg = choice.message
    tool_call_deltas: list[_StreamToolCallDelta] | None = None
    if msg.tool_calls:
        tool_call_deltas = [
            _StreamToolCallDelta(
                index=i,
                id=tc.id,
                type="function",
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for i, tc in enumerate(msg.tool_calls)
        ]
    return _StreamChunk(
        delta=_Delta(content=msg.content, tool_calls=tool_call_deltas),
        usage=resp.usage,
        model=resp.model,
        finish_reason=choice.finish_reason,
    )


# ---------------------------------------------------------------------------
# Response / chunk adaptation
# ---------------------------------------------------------------------------


def _parsed_to_json_str(parsed: Any) -> str | None:
    """Serialize an OpenAI Structured-Outputs ``message.parsed`` payload to a
    JSON string.

    ``parsed`` may be a Pydantic model (``model_dump_json``), a plain dict, or
    already a string. Returns ``None`` when there is nothing to recover or the
    payload can't be serialized.
    """
    if parsed is None:
        return None
    if isinstance(parsed, str):
        return parsed
    dump = getattr(parsed, "model_dump_json", None)
    if callable(dump):
        try:
            return dump()
        except Exception:  # noqa: BLE001 - defensive; fall through to json
            pass
    try:
        # ``default=str`` coerces stray non-serializable leaves (datetimes,
        # nested Pydantic models, etc.) so a plain-dict payload still recovers
        # instead of collapsing to ``None``.
        return json.dumps(parsed, default=str)
    except (TypeError, ValueError):
        return None


def _adapt_response(raw: Any) -> _Response:
    """Translate openai.ChatCompletion → litellm-shape ``_Response``.

    The OpenAI SDK already returns Pydantic models that closely match the
    mesh-internal shape, but downstream callers in ``helpers.py`` and
    ``mesh_llm_agent`` rely on attribute access patterns that include
    fields the OpenAI SDK doesn't always populate (e.g. ``message.role``
    on tool-only responses). We unpack into our own slot-based shapes so
    the contract is enforced uniformly across vendor backends.
    """
    choices = getattr(raw, "choices", None) or []
    first_choice = choices[0] if choices else None

    # OpenAI's Structured Outputs spec (late 2024) returns refusals via
    # ``message.refusal`` (non-null) with ``content=None`` / ``tool_calls=None``.
    # The refusal text is the model's articulated reason in natural prose,
    # structurally distinct from ``content``. Surface as a typed exception so
    # the reason reaches the @mesh.llm consumer rather than collapsing into a
    # generic empty-response shape (which then trips Pydantic with an opaque
    # validation error — the refusal-text-leak class). Imported lazily to avoid a hard
    # dependency from this module on the engine errors package (helpers.py
    # imports adapter modules, so the engine→adapter direction is circular-
    # prone).
    if first_choice is not None:
        msg = getattr(first_choice, "message", None)
        if msg is not None:
            refusal = getattr(msg, "refusal", None)
            if refusal:
                from _mcp_mesh.engine.llm_errors import LLMRefusedError

                model_name = getattr(raw, "model", None)
                logger.info(
                    "Native OpenAI adapter: model refused structured output "
                    "(model=%s, refusal=%r)",
                    model_name,
                    refusal,
                )
                raise LLMRefusedError(
                    refusal,
                    vendor="openai",
                    model=model_name,
                )

    text: str | None = None
    tool_calls: list[_ToolCall] = []
    finish_reason: str = "stop"

    if first_choice is not None:
        msg = getattr(first_choice, "message", None)
        if msg is not None:
            text = getattr(msg, "content", None)
            raw_tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in raw_tool_calls:
                tc_id = getattr(tc, "id", "") or ""
                fn = getattr(tc, "function", None)
                tc_name = getattr(fn, "name", "") if fn is not None else ""
                tc_args = getattr(fn, "arguments", "") if fn is not None else ""
                # OpenAI returns arguments already as a JSON string.
                if not isinstance(tc_args, str):
                    try:
                        tc_args = json.dumps(tc_args)
                    except (TypeError, ValueError):
                        tc_args = "{}"
                tool_calls.append(
                    _ToolCall(id=tc_id, name=tc_name or "", arguments=tc_args or "")
                )

            # Structured output can arrive in a non-text carrier: OpenAI's
            # Structured Outputs (``.parse``) surfaces the answer on
            # ``message.parsed`` with ``content=None`` and no tool_calls. A
            # non-refusal ``content=None`` collapses to ``""`` downstream and
            # degrades into an opaque "failed to parse" error, so recover it as
            # a string here (refusals were already raised above). Gated on the
            # absence of tool_calls: on an ordinary tool-call turn ``content``
            # is legitimately ``None`` and MUST stay ``None`` so it isn't
            # replayed as a synthetic text block on the next iteration.
            if text is None and not tool_calls:
                text = _parsed_to_json_str(getattr(msg, "parsed", None))
        finish_reason = getattr(first_choice, "finish_reason", None) or "stop"

    message = _Message(
        content=text,
        role="assistant",
        tool_calls=tool_calls or None,
    )

    usage_obj = getattr(raw, "usage", None)
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )
    else:
        usage = None

    return _Response(
        message=message,
        usage=usage,
        model=getattr(raw, "model", None),
        finish_reason=finish_reason,
    )


def _adapt_chunk(raw: Any) -> _StreamChunk:
    """Translate openai.ChatCompletionChunk → litellm-shape ``_StreamChunk``.

    OpenAI streams emit:
      * Per content delta: ``raw.choices[0].delta.content`` populated with
        the new text fragment.
      * Per tool-call delta: ``raw.choices[0].delta.tool_calls`` populated
        with one ``ChoiceDeltaToolCall`` per call (id+type+function.name on
        the first chunk, function.arguments on subsequent chunks).
      * Final chunk (only when ``stream_options.include_usage=True``):
        ``raw.usage`` populated with the cumulative token counts and
        ``raw.choices`` empty.
    """
    choices = getattr(raw, "choices", None) or []
    first_choice = choices[0] if choices else None

    content: str | None = None
    tool_call_deltas: list[_StreamToolCallDelta] | None = None
    finish_reason: str | None = None

    if first_choice is not None:
        delta = getattr(first_choice, "delta", None)
        if delta is not None:
            content = getattr(delta, "content", None)
            raw_tcs = getattr(delta, "tool_calls", None) or []
            if raw_tcs:
                tool_call_deltas = []
                for tc in raw_tcs:
                    fn = getattr(tc, "function", None)
                    tool_call_deltas.append(
                        _StreamToolCallDelta(
                            index=getattr(tc, "index", 0) or 0,
                            id=getattr(tc, "id", None),
                            type=getattr(tc, "type", None),
                            name=getattr(fn, "name", None) if fn is not None else None,
                            arguments=(
                                getattr(fn, "arguments", None) if fn is not None else None
                            ),
                        )
                    )
        finish_reason = getattr(first_choice, "finish_reason", None)

    usage_obj = getattr(raw, "usage", None)
    usage: _Usage | None = None
    if usage_obj is not None:
        usage = _Usage(
            prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

    return _StreamChunk(
        delta=_Delta(content=content, tool_calls=tool_call_deltas),
        usage=usage,
        model=getattr(raw, "model", None),
        finish_reason=finish_reason,
    )


async def complete(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> _Response:
    """Run a buffered OpenAI completion and adapt to litellm-shape response.

    Reasoning models (o-series / gpt-5 non-chat) WITH tools route to the
    Responses API (issue #1334) so reasoning + function tools coexist; every
    other model — and no-tools reasoning calls — stay on chat.completions.
    """
    client = _build_client(model, api_key, base_url)
    if _openai_wants_responses_api(model, request_params):
        responses_kwargs = _build_responses_kwargs(request_params, model=model)
        raw = await client.responses.create(**responses_kwargs)
        return _adapt_responses_response(raw)
    create_kwargs = _build_create_kwargs(request_params, model=model)
    raw = await client.chat.completions.create(**create_kwargs)
    return _adapt_response(raw)


async def complete_stream(
    request_params: dict[str, Any],
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[Any]:
    """Stream an OpenAI completion as litellm-shape chunks.

    OpenAI's SDK exposes streaming via ``await client.chat.completions.create(
    stream=True)`` which returns an ``AsyncStream[ChatCompletionChunk]``.
    The adapter forces ``stream_options.include_usage=True`` so the final
    chunk carries the authoritative usage tally (matches LiteLLM's
    behavior when callers set ``stream_options.include_usage=True``).

    Best-effort usage emission: if the stream is interrupted before the
    final usage chunk arrives (server cutoff, consumer aclose, network
    drop), the ``finally`` block emits a fallback usage chunk built from
    the last counters we observed so telemetry doesn't silently record
    0 tokens for partial generations.
    """
    client = _build_client(model, api_key, base_url)

    # Reasoning models WITH tools must use the Responses API (issue #1334).
    # TODO(#1334): native Responses streaming. mesh does not yet stream the
    # Responses API natively; run the call buffered and emit the terminal
    # result as a single chunk. The provider-side consumer buffers all chunks
    # and merges content / tool_calls / usage across them, so a single
    # all-in-one chunk reassembles correctly (no interrupted-stream fallback
    # is needed here — a buffered call has no partial-usage hole).
    if _openai_wants_responses_api(model, request_params):
        logger.info(
            "Native OpenAI Responses path: buffering reasoning+tools stream "
            "(native Responses streaming not yet implemented — #1334)"
        )
        responses_kwargs = _build_responses_kwargs(request_params, model=model)
        raw = await client.responses.create(**responses_kwargs)
        yield _responses_result_to_stream_chunk(_adapt_responses_response(raw))
        return

    create_kwargs = _build_create_kwargs(request_params, model=model)
    create_kwargs["stream"] = True

    # Force include_usage so the final chunk carries usage. Merge with any
    # caller-supplied stream_options (don't clobber other knobs like
    # ``include_usage`` set explicitly by helpers.py).
    existing_opts = create_kwargs.get("stream_options") or {}
    create_kwargs["stream_options"] = {**existing_opts, "include_usage": True}

    # Track usage for finally-block fallback (telemetry integrity if stream
    # is interrupted — same pattern as anthropic_native).
    last_input_tokens = 0
    last_output_tokens = 0
    last_model: str | None = _strip_prefix(model)
    # Tracks whether the authoritative final-usage chunk has been
    # successfully yielded to the consumer. Set to True ONLY after the
    # yield returns — so any failure mode (stream raises, consumer cancels
    # mid-yield) leaves it False and the ``finally`` block emits the
    # best-effort fallback. Setting it BEFORE the yield would create a
    # telemetry hole: usage was observed but the chunk never reached the
    # consumer, yet the fallback would be skipped.
    final_usage_emitted = False

    try:
        # OpenAI returns an AsyncStream of ChatCompletionChunk. ``create``
        # is itself an awaitable that returns the stream object, hence the
        # ``await`` before ``async for``.
        stream = await client.chat.completions.create(**create_kwargs)
        async for raw_chunk in stream:
            chunk = _adapt_chunk(raw_chunk)
            if chunk.model:
                last_model = chunk.model
            if chunk.usage is not None:
                last_input_tokens = chunk.usage.prompt_tokens
                last_output_tokens = chunk.usage.completion_tokens
                yield chunk
                final_usage_emitted = True
                continue
            yield chunk
    finally:
        # If the authoritative final-usage chunk was never delivered to the
        # consumer (server cutoff, consumer cancelled mid-yield, network
        # drop, etc.), emit a best-effort usage chunk built from the last
        # counters we observed. Otherwise telemetry would silently record
        # zero tokens for any interrupted stream — masking real cost on
        # partial generations.
        if not final_usage_emitted and (last_input_tokens or last_output_tokens):
            try:
                yield _StreamChunk(
                    delta=_Delta(),
                    usage=_Usage(
                        prompt_tokens=last_input_tokens,
                        completion_tokens=last_output_tokens,
                    ),
                    model=last_model,
                )
            except (GeneratorExit, StopAsyncIteration):
                # The consumer has already called ``aclose()`` on this async
                # generator, so executing ``yield`` inside ``finally`` raises
                # GeneratorExit (or in rare cases StopAsyncIteration). Python
                # forbids re-raising during finally cleanup — and there's
                # nowhere to deliver the fallback usage chunk anyway. Swallow
                # silently and let normal generator teardown proceed.
                pass


# ---------------------------------------------------------------------------
# Fallback-logging helpers
# ---------------------------------------------------------------------------

# One-time LiteLLM-fallback notice ("Install `mcp-mesh[openai]` ...")
# emitted from ``OpenAIHandler.has_native()`` when native dispatch was
# attempted (the default) but the ``openai`` SDK is not importable. In
# normal installs the SDK is a base dep so this branch should never fire —
# kept for symmetry with the Anthropic path and to guard against custom
# installs that strip the SDK. ``is_fallback_logged()`` lets callers skip
# the call entirely after the first miss.
#
# State is the module-level ``_logged_fallback_once`` flag read/written
# through this module's globals by the factory closures (tests monkeypatch
# the flag as a module attribute).
_logged_fallback_once = False
log_fallback_once, is_fallback_logged, _reset_fallback_logged = make_fallback_logger(
    "openai", logger, module_globals=globals()
)


# Module-level dedupe set for the unsupported-kwarg WARN. WARN once per
# unique kwarg name across the lifetime of the process — high-volume
# providers receiving the same litellm-only kwarg every request would
# otherwise flood the log with identical messages (unbounded growth
# pre-fix).
#
# The dedupe set is per-vendor: a LiteLLM-only kwarg dropped on the
# OpenAI path won't suppress the WARN if it later shows up on the
# Anthropic path. The actual WARN-emit + dedupe machinery lives in
# ``_native_client_helpers.warn_unsupported_kwarg_once``; this module
# owns only the per-vendor state.
_logged_unsupported_kwargs: set[str] = set()


def _warn_unsupported_kwarg_once(
    key: str,
    *,
    sdk_call_label: str = "openai.chat.completions.create",
) -> None:
    """WARN once per unique unsupported kwarg name.

    Thin wrapper over the shared helper so call sites stay terse
    (single-arg) and the per-vendor dedupe state stays local to this
    module. Used by ``_build_create_kwargs`` to surface litellm-only
    knobs the adapter is silently dropping (or new fields the OpenAI SDK
    doesn't accept yet) without logging on every single request. The
    Responses builder passes ``sdk_call_label="openai.responses.create"``
    so the WARN names the correct endpoint.
    """
    warn_unsupported_kwarg_once(
        _logged_unsupported_kwargs,
        kwarg=key,
        adapter_label="OpenAI",
        sdk_call_label=sdk_call_label,
        logger=logger,
    )


def _reset_unsupported_kwargs_dedupe() -> None:
    """For tests — drop the WARN-once dedupe set so each test sees a fresh
    WARN trail. NOT for production use.
    """
    reset_unsupported_kwargs_dedupe(_logged_unsupported_kwargs)
