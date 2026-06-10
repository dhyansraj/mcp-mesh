"""Issue #1162 LOW-5: claim dispatcher must retain and drain dispatch tasks.

Before the fix, ``asyncio.create_task(self._dispatch_with_permit(job))``
results were not retained (weak-ref GC hazard for long handlers) and
``stop()`` awaited only the poll loop — in-flight dispatch tasks died with
the loop without their best-effort terminal ``fail()`` report.

Now tasks are tracked in a strong-ref set and ``stop()`` drains them with a
bounded timeout (default mirrors the TypeScript ``ClaimDispatcher.stop``
30s drain), cancelling stragglers. Permit accounting must stay balanced
through both completion and cancellation.
"""

import asyncio
import time
from unittest import mock

import pytest
from _mcp_mesh.engine import claim_dispatcher as claim_dispatcher_module
from _mcp_mesh.engine.claim_dispatcher import (
    _MAX_CONCURRENT_DISPATCHES,
    PythonClaimDispatcher,
)


def _make_dispatcher(handler) -> PythonClaimDispatcher:
    return PythonClaimDispatcher(
        capability="test_cap",
        instance_id="test-instance",
        registry_url="http://registry:8000",
        handler=handler,
    )


def _single_job_claimer(dispatcher: PythonClaimDispatcher, job_id: str = "job-1"):
    """Patch _claim_once to yield exactly one job, then no work."""
    jobs = [[{"id": job_id, "submitted_payload": {}}]]

    async def fake_claim_once():
        return jobs.pop(0) if jobs else []

    dispatcher._claim_once = fake_claim_once


class TestStopDrainsInflightDispatch:
    @pytest.mark.asyncio
    async def test_stop_waits_for_slow_handler_to_complete(self):
        started = asyncio.Event()
        completed: list[bool] = []

        async def handler(**kwargs):
            started.set()
            await asyncio.sleep(0.2)
            completed.append(True)

        dispatcher = _make_dispatcher(handler)
        _single_job_claimer(dispatcher)

        dispatcher.start()
        await asyncio.wait_for(started.wait(), timeout=2.0)

        await dispatcher.stop(drain_timeout=5.0)

        assert completed == [True]
        assert not dispatcher._dispatch_tasks
        # Permit accounting balanced after a drained completion.
        assert dispatcher._dispatch_sem._value == _MAX_CONCURRENT_DISPATCHES

    @pytest.mark.asyncio
    async def test_stop_drain_lets_terminal_fail_report_fire(self):
        """A handler that raises reports fail() to the registry; stop()
        must not kill the dispatch task before that report fires."""
        started = asyncio.Event()
        fail_reports: list[tuple[str, str]] = []

        class _FakeController:
            def __init__(self, job_id, instance_id, registry_url):
                self.job_id = job_id

            async def fail(self, error):
                # Yield once so the report itself needs the drain window.
                await asyncio.sleep(0.05)
                fail_reports.append((self.job_id, error))

        async def handler(**kwargs):
            started.set()
            await asyncio.sleep(0.1)
            raise RuntimeError("boom")

        dispatcher = _make_dispatcher(handler)
        _single_job_claimer(dispatcher, job_id="job-fail")

        with mock.patch("mcp_mesh_core.JobController", _FakeController, create=True):
            dispatcher.start()
            await asyncio.wait_for(started.wait(), timeout=2.0)
            await dispatcher.stop(drain_timeout=5.0)

        assert fail_reports == [("job-fail", "boom")]
        assert dispatcher._dispatch_sem._value == _MAX_CONCURRENT_DISPATCHES

    @pytest.mark.asyncio
    async def test_stragglers_past_drain_timeout_are_cancelled(self):
        started = asyncio.Event()
        completed: list[bool] = []
        cancelled = asyncio.Event()

        async def handler(**kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
                completed.append(True)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        dispatcher = _make_dispatcher(handler)
        _single_job_claimer(dispatcher)

        dispatcher.start()
        await asyncio.wait_for(started.wait(), timeout=2.0)

        await dispatcher.stop(drain_timeout=0.05)

        assert cancelled.is_set()
        assert completed == []
        assert not dispatcher._dispatch_tasks
        # Cancellation must hit _dispatch_with_permit's finally and
        # release the permit — accounting stays balanced.
        assert dispatcher._dispatch_sem._value == _MAX_CONCURRENT_DISPATCHES

    @pytest.mark.asyncio
    async def test_handler_swallowing_cancellation_is_abandoned_bounded(
        self, monkeypatch, caplog
    ):
        """Post-cancel wait is bounded: a handler that swallows
        CancelledError must not hang stop() forever — the task is logged
        and abandoned after _STOP_CANCEL_WAIT_SECS."""
        monkeypatch.setattr(
            claim_dispatcher_module, "_STOP_CANCEL_WAIT_SECS", 0.2
        )

        started = asyncio.Event()
        release = asyncio.Event()
        swallowed = asyncio.Event()

        async def handler(**kwargs):
            started.set()
            while True:
                try:
                    await release.wait()
                    return
                except asyncio.CancelledError:
                    # Misbehaving handler: swallow the cancellation and
                    # keep waiting (retry-loop / shielded-await pattern).
                    swallowed.set()

        dispatcher = _make_dispatcher(handler)
        _single_job_claimer(dispatcher)

        dispatcher.start()
        await asyncio.wait_for(started.wait(), timeout=2.0)
        abandoned_task = next(iter(dispatcher._dispatch_tasks))

        t0 = time.monotonic()
        with caplog.at_level("WARNING"):
            await dispatcher.stop(drain_timeout=0.05)
        elapsed = time.monotonic() - t0

        assert swallowed.is_set()
        assert elapsed < 2.0  # bounded, not hung on the swallowed cancel
        assert any(
            "abandoning" in rec.getMessage()
            for rec in caplog.records
            if rec.levelname == "WARNING"
        )

        # Clean up the abandoned task so it doesn't leak past the test.
        release.set()
        await asyncio.wait_for(abandoned_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_dispatch_tasks_strongly_referenced_while_inflight(self):
        """The task set holds a strong reference for the lifetime of the
        dispatch (asyncio itself only keeps weak refs) and self-cleans on
        completion via the done callback."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(**kwargs):
            started.set()
            await release.wait()

        dispatcher = _make_dispatcher(handler)
        _single_job_claimer(dispatcher)

        dispatcher.start()
        await asyncio.wait_for(started.wait(), timeout=2.0)

        assert len(dispatcher._dispatch_tasks) == 1

        release.set()
        await dispatcher.stop(drain_timeout=5.0)
        assert not dispatcher._dispatch_tasks
