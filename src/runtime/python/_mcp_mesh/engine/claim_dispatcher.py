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

Concurrency is bounded by an :class:`asyncio.Semaphore` (default 4 —
matches ``ClaimWorkerConfig::new`` in the Rust core). The permit is
acquired in :meth:`PythonClaimDispatcher._run_loop` BEFORE
``POST /jobs/claim`` is issued, mirroring the Rust loop's
acquire-then-claim ordering. Without this, ``_claim_once`` could
outpace ``_dispatch`` under sustained load and the registry would see
"this agent claimed N jobs" while N-max_concurrent of them sat in
asyncio's task queue with their leases ticking down — leading to a
re-claim storm once the leases expired.
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

# Phase 1 dispatch concurrency cap. Mirrors the Rust ``ClaimWorker``
# semaphore (``max_concurrent`` in ``crate::claim_worker::ClaimWorkerConfig``)
# so a single Python claim dispatcher cannot drown its agent process by
# spinning unbounded handler tasks. Four matches the Rust default of 4.
_MAX_CONCURRENT_DISPATCHES = 4

# How many consecutive ``_claim_once`` failures we tolerate at WARNING
# level before escalating to ERROR. Helps surface a wedged dispatcher in
# operator dashboards without spamming on a single transient blip.
_CONSECUTIVE_FAILURES_ERROR_THRESHOLD = 5

# Bounded wait for in-flight dispatch tasks during ``stop()``. Mirrors the
# TypeScript ``ClaimDispatcher.stop(timeoutMs = 30_000)`` drain default
# (``src/runtime/typescript/src/claim-dispatcher.ts``): long enough that a
# typical job's terminal complete/fail flush finishes, short enough that a
# runaway handler doesn't block shutdown forever.
_STOP_DRAIN_TIMEOUT_SECS = 30.0

# Bounded wait for cancelled stragglers AFTER the drain window. A handler
# that swallows CancelledError (broad retry loops, shielded awaits) would
# make an unbounded await hang ``stop()`` forever; past this window the
# tasks are logged and abandoned.
_STOP_CANCEL_WAIT_SECS = 5.0

# Extra headroom on top of the shared drain budget in ``stop_dispatchers``:
# covers the per-dispatcher poll-loop stop (<=5s), straggler-cancel wait
# (<=_STOP_CANCEL_WAIT_SECS) and HTTP client close, which all happen
# outside the drain window itself.
_STOP_BUDGET_GRACE_SECS = 10.0


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
        # One httpx.AsyncClient per dispatcher instead of per poll —
        # avoids burning a TCP/TLS handshake on every claim cycle once
        # connection reuse is in play. Constructed lazily on first
        # ``_claim_once`` so we bind to the running event loop, not the
        # pipeline's one-shot loop (see jobs_claim_workers.py for the
        # lifetime story).
        self._http_client: Optional[Any] = None
        # Bounded concurrency for handler dispatch (W6).
        self._dispatch_sem = asyncio.Semaphore(_MAX_CONCURRENT_DISPATCHES)
        # Consecutive failure tracker for log-level escalation (W1).
        self._consecutive_failures = 0
        # Strong refs to in-flight dispatch tasks (issue #1162 LOW-5):
        # asyncio only keeps a weak reference to tasks, so a long-running
        # handler task with no other referent can be GC'd mid-flight. The
        # set also lets stop() drain in-flight dispatches so their
        # best-effort terminal fail() reports aren't killed with the loop.
        self._dispatch_tasks: set[asyncio.Task] = set()

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

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)

        url = f"{self.registry_url.rstrip('/')}/jobs/claim"
        payload = {
            "capability": self.capability,
            "instance_id": self.instance_id,
        }
        try:
            resp = await self._http_client.post(url, json=payload)
            if resp.status_code == 204:
                self._consecutive_failures = 0
                return []  # no work — registry returns 204 No Content
            if resp.status_code != 200:
                # Non-204/200 statuses are operational issues operators
                # should see. Bump the failure counter so a wedged
                # registry surfaces at ERROR after the threshold.
                self._consecutive_failures += 1
                self._log_claim_failure(
                    "unexpected status %s from %s" % (resp.status_code, url)
                )
                return []
            body = resp.json() or {}
            # OpenAPI ClaimJobsResponse: {"claimed": [...]} (required).
            claimed = body.get("claimed") or []
            if not isinstance(claimed, list):
                self._consecutive_failures += 1
                self._log_claim_failure(
                    "malformed response — 'claimed' is not a list: %r" % (claimed,)
                )
                return []
            # Successful poll — reset failure window so a one-off blip
            # doesn't accumulate against later failures.
            self._consecutive_failures = 0
            # Filter out entries without an id — defensive against
            # any future schema drift.
            return [c for c in claimed if isinstance(c, dict) and c.get("id")]
        except Exception as e:
            self._consecutive_failures += 1
            self._log_claim_failure(
                "claim_once error: %s: %s" % (type(e).__name__, e)
            )
            return []

    def _log_claim_failure(self, detail: str) -> None:
        """Surface a claim-poll failure at the appropriate log level.

        First few consecutive failures land at WARNING so default-INFO
        agent logs still flag the problem; once we're past
        ``_CONSECUTIVE_FAILURES_ERROR_THRESHOLD`` we escalate to ERROR
        so operator dashboards / log scrapers pick it up as actionable
        (a wedged dispatcher means jobs in this capability never run).
        """
        msg = (
            "claim_dispatcher capability=%s instance=%s: %s "
            "(consecutive_failures=%d)"
        ) % (self.capability, self.instance_id, detail, self._consecutive_failures)
        if self._consecutive_failures >= _CONSECUTIVE_FAILURES_ERROR_THRESHOLD:
            logger.error(msg)
        else:
            logger.warning(msg)

    async def _dispatch(self, claimed: dict) -> None:
        """Run the local handler for a claimed job. Calls
        ``handler(**submitted_payload)`` — the wrapped DI handler reads
        the X-Mesh-Job-Id from headers via the contextvar; for the
        claim path we set the contextvar manually before invoking it.

        Concurrency gating is performed by ``_run_loop`` BEFORE the claim
        is issued (matching ``crate::claim_worker::run_loop`` in the Rust
        core). The permit is held for the lifetime of this dispatch and
        released by the caller via ``_run_loop``'s ``finally`` block, so
        the dispatcher can never claim more jobs than it can immediately
        execute.
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
            await self._report_terminal_fail(job_id, e)

    async def _report_terminal_fail(self, job_id: str, error: Exception) -> None:
        """Best-effort: report failure to registry so the job doesn't
        stay "working" until lease expiry. Failures here are logged and
        swallowed — the registry's stale-agent sweep is the ultimate
        backstop.

        Injectable seam (#1176): unit tests stub this method so a raising
        handler doesn't construct a real ``JobController`` and POST to the
        registry while the dispatch permit is held.
        """
        try:
            from mcp_mesh_core import JobController as _JobController

            ctrl = _JobController(job_id, self.instance_id, self.registry_url)
            await ctrl.fail(str(error))
        except Exception as inner:
            logger.debug(
                "claim_dispatcher: terminal-fail report failed: %s", inner
            )

    async def _run_loop(self) -> None:
        """Main loop: gate, poll, claim, dispatch, backoff.

        Concurrency model: a permit from ``self._dispatch_sem`` is acquired
        BEFORE issuing ``_claim_once``. This mirrors
        ``crate::claim_worker::run_loop`` in the Rust core (see
        ``src/runtime/core/src/claim_worker.rs`` ~line 224) and prevents the
        "owned but waiting" pile-up where ``_claim_once`` outpaces
        ``_dispatch`` under sustained load: jobs would be stamped owner=this
        agent in the registry, then sit in an asyncio queue while their
        leases tick down, eventually getting orphaned and re-claimed.
        Acquiring first means a 5th claim attempt blocks at the semaphore
        until one of the 4 in-flight dispatches completes — the registry
        only sees claims this agent can immediately start executing.

        The permit is released in the spawned dispatch task's ``finally``
        block so a handler that raises (or is cancelled at agent shutdown)
        still frees the slot for the next claim.
        """
        backoff = _POLL_BASE_SECS
        logger.info(
            "📨 claim_dispatcher started: capability=%s instance=%s",
            self.capability,
            self.instance_id,
        )
        while not self._stop.is_set():
            # Acquire a permit BEFORE claiming so we never pull a job from
            # the registry that we can't immediately dispatch. Wrap the
            # acquire in a stop-aware wait so a shutdown signal can break
            # us out even when all permits are held by long-running
            # handlers.
            acquire_task = asyncio.ensure_future(self._dispatch_sem.acquire())
            stop_task = asyncio.ensure_future(self._stop.wait())
            try:
                done, _pending = await asyncio.wait(
                    {acquire_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                acquire_task.cancel()
                stop_task.cancel()
                raise

            if stop_task in done and acquire_task not in done:
                # Shutdown requested before we got a permit — abandon the
                # acquire and exit cleanly.
                acquire_task.cancel()
                try:
                    await acquire_task
                except (asyncio.CancelledError, Exception):
                    pass
                break

            # Permit acquired (possibly together with the stop signal — in
            # which case we still release the permit and exit).
            stop_task.cancel()
            try:
                await stop_task
            except (asyncio.CancelledError, Exception):
                pass
            permit_held = True

            try:
                if self._stop.is_set():
                    break

                claimed = await self._claim_once()
                if claimed:
                    # Phase 1 wire returns 0 or 1 entries (single-claim
                    # semantics) — we hand the permit to the dispatch task
                    # for the first claim and acquire fresh permits for
                    # any extras (future-safe; current wire never trips
                    # this branch).
                    first = True
                    for job in claimed:
                        logger.debug(
                            "claim_dispatcher: claim attempt for capability=%s "
                            "→ job_id=%s",
                            self.capability,
                            job.get("id"),
                        )
                        if first:
                            self._spawn_dispatch(job)
                            permit_held = False  # ownership transferred
                            first = False
                        else:
                            # Future-safe: extra claims need their own
                            # permits. Acquire synchronously here so we
                            # don't dispatch more concurrently than
                            # ``_MAX_CONCURRENT_DISPATCHES`` allows.
                            await self._dispatch_sem.acquire()
                            self._spawn_dispatch(job)
                    backoff = _POLL_BASE_SECS  # reset on success
                    continue

                # No work — release the permit (we won't need it) and
                # sleep with a cancellation-friendly Event wait.
                self._dispatch_sem.release()
                permit_held = False
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _POLL_MAX_SECS)
            finally:
                # Defensive: if anything inside the try block raised after
                # we acquired the permit but before we either transferred
                # it or released it, give it back so the loop can make
                # progress on the next iteration.
                if permit_held:
                    self._dispatch_sem.release()
        logger.info(
            "📨 claim_dispatcher stopped: capability=%s instance=%s",
            self.capability,
            self.instance_id,
        )

    def _spawn_dispatch(self, claimed: dict) -> None:
        """Spawn a dispatch task and retain a strong reference to it.

        The done-callback discard keeps the set bounded to genuinely
        in-flight tasks; ``stop()`` drains whatever remains.
        """
        task = asyncio.create_task(self._dispatch_with_permit(claimed))
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    async def _dispatch_with_permit(self, claimed: dict) -> None:
        """Run ``_dispatch`` and guarantee the semaphore permit is released.

        ``_run_loop`` acquires the permit BEFORE the claim and transfers
        ownership to the spawned dispatch task; this wrapper ensures the
        permit is released exactly once on every code path (success,
        handler exception, cancellation).
        """
        try:
            await self._dispatch(claimed)
        finally:
            self._dispatch_sem.release()

    def start(self) -> None:
        """Spawn the background loop on the current event loop."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name=f"mesh-claim-{self.capability}"
        )

    async def stop(self, drain_timeout: float = _STOP_DRAIN_TIMEOUT_SECS) -> None:
        """Signal the loop to exit, await it, then drain in-flight dispatches.

        Drain order (mirrors the TypeScript ``ClaimDispatcher.stop()``):

        1. stop the poll loop — no new claims/dispatches after this;
        2. await in-flight dispatch tasks, bounded by ``drain_timeout``,
           so handlers finish their terminal ``complete``/``fail`` reports
           instead of dying with the loop;
        3. cancel stragglers that outlive the window and await the
           cancellations, bounded by ``_STOP_CANCEL_WAIT_SECS`` (permit
           release is guaranteed by ``_dispatch_with_permit``'s
           ``finally``; a handler that swallows CancelledError is logged
           and abandoned rather than hanging stop() forever);
        4. close the dispatcher-owned HTTP client.

        Args:
            drain_timeout: Bounded wait (seconds) for in-flight handlers.
                ``<= 0`` skips the drain and cancels immediately (tests).
        """
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

        # Drain in-flight dispatch tasks (issue #1162 LOW-5). The poll loop
        # is down so the set can only shrink from here.
        pending = {t for t in self._dispatch_tasks if not t.done()}
        if pending:
            if drain_timeout > 0:
                _done, pending = await asyncio.wait(pending, timeout=drain_timeout)
            if pending:
                logger.warning(
                    "claim_dispatcher: stop() drain timed out for capability=%s "
                    "with %d dispatch task(s) still in flight; cancelling",
                    self.capability,
                    len(pending),
                )
                for task in pending:
                    task.cancel()
                # Bounded: a handler that swallows CancelledError would
                # otherwise hang stop() forever (post-#1162 review). The
                # tasks only ever end cancelled or clean (_dispatch
                # swallows handler exceptions), so abandoning here leaks
                # no unretrieved exceptions.
                _done, abandoned = await asyncio.wait(
                    pending, timeout=_STOP_CANCEL_WAIT_SECS
                )
                if abandoned:
                    logger.warning(
                        "claim_dispatcher: %d dispatch task(s) for "
                        "capability=%s did not exit within %.1fs of "
                        "cancellation (handler may be swallowing "
                        "CancelledError); abandoning",
                        len(abandoned),
                        self.capability,
                        _STOP_CANCEL_WAIT_SECS,
                    )

        # Close the dispatcher-owned HTTP client so connection pools
        # don't leak across agent restarts in long-lived test harnesses.
        client = self._http_client
        if client is not None:
            self._http_client = None
            try:
                await client.aclose()
            except Exception as e:  # noqa: BLE001 - best-effort cleanup
                logger.debug(
                    "claim_dispatcher: http client close raised (%s); ignoring",
                    e,
                )


async def stop_dispatchers(
    dispatchers: list,
    drain_timeout: float = _STOP_DRAIN_TIMEOUT_SECS,
    grace: float = _STOP_BUDGET_GRACE_SECS,
) -> None:
    """Stop multiple dispatchers concurrently under ONE shared drain budget.

    Every dispatcher drains against the SAME ``drain_timeout`` window —
    the ``stop()`` calls run in parallel via ``asyncio.gather`` — so N
    dispatchers with in-flight jobs cost roughly one drain window of wall
    time, not N stacked windows. Sequential 30s drains would starve
    whatever the caller sequences after this (registry unregister, Rust
    core shutdown) past a typical SIGTERM grace period (K8s default 30s),
    getting the process SIGKILLed before cleanup runs.

    The whole phase is additionally hard-capped at ``drain_timeout +
    grace``: past that, the remaining ``stop()`` calls are cancelled and
    abandoned with a warning. Never raises (short of outer cancellation)
    — a wedged dispatcher must not prevent the registry cleanup that
    callers run after this.

    Args:
        dispatchers: Dispatchers to stop (objects exposing
            ``stop(drain_timeout=...)``).
        drain_timeout: Shared in-flight-handler drain window, passed to
            every ``stop()`` call.
        grace: Headroom on top of ``drain_timeout`` for per-dispatcher
            bookkeeping (poll-loop stop, straggler cancel, client close)
            before the phase is abandoned wholesale.
    """
    if not dispatchers:
        return

    async def _stop_one(d: Any) -> None:
        try:
            await d.stop(drain_timeout=drain_timeout)
        except Exception as e:
            logger.warning(
                "claim_dispatcher: error stopping dispatcher for "
                "capability=%s: %s",
                getattr(d, "capability", "?"),
                e,
            )

    try:
        await asyncio.wait_for(
            asyncio.gather(*(_stop_one(d) for d in dispatchers)),
            timeout=drain_timeout + grace,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "claim_dispatcher: shutdown of %d dispatcher(s) exceeded the "
            "shared budget (%.1fs drain + %.1fs grace); abandoning "
            "remaining drains so shutdown can proceed to registry cleanup",
            len(dispatchers),
            drain_timeout,
            grace,
        )


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
