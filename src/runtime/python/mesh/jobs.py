"""Public ``mesh.jobs`` submodule — convenience helpers for the MeshJob
event-injection primitive (Phase 1, MeshJob substrate; event-channel
extension landed in v2.2).

The primary surfaces are:

* :func:`post_event` — fire-and-forget helper to push an event into a
  running job by id, without holding a :class:`mcp_mesh_core.JobProxy`
  reference. Intended for MCP tool bodies that receive a ``job_id`` in
  their request payload (e.g. a "submit_user_input" tool exposed by an
  orchestrator agent).

* :class:`JobNotFoundError` / :class:`JobTerminalError` — typed
  ``RuntimeError`` subclasses translated from the Rust core's
  :enum:`JobError` variants. Because pyo3 surfaces all
  :enum:`JobError` variants as ``RuntimeError`` today (see
  ``src/runtime/core/src/jobs_py.rs::job_error_to_py``), we re-classify
  on the Python side via stable error-message substrings.

The :class:`mcp_mesh_core.JobController` / :class:`mcp_mesh_core.JobProxy`
methods (``recv_event`` / ``send_event``) are exposed directly on the
pyo3-bound classes — application code calls them via the
``MeshJob``-typed parameter the framework injects. This module just
adds the helper + error classes around that surface.
"""

from __future__ import annotations

import os
from typing import Any, Optional

__all__ = [
    "JobNotFoundError",
    "JobTerminalError",
    "post_event",
]


# ---------------------------------------------------------------------------
# Typed error classes
# ---------------------------------------------------------------------------
#
# The Rust core's `JobError::JobNotFound` and `JobError::JobTerminal`
# variants currently surface as plain `RuntimeError` from the pyo3 layer
# (see `src/runtime/core/src/jobs_py.rs::job_error_to_py`). Until the
# pyo3 binding switches to a custom exception type, we re-classify on
# the Python side via stable substrings emitted by the Rust error
# `Display` impls — `JobError::Display` in `src/runtime/core/src/jobs.rs`
# is the source of truth. Both classes derive from `RuntimeError` so
# existing `except RuntimeError:` handlers continue to catch them.


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
            "mesh.jobs.post_event: MCP_MESH_REGISTRY_URL is not set; "
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
    try:
        from mcp_mesh_core import JobProxy
    except Exception as e:  # pragma: no cover - extension build issue
        raise RuntimeError(
            f"mesh.jobs.post_event: mcp_mesh_core.JobProxy unavailable "
            f"({e}); cannot construct a transient proxy"
        ) from e

    registry_url = _resolve_registry_url()
    proxy = JobProxy(job_id, registry_url)
    safe_payload: dict = payload if payload is not None else {}
    try:
        return await proxy.send_event(event_type, safe_payload)
    except RuntimeError as exc:
        translated = _translate_job_error(exc)
        if translated is exc:
            raise
        raise translated from exc
