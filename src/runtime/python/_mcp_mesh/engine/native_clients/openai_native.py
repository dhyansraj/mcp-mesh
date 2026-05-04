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

import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Model prefixes that route through this adapter.
_OPENAI_PREFIX = "openai/"


# ---------------------------------------------------------------------------
# Shared httpx connection pool (issue #834 perf fix)
# ---------------------------------------------------------------------------
# A single ``httpx.AsyncClient`` is reused across all native OpenAI calls in
# this process. ``openai.AsyncOpenAI`` accepts ``http_client=`` and uses the
# supplied client (and its connection pool) instead of constructing a fresh
# one per call. This eliminates ~150-300ms per-call TLS+H2 setup overhead
# vs. LiteLLM (which does its own pool reuse).
#
# K8s secret rotation still works because the api_key is still read fresh
# per call by callers and forwarded to the per-call ``AsyncOpenAI`` wrapper
# — the pool itself carries no credential state, only TCP/TLS connections.
_CACHED_HTTPX_CLIENT: httpx.AsyncClient | None = None
# Guards lazy-init / rebuild of the shared httpx client. The pool itself is
# safe for concurrent use; the lock only protects the check-then-create race
# at construction. Cheap (uncontended after first call) and correct under
# threaded harnesses (tests, sync wrapper paths) that touch the cache.
_CACHED_HTTPX_CLIENT_LOCK = threading.Lock()


def _get_shared_httpx_client() -> httpx.AsyncClient:
    """Lazily construct (or rebuild if closed) the shared httpx client.

    Single connection pool shared across all native OpenAI calls in this
    process. Per-call ``AsyncOpenAI`` wrappers reuse this pool —
    eliminating ~150-300ms per-call TLS+H2 setup overhead. K8s secret
    rotation still works: ``api_key`` is read fresh per call; the pool
    carries no credential state.
    """
    global _CACHED_HTTPX_CLIENT
    # Fast path — no lock when the cached client is healthy. The check is
    # benign-racy (worst case: two threads both observe None and both enter
    # the lock; the second one finds the cache populated under the lock and
    # returns early).
    if _CACHED_HTTPX_CLIENT is not None and not _CACHED_HTTPX_CLIENT.is_closed:
        return _CACHED_HTTPX_CLIENT
    with _CACHED_HTTPX_CLIENT_LOCK:
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
    with _CACHED_HTTPX_CLIENT_LOCK:
        _CACHED_HTTPX_CLIENT = None


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


_IS_AVAILABLE_CACHE: bool | None = None


def is_available() -> bool:
    """True if the ``openai`` SDK is importable in this process.

    Result is cached after the first probe — the SDK presence does not
    change at runtime, and the import-then-immediately-discard pattern
    showed up as needless overhead on the dispatch-decision hot path in
    PR 1 (anthropic_native) so the same caching is applied here.
    """
    global _IS_AVAILABLE_CACHE
    if _IS_AVAILABLE_CACHE is not None:
        return _IS_AVAILABLE_CACHE
    try:
        import openai  # noqa: F401
    except ImportError:
        _IS_AVAILABLE_CACHE = False
        return False
    _IS_AVAILABLE_CACHE = True
    return True


def _reset_is_available_cache() -> None:
    """For tests — reset the cached availability probe. NOT for production."""
    global _IS_AVAILABLE_CACHE
    _IS_AVAILABLE_CACHE = None


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
    create_kwargs: dict[str, Any] = {"model": _strip_prefix(model)}

    for key in _OPENAI_PASSTHROUGH_KWARGS:
        value = request_params.get(key)
        # Drop None values — OpenAI rejects ``max_tokens=None`` etc., and
        # leaving them out matches the "unset → SDK default" semantics that
        # callers expect. (``request_params.get`` already returns None for
        # missing keys, so the absence check collapses into the value check.)
        if value is None:
            continue
        create_kwargs[key] = value

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
# Response / chunk adaptation
# ---------------------------------------------------------------------------


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
    """Run a buffered OpenAI completion and adapt to litellm-shape response."""
    client = _build_client(model, api_key, base_url)
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

_logged_fallback_once = False


def log_fallback_once() -> None:
    """Emit the LiteLLM-fallback notice exactly once per process.

    Called from the dispatch sites in ``OpenAIHandler.has_native()`` when
    native dispatch was attempted (the default) but the ``openai`` SDK is
    not importable. In normal installs the SDK is a base dep so this
    branch should never fire — kept for symmetry with the Anthropic path
    and to guard against custom installs that strip the SDK.
    """
    global _logged_fallback_once
    if _logged_fallback_once:
        return
    _logged_fallback_once = True
    logger.info(
        "Install `mcp-mesh[openai]` for native SDK with full feature "
        "support — falling back to LiteLLM"
    )


def is_fallback_logged() -> bool:
    """True once :func:`log_fallback_once` has emitted its notice.

    Lets callers (notably ``OpenAIHandler.has_native``) skip the call entirely
    on the hot path after the first miss — avoids one function-frame per
    request once we've already published the install nudge.
    """
    return _logged_fallback_once


# Module-level dedupe set for the unsupported-kwarg WARN. WARN once per
# unique kwarg name across the lifetime of the process — high-volume
# providers receiving the same litellm-only kwarg every request would
# otherwise flood the log with identical messages (unbounded growth
# pre-fix).
_logged_unsupported_kwargs: set[str] = set()


def _warn_unsupported_kwarg_once(key: str) -> None:
    """WARN once per unique unsupported kwarg name.

    Used by ``_build_create_kwargs`` to surface litellm-only knobs the
    adapter is silently dropping (or new fields the OpenAI SDK doesn't
    accept yet) without logging on every single request.
    """
    if key in _logged_unsupported_kwargs:
        return
    _logged_unsupported_kwargs.add(key)
    logger.warning(
        "Native OpenAI adapter dropping unsupported kwarg: '%s' "
        "(LiteLLM-only — not forwarded to openai.chat.completions.create)",
        key,
    )
