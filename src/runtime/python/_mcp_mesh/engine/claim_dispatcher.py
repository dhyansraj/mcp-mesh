"""Python-side claim dispatcher (Phase 1 — MeshJob substrate).

Per ``MESHJOB_DESIGN.org`` "Architecture / Producer-side flow / Resched":
the registry's HEAD heartbeat may include ``X-Mesh-Pending-Jobs: <n>``
when this agent has unclaimed jobs in capabilities it serves. The
runtime calls ``POST /jobs/claim`` to atomically acquire one job per
round-trip, then dispatches it locally.

Architecture choice for Phase 1
-------------------------------

The Rust core exposes the substrate to do this in-process via
:func:`crate::claim_worker::spawn_claim_worker` + a per-language
``ClaimDispatcher`` trait. Bridging an async Rust trait to a Python
object across PyO3 (with proper ``Send + Sync + 'static`` bounds and an
async return) is non-trivial — the cleanest cross-language design ships
in Phase 2 once we know the per-language contract sticks.

For Phase 1 the dispatcher is implemented purely in Python: a
background ``asyncio.Task`` polls the registry directly via
:func:`mcp_mesh_core.submit_job`'s sibling endpoints (poll-based, not
HEAD-driven). When a claim succeeds, the task constructs a
:class:`mcp_mesh_core.JobController` bound to the claimed job, looks up
the local handler in the :class:`DecoratorRegistry`, and invokes it
through :func:`maybe_dispatch_as_job` — which is the SAME entry point
the inbound HTTP path uses, so the contract (cancel registry, Rust
task-local, Python contextvar) is identical.

Trade-off vs the Rust-driven path:

* No HEAD-hint coalescing (the worker polls on a fixed cadence).
* No per-process semaphore enforcing ``max_concurrent`` — Python's
  asyncio model already serializes per-task; concurrency is bounded
  by ``asyncio.create_task`` calls (at most one per claim cycle).

These limitations are documented; they're acceptable for Phase 1
because the MOST common use case (a single agent owning one task=True
capability with infrequent submissions) sees identical behaviour.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from .job_dispatch import maybe_dispatch_as_job

logger = logging.getLogger(__name__)


# Polling cadence — matches the design's "backoff_min" / "backoff_max"
# from ``crate::claim_worker::ClaimWorkerConfig::new`` so behaviour is
# observably similar across the two implementations.
_POLL_BASE_SECS = 0.5
_POLL_MAX_SECS = 5.0


class PythonClaimDispatcher:
    """Background task that claims pending jobs for a single capability
    and dispatches them to the local handler.

    One instance per (capability, function) pair. The startup pipeline
    spawns one for each ``@mesh.tool(task=True)`` function discovered
    on agent startup.
    """

    def __init__(
        self,
        capability: str,
        instance_id: str,
        registry_url: str,
        handler: Any,
    ) -> None:
        self.capability = capability
        self.instance_id = instance_id
        self.registry_url = registry_url
        # ``handler`` is the wrapped function from the DI injector; it
        # already knows how to inject McpMeshTool deps and handle
        # job-context dispatch via maybe_dispatch_as_job. We just pass
        # the claimed payload as kwargs.
        self.handler = handler
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def _claim_once(self) -> list[dict]:
        """Single ``POST /jobs/claim`` call. Returns the list of claimed
        jobs (each with ``id``, ``submitted_payload``, ``attempt_count``,
        etc.) — empty list when no work is available.

        Wire shape per ``api/mcp-mesh-registry.openapi.yaml`` →
        ``ClaimJobsResponse``: ``{"claimed": [ClaimedJob, ...]}``. Phase 1
        single-claim semantics mean the array is length 0 or 1, but we
        iterate to be future-safe (#bug 3).

        Errors (non-2xx, transport) are logged and treated as "no work"
        so the loop backs off rather than crashing.
        """
        import httpx

        url = f"{self.registry_url.rstrip('/')}/jobs/claim"
        payload = {
            "capability": self.capability,
            "instance_id": self.instance_id,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 204:
                    return []  # no work — registry returns 204 No Content
                if resp.status_code != 200:
                    logger.debug(
                        "claim_dispatcher: unexpected status %s from %s",
                        resp.status_code,
                        url,
                    )
                    return []
                body = resp.json() or {}
                # OpenAPI ClaimJobsResponse: {"claimed": [...]} (required).
                claimed = body.get("claimed") or []
                if not isinstance(claimed, list):
                    logger.debug(
                        "claim_dispatcher: malformed response — 'claimed' "
                        "is not a list: %r",
                        claimed,
                    )
                    return []
                # Filter out entries without an id — defensive against
                # any future schema drift.
                return [c for c in claimed if isinstance(c, dict) and c.get("id")]
        except Exception as e:
            logger.debug("claim_dispatcher: claim_once error %s", e)
            return []

    async def _dispatch(self, claimed: dict) -> None:
        """Run the local handler for a claimed job. Calls
        ``handler(**submitted_payload)`` — the wrapped DI handler reads
        the X-Mesh-Job-Id from headers via the contextvar; for the
        claim path we set the contextvar manually before invoking it.
        """
        job_id = claimed.get("id")
        if not job_id:
            return

        payload = claimed.get("submitted_payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        # Set propagated headers for this task so maybe_dispatch_as_job
        # picks up the job_id (mirrors how the inbound HTTP path delivers
        # it via the FastMCP middleware).
        try:
            from ..tracing.context import TraceContext

            existing = TraceContext.get_propagated_headers() or {}
            merged = dict(existing)
            merged["x-mesh-job-id"] = job_id
            max_dur = claimed.get("max_duration")
            if max_dur:
                merged["x-mesh-timeout"] = str(int(max_dur))
            TraceContext.set_propagated_headers(merged)
        except Exception as e:
            logger.debug(
                "claim_dispatcher: could not seed propagated headers (%s); "
                "dispatching without job context",
                e,
            )

        try:
            await self.handler(**payload)
        except Exception as e:
            logger.warning(
                "claim_dispatcher: handler for job=%s capability=%s raised: %s",
                job_id,
                self.capability,
                e,
            )
            # Best-effort: report failure to registry so the job doesn't
            # stay "working" until lease expiry. Failures here are
            # logged and swallowed — the registry's stale-agent sweep is
            # the ultimate backstop.
            try:
                from mcp_mesh_core import JobController as _JobController

                ctrl = _JobController(job_id, self.instance_id, self.registry_url)
                await ctrl.fail(str(e))
            except Exception as inner:
                logger.debug(
                    "claim_dispatcher: terminal-fail report failed: %s", inner
                )

    async def _run_loop(self) -> None:
        """Main loop: poll, claim, dispatch, backoff."""
        backoff = _POLL_BASE_SECS
        logger.info(
            "📨 claim_dispatcher started: capability=%s instance=%s",
            self.capability,
            self.instance_id,
        )
        while not self._stop.is_set():
            claimed = await self._claim_once()
            if claimed:
                # Dispatch concurrently so a long-running handler doesn't
                # block the next poll. Asyncio tasks are cheap; we don't
                # cap concurrency in Phase 1 (see module docstring).
                # Iterate the list — Phase 1 wire returns 0 or 1 entries
                # (single-claim semantics) but the loop is future-safe.
                for job in claimed:
                    logger.debug(
                        "claim_dispatcher: claim attempt for capability=%s "
                        "→ job_id=%s",
                        self.capability,
                        job.get("id"),
                    )
                    asyncio.create_task(self._dispatch(job))
                backoff = _POLL_BASE_SECS  # reset on success
                continue

            # No work — sleep with the cancellation-friendly Event wait.
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, _POLL_MAX_SECS)
        logger.info(
            "📨 claim_dispatcher stopped: capability=%s instance=%s",
            self.capability,
            self.instance_id,
        )

    def start(self) -> None:
        """Spawn the background loop on the current event loop."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name=f"mesh-claim-{self.capability}"
        )

    async def stop(self) -> None:
        """Signal the loop to exit and await it."""
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "claim_dispatcher: stop timed out for capability=%s; "
                    "cancelling task",
                    self.capability,
                )
                self._task.cancel()


def discover_task_handlers(
    instance_id: str, registry_url: str
) -> list[PythonClaimDispatcher]:
    """Build a :class:`PythonClaimDispatcher` for every registered
    ``@mesh.tool(task=True)`` function.

    Reads the :class:`DecoratorRegistry` to find candidate handlers.
    Returns an empty list when no task handlers are registered (most
    consumer-only agents) — caller should treat the empty case as "no
    claim workers needed" and skip startup.
    """
    from .decorator_registry import DecoratorRegistry

    dispatchers: list[PythonClaimDispatcher] = []
    try:
        tools = DecoratorRegistry.get_mesh_tools()
    except Exception as e:
        logger.warning("claim_dispatcher: get_mesh_tools failed: %s", e)
        return dispatchers

    for tool_name, decorated in tools.items():
        meta = getattr(decorated, "metadata", None)
        if not isinstance(meta, dict):
            continue
        if not meta.get("task"):
            continue
        capability = meta.get("capability") or tool_name
        # ``decorated.function`` is the wrapped function returned by
        # @mesh.tool. It already knows how to do DI + job dispatch via
        # maybe_dispatch_as_job; we just call it.
        handler = getattr(decorated, "function", None)
        if handler is None:
            logger.warning(
                "claim_dispatcher: no callable for tool %s; skipping",
                tool_name,
            )
            continue
        dispatchers.append(
            PythonClaimDispatcher(
                capability=capability,
                instance_id=instance_id,
                registry_url=registry_url,
                handler=handler,
            )
        )
    return dispatchers
