"""User-facing A2A surface helpers (issue #903 Phase 1B / Phase 2 / Phase 3).

Two complementary entry points:

* ``@mesh.a2a(path=..., dependencies=[...])`` — decorator that stamps
  ``_mesh_a2a_metadata`` on the function and wires DDDI dependency
  injection (mirrors ``@mesh.route``). Pure metadata + DI; does NOT
  mount any FastAPI routes. Imported from ``mesh.decorators`` and
  re-exposed here under the ``mesh.a2a`` callable so users can write
  ``@mesh.a2a(...)`` for advanced cases (multi-app fan-out, custom
  mounting, library-style integrations).

* ``mesh.a2a.mount(app, *, path=..., dependencies=[...])`` — the
  recommended entry point. Mirrors the ``@mesh.route`` UX: the user
  owns the FastAPI app, the helper applies ``@mesh.a2a`` AND mounts
  the two companion routes the A2A protocol surface needs:

    GET  ``{path}/.well-known/agent.json``  → A2A AgentCard
    POST ``{path}``                         → JSON-RPC 2.0 entry point

Phase 2 (this module) dispatches sync ``tasks/send`` into the user
handler and wraps the result in an A2A v1.0 ``Task`` envelope.

Phase 2-leftover wires the long-running task lifecycle: when the user
handler returns a ``mcp_mesh_core.JobProxy`` (i.e., the handler called
``await meshjob_dep.submit(...)``), the framework treats the call as
long-running — stores the proxy in a process-local map keyed by A2A
``task_id``, and exposes ``tasks/get`` / ``tasks/cancel`` against that
proxy. Detecting long-running via the *return value* (rather than the
metadata-driven ``_underlying_tool_is_task`` helper) is intentional:
the helper can't see cross-agent deps, but the return-value pattern
works uniformly for local *and* remote ``task=True`` deps.

Phase 3 wires SSE streaming via ``tasks/sendSubscribe`` and
``tasks/resubscribe`` — the same dispatch as ``tasks/send`` but the
response is a ``StreamingResponse`` of A2A v1.0 ``TaskStatusUpdateEvent``
/ ``TaskArtifactUpdateEvent`` JSON-RPC envelopes. Per spec, client
disconnect does NOT cancel the underlying job; the client may rejoin
via ``tasks/resubscribe``.

Public URL caching
==================
Each surface caches the registry-stamped public URL (delivered on the
heartbeat response under ``surfaces[].public_url``) on a module-level
dict keyed by ``(path, skill_id)``. The agent-card endpoint reads
this cache so the card's ``url`` field reflects the public FQDN. When
the cache is empty (e.g., first request before the first heartbeat
round-trip, or ``MCP_MESH_PUBLIC_URL_PREFIX`` unset), the URL falls
back to the agent's local ``http_host:http_port + path`` — sufficient
for local development and integration tests.

NOTE: we deliberately avoid ``from __future__ import annotations`` in
this module — FastAPI's Dependant builder calls ``inspect.signature``
and stringified annotations cause it to misclassify ``request: Request``
as a query parameter (yielding 422 on every POST).
"""

import asyncio
import json as _json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Long-running task store
# ---------------------------------------------------------------------------
#
# Shape: ``{ task_id (str) -> { "proxy": JobProxy, "terminal_at": float|None } }``
#
# - ``proxy`` is a ``mcp_mesh_core.JobProxy`` returned from the user
#   handler when it submitted a ``MeshJob``. Keeping the proxy lets
#   ``tasks/get`` / ``tasks/cancel`` / ``tasks/resubscribe`` poll +
#   cancel the underlying mesh job without re-resolving.
# - ``terminal_at`` is the monotonic-clock timestamp when the task was
#   first observed in a terminal state (``completed`` / ``failed`` /
#   ``cancelled``). ``None`` while still working. Used by the sweep to
#   evict entries older than ``_TERMINAL_GRACE_SECS`` so the store
#   doesn't grow unbounded for long-lived agents.
#
# The store is process-local — A2A surfaces do not currently share state
# across replicas. A client that connected to replica A and then
# reconnects (via ``tasks/resubscribe``) to replica B would get an
# unknown-task error. Cross-replica sharing is out of scope for v1.
_A2A_TASK_STORE: Dict[str, dict] = {}

# Evict terminal-state entries from ``_A2A_TASK_STORE`` after this many
# seconds. Five minutes balances "give the client time to fetch the
# final result" against "don't keep references to dead Rust JobProxy
# objects forever".
_TERMINAL_GRACE_SECS = 300.0


# A2A v1.0 spec uses a single-l ``"canceled"`` (US spelling); the mesh
# job lifecycle uses double-l ``"cancelled"`` (UK spelling, matches the
# Rust ``JobStatus::Cancelled`` variant). Translate at the boundary.
_MESH_TO_A2A_STATE = {
    "working": "working",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "canceled",
}


def _map_mesh_state(mesh_status: Optional[str]) -> str:
    """Translate a mesh job status string to its A2A v1.0 equivalent.

    Unknown / unset statuses fall back to ``"working"`` — preserves the
    invariant that we never emit an A2A state outside the spec's
    enumerated set, even if the registry adds a new internal status
    we haven't mapped yet.
    """
    if not mesh_status:
        return "working"
    return _MESH_TO_A2A_STATE.get(mesh_status, "working")


def _is_job_proxy(value: Any) -> bool:
    """Return True iff ``value`` is a ``mcp_mesh_core.JobProxy`` instance.

    Lazy import: ``mcp_mesh_core`` is a Rust extension that may not be
    available in pure-Python test environments. When the import fails
    we fall back to ``False`` — handlers in test envs that mock the
    proxy can still use the duck-typed helpers via ``isinstance`` checks
    against their mock class. Production agents always have the
    extension installed.
    """
    try:
        from mcp_mesh_core import JobProxy  # type: ignore[attr-defined]
    except Exception:
        return False
    return isinstance(value, JobProxy)


def _sweep_terminal_tasks(now: Optional[float] = None) -> None:
    """Evict entries from ``_A2A_TASK_STORE`` whose terminal_at is older
    than ``_TERMINAL_GRACE_SECS`` ago. Best-effort housekeeping called
    on each store access — keeps the dict bounded for long-lived agents
    without requiring a background sweeper task.
    """
    if not _A2A_TASK_STORE:
        return
    now = now if now is not None else time.monotonic()
    expired = [
        tid
        for tid, entry in _A2A_TASK_STORE.items()
        if entry.get("terminal_at") is not None
        and (now - entry["terminal_at"]) > _TERMINAL_GRACE_SECS
    ]
    for tid in expired:
        _A2A_TASK_STORE.pop(tid, None)


def _store_task(
    task_id: str,
    proxy: Any,
    *,
    request_message: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> None:
    """Register a long-running task → proxy mapping for later lookups.

    Sweeps terminal entries first, then rejects duplicates: if ``task_id``
    already maps to an in-flight task, raises ``ValueError`` rather than
    silently overwriting (which would orphan the prior ``JobProxy`` and
    leave the originating client unable to poll/cancel its task).

    Persists ``request_message`` and ``session_id`` alongside the proxy
    so ``tasks/get`` envelopes can echo the originating request in the
    A2A ``history`` field (which is otherwise empty for polled lookups).
    """
    _sweep_terminal_tasks()
    if task_id in _A2A_TASK_STORE:
        raise ValueError(
            f"A2A task id {task_id!r} is already in use; pick a fresh "
            "id or wait for the existing task to terminate (entries are "
            f"swept after {_TERMINAL_GRACE_SECS}s in terminal state)"
        )
    _A2A_TASK_STORE[task_id] = {
        "proxy": proxy,
        "terminal_at": None,
        "request_message": request_message,
        "session_id": session_id,
    }


def _mark_terminal(task_id: str) -> None:
    """Record that ``task_id`` reached a terminal state, starting the
    eviction grace window. No-op if the task isn't in the store."""
    entry = _A2A_TASK_STORE.get(task_id)
    if entry is not None and entry.get("terminal_at") is None:
        entry["terminal_at"] = time.monotonic()


# Module-level cache of the registry-stamped public URLs, keyed by
# (path, skill_id). Populated by :func:`update_public_url_cache` from the
# heartbeat-response handler; read by the agent-card endpoint at request
# time. Process-local — not persisted.
_PUBLIC_URL_CACHE: Dict[tuple, str] = {}


# Tracks already-mounted A2A surfaces keyed by ``(id(app), path)`` so a
# duplicate ``mount(app, path=X, ...)`` call raises instead of silently
# splitting into two DecoratorRegistry entries (heartbeat would report 2
# surfaces) plus a single reachable route. Keying by ``id(app)`` allows
# the same path on different FastAPI app instances (e.g. multiple test apps).
_MOUNTED_A2A_PATHS: set = set()


def update_public_url_cache(path: str, skill_id: str, public_url: Optional[str]) -> None:
    """Cache (or clear) a registry-stamped public URL for one A2A surface.

    Called from the heartbeat-response handler when the registry returns
    ``surfaces[].public_url``. Empty/None clears the cache entry so the
    agent-card endpoint falls back to the local host:port.
    """
    key = (path, skill_id)
    if public_url:
        _PUBLIC_URL_CACHE[key] = public_url
    else:
        _PUBLIC_URL_CACHE.pop(key, None)


def get_cached_public_url(path: str, skill_id: str) -> Optional[str]:
    """Return the registry-stamped public URL for a surface, if cached."""
    return _PUBLIC_URL_CACHE.get((path, skill_id))


def _local_fallback_url(agent_config: dict, path: str) -> str:
    """Build a host:port + path URL for local-development fallback.

    Used when the registry hasn't stamped a public URL yet (or
    ``MCP_MESH_PUBLIC_URL_PREFIX`` is unset). Not addressable from
    outside the local network — appropriate only for dev/CI.
    """
    host = agent_config.get("http_host") or "localhost"
    port = agent_config.get("http_port") or 0
    if port:
        return f"http://{host}:{port}{path}"
    return f"http://{host}{path}"


def _resolve_agent_config() -> dict:
    """Best-effort lookup of the resolved @mesh.agent config at mount time.

    Falls back to an empty dict — the agent-card endpoint then uses
    ``localhost`` for the fallback URL. Once the heartbeat round-trip
    populates the public-URL cache, the fallback path stops mattering.
    """
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        return DecoratorRegistry.get_resolved_agent_config() or {}
    except Exception:
        return {}


def _underlying_tool_is_task(metadata: dict) -> bool:
    """Return True iff the underlying mesh tool dep is task=True.

    Best-effort: looks up the dependency's capability in the
    DecoratorRegistry's mesh_tools and checks the producer-side
    ``task`` flag stamped by ``@mesh.tool(task=True)``. Returns
    False when the dep is missing, multi-dep, or the tool isn't
    locally registered (cross-agent dep).
    """
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
    except Exception:
        return False

    deps = metadata.get("dependencies") or []
    if len(deps) != 1:
        return False
    cap = deps[0].get("capability")
    if not cap:
        return False
    for _, decorated in DecoratorRegistry.get_mesh_tools().items():
        tool_meta = decorated.metadata or {}
        if tool_meta.get("capability") == cap and tool_meta.get("task"):
            return True
    return False


def _underlying_tool_input_schema(metadata: dict) -> Optional[dict]:
    """Return the underlying mesh tool's input schema if available."""
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.utils.fastmcp_schema_extractor import (
            FastMCPSchemaExtractor,
        )
    except Exception:
        return None

    deps = metadata.get("dependencies") or []
    if len(deps) != 1:
        return None
    cap = deps[0].get("capability")
    if not cap:
        return None
    for _, decorated in DecoratorRegistry.get_mesh_tools().items():
        tool_meta = decorated.metadata or {}
        if tool_meta.get("capability") == cap:
            schema = tool_meta.get("input_schema")
            if schema:
                return schema
            try:
                return FastMCPSchemaExtractor.extract_input_schema(decorated.function)
            except Exception:
                return None
    return None


def _make_card_endpoint(
    *,
    metadata: dict,
    agent_config_provider: Callable[[], dict],
):
    """Build a FastAPI endpoint coroutine returning the AgentCard JSON.

    ``agent_config_provider`` is called lazily on each request so the
    card picks up agent config that may not have been resolved yet at
    mount time (mount() is typically called at module import, before
    the @mesh.agent class is processed).
    """
    from _mcp_mesh.engine.a2a_card import build_agent_card

    path = metadata["path"]
    skill_id = metadata["skill_id"]

    async def get_agent_card() -> dict:
        agent_config = agent_config_provider() or {}
        agent_name = (
            agent_config.get("name")
            or agent_config.get("agent_id")
            or "agent"
        )
        agent_version = agent_config.get("version", "1.0.0")
        agent_description = agent_config.get("description")

        cached = get_cached_public_url(path, skill_id)
        public_url = cached or _local_fallback_url(agent_config, path)

        # Per A2A v1.0 spec, capabilities.streaming = "supports
        # tasks/sendSubscribe + tasks/resubscribe". The mount() helper
        # ALWAYS wires both routes (sync handlers stream a single
        # artifact + terminal event; long-running stream progress +
        # artifact + terminal). So streaming is always advertised true.
        # _underlying_tool_is_task remains as a documented fallback for
        # debug/diagnostic builds that disable the SSE handlers.
        streaming = True or _underlying_tool_is_task(metadata)
        input_schema = _underlying_tool_input_schema(metadata)
        bearer_auth = metadata.get("auth") == "bearer"

        return build_agent_card(
            name=agent_name,
            description=agent_description,
            version=agent_version,
            public_url=public_url,
            skill_id=skill_id,
            skill_name=metadata.get("skill_name") or skill_id,
            skill_description=metadata.get("description"),
            input_modes=metadata.get("input_modes") or ["application/json"],
            output_modes=metadata.get("output_modes") or ["application/json"],
            tags=metadata.get("tags") or [],
            streaming=streaming,
            bearer_auth=bearer_auth,
            underlying_tool_input_schema=input_schema,
        )

    return get_agent_card


def _utc_now_iso() -> str:
    """Return current UTC time in A2A v1.0 ``...Z`` ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_completed_task(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    result: Any,
) -> dict:
    """Build an A2A v1.0 ``Task`` with ``state=completed``.

    The user-handler return value becomes the single ``result`` artifact's
    text part. Non-string results are JSON-stringified so the artifact's
    ``text`` field stays string-typed per the A2A v1.0 ``TextPart`` shape.
    Non-JSON-serializable types (datetime, Decimal, Path, dataclass, set,
    etc.) are coerced best-effort via ``default=str`` so a handler that
    returns one of these doesn't crash the JSON-RPC entry — the user's
    try/except is honoured by routing exceptions through ``state=failed``,
    not bubbling them up as 500s.
    """
    text = result if isinstance(result, str) else _json.dumps(result, default=str)
    return {
        "id": task_id,
        "sessionId": session_id,
        "status": {
            "state": "completed",
            "timestamp": _utc_now_iso(),
        },
        "artifacts": [
            {
                "name": "result",
                "parts": [{"type": "text", "text": text}],
                "index": 0,
            }
        ],
        "history": [request_message] if request_message else [],
    }


def _build_failed_task(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    error_msg: str,
) -> dict:
    """Build an A2A v1.0 ``Task`` with ``state=failed``.

    Per A2A v1.0, handler exceptions become a ``failed`` task (NOT a
    JSON-RPC error). JSON-RPC errors are reserved for protocol-level
    issues like bad request shape or missing method.
    """
    return {
        "id": task_id,
        "sessionId": session_id,
        "status": {
            "state": "failed",
            "timestamp": _utc_now_iso(),
            "message": {
                "role": "agent",
                "parts": [{"type": "text", "text": error_msg}],
            },
        },
        "artifacts": [],
        "history": [request_message] if request_message else [],
    }


def _build_working_task(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    *,
    progress: Optional[Any] = None,
    progress_message: Optional[str] = None,
) -> dict:
    """Build an A2A v1.0 ``Task`` envelope with ``state=working``.

    Returned synchronously from ``tasks/send`` once the user handler
    has dispatched the underlying mesh job and handed us back a
    ``JobProxy`` — the framework owns lifecycle from this point on.
    The artifacts list is empty because the job hasn't produced one yet;
    the client either polls ``tasks/get`` for terminal status or
    subscribes via ``tasks/sendSubscribe`` for incremental updates.
    """
    status: dict = {"state": "working", "timestamp": _utc_now_iso()}
    if progress_message:
        status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": progress_message}],
        }
    envelope: dict = {
        "id": task_id,
        "sessionId": session_id,
        "status": status,
        "artifacts": [],
        "history": [request_message] if request_message else [],
    }
    if progress is not None:
        envelope["metadata"] = {"progress": progress}
    return envelope


def _build_task_from_status(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    status: dict,
    *,
    final_result: Any = None,
    has_final_result: bool = False,
) -> dict:
    """Build an A2A v1.0 ``Task`` envelope from a ``JobProxy.status()`` dict.

    ``status`` is the dict the mesh registry returns — keys include
    ``status`` (working/completed/failed/cancelled), ``progress``,
    ``progress_message``, ``error``, etc. We map mesh→A2A states and
    fold ``error``/``progress_message`` into the A2A status.message
    when present.

    ``final_result`` is only populated when the caller already invoked
    ``proxy.wait()`` and got a value back (i.e., the job is completed).
    For ``tasks/get`` we don't block on ``wait()`` — terminal-state
    callers that want the artifact should subscribe via SSE instead.
    """
    mesh_state = status.get("status") or "working"
    a2a_state = _map_mesh_state(mesh_state)

    a2a_status: dict = {"state": a2a_state, "timestamp": _utc_now_iso()}

    msg_text = None
    if a2a_state == "failed":
        msg_text = status.get("error") or status.get("progress_message")
    else:
        msg_text = status.get("progress_message")
    if msg_text:
        a2a_status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": str(msg_text)}],
        }

    artifacts: list = []
    if has_final_result and a2a_state == "completed":
        text = (
            final_result
            if isinstance(final_result, str)
            else _json.dumps(final_result, default=str)
        )
        artifacts.append(
            {
                "name": "result",
                "parts": [{"type": "text", "text": text}],
                "index": 0,
            }
        )

    envelope: dict = {
        "id": task_id,
        "sessionId": session_id,
        "status": a2a_status,
        "artifacts": artifacts,
        "history": [request_message] if request_message else [],
    }

    progress = status.get("progress")
    if progress is not None:
        envelope["metadata"] = {"progress": progress}

    return envelope


def _jsonrpc_success(req_id: Any, result_obj: Any) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"jsonrpc": "2.0", "id": req_id, "result": result_obj},
    )


def _jsonrpc_error(
    req_id: Any,
    code: int,
    message: str,
    *,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        },
    )


def _extract_task_inputs(params: dict) -> tuple[str, str, dict]:
    """Pull (task_id, session_id, message) out of JSON-RPC ``params``.

    Centralised so all four handlers (send / sendSubscribe / get /
    cancel / resubscribe) follow the same defaulting rules: missing
    task_id → fresh UUID4, missing sessionId → reuse task_id, missing
    or non-dict message → empty dict.
    """
    if not isinstance(params, dict):
        params = {}
    task_id = params.get("id") or str(uuid.uuid4())
    session_id = params.get("sessionId") or task_id
    raw_message = params.get("message")
    message = raw_message if isinstance(raw_message, dict) else {}
    return task_id, session_id, message


async def _invoke_user_handler(
    user_handler: Callable[..., Any], message: dict
) -> Any:
    """Call the user handler, awaiting if it returned a coroutine.

    Handler errors propagate to the caller — each tasks/* handler wraps
    this call in its own try/except to translate exceptions into the
    A2A v1.0 ``state=failed`` envelope (or the SSE failed event for
    ``sendSubscribe``).
    """
    import inspect

    result = user_handler(message)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _handle_tasks_send(
    *,
    req_id: Any,
    params: dict,
    user_handler: Callable[..., Any],
    metadata: dict,
) -> JSONResponse:
    """Phase 2 / 2-leftover ``tasks/send`` dispatch.

    Calls the user's ``@mesh.a2a`` handler with the A2A ``message`` dict
    as the positional payload. Dependency injection (e.g. ``date_service``,
    ``MeshJob`` submitters) is wired by the decorator wrapper.

    Sync vs long-running detection: introspect the *return value*, not
    the metadata. If the handler returned a ``mcp_mesh_core.JobProxy``
    instance, the user submitted a mesh job via ``MeshJob.submit(...)``
    → store the proxy and respond with ``state=working``. Otherwise the
    return value is the synchronous result → wrap as ``state=completed``.

    Detecting via return value (rather than the local-only
    ``_underlying_tool_is_task`` helper) is the canonical pattern because
    it works for cross-agent ``task=True`` deps too — the helper can't
    see remote tool metadata, but the JobProxy class membership is
    unambiguous.
    """
    task_id, session_id, message = _extract_task_inputs(params)

    try:
        result = await _invoke_user_handler(user_handler, message)
    except Exception as exc:
        # Per A2A v1.0: handler exceptions surface as Task.state=failed,
        # NOT as a JSON-RPC -3260x error.
        logger.warning(
            "A2A tasks/send handler raised on %s: %s",
            metadata.get("path"),
            exc,
        )
        return _jsonrpc_success(
            req_id,
            _build_failed_task(task_id, session_id, message or None, str(exc)),
        )

    if _is_job_proxy(result):
        # Long-running: park the proxy in the task store, return the
        # working envelope. The client polls tasks/get / subscribes via
        # tasks/sendSubscribe / tasks/resubscribe to track progress.
        try:
            _store_task(
                task_id,
                result,
                request_message=message or None,
                session_id=session_id,
            )
        except ValueError as exc:
            return _jsonrpc_error(req_id, -32602, str(exc))
        logger.info(
            "A2A tasks/send: long-running task started "
            "(task_id=%s, mesh_job_id=%s, path=%s)",
            task_id,
            getattr(result, "job_id", "<unknown>"),
            metadata.get("path"),
        )
        return _jsonrpc_success(
            req_id,
            _build_working_task(task_id, session_id, message or None),
        )

    return _jsonrpc_success(
        req_id,
        _build_completed_task(task_id, session_id, message or None, result),
    )


async def _handle_tasks_get(
    *,
    req_id: Any,
    params: dict,
) -> JSONResponse:
    """Look up a long-running A2A task by id and return its current Task envelope.

    The task must have been minted by an earlier ``tasks/send`` /
    ``tasks/sendSubscribe`` call on this process — long-running task
    state is process-local (see ``_A2A_TASK_STORE`` doc for the
    cross-replica caveat).

    Unknown task ids surface as JSON-RPC -32602 (Invalid params) per the
    A2A v1.0 convention — the spec doesn't dedicate an error code to
    "task not found" so we reuse the closest standard code.
    """
    _sweep_terminal_tasks()

    if not isinstance(params, dict):
        params = {}
    task_id = params.get("id")
    if not task_id:
        return _jsonrpc_error(
            req_id, -32602, "Invalid params: 'id' is required for tasks/get"
        )

    entry = _A2A_TASK_STORE.get(task_id)
    if entry is None:
        return _jsonrpc_error(
            req_id, -32602, f"Unknown task id: {task_id}"
        )

    proxy = entry["proxy"]
    try:
        status = await proxy.status()
    except Exception as exc:
        logger.warning(
            "A2A tasks/get: proxy.status() raised for task %s: %s", task_id, exc
        )
        # Surface as a working task with the error in the message — we
        # can't reliably tell from a status() failure whether the underlying
        # job is dead or just transiently unreachable.
        return _jsonrpc_success(
            req_id,
            _build_working_task(
                task_id,
                params.get("sessionId") or task_id,
                None,
                progress_message=f"status unavailable: {exc}",
            ),
        )

    if not isinstance(status, dict):
        status = {}

    mesh_state = status.get("status") or "working"
    if mesh_state in ("completed", "failed", "cancelled"):
        _mark_terminal(task_id)

    # On terminal=completed, fetch the final result via proxy.wait() so the
    # A2A Task envelope carries the result as an artifact[0]. SSE delivers
    # this via TaskArtifactUpdateEvent; non-streaming tasks/get callers
    # need it embedded inline. Use a tight timeout so we don't block on a
    # job that the registry believes is completed but whose payload is
    # transiently unreachable — fall back to no artifact in that case.
    final_result: Any = None
    has_final_result = False
    if mesh_state == "completed":
        try:
            final_result = await proxy.wait(timeout_secs=1)
            has_final_result = True
        except Exception as exc:
            logger.debug(
                "A2A tasks/get: proxy.wait() failed for completed task %s: %s",
                task_id,
                exc,
            )

    # Echo the original request_message in the A2A history field if we
    # captured it at submit time (otherwise empty per existing behavior).
    envelope = _build_task_from_status(
        task_id,
        entry.get("session_id") or params.get("sessionId") or task_id,
        entry.get("request_message"),
        status,
        final_result=final_result,
        has_final_result=has_final_result,
    )
    return _jsonrpc_success(req_id, envelope)


async def _handle_tasks_cancel(
    *,
    req_id: Any,
    params: dict,
) -> JSONResponse:
    """Cancel a long-running A2A task via its underlying mesh ``JobProxy``.

    Best-effort: cancel exceptions are logged and swallowed because the
    registry may have already terminated the job (e.g., it just finished
    on the producer side). We always re-fetch ``proxy.status()`` after
    the cancel attempt so the response reflects the latest state the
    client should trust.
    """
    _sweep_terminal_tasks()

    if not isinstance(params, dict):
        params = {}
    task_id = params.get("id")
    if not task_id:
        return _jsonrpc_error(
            req_id, -32602, "Invalid params: 'id' is required for tasks/cancel"
        )

    entry = _A2A_TASK_STORE.get(task_id)
    if entry is None:
        return _jsonrpc_error(
            req_id, -32602, f"Unknown task id: {task_id}"
        )

    proxy = entry["proxy"]
    reason = params.get("reason")
    try:
        await proxy.cancel(reason=reason) if reason is not None else await proxy.cancel()
    except Exception as exc:
        logger.info(
            "A2A tasks/cancel: proxy.cancel() raised for task %s "
            "(may already be terminal): %s",
            task_id,
            exc,
        )

    try:
        status = await proxy.status()
    except Exception as exc:
        logger.warning(
            "A2A tasks/cancel: proxy.status() raised post-cancel for task %s: %s",
            task_id,
            exc,
        )
        status = {"status": "cancelled"}

    if not isinstance(status, dict):
        status = {"status": "cancelled"}

    mesh_state = status.get("status") or "cancelled"
    if mesh_state in ("completed", "failed", "cancelled"):
        _mark_terminal(task_id)

    envelope = _build_task_from_status(
        task_id,
        entry.get("session_id") or task_id,
        entry.get("request_message"),
        status,
    )
    return _jsonrpc_success(req_id, envelope)


# ---------------------------------------------------------------------------
# Phase 3 — SSE streaming (tasks/sendSubscribe + tasks/resubscribe)
# ---------------------------------------------------------------------------

# Headers we attach to every SSE response. ``X-Accel-Buffering: no``
# tells nginx not to buffer the stream; ``Cache-Control: no-cache``
# stops intermediaries from caching mid-flight events; keep-alive lets
# clients hold the connection open across keepalives.
_A2A_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# Polling cadence for the long-running SSE generator. One second is
# fast enough for a human-perceptible "this is making progress" feel
# without hammering the registry. The keepalive interval guards against
# proxy-layer idle timeouts (most defaults are 30-60s).
_SSE_POLL_INTERVAL_SECS = 1.0
_SSE_KEEPALIVE_SECS = 15.0


def _sse_event(payload: dict) -> str:
    """Format a JSON payload as one SSE ``data:`` frame.

    SSE frames are terminated by a blank line (``\\n\\n``); the JSON
    body goes after a single ``data: `` prefix. We do NOT split across
    multiple ``data:`` lines because the A2A v1.0 events are compact
    JSON (one object per frame).
    """
    return f"data: {_json.dumps(payload, default=str)}\n\n"


def _status_update_event(
    req_id: Any,
    task_id: str,
    a2a_state: str,
    message_text: Optional[str],
    *,
    final: bool,
    progress: Optional[Any] = None,
) -> dict:
    """Build an A2A v1.0 ``TaskStatusUpdateEvent`` wrapped in a JSON-RPC envelope.

    The ``final`` flag tells the client this is the terminal event for
    the task — the client closes its SSE connection on ``final=True``.
    """
    status: dict = {"state": a2a_state, "timestamp": _utc_now_iso()}
    if message_text:
        status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": str(message_text)}],
        }
    result: dict = {
        "id": task_id,
        "status": status,
        "final": final,
    }
    if progress is not None:
        result["metadata"] = {"progress": progress}
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _artifact_update_event(req_id: Any, task_id: str, value: Any) -> dict:
    """Build an A2A v1.0 ``TaskArtifactUpdateEvent`` wrapped in JSON-RPC.

    ``value`` is whatever ``proxy.wait()`` returned for the underlying
    job. Strings ride verbatim in the text part; everything else gets
    JSON-stringified so the part stays string-typed per the v1.0
    ``TextPart`` shape.
    """
    text = value if isinstance(value, str) else _json.dumps(value, default=str)
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "id": task_id,
            "artifact": {
                "name": "result",
                "parts": [{"type": "text", "text": text}],
                "index": 0,
            },
        },
    }


async def _stream_completed_only(
    req_id: Any, task_id: str, _session_id: str, _message: dict, value: Any
) -> AsyncIterator[str]:
    """SSE stream for a sync handler return: emit one terminal event + done.

    Used when ``tasks/sendSubscribe`` runs against a sync handler. We
    fold the handler's return value into a single artifact event and
    follow it with a final status event so the client sees both the
    payload and the explicit completion signal before the stream closes.
    """
    yield _sse_event(_artifact_update_event(req_id, task_id, value))
    yield _sse_event(
        _status_update_event(req_id, task_id, "completed", None, final=True)
    )


async def _stream_failed_only(
    req_id: Any, task_id: str, _session_id: str, _message: dict, error: str
) -> AsyncIterator[str]:
    """SSE stream for a handler that raised: emit one terminal failed event.

    Mirrors the JSON-RPC ``state=failed`` envelope but as a single SSE
    frame followed by stream close. No artifact event because there's
    no result payload to carry.
    """
    yield _sse_event(
        _status_update_event(req_id, task_id, "failed", error, final=True)
    )


async def _stream_long_running(
    req_id: Any, task_id: str, _session_id: str, _message: dict, proxy: Any
) -> AsyncIterator[str]:
    """SSE stream for a JobProxy: emit working → progress → terminal events.

    Loop invariants:
      1. Always emit an initial ``state=working`` event so the client
         confirms the subscription is live before any polling latency.
      2. Emit a status-update only when ``progress`` or
         ``progress_message`` actually changed — natural backpressure
         that drops redundant events without an explicit queue.
      3. Emit an SSE comment (``: keepalive\\n\\n``) every
         ``_SSE_KEEPALIVE_SECS`` of inactivity to defeat proxy-layer
         idle timeouts. Comments are ignored by SSE parsers.
      4. On terminal state, attempt ``proxy.wait()`` for the result and
         emit it as an artifact event, then the final status event,
         then exit.
      5. On client disconnect (``CancelledError`` raised mid-yield), do
         NOT call ``proxy.cancel()`` — the A2A spec is explicit that
         disconnect is a transient condition and the underlying job
         keeps running. The client may rejoin via ``tasks/resubscribe``.
    """
    # Initial event so the client sees an immediate "subscribed" signal
    # before the first poll. Seed last_progress/last_message to ``None``
    # so the first poll only re-emits if the registry actually reported
    # *real* progress — otherwise the immediate "still working with no
    # progress" status would emit a redundant duplicate of this initial
    # event.
    yield _sse_event(
        _status_update_event(req_id, task_id, "working", None, final=False)
    )

    last_progress: Any = None
    last_message: Any = None
    last_event_time = time.monotonic()

    try:
        while True:
            try:
                status = await proxy.status()
            except Exception as exc:
                logger.warning(
                    "A2A SSE poll: proxy.status() raised for task %s: %s",
                    task_id,
                    exc,
                )
                yield _sse_event(
                    _status_update_event(
                        req_id, task_id, "failed", f"status unavailable: {exc}",
                        final=True,
                    )
                )
                _mark_terminal(task_id)
                return

            if not isinstance(status, dict):
                status = {}

            mesh_state = status.get("status") or "working"

            if mesh_state in ("completed", "failed", "cancelled"):
                # Emit artifact + final status, then exit. ``proxy.wait()``
                # returns the result for completed jobs; for failed/cancelled
                # it raises — we surface the error text in the status message.
                if mesh_state == "completed":
                    try:
                        result = await proxy.wait(timeout_secs=1)
                        yield _sse_event(
                            _artifact_update_event(req_id, task_id, result)
                        )
                    except Exception as exc:
                        logger.debug(
                            "A2A SSE poll: proxy.wait() raised on completed "
                            "task %s: %s",
                            task_id,
                            exc,
                        )
                final_msg = None
                if mesh_state == "failed":
                    final_msg = status.get("error") or status.get("progress_message")
                elif mesh_state == "cancelled":
                    final_msg = status.get("progress_message")
                yield _sse_event(
                    _status_update_event(
                        req_id,
                        task_id,
                        _map_mesh_state(mesh_state),
                        final_msg,
                        final=True,
                    )
                )
                _mark_terminal(task_id)
                return

            progress = status.get("progress")
            progress_message = status.get("progress_message")
            now = time.monotonic()

            if progress != last_progress or progress_message != last_message:
                yield _sse_event(
                    _status_update_event(
                        req_id,
                        task_id,
                        "working",
                        progress_message,
                        final=False,
                        progress=progress,
                    )
                )
                last_progress = progress
                last_message = progress_message
                last_event_time = now
            elif (now - last_event_time) > _SSE_KEEPALIVE_SECS:
                # No state change in a while — emit an SSE comment to
                # keep intermediaries from idling the connection out.
                # SSE comments start with ``:`` and are ignored by
                # parsers but reset the proxy's keepalive timer.
                yield ": keepalive\n\n"
                last_event_time = now

            await asyncio.sleep(_SSE_POLL_INTERVAL_SECS)
    except asyncio.CancelledError:
        # Client disconnected. Per A2A v1.0 this MUST NOT cancel the
        # underlying mesh job — the client may rejoin via tasks/resubscribe.
        logger.debug(
            "A2A SSE poll: client disconnected for task %s; "
            "underlying mesh job continues",
            task_id,
        )
        raise


def _sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    """Wrap an async generator of SSE frames in a ``StreamingResponse``.

    ``media_type="text/event-stream"`` is the SSE content type per
    HTML5; the headers defeat common proxy/CDN buffering that would
    otherwise break streaming end-to-end.
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers=_A2A_SSE_HEADERS,
    )


async def _handle_tasks_send_subscribe(
    *,
    req_id: Any,
    params: dict,
    user_handler: Callable[..., Any],
    metadata: dict,
) -> Any:
    """Phase 3 ``tasks/sendSubscribe`` dispatch — same as send, SSE response.

    The user handler runs to completion (or raises) BEFORE the SSE
    stream opens, so the framework knows whether to spin up the long-
    running poll loop or just emit a single completed event. Doing the
    handler invocation eagerly (rather than inside the generator) keeps
    handler exceptions out of the streaming codepath where they'd be
    invisible to the FastAPI exception handler chain.
    """
    task_id, session_id, message = _extract_task_inputs(params)

    try:
        result = await _invoke_user_handler(user_handler, message)
    except Exception as exc:
        logger.warning(
            "A2A tasks/sendSubscribe handler raised on %s: %s",
            metadata.get("path"),
            exc,
        )
        return _sse_response(
            _stream_failed_only(req_id, task_id, session_id, message, str(exc))
        )

    if _is_job_proxy(result):
        try:
            _store_task(
                task_id,
                result,
                request_message=message,
                session_id=session_id,
            )
        except ValueError as exc:
            # Duplicate task_id — surface as a single SSE failed event
            # so the SSE client sees a structured A2A failure rather
            # than an opaque HTTP error.
            return _sse_response(
                _stream_failed_only(req_id, task_id, session_id, message, str(exc))
            )
        logger.info(
            "A2A tasks/sendSubscribe: long-running stream started "
            "(task_id=%s, mesh_job_id=%s, path=%s)",
            task_id,
            getattr(result, "job_id", "<unknown>"),
            metadata.get("path"),
        )
        return _sse_response(
            _stream_long_running(req_id, task_id, session_id, message, result)
        )

    return _sse_response(
        _stream_completed_only(req_id, task_id, session_id, message, result)
    )


async def _handle_tasks_resubscribe(
    *,
    req_id: Any,
    params: dict,
) -> Any:
    """Re-attach an SSE stream to an existing long-running task.

    Idempotent: returns the same poll-loop generator as the original
    ``tasks/sendSubscribe`` call would. The client re-receives the
    initial ``working`` event, then catches up to live progress from
    the registry's current view (we don't replay old events because
    we don't store them — clients that need replay should rely on
    ``tasks/get`` for the current snapshot).
    """
    _sweep_terminal_tasks()

    if not isinstance(params, dict):
        params = {}
    task_id = params.get("id")
    if not task_id:
        return _jsonrpc_error(
            req_id, -32602, "Invalid params: 'id' is required for tasks/resubscribe"
        )

    entry = _A2A_TASK_STORE.get(task_id)
    if entry is None:
        return _jsonrpc_error(
            req_id, -32602, f"Unknown task id: {task_id}"
        )

    proxy = entry["proxy"]
    return _sse_response(
        _stream_long_running(req_id, task_id, task_id, {}, proxy)
    )


def _make_rpc_endpoint(*, metadata: dict, user_handler: Callable[..., Any]):
    """Build a FastAPI endpoint coroutine for the JSON-RPC entry point.

    Dispatch table:
      - ``tasks/send`` → sync result (state=completed) OR JobProxy
        return (state=working, parked in ``_A2A_TASK_STORE``).
      - ``tasks/get`` → look up parked task, return current Task envelope.
      - ``tasks/cancel`` → call ``proxy.cancel()``, return updated Task.
      - ``tasks/sendSubscribe`` → same dispatch as ``tasks/send`` but
        the response is an SSE stream of ``TaskStatusUpdateEvent`` /
        ``TaskArtifactUpdateEvent`` JSON-RPC envelopes.
      - ``tasks/resubscribe`` → re-attach SSE to an existing parked task.
      - Anything else → JSON-RPC -32601 ``Method not implemented``.

    Honours the decorator's ``auth="bearer"`` setting at the header-
    presence level only — token validation (signature/issuer/audience)
    is Phase-2+ scope.
    """
    bearer_auth = metadata.get("auth") == "bearer"

    async def jsonrpc_entry(request: Request) -> JSONResponse:
        if bearer_auth:
            authz = request.headers.get("authorization") or ""
            if not authz.lower().startswith("bearer "):
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": (
                                "Authentication required: missing "
                                "Authorization: Bearer <token> header"
                            ),
                        },
                        "id": None,
                    },
                )
            # Reject "Bearer " (or "Bearer ...empty/whitespace token...") —
            # accepting a prefix-only header would let any client past the
            # auth gate without supplying a real token.
            parts = authz.split(" ", 1)
            if len(parts) != 2 or not parts[1].strip():
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": (
                                "Authentication required: empty bearer token "
                                "in Authorization header"
                            ),
                        },
                        "id": None,
                    },
                )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32700,
                        "message": "Parse error: request body is not valid JSON",
                    },
                    "id": None,
                },
            )

        req_id = None
        method = None
        params: dict = {}
        if isinstance(body, dict):
            req_id = body.get("id")
            method = body.get("method")
            raw_params = body.get("params")
            if isinstance(raw_params, dict):
                params = raw_params

        if method == "tasks/send":
            return await _handle_tasks_send(
                req_id=req_id,
                params=params,
                user_handler=user_handler,
                metadata=metadata,
            )

        if method == "tasks/get":
            return await _handle_tasks_get(req_id=req_id, params=params)

        if method == "tasks/cancel":
            return await _handle_tasks_cancel(req_id=req_id, params=params)

        if method == "tasks/sendSubscribe":
            return await _handle_tasks_send_subscribe(
                req_id=req_id,
                params=params,
                user_handler=user_handler,
                metadata=metadata,
            )

        if method == "tasks/resubscribe":
            return await _handle_tasks_resubscribe(req_id=req_id, params=params)

        return _jsonrpc_error(
            req_id,
            -32601,
            (
                f"Method not implemented: {method!r}. "
                "Supported A2A v1.0 methods: tasks/send, tasks/get, "
                "tasks/cancel, tasks/sendSubscribe, tasks/resubscribe."
            ),
        )

    return jsonrpc_entry


def mount(
    app: FastAPI,
    *,
    path: str,
    dependencies: Optional[list] = None,
    description: Optional[str] = None,
    skill_id: Optional[str] = None,
    skill_name: Optional[str] = None,
    input_modes: Optional[list] = None,
    output_modes: Optional[list] = None,
    tags: Optional[list] = None,
    auth: Optional[str] = None,
    **kwargs: Any,
) -> Callable[[Callable], Callable]:
    """Mount an A2A surface on the user's FastAPI ``app``.

    Mirrors the ``@mesh.route`` UX: the user owns the FastAPI app,
    this helper applies ``@mesh.a2a`` (DI + metadata stamping) AND
    registers the two routes A2A v1.0 requires:

      * ``GET  {path}/.well-known/agent.json`` — agent card
      * ``POST {path}``                        — JSON-RPC tasks/* entry

    Phase 1 returns ``Method not implemented`` for every ``tasks/*``
    JSON-RPC method; Phase 2 wires actual task routing.

    Args:
        app: User-owned ``FastAPI`` application instance.
        path: REQUIRED URL path prefix for this surface (must start
            with ``/``), e.g. ``/agents/report-generator``. The
            registry concatenates ``MCP_MESH_PUBLIC_URL_PREFIX`` with
            this path to compute the public FQDN stamped on the card.
        dependencies: Optional list of mesh capabilities to inject
            (same shape as ``@mesh.tool`` deps). For v1, typically a
            single capability — the user's handler may declare more
            but multi-skill grouping in a single card is v2 scope.
        description: Free-form skill description shown on the agent
            card. Defaults to the function's docstring when not set.
        skill_id: A2A skill identifier (kebab-case canonical). When
            unset, derived from the path's last segment.
        skill_name: Human-readable skill name. When unset, derived
            from ``skill_id`` (TitleCase).
        input_modes: A2A inputModes (default ``["application/json"]``).
        output_modes: A2A outputModes (default ``["application/json"]``).
        tags: Skill tags surfaced on the agent card.
        auth: Authentication scheme. v1 accepts ``"bearer"`` or ``None``
            (no auth). Anything else raises ``ValueError`` —  broader
            schemes (SPIRE/mTLS/OAuth) land in v2.
        **kwargs: Additional metadata stamped onto the surface.

    Returns:
        A decorator that:
          1. Applies ``@mesh.a2a(...)`` to the user's handler function
             (DI + metadata stamping).
          2. Mounts the agent-card and JSON-RPC routes on ``app``.
          3. Returns the wrapped function so the user's variable points
             to a usable callable (e.g., for direct unit tests).

    Example:
        from fastapi import FastAPI
        import mesh
        from mesh.types import McpMeshTool

        app = FastAPI()

        @mesh.a2a.mount(
            app,
            path="/agents/date",
            dependencies=["date_service"],
        )
        async def date_a2a(payload: dict, date_service: McpMeshTool = None):
            return await date_service()
    """
    if not isinstance(app, FastAPI):
        raise ValueError(
            "mesh.a2a.mount requires a FastAPI app instance as the first argument"
        )

    # Reject duplicate mounts on the same (app, path) pair — silently
    # accepting the second call would add another `mesh_a2a` entry to the
    # DecoratorRegistry (heartbeat reports 2 surfaces) while only one
    # endpoint stays reachable, since route registration short-circuits
    # on path collision below.
    #
    # NOTE: do NOT add ``dup_key`` to ``_MOUNTED_A2A_PATHS`` here — if any
    # validation or route registration in the inner ``decorator`` raises,
    # the key would leak and block legitimate retries on the same path.
    # Add it on the success path at the end of ``decorator`` instead.
    dup_key = (id(app), (path or "").rstrip("/") or "/")
    if dup_key in _MOUNTED_A2A_PATHS:
        raise ValueError(
            f"mesh.a2a.mount: path {dup_key[1]!r} is already mounted on this "
            "FastAPI app. A2A surfaces must have unique paths per app."
        )

    # Late-bind the decorator import to avoid circular import at module load.
    from .decorators import a2a as a2a_decorator

    def decorator(target: Callable) -> Callable:
        # Apply @mesh.a2a(...) for DI + metadata stamping. The decorator
        # registers the surface in DecoratorRegistry under "mesh_a2a" so
        # heartbeat preparation picks it up and emits agent_type=a2a.
        wrapped = a2a_decorator(
            path=path,
            description=description,
            dependencies=dependencies,
            skill_id=skill_id,
            skill_name=skill_name,
            input_modes=input_modes,
            output_modes=output_modes,
            tags=tags,
            auth=auth,
            **kwargs,
        )(target)

        # The decorator stamps the (possibly-derived) final metadata on
        # the wrapper. Use that as the source of truth for the routes.
        metadata = getattr(wrapped, "_mesh_a2a_metadata", None)
        if metadata is None:
            # The DI wrapper failed and we got the raw target back;
            # pull metadata directly from the target.
            metadata = getattr(target, "_mesh_a2a_metadata", None)
        if metadata is None:
            # Nothing to mount — decorator failed catastrophically. Log
            # and return the (un)wrapped function so the caller's import
            # doesn't blow up.
            logger.error(
                "mesh.a2a.mount: @mesh.a2a metadata missing on %s; "
                "skipping route registration",
                getattr(target, "__name__", target),
            )
            return wrapped

        skill_id_resolved = metadata["skill_id"]
        path_resolved = metadata["path"]

        card_path = path_resolved.rstrip("/") + "/.well-known/agent.json"
        rpc_path = path_resolved.rstrip("/") or "/"

        # Map existing paths to their endpoint callables so we can
        # distinguish a legitimate idempotent re-mount (same endpoint
        # function — typical in test fixtures that call ``mount()``
        # multiple times against a fresh ``_MOUNTED_A2A_PATHS``) from a
        # foreign route hijacking the path. Silently skipping on path
        # collision would let a hostile/typo'd route own ``card_path`` /
        # ``rpc_path`` while heartbeat still advertises the surface for
        # this agent — clients would then call the wrong handler.
        existing_endpoints: dict = {}
        for r in app.router.routes:
            r_path = getattr(r, "path", None)
            if r_path is not None:
                existing_endpoints[r_path] = getattr(r, "endpoint", None)

        card_endpoint = _make_card_endpoint(
            metadata=metadata,
            agent_config_provider=_resolve_agent_config,
        )
        rpc_endpoint = _make_rpc_endpoint(metadata=metadata, user_handler=wrapped)

        added_paths: list = []
        if card_path not in existing_endpoints:
            app.add_api_route(
                path=card_path,
                endpoint=card_endpoint,
                methods=["GET"],
                tags=["a2a"],
                summary=f"A2A AgentCard for skill '{skill_id_resolved}'",
            )
            added_paths.append(card_path)
            logger.debug(
                "Mounted A2A card route GET %s (skill=%s)",
                card_path, skill_id_resolved,
            )
        elif existing_endpoints[card_path] is card_endpoint:
            # Identical callable already wired (e.g., test fixture re-mount
            # after wiping ``_MOUNTED_A2A_PATHS``) — safe to skip.
            logger.debug(
                "A2A card route %s already registered with identical endpoint; skipping",
                card_path,
            )
        else:
            raise RuntimeError(
                f"mesh.a2a.mount: cannot mount A2A card route at {card_path!r} — "
                "the path is already registered with a different endpoint. "
                "Refusing to silently let a foreign route own this path while "
                "the agent's heartbeat advertises it as an A2A surface."
            )

        if rpc_path not in existing_endpoints:
            app.add_api_route(
                path=rpc_path,
                endpoint=rpc_endpoint,
                methods=["POST"],
                tags=["a2a"],
                summary=f"A2A JSON-RPC entry point for skill '{skill_id_resolved}'",
            )
            added_paths.append(rpc_path)
            logger.debug(
                "Mounted A2A RPC route POST %s (skill=%s)",
                rpc_path, skill_id_resolved,
            )
        elif existing_endpoints[rpc_path] is rpc_endpoint:
            logger.debug(
                "A2A RPC route %s already registered with identical endpoint; skipping",
                rpc_path,
            )
        else:
            raise RuntimeError(
                f"mesh.a2a.mount: cannot mount A2A JSON-RPC route at {rpc_path!r} — "
                "the path is already registered with a different endpoint. "
                "Refusing to silently let a foreign route own this path while "
                "the agent's heartbeat advertises it as an A2A surface."
            )

        # Move the newly-added routes to the FRONT of the router so the
        # FastMCP catch-all (mounted at "" by FastAPIServerSetupStep)
        # doesn't shadow them. Mirrors jobs_cancel_route.py #bug 4.
        # Starlette resolves routes in registration order and Mount("")
        # matches every path — explicit routes added AFTER the mount
        # would yield 404 without this re-ordering.
        if added_paths:
            head: list = []
            rest: list = []
            for r in app.router.routes:
                if getattr(r, "path", None) in added_paths:
                    head.append(r)
                else:
                    rest.append(r)
            app.router.routes[:] = head + rest

        logger.info(
            "🌐 Mounted A2A surface: %s (skill=%s, %d route(s))",
            path_resolved, skill_id_resolved, len(added_paths),
        )

        # Validation + route registration succeeded — only NOW record the
        # (app, path) pair so a future re-mount on the same pair raises.
        # Adding before this point would leak the key on validation
        # failures and block legitimate retries.
        _MOUNTED_A2A_PATHS.add(dup_key)
        return wrapped

    return decorator
