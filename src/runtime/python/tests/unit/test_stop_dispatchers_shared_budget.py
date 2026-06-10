"""Post-#1162 review: dispatcher shutdown must not starve registry cleanup.

``_stop_claim_dispatchers`` (both the lifespan-factory and the
rust-heartbeat copies) used to await each dispatcher's ``stop()``
sequentially. With the 30s drain default, N dispatchers with in-flight
jobs cost N x 30s+ of wall time before the registry unregister that runs
after them — past a typical SIGTERM grace period (K8s default 30s), the
process is SIGKILLed before cleanup.

Now both delegate to :func:`_mcp_mesh.engine.claim_dispatcher.stop_dispatchers`:

* all ``stop()`` calls run concurrently via ``asyncio.gather`` against
  ONE shared drain budget (one window of wall time, not N stacked);
* the whole phase is hard-capped at ``drain_timeout + grace`` — past
  that the remaining drains are cancelled and abandoned;
* a drain failure or timeout in one dispatcher can never prevent the
  registry cleanup sequenced after the call from running.
"""

import asyncio
import time

import pytest
from _mcp_mesh.engine import claim_dispatcher as claim_dispatcher_module
from _mcp_mesh.engine.claim_dispatcher import stop_dispatchers
from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat
from _mcp_mesh.pipeline.mcp_startup import lifespan_factory


class _FakeDispatcher:
    """Minimal stand-in exposing the ``stop(drain_timeout=...)`` surface."""

    def __init__(
        self,
        capability: str,
        stop_duration: float = 0.0,
        hang: bool = False,
        fail: bool = False,
    ) -> None:
        self.capability = capability
        self.stop_duration = stop_duration
        self.hang = hang
        self.fail = fail
        self.stop_started_at: float | None = None
        self.stop_finished = False
        self.received_drain_timeout: float | None = None

    async def stop(self, drain_timeout: float = 30.0) -> None:
        self.stop_started_at = time.monotonic()
        self.received_drain_timeout = drain_timeout
        if self.fail:
            raise RuntimeError(f"stop failed for {self.capability}")
        if self.hang:
            await asyncio.Event().wait()  # never completes
        if self.stop_duration:
            await asyncio.sleep(self.stop_duration)
        self.stop_finished = True


class TestStopDispatchersSharedBudget:
    @pytest.mark.asyncio
    async def test_two_slow_dispatchers_drain_concurrently_not_stacked(self):
        """2 dispatchers each needing ~0.4s must finish in ~one window
        (concurrent), not ~0.8s+ (sequential)."""
        d1 = _FakeDispatcher("cap-a", stop_duration=0.4)
        d2 = _FakeDispatcher("cap-b", stop_duration=0.4)

        t0 = time.monotonic()
        await stop_dispatchers([d1, d2], drain_timeout=2.0, grace=1.0)
        elapsed = time.monotonic() - t0

        assert d1.stop_finished and d2.stop_finished
        # Concurrent: ~0.4s wall. Sequential would be >= 0.8s.
        assert elapsed < 0.75, f"stops appear sequential: {elapsed:.2f}s"
        # Both started inside the same window (overlap, not back-to-back).
        assert abs(d1.stop_started_at - d2.stop_started_at) < 0.1

    @pytest.mark.asyncio
    async def test_every_dispatcher_gets_the_shared_drain_window(self):
        """Each stop() receives the SAME shared drain_timeout — the budget
        is not split per dispatcher."""
        dispatchers = [_FakeDispatcher(f"cap-{i}") for i in range(3)]
        await stop_dispatchers(dispatchers, drain_timeout=7.0, grace=1.0)
        assert [d.received_drain_timeout for d in dispatchers] == [7.0] * 3

    @pytest.mark.asyncio
    async def test_hanging_drain_is_abandoned_and_code_after_still_runs(
        self, caplog
    ):
        """A drain that never completes must not block past the hard cap;
        registry-cleanup-style code sequenced after the call still runs."""
        hanging = _FakeDispatcher("cap-stuck", hang=True)
        healthy = _FakeDispatcher("cap-ok", stop_duration=0.05)

        cleanup_ran = False
        t0 = time.monotonic()
        with caplog.at_level("WARNING"):
            await stop_dispatchers(
                [hanging, healthy], drain_timeout=0.1, grace=0.1
            )
        # Mirrors the lifespan finally block: cleanup is the next statement.
        cleanup_ran = True
        elapsed = time.monotonic() - t0

        assert cleanup_ran
        assert healthy.stop_finished
        assert not hanging.stop_finished
        assert elapsed < 1.0, f"hard cap did not engage: {elapsed:.2f}s"
        assert any(
            "exceeded the shared budget" in rec.getMessage()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_one_failing_stop_does_not_block_the_others_or_raise(self):
        failing = _FakeDispatcher("cap-bad", fail=True)
        healthy = _FakeDispatcher("cap-ok", stop_duration=0.05)

        # Must not raise — and the healthy dispatcher still drains.
        await stop_dispatchers([failing, healthy], drain_timeout=1.0, grace=0.5)
        assert healthy.stop_finished

    @pytest.mark.asyncio
    async def test_empty_list_is_a_noop(self):
        await stop_dispatchers([], drain_timeout=0.0, grace=0.0)


@pytest.mark.parametrize(
    "wrapper",
    [
        lifespan_factory._stop_claim_dispatchers,
        rust_heartbeat._stop_claim_dispatchers,
    ],
    ids=["lifespan_factory", "rust_heartbeat"],
)
class TestStopClaimDispatcherWrappers:
    """Both shutdown call sites delegate to the shared-budget helper and
    never let a dispatcher failure escape to skip registry cleanup."""

    @pytest.mark.asyncio
    async def test_wrapper_stops_concurrently(self, wrapper):
        d1 = _FakeDispatcher("cap-a", stop_duration=0.3)
        d2 = _FakeDispatcher("cap-b", stop_duration=0.3)

        t0 = time.monotonic()
        await wrapper([d1, d2])
        elapsed = time.monotonic() - t0

        assert d1.stop_finished and d2.stop_finished
        assert elapsed < 0.55, f"wrapper stops appear sequential: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_wrapper_swallows_helper_failure(self, wrapper, monkeypatch):
        async def exploding_stop_dispatchers(dispatchers, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            claim_dispatcher_module,
            "stop_dispatchers",
            exploding_stop_dispatchers,
        )
        # Must not raise — cleanup after the call site depends on it.
        await wrapper([_FakeDispatcher("cap-a")])

    @pytest.mark.asyncio
    async def test_wrapper_survives_hanging_drain_within_budget(
        self, wrapper, monkeypatch
    ):
        """End-to-end through the wrapper: with a tightened budget, a
        hanging dispatcher is abandoned and the call returns so the
        cleanup sequenced after it can run."""
        real = claim_dispatcher_module.stop_dispatchers

        async def fast_budget(dispatchers, drain_timeout=0.05, grace=0.1):
            await real(dispatchers, drain_timeout=drain_timeout, grace=grace)

        monkeypatch.setattr(
            claim_dispatcher_module, "stop_dispatchers", fast_budget
        )

        hanging = _FakeDispatcher("cap-stuck", hang=True)
        t0 = time.monotonic()
        await wrapper([hanging])
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0
        assert not hanging.stop_finished
