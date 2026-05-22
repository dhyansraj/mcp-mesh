"""Public ``mesh.jobs`` submodule — convenience helpers for the MeshJob
event-injection primitive (Phase 1, MeshJob substrate; event-channel
extension landed in v2.2).

The primary surfaces are:

* :func:`post_event` — fire-and-forget helper to push an event into a
  running job by id, without holding a :class:`mcp_mesh_core.JobProxy`
  reference. Intended for MCP tool bodies that receive a ``job_id`` in
  their request payload (e.g. a "submit_user_input" tool exposed by an
  orchestrator agent).

* :func:`subscribe_events` — observer-side async iterator over events
  posted to a running job. Useful for UI gateways that want to mirror
  events as they arrive, or any agent that wants to forward events to
  a downstream system in real time. Each call manages its own cursor,
  so multiple subscribers can observe the same job's events
  independently without disturbing the producer's ``recv_event``
  consumption.

* :class:`JobNotFoundError` / :class:`JobTerminalError` — typed
  ``RuntimeError`` subclasses translated from the Rust core's
  :enum:`JobError` variants. Because pyo3 surfaces all
  :enum:`JobError` variants as ``RuntimeError`` today (see
  ``src/runtime/core/src/jobs_py.rs::job_error_to_py``), we re-classify
  on the Python side via stable error-message substrings.

The :class:`mcp_mesh_core.JobController` / :class:`mcp_mesh_core.JobProxy`
methods (``recv_event`` / ``send_event`` / ``list_events``) are exposed
directly on the pyo3-bound classes — application code calls them via
the ``MeshJob``-typed parameter the framework injects. This module
just adds the helpers + error classes around that surface.
"""

from __future__ import annotations

import asyncio
import os
from collections import OrderedDict
from typing import Any, AsyncIterator, Optional

__all__ = [
    "JobNotFoundError",
    "JobTerminalError",
    "cancel",
    "post_event",
    "status",
    "subscribe_events",
    "wait",
]


# ---------------------------------------------------------------------------
# JobProxy cache (W5 — review #1032)
# ---------------------------------------------------------------------------
#
# ``post_event`` used to construct a fresh ``mcp_mesh_core.JobProxy`` on
# every call. Each proxy wraps a Rust ``reqwest::Client`` with its own
# connection pool, so a steady-state sender that fires off `post_event`
# in a hot loop would force a fresh TCP/TLS handshake against the
# registry on every call. Cache by ``(registry_url, job_id)`` for the
# process lifetime; the cache key is invalidated naturally when a
# different registry URL or job id is used. If a job is cancelled and
# re-submitted with the same id (rare in practice), the cached proxy
# would just see a JobTerminalError on its next send_event call — the
# correct surface — and the caller can retry.
#
# Bounded LRU eviction: long-lived senders that post events to many
# distinct jobs (e.g. a router fanning out across thousands of jobs)
# would otherwise grow the cache without bound. ``OrderedDict`` +
# ``move_to_end`` on hit / ``popitem(last=False)`` on overflow gives us
# O(1) LRU semantics. The Rust ``JobProxy`` does not expose an explicit
# ``close()`` over pyo3 — eviction just drops the dict entry and lets
# Python GC release the wrapped ``reqwest::Client`` connection pool when
# the last reference falls off the stack.
_PROXY_CACHE_DEFAULT_MAX = 256


def _proxy_cache_max() -> int:
    """Resolve the cache cap from ``MCP_MESH_JOBPROXY_CACHE_MAX`` (env
    override; falls back to ``_PROXY_CACHE_DEFAULT_MAX``). Invalid /
    non-positive values fall back to the default so a typo'd env doesn't
    silently disable the cache."""
    raw = os.environ.get("MCP_MESH_JOBPROXY_CACHE_MAX")
    if not raw:
        return _PROXY_CACHE_DEFAULT_MAX
    try:
        value = int(raw)
    except ValueError:
        return _PROXY_CACHE_DEFAULT_MAX
    return value if value > 0 else _PROXY_CACHE_DEFAULT_MAX


_proxy_cache: "OrderedDict[tuple[str, str], Any]" = OrderedDict()
_proxy_cache_lock = asyncio.Lock()


async def _get_or_create_proxy(registry_url: str, job_id: str) -> Any:
    """Return a process-cached ``mcp_mesh_core.JobProxy`` for the given
    ``(registry_url, job_id)`` pair, constructing one on first miss.

    Double-checked locking under an asyncio ``Lock`` so concurrent
    callers in the same event loop end up sharing a single proxy
    instance — the lock is only contended on the first call per key.
    Cache is a bounded LRU: hits bump the entry to the most-recent end,
    misses on a full cache evict the least-recent entry before
    inserting.
    """
    key = (registry_url, job_id)
    proxy = _proxy_cache.get(key)
    if proxy is not None:
        _proxy_cache.move_to_end(key)
        return proxy
    async with _proxy_cache_lock:
        proxy = _proxy_cache.get(key)
        if proxy is not None:
            _proxy_cache.move_to_end(key)
            return proxy
        try:
            from mcp_mesh_core import JobProxy
        except Exception as e:  # pragma: no cover - extension build issue
            raise RuntimeError(
                f"mesh.jobs: mcp_mesh_core.JobProxy unavailable "
                f"({e}); cannot construct a transient proxy"
            ) from e
        proxy = JobProxy(job_id, registry_url)
        max_size = _proxy_cache_max()
        while len(_proxy_cache) >= max_size:
            # Evict LRU. Dropping the entry releases our reference to
            # the JobProxy; Python GC reclaims the wrapped reqwest
            # client (and its connection pool) when no other refs exist.
            _proxy_cache.popitem(last=False)
        _proxy_cache[key] = proxy
        return proxy


# ---------------------------------------------------------------------------
# Typed error classes
# ---------------------------------------------------------------------------
#
# The Rust core's `JobError::JobNotFound` and `JobError::JobTerminal`
# variants currently surface as plain `RuntimeError` from the pyo3 layer
# (see `src/runtime/core/src/jobs_py.rs::job_error_to_py`). Until the
# pyo3 binding switches to a custom exception type, we re-classify on
# the Python side via stable substrings emitted by the pyo3 wrapper's
# explicit error remap in `src/runtime/core/src/jobs_py.rs`
# (`job_error_to_py` at lines 66-81, specifically the `JobTerminal` arm
# at line 78). The wrapper deliberately remaps `JobError::Display` to a
# stable SDK-facing format — do NOT collapse this remap thinking it just
# passes core's Display through; the substring contract here depends on
# it. Both classes derive from `RuntimeError` so existing
# `except RuntimeError:` handlers continue to catch them.


class JobNotFoundError(RuntimeError):
    """The targeted job does not exist (or has been swept) in the registry.

    Translated from the Rust ``JobError::Other(BackendError::NotFound)``
    error path (``GET/POST /jobs/{id}/events`` → HTTP 404).
    """


class JobTerminalError(RuntimeError):
    """The targeted job is in a terminal state (completed / failed /
    cancelled) and no longer accepts events.

    Translated from the Rust ``JobError::JobTerminal`` variant —
    ``POST /jobs/{id}/events`` returns HTTP 409 once the job row is
    terminal, and the Rust layer maps that to ``JobTerminal``.
    """


def _translate_job_error(exc: BaseException) -> BaseException:
    """Re-classify a generic :class:`RuntimeError` raised by the pyo3
    layer into one of the typed subclasses, if the message matches.

    Returns the original exception (or a typed clone) — caller should
    ``raise`` the returned value. Non-RuntimeError exceptions pass
    through unchanged.
    """
    if not isinstance(exc, RuntimeError) or isinstance(
        exc, (JobNotFoundError, JobTerminalError)
    ):
        return exc
    msg = str(exc)
    msg_lower = msg.lower()
    # Order matters: "job is terminal" is the JobTerminal variant's
    # Display prefix (see jobs_py.rs::job_error_to_py); "job not found"
    # is BackendError::NotFound's Display prefix.
    if "job is terminal" in msg_lower:
        new = JobTerminalError(msg)
        new.__cause__ = exc
        return new
    if "job not found" in msg_lower:
        new = JobNotFoundError(msg)
        new.__cause__ = exc
        return new
    return exc


# ---------------------------------------------------------------------------
# post_event convenience helper
# ---------------------------------------------------------------------------


def _resolve_registry_url() -> str:
    """Discover the registry base URL the running agent is bound to.

    Mirrors the same convention used by the inbound-job dispatch wrapper
    (``_mcp_mesh.engine.job_dispatch._resolve_runtime_identity``): the
    canonical source is the ``MCP_MESH_REGISTRY_URL`` environment
    variable. The configuration pipeline writes this on agent startup
    and every job-substrate code path reads it.

    Raises:
        RuntimeError: If the variable isn't set — the caller can't post
            an event without knowing which registry to target.
    """
    url = os.environ.get("MCP_MESH_REGISTRY_URL")
    if not url:
        raise RuntimeError(
            "mesh.jobs: MCP_MESH_REGISTRY_URL is not set; "
            "cannot resolve registry base URL. Ensure the calling "
            "process is running inside a mesh agent."
        )
    return url


async def post_event(
    job_id: str,
    event_type: str,
    payload: Optional[dict] = None,
) -> dict:
    """Post an event to a running job by ID.

    Convenience helper for tool bodies that hold a ``job_id`` (e.g. from
    a request body, a token lookup, or a stashed reference) but do NOT
    have a :class:`mcp_mesh_core.JobProxy` reference in scope.
    Constructs a transient proxy bound to the current agent's registry
    URL and forwards the call.

    Args:
        job_id: Target job's server-assigned id.
        event_type: Event type tag (e.g. ``"extend_deadline"``,
            ``"user_input"``, or any user-defined string). The running
            handler can filter via ``await job.recv_event(types=[...])``.
        payload: Optional JSON-serialisable dict carried with the event.
            ``None`` is normalised to an empty dict before forwarding —
            the Rust layer accepts either.

    Returns:
        Receipt dict ``{"job_id": str, "seq": int, "created_at": int}``.
        ``seq`` is the server-assigned sequence number useful for
        stitching follow-up ``recv_event`` calls.

    Raises:
        JobNotFoundError: If the registry doesn't know the job
            (sweep already removed it, or wrong id).
        JobTerminalError: If the job has already reached a terminal
            state — no more events accepted.
        RuntimeError: For transport errors (registry unreachable,
            5xx after retries, malformed payload, etc.) — the
            underlying error message is preserved.

    Example:
        Inside an MCP tool body that holds a job id::

            @mesh.tool(capability="submit_user_input")
            async def submit_input(job_id: str, text: str) -> dict:
                receipt = await mesh.jobs.post_event(
                    job_id,
                    "user_input",
                    {"text": text},
                )
                return {"posted_seq": receipt["seq"]}
    """
    registry_url = _resolve_registry_url()
    proxy = await _get_or_create_proxy(registry_url, job_id)
    safe_payload: dict = payload if payload is not None else {}
    try:
        return await proxy.send_event(event_type, safe_payload)
    except RuntimeError as exc:
        translated = _translate_job_error(exc)
        if translated is exc:
            raise
        raise translated from exc


# ---------------------------------------------------------------------------
# subscribe_events convenience helper (observer-side iterator)
# ---------------------------------------------------------------------------


async def subscribe_events(
    job_id: str,
    types: Optional[list[str]] = None,
    after: int = 0,
    long_poll_secs: Optional[float] = 30.0,
) -> AsyncIterator[dict]:
    """Subscribe to events posted to a running job by ID.

    Long-lived async iterator. Each call manages its own cursor — multiple
    subscribers can observe the same job's events independently without
    affecting the producer's ``recv_event`` consumption (the producer's
    cursor is per-controller, this observer's cursor is per-call).

    The iterator runs indefinitely until the caller breaks out of the
    ``async for`` loop or the underlying registry returns
    :class:`JobNotFoundError`. There is no automatic terminal-state
    detection — use a synthetic event type (e.g. ``{"type": "ended"}``)
    posted by your application to signal iteration end.

    Args:
        job_id: Target job's server-assigned id.
        types: Optional filter; only events whose ``type`` matches one
            of these is yielded. ``None`` ≡ all types.
        after: Initial cursor (default ``0`` ≡ from the beginning of the
            event log). Pass a higher value to skip historical events.
        long_poll_secs: Long-poll wait budget per registry call.
            Default ``30s``. Capped at ``60s`` by the registry.
            Pass ``None`` to skip the long-poll entirely (single
            immediate read; rarely needed — tight-poll callers should
            pass ``0.0`` instead).

    Yields:
        Event dicts: ``{seq, type, payload, trace_context, posted_by,
        created_at, job_id}``.

    Raises:
        JobNotFoundError: If the job has been reaped from the registry
            (404 on the ``GET /jobs/{id}/events`` endpoint).
        RuntimeError: For transport errors (registry unreachable, 5xx
            after retries, malformed payload, etc.) — the underlying
            error message is preserved.

    Example:
        Mirror events from a running job into a downstream system::

            async def mirror_events(job_id: str) -> None:
                async for event in mesh.jobs.subscribe_events(
                    job_id, types=["progress", "result"]
                ):
                    await downstream.publish(event)
                    if event["type"] == "result":
                        break  # caller-defined termination
    """
    registry_url = _resolve_registry_url()
    proxy = await _get_or_create_proxy(registry_url, job_id)
    cursor = after
    while True:
        try:
            events, next_after = await proxy.list_events(
                cursor, types, long_poll_secs
            )
        except RuntimeError as exc:
            translated = _translate_job_error(exc)
            if translated is exc:
                raise
            raise translated from exc
        for event in events:
            seq = event.get("seq")
            # `type(...) is not int` (rather than `isinstance(..., int)`)
            # rejects booleans: `type(True) is bool`, but
            # `isinstance(True, int)` is True. The registry contract is
            # integer seqs; a bool here would be a wire-level malformed
            # payload.
            if type(seq) is not int:
                raise RuntimeError(
                    f"subscribe_events: registry returned event without integer 'seq': {event!r}"
                )
            cursor = max(cursor, seq)
            # list_events returns ascending-seq; cursor advance before
            # yield ensures correctness across consumer cancellation.
            yield event
        # Empty pages (or pages filtered by `types` server-side) still
        # advance the cursor via the registry-supplied watermark, so
        # subsequent polls don't re-scan the same filtered range.
        if next_after > cursor:
            cursor = next_after


# ---------------------------------------------------------------------------
# cancel / status / wait — DDDI-clean lifecycle facades (issue #1074)
# ---------------------------------------------------------------------------
#
# Mirror the ``post_event`` / ``subscribe_events`` pattern: take a
# ``job_id`` as the first positional arg, resolve the registry URL
# internally via ``_resolve_registry_url()``, dispatch through a cached
# ``JobProxy`` from ``_get_or_create_proxy()``, and re-classify the
# pyo3 layer's ``RuntimeError`` output via ``_translate_job_error``.
#
# These exist so callers that hold only a ``job_id`` (e.g. an HTTP route
# handler, a tool body whose request payload carries a stashed id) can
# operate on the job's lifecycle without constructing a ``JobProxy``
# directly — which would leak ``MCP_MESH_REGISTRY_URL`` addressing into
# user code and break the DDDI contract.


async def cancel(job_id: str, reason: Optional[str] = None) -> None:
    """Cancel a running job by ID.

    Convenience helper for callers that hold a ``job_id`` but do not have
    a :class:`mcp_mesh_core.JobProxy` reference in scope. Constructs a
    transient proxy bound to the current agent's registry URL and
    forwards the call.

    Calling ``cancel`` on a job that is already in a terminal state is
    a no-op per the registry's idempotency contract — the call returns
    successfully without re-firing cancellation. If the registry's
    contract changes or returns a 409 conflict for some other reason,
    the facade surfaces it as :class:`JobTerminalError`. The registry
    forwards the cancel signal to the owner replica via
    ``POST /jobs/{id}/cancel``; the running handler's cancel token
    fires on the next ``await`` point, and any outbound ``McpMeshTool``
    proxy calls abort their underlying HTTP requests.

    Args:
        job_id: Target job's server-assigned id.
        reason: Optional human-readable reason recorded against the
            cancellation. Surfaces in the synthetic
            ``{"type": "cancelled"}`` event the registry writes into
            the job's event log, so a handler parked on
            ``recv_event(types=["cancelled"])`` can return cleanly with
            the reason in scope.

    Raises:
        JobNotFoundError: If the registry doesn't know the job
            (sweep already removed it, or wrong id).
        JobTerminalError: If the registry surfaces a 409 conflict for
            this cancel (e.g. the idempotency contract changes upstream
            or the registry treats the targeted terminal state as a
            conflict).
        RuntimeError: For transport errors (registry unreachable,
            5xx after retries, malformed payload, etc.) — the
            underlying error message is preserved.

    Example:
        Cancel a job from a tool that receives the id in its payload::

            @mesh.tool(capability="abort_workflow")
            async def abort_workflow(job_id: str, reason: str) -> dict:
                await mesh.jobs.cancel(job_id, reason)
                return {"cancelled": job_id}
    """
    registry_url = _resolve_registry_url()
    proxy = await _get_or_create_proxy(registry_url, job_id)
    try:
        await proxy.cancel(reason)
    except RuntimeError as exc:
        translated = _translate_job_error(exc)
        if translated is exc:
            raise
        raise translated from exc


async def status(job_id: str) -> dict:
    """Get the current status of a job by ID.

    Convenience helper for callers that hold a ``job_id`` but do not
    have a :class:`mcp_mesh_core.JobProxy` reference in scope.
    Constructs a transient proxy bound to the current agent's registry
    URL and forwards a single ``GET /jobs/{id}`` to the registry.

    Args:
        job_id: Target job's server-assigned id.

    Returns:
        Job status dict — the same shape :meth:`JobProxy.status` returns,
        mirroring the registry's ``Job`` schema field-for-field. Keys
        include ``id``, ``capability``, ``status`` (one of
        ``"working" | "input_required" | "completed" | "failed" | "cancelled"``),
        ``progress``, ``progress_message``, ``result``, ``error``,
        ``attempt_count``, ``max_retries``, ``max_duration``,
        ``total_deadline``, ``submitted_at``, ``submitted_by``,
        ``submitted_payload`` (the request payload the job was created
        with), plus the lease-tracking fields ``owner_instance_id`` /
        ``lease_expires_at`` / ``last_heartbeat_at``.

    Raises:
        JobNotFoundError: If the registry doesn't know the job
            (sweep already removed it, or wrong id).
        RuntimeError: For transport errors (registry unreachable,
            5xx after retries, malformed payload, etc.) — the
            underlying error message is preserved.

    Example:
        Poll a job's progress from outside the producer agent::

            @mesh.tool(capability="check_progress")
            async def check_progress(job_id: str) -> dict:
                snapshot = await mesh.jobs.status(job_id)
                return {
                    "status": snapshot["status"],
                    "progress": snapshot["progress"],
                    "message": snapshot["progress_message"],
                }
    """
    registry_url = _resolve_registry_url()
    proxy = await _get_or_create_proxy(registry_url, job_id)
    try:
        return await proxy.status()
    except RuntimeError as exc:
        translated = _translate_job_error(exc)
        if translated is exc:
            raise
        raise translated from exc


async def wait(job_id: str, timeout_secs: Optional[float] = None) -> Any:
    """Wait for a job to complete and return its result.

    Convenience helper for callers that hold a ``job_id`` but do not
    have a :class:`mcp_mesh_core.JobProxy` reference in scope.
    Constructs a transient proxy bound to the current agent's registry
    URL and polls until the job reaches a terminal state.

    On success, returns the ``result`` payload the handler passed to
    :meth:`JobController.complete` — any JSON-shaped Python value (dict /
    list / primitive). On a non-success terminal (failed / cancelled)
    the underlying pyo3 layer raises a ``RuntimeError`` carrying the
    Rust ``JobError`` display string; on ``timeout_secs`` expiry the
    layer raises :class:`TimeoutError`.

    Args:
        job_id: Target job's server-assigned id.
        timeout_secs: Maximum wait duration in seconds. ``None`` ≡ no
            timeout (default) — wait until the job reaches a terminal
            state. Negative / NaN / infinite values are rejected by
            the pyo3 layer with :class:`ValueError`.

    Returns:
        The job's result payload (whatever the handler passed to
        ``complete()``). Shape is application-defined — typically a
        dict, but any JSON-shaped value is valid.

    Raises:
        TimeoutError: If ``timeout_secs`` elapses before the job reaches
            a terminal state.
        ValueError: If ``timeout_secs`` is negative, NaN, or infinite
            — rejected by the pyo3 layer before any registry call.
        JobNotFoundError: If the registry doesn't know the job
            (sweep already removed it, or wrong id).
        RuntimeError: If the job reached a non-success terminal state
            (``failed`` / ``cancelled``) or for transport errors —
            the underlying error message is preserved.

    Example:
        Submit-then-wait from a tool that doesn't hold the proxy::

            @mesh.tool(capability="run_to_completion")
            async def run_to_completion(job_id: str) -> dict:
                result = await mesh.jobs.wait(job_id, timeout_secs=300.0)
                return {"result": result}
    """
    registry_url = _resolve_registry_url()
    proxy = await _get_or_create_proxy(registry_url, job_id)
    try:
        return await proxy.wait(timeout_secs)
    except RuntimeError as exc:
        translated = _translate_job_error(exc)
        if translated is exc:
            raise
        raise translated from exc
