"""Consumer-side ``MeshJob`` submitter (Phase 1 — MeshJob substrate).

When a consumer tool declares a parameter annotated ``MeshJob`` whose name
matches a declared dependency capability, the runtime injects an instance
of :class:`MeshJobSubmitter` into that slot. The user calls
``await submitter.submit(...)`` to enqueue work on the remote producer
and gets back a :class:`mcp_mesh_core.JobProxy` to await/poll/cancel.

This is a thin Python wrapper around :func:`mcp_mesh_core.submit_job` —
it carries the per-binding context (capability + submitted_by +
registry_url) so the user only supplies the call payload + per-submission
knobs (``max_duration``, ``max_retries``, ``total_deadline``).

Per the design's "decouple resolver from capability metadata" decision:
this class does NOT verify that the target capability is registered with
``task=True`` — the registry rejects ``submit_job`` against a
non-task capability with a clear error, and that error surfaces to the
caller verbatim. Doing the check here would require pulling capability
metadata into the DDDI resolver (which currently knows only types).

Resilience: ``submit`` retries on transient registry errors (network
drops, 5xx, 503) up to a small bounded number of attempts. 4xx /
serialisation / NotFound errors propagate immediately — those won't
self-heal so retrying just delays the user-facing failure.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transient-error retry helper
# ---------------------------------------------------------------------------
#
# Rust exposes JobError to Python only as RuntimeError(message), so we
# fall back to substring checks against the error string. The Rust side
# emits messages like:
#   "backend error: network error: <reqwest::Error>"
#   "backend error: backend unavailable: <body>"
#   "backend error: server error (HTTP 502): <body>"
#   "backend error: backend error: HTTP 400: <body>"   (4xx, NOT transient)
#   "backend error: job not found: <id>"               (404, NOT transient)
#   "backend error: conflict: <reason>"                (409, NOT transient)
# We classify by these stable substrings.

_SUBMIT_MAX_ATTEMPTS = 3
# Backoff per attempt (seconds): 200ms, 1s, 5s. Last slot unused (we
# only sleep BETWEEN attempts so N-1 entries are consulted).
_SUBMIT_BACKOFF_SECS = (0.2, 1.0, 5.0)


def _is_transient_submit_error(exc: BaseException) -> bool:
    """Heuristic: does this RuntimeError represent a transient registry
    failure that's worth retrying? Errs on the side of NOT retrying when
    the signal is ambiguous — submit failures are user-facing and a
    fast clear failure beats a slow flaky one."""
    msg = str(exc).lower()
    # Definite transients (Rust BackendError::is_transient == true).
    if "network error" in msg:
        return True
    if "backend unavailable" in msg:
        return True
    if "server error (http 5" in msg:
        return True
    # Defensively don't retry on 4xx / NotFound / Conflict / serialisation.
    return False


class MeshJobSubmitter:
    """Per-binding submit handle for a ``MeshJob``-typed dependency.

    Constructed by the dependency injector at call time, one per
    (consumer-function, dependency-capability) pair.

    Attributes:
        capability: The remote capability this submitter targets (matches
            the dependency declaration on the consumer's ``@mesh.tool``).
        submitted_by: Identifier written to the registry's
            ``submitted_by`` column. Defaults to the running agent's
            instance id, so the registry can correlate this submission
            with the calling agent.
        registry_url: Base URL of the mesh registry. Reused for every
            submission via this submitter.
    """

    def __init__(
        self,
        capability: str,
        submitted_by: str,
        registry_url: str,
    ) -> None:
        self.capability = capability
        self.submitted_by = submitted_by
        self.registry_url = registry_url

    def __repr__(self) -> str:  # pragma: no cover - diagnostic
        return (
            f"MeshJobSubmitter(capability={self.capability!r}, "
            f"submitted_by={self.submitted_by!r})"
        )

    async def submit(
        self,
        *,
        max_duration: Optional[int] = None,
        max_retries: Optional[int] = None,
        total_deadline: Optional[datetime] = None,
        **payload: Any,
    ) -> Any:
        """Submit a new job on the bound capability and return a
        :class:`mcp_mesh_core.JobProxy`.

        Args:
            max_duration: Per-attempt soft timeout (seconds). ``None`` ≡
                registry default (300s, see design doc).
            max_retries: Maximum retries on failure. ``None`` ≡ registry
                default (1 attempt — no retry).
            total_deadline: Absolute wall-clock deadline across all
                retries. ``None`` ≡ unlimited (per "Resolved Decisions"
                in design doc). When supplied, converted to a Unix-epoch
                integer for the registry.
            **payload: User-supplied call arguments — passed verbatim
                as ``submitted_payload`` on the new job row. Must be
                JSON-serialisable (MCP tool results / args are JSON by
                spec).

        Returns:
            :class:`mcp_mesh_core.JobProxy` bound to the new job's id.
            Use ``await proxy.wait(timeout_secs=...)`` to await
            terminal status, or ``await proxy.status()`` for a single
            registry read.

        Raises:
            RuntimeError: If the registry rejects the submission (e.g.
                target capability isn't registered with ``task=True``,
                or the registry is unreachable). The underlying error
                message is propagated for diagnosability.
        """
        # Lazy import: keeps the SDK importable in test environments
        # where the native mcp_mesh_core extension isn't available.
        try:
            from mcp_mesh_core import submit_job
        except Exception as e:
            raise RuntimeError(
                f"MeshJobSubmitter.submit: mcp_mesh_core.submit_job "
                f"unavailable ({e}); cannot submit job to capability "
                f"{self.capability!r}"
            ) from e

        # Normalise total_deadline → Unix epoch int (the schema column is
        # INTEGER per MESHJOB_DESIGN.org "Schema").
        total_deadline_epoch: Optional[int] = None
        if total_deadline is not None:
            try:
                total_deadline_epoch = int(total_deadline.timestamp())
            except Exception as e:
                raise ValueError(
                    f"MeshJobSubmitter.submit: total_deadline must be a "
                    f"datetime (got {type(total_deadline).__name__}): {e}"
                ) from e

        logger.debug(
            "MeshJobSubmitter.submit: capability=%s submitted_by=%s "
            "max_duration=%s max_retries=%s payload_keys=%s",
            self.capability,
            self.submitted_by,
            max_duration,
            max_retries,
            list(payload.keys()),
        )

        # Bounded retry on transient registry errors (network blips, 5xx,
        # 503). 4xx / NotFound / Conflict propagate immediately — they
        # won't self-heal in 5 seconds. Submit failures are user-facing
        # so we keep the window small (3 attempts, max ~6.2s total).
        last_exc: Optional[BaseException] = None
        for attempt in range(1, _SUBMIT_MAX_ATTEMPTS + 1):
            try:
                proxy = await submit_job(
                    self.registry_url,
                    self.capability,
                    payload,
                    self.submitted_by,
                    None,  # owner_instance_id — let the registry pull-claim assign it
                    max_duration,
                    max_retries,
                    total_deadline_epoch,
                )
                if attempt > 1:
                    logger.info(
                        "MeshJobSubmitter.submit recovered on attempt %d "
                        "(capability=%s)",
                        attempt,
                        self.capability,
                    )
                return proxy
            except RuntimeError as e:
                last_exc = e
                if not _is_transient_submit_error(e):
                    # 4xx / NotFound / Conflict / serialisation — fail fast.
                    raise
                if attempt >= _SUBMIT_MAX_ATTEMPTS:
                    logger.warning(
                        "MeshJobSubmitter.submit giving up after %d attempts "
                        "(capability=%s, last_err=%s)",
                        attempt,
                        self.capability,
                        e,
                    )
                    raise
                # Backoff index uses attempt-1 (so attempt 1 sleeps 0.2s).
                backoff = _SUBMIT_BACKOFF_SECS[
                    min(attempt - 1, len(_SUBMIT_BACKOFF_SECS) - 1)
                ]
                logger.info(
                    "MeshJobSubmitter.submit transient failure on attempt %d "
                    "(capability=%s, err=%s); retrying in %.2fs",
                    attempt,
                    self.capability,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
        # Defensive — unreachable: we either return a proxy or raise above.
        assert last_exc is not None
        raise last_exc
