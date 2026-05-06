"""Inbound MeshJob dispatch wrapper (Phase 1 — MeshJob substrate).

This module wires the producer-side dispatch path: when a tool decorated
with ``@mesh.tool(task=True)`` receives an inbound ``tools/call`` bearing
``X-Mesh-Job-Id``, the wrapper:

1. Reads ``X-Mesh-Job-Id`` and (optionally) ``X-Mesh-Timeout`` from the
   active propagated-headers contextvar (populated by the FastMCP session
   middleware in ``http_wrapper.py``).
2. Builds a :class:`mcp_mesh_core.JobController` bound to that job id and
   the running agent's instance id.
3. Sets both the Python :data:`CURRENT_JOB` contextvar and (via
   :func:`mcp_mesh_core.with_job_async`) the Rust core's
   ``job_context::CURRENT_JOB`` task-local, plus the cancel-registry
   entry under the job id.
4. Injects the controller into the user function's ``mesh_job_param_name``
   kwarg.
5. Awaits the user function inside both contexts.
6. Cleans up both contexts on exit (including the panic / exception path).

Tools without ``task=True`` are bypassed entirely (zero overhead). Tools
with ``task=True`` invoked WITHOUT ``X-Mesh-Job-Id`` (a regular synchronous
``tools/call``) fall through to the user function with ``None`` in the
MeshJob slot — per :file:`MESHJOB_DDDI_CONTRACT.md` "Tool invocation: when
``MeshJob`` is present but the call is NOT a job".

The dispatch logic is centralised here so the per-decorator wrapper
created by :func:`_mcp_mesh.engine.dependency_injector.create_injection_wrapper`
can call into it without re-implementing the contract.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Optional

from .job_context import CURRENT_JOB, JobContextSnapshot

logger = logging.getLogger(__name__)


# Header names — lowercased to match how the FastMCP middleware stores
# captured inbound headers (via ``str.lower()`` in
# ``http_wrapper.py::MCPSessionRoutingMiddleware.dispatch``).
_HDR_JOB_ID = "x-mesh-job-id"
_HDR_TIMEOUT = "x-mesh-timeout"


def _read_job_headers() -> tuple[Optional[str], Optional[float]]:
    """Pull ``X-Mesh-Job-Id`` / ``X-Mesh-Timeout`` from the propagated-
    headers contextvar populated by the MCP session middleware.

    Returns ``(job_id, deadline_secs_remaining)`` — either may be ``None``.

    Defensive: never raises. If the trace-context module is somehow not
    importable (test harness with stubs), returns ``(None, None)``.
    """
    try:
        from ..tracing.context import TraceContext
    except Exception:
        return None, None

    headers = TraceContext.get_propagated_headers() or {}
    if not headers:
        return None, None

    # Header dict is lowercased by the middleware before storing.
    job_id = headers.get(_HDR_JOB_ID)
    if not job_id:
        return None, None

    timeout_raw = headers.get(_HDR_TIMEOUT)
    deadline_secs: Optional[float] = None
    if timeout_raw:
        try:
            deadline_secs = float(timeout_raw)
            if deadline_secs <= 0:
                deadline_secs = None
        except (TypeError, ValueError):
            logger.debug(
                "job_dispatch: ignoring malformed %s header value %r",
                _HDR_TIMEOUT,
                timeout_raw,
            )
            deadline_secs = None
    return job_id, deadline_secs


def _resolve_runtime_identity() -> tuple[Optional[str], Optional[str]]:
    """Resolve ``(registry_url, instance_id)`` for constructing a
    JobController. Both are needed:

    * ``registry_url`` — the controller flushes terminal deltas (and
      progress, via the batching tick) directly to the registry's
      ``/jobs/batch`` endpoint.
    * ``instance_id`` — written into ``owner_instance_id`` on each delta
      so the registry can correlate this replica with claimed work.

    The ``instance_id`` MUST match the value the claim worker sent on
    ``POST /jobs/claim`` (which uses the pipeline ``agent_id`` from the
    decorator registry); otherwise the registry rejects deltas as
    ``not_owner``. This is centralised in
    :func:`_mcp_mesh.shared.agent_identity.resolve_agent_id` so both
    code paths read from the same source.

    Returns ``(None, None)`` when either piece is missing — the wrapper
    treats that as "job dispatch not available; fall through to a regular
    call". The user function still runs; only the MeshJob slot stays
    ``None``.
    """
    from ..shared.agent_identity import resolve_agent_id

    registry_url = os.environ.get("MCP_MESH_REGISTRY_URL")
    instance_id = resolve_agent_id()
    if not registry_url or not instance_id:
        return None, None
    return registry_url, instance_id


def is_task_tool(func: Any) -> bool:
    """Return ``True`` iff the function is decorated with
    ``@mesh.tool(task=True)``.

    Reads the metadata stamped by the decorator (see
    ``mesh/decorators.py::tool``). Returns ``False`` defensively if the
    metadata is missing — non-task tools must NOT pay the dispatch cost.
    """
    meta = getattr(func, "_mesh_tool_metadata", None)
    if not isinstance(meta, dict):
        # Some wrappers stash metadata on the original function instead.
        original = getattr(func, "_mesh_original_func", None)
        if original is not None:
            meta = getattr(original, "_mesh_tool_metadata", None)
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("task"))


def get_mesh_job_param_name(func: Any) -> Optional[str]:
    """Return the function's ``MeshJob`` parameter name, or ``None`` if
    the function does not declare one.

    Resolves via the DDDI contract analyzer
    (:func:`signature_analyzer.analyze_mesh_job_signature`). Failures
    (forward-ref resolution, missing imports) degrade to ``None`` —
    same defensive posture used elsewhere in the engine.
    """
    try:
        from .signature_analyzer import analyze_mesh_job_signature

        resolution = analyze_mesh_job_signature(func)
        return resolution.mesh_job_param_name
    except Exception as e:
        logger.debug(
            "job_dispatch: analyze_mesh_job_signature failed for %s: %s", func, e
        )
        return None


async def maybe_dispatch_as_job(
    func: Any,
    invoke: Callable[[dict], Awaitable[Any]],
    final_kwargs: dict,
) -> Any:
    """Run ``invoke(kwargs)`` either inside a job context (when an
    inbound ``X-Mesh-Job-Id`` is present and ``func`` is a task tool) or
    directly (otherwise).

    Returns the user function's result verbatim. Never injects job
    semantics into a tool that wasn't decorated ``task=True`` — the
    decorator's intent is the source of truth.

    Args:
        func: The original (or wrapped) user tool function. Used for
            metadata lookups (``task=True`` flag, MeshJob param name) only.
        invoke: A coroutine factory that, given a kwargs dict, returns
            the awaitable invocation of the user function. Wrappers
            already handle DI, tracing, isolation, etc.; this layer just
            wraps the call in a job-context scope.
        final_kwargs: The kwargs dict the wrapper would otherwise pass
            to ``invoke``. The MeshJob param is overlaid on this dict
            when dispatch is active.

    Returns:
        Whatever ``invoke`` returns.
    """
    # Fast bail: not a task tool → no dispatch logic at all (zero overhead).
    if not is_task_tool(func):
        return await invoke(final_kwargs)

    job_id, deadline_secs = _read_job_headers()
    mesh_job_param = get_mesh_job_param_name(func)

    # Ensure the MeshJob param defaults to ``None`` — this is what the
    # contract promises tools that declare ``MeshJob`` but are invoked
    # via a regular tools/call. Done unconditionally so the param is
    # always present in kwargs.
    if mesh_job_param and mesh_job_param not in final_kwargs:
        final_kwargs[mesh_job_param] = None

    if not job_id:
        # task=True tool invoked synchronously (no X-Mesh-Job-Id).
        # Per contract: pass ``None`` in the slot, run as a regular call.
        logger.debug(
            "job_dispatch: %s is task=True but no X-Mesh-Job-Id header; "
            "running as regular tools/call",
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    registry_url, instance_id = _resolve_runtime_identity()
    if not registry_url or not instance_id:
        logger.warning(
            "job_dispatch: %s received X-Mesh-Job-Id=%s but registry_url / "
            "instance_id is not resolvable (need MCP_MESH_REGISTRY_URL plus a "
            "stable agent identity from MCP_MESH_AGENT_ID / decorator registry / "
            "socket.gethostname()); falling back to a regular call",
            getattr(func, "__name__", "?"),
            job_id,
        )
        return await invoke(final_kwargs)

    # Build the controller. Failure here (e.g. unreachable registry at
    # construction time) is logged and downgraded to a regular call so
    # the user function still runs.
    try:
        from mcp_mesh_core import JobController as PyJobController
    except Exception as e:
        logger.warning(
            "job_dispatch: mcp_mesh_core.JobController unavailable (%s); "
            "running %s as a regular call",
            e,
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    try:
        controller = PyJobController(job_id, instance_id, registry_url)
    except Exception as e:
        logger.warning(
            "job_dispatch: failed to construct JobController for job=%s "
            "(%s); running %s as a regular call",
            job_id,
            e,
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    if mesh_job_param:
        final_kwargs[mesh_job_param] = controller

    # Bind the Python contextvar so user code (and the outbound proxy
    # inside this Python process) can observe the active job.
    snap = JobContextSnapshot(
        job_id=job_id, deadline_secs_remaining=deadline_secs
    )
    token = CURRENT_JOB.set(snap)
    try:
        # Bind the Rust task-local + cancel registry entry via the FFI
        # helper. The user function call is passed as a Python awaitable
        # so it executes inside the run_as_job scope on the Rust side.
        try:
            from mcp_mesh_core import with_job_async
        except Exception:
            with_job_async = None  # type: ignore[assignment]

        if with_job_async is not None:
            return await with_job_async(
                job_id, deadline_secs, invoke(final_kwargs)
            )
        else:
            # Defensive fallback: if the FFI helper isn't available
            # (e.g. older mcp-mesh-core .so), still run the user
            # function with the Python contextvar set. Outbound HTTP
            # via the unified proxy reads the Python contextvar
            # directly, so X-Mesh-Job-Id propagation still works for
            # Python-originated downstream calls — only the Rust-core
            # task-local is missing.
            logger.debug(
                "job_dispatch: with_job_async not available; running with "
                "Python contextvar only (Rust task-local will not be set)"
            )
            return await invoke(final_kwargs)
    finally:
        CURRENT_JOB.reset(token)
