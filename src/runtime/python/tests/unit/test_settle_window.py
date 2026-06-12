"""
Unit tests for the settling-window dependency grace (issue #1193).

Covers the cross-runtime contract for Python:

* a call that fires while a declared dependency is still unresolved waits —
  bounded by the remaining settle budget — and proceeds EARLY the moment the
  resolution event lands (event-driven, never a sleep);
* on timeout the call proceeds with ``None`` exactly as today (defensive
  ``if dep:`` user code untouched);
* the settled latch is permanent (window expiry or all-declared-resolved)
  and the steady-state call path never touches the wait primitives;
* ``MCP_MESH_SETTLE_TIMEOUT=0`` disables the grace entirely;
* sync tools (dispatched on worker threads, mirroring FastMCP's
  ``anyio.to_thread`` dispatch) block safely while the event loop stays free;
* a sync wrapper invoked ON a running loop skips the wait entirely (the
  blocking wait would stall the loop that delivers resolution events);
* async waits are loop-native (``asyncio.Event`` mirrors set via
  ``call_soon_threadsafe``) — zero executor usage;
* the window is anchored at the FIRST dependency declaration, not import;
* caller-supplied slots (the documented mock contract) never wait;
* ``MCP_MESH_STRICT_DI`` never interacts with the settle window.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import mesh
import pytest

from _mcp_mesh.engine import settle
from _mcp_mesh.engine.dependency_injector import DependencyInjector
from _mcp_mesh.engine.settle import (
    SETTLE_TIMEOUT_DEFAULT_SECONDS,
    get_settle_state,
    get_settle_timeout,
)
from _mcp_mesh.engine.strict_di import _reset_strict_di_cache


@pytest.fixture(autouse=True)
def fresh_settle_state(monkeypatch):
    """Isolate every test: fresh settle state + uncached timeout knob."""
    monkeypatch.delenv("MCP_MESH_SETTLE_TIMEOUT", raising=False)
    settle._reset_settle_state_for_tests()
    yield
    settle._reset_settle_state_for_tests()


def _set_budget(monkeypatch, value: str) -> None:
    """Set the settle budget and re-anchor the settle state on it."""
    monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", value)
    settle._reset_settle_state_for_tests()


def _make_async_wrapper(injector, dep_name="db_cap"):
    async def tool(db: mesh.McpMeshTool = None):
        # Defensive user idiom — must keep working unchanged.
        if db is None:
            return "degraded"
        return db

    return injector.create_injection_wrapper(tool, [dep_name])


class TestSettleTimeoutKnob:
    def test_default_is_20_seconds(self):
        assert get_settle_timeout() == SETTLE_TIMEOUT_DEFAULT_SECONDS == 20.0

    def test_env_override_float(self, monkeypatch):
        _set_budget(monkeypatch, "3.5")
        assert get_settle_timeout() == 3.5

    def test_cached_per_process(self, monkeypatch):
        _set_budget(monkeypatch, "3.5")
        assert get_settle_timeout() == 3.5
        # Changing the env after the first read has no effect (cached).
        monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", "99")
        assert get_settle_timeout() == 3.5

    def test_negative_falls_back_to_default(self, monkeypatch):
        _set_budget(monkeypatch, "-5")
        assert get_settle_timeout() == SETTLE_TIMEOUT_DEFAULT_SECONDS


class TestSettleWait:
    @pytest.mark.asyncio
    async def test_resolution_mid_wait_unblocks_early(self, monkeypatch):
        """(a) Event arriving mid-wait → call proceeds early with the proxy."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        proxy = MagicMock(name="proxy")

        async def resolve_later():
            await asyncio.sleep(0.2)
            wrapper._mesh_update_dependency(0, proxy)

        resolver = asyncio.create_task(resolve_later())
        start = time.monotonic()
        result = await wrapper()
        elapsed = time.monotonic() - start
        await resolver

        assert result is proxy
        # Unblocked by the event, not the 10s budget ceiling.
        assert elapsed < 5.0
        assert get_settle_state().wait_count >= 1

    @pytest.mark.asyncio
    async def test_timeout_proceeds_with_none(self, monkeypatch):
        """(b) No event → call proceeds at budget with None; defensive
        user code runs (today-behavior on expiry)."""
        _set_budget(monkeypatch, "0.3")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)

        start = time.monotonic()
        result = await wrapper()
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert elapsed >= 0.2  # actually waited toward the budget

    @pytest.mark.asyncio
    async def test_settled_by_window_expiry_never_waits_again(
        self, monkeypatch
    ):
        """(c) Window expired → latch is permanent; calls never wait."""
        _set_budget(monkeypatch, "0.1")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        await asyncio.sleep(0.15)

        for _ in range(2):
            start = time.monotonic()
            result = await wrapper()
            elapsed = time.monotonic() - start
            assert result == "degraded"
            assert elapsed < 0.05

        state = get_settle_state()
        assert state.is_settled()
        assert state.wait_count == 0

    @pytest.mark.asyncio
    async def test_settled_by_all_resolved_never_waits(self, monkeypatch):
        """(d) All declared deps resolved → eager latch; calls never wait."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        proxy = MagicMock(name="proxy")
        wrapper._mesh_update_dependency(0, proxy)

        state = get_settle_state()
        assert state.is_settled()

        start = time.monotonic()
        result = await wrapper()
        elapsed = time.monotonic() - start

        assert result is proxy
        assert elapsed < 0.05
        assert state.wait_count == 0

    @pytest.mark.asyncio
    async def test_agent_level_union_across_functions(self, monkeypatch):
        """The latch tracks the UNION of declared deps across functions:
        resolving one function's dep does not settle the agent, and only
        the call whose dep is unresolved waits."""
        _set_budget(monkeypatch, "0.3")
        injector = DependencyInjector()
        wrapper_a = _make_async_wrapper(injector, "cap_a")

        async def other_tool(svc: mesh.McpMeshTool = None):
            return "ok" if svc is None else svc

        wrapper_b = injector.create_injection_wrapper(other_tool, ["cap_b"])

        proxy = MagicMock(name="proxy_a")
        wrapper_a._mesh_update_dependency(0, proxy)

        state = get_settle_state()
        assert not state.is_settled()  # cap_b still unresolved

        # wrapper_a's dep is resolved — no wait even though unsettled.
        start = time.monotonic()
        assert await wrapper_a() is proxy
        assert time.monotonic() - start < 0.05

        # wrapper_b's dep is unresolved — it waits toward the budget.
        start = time.monotonic()
        assert await wrapper_b() == "ok"
        assert time.monotonic() - start >= 0.2

    @pytest.mark.asyncio
    async def test_zero_timeout_disables_grace(self, monkeypatch):
        """(e) MCP_MESH_SETTLE_TIMEOUT=0 → no waits anywhere."""
        _set_budget(monkeypatch, "0")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)

        start = time.monotonic()
        result = await wrapper()
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert elapsed < 0.05
        state = get_settle_state()
        assert state.is_settled()
        assert state.wait_count == 0

    @pytest.mark.asyncio
    async def test_sync_tool_blocking_wait_keeps_loop_free(self, monkeypatch):
        """(f) Sync tool on its worker thread: the blocking threading.Event
        wait works AND the event loop stays unblocked meanwhile (proven by
        a concurrent health-style ticker)."""
        _set_budget(monkeypatch, "5")
        injector = DependencyInjector()

        def sync_tool(db: mesh.McpMeshTool = None):
            return db if db is not None else "degraded"

        wrapper = injector.create_injection_wrapper(sync_tool, ["db_cap"])
        proxy = MagicMock(name="proxy")

        ticks = 0

        async def health_ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        ticker = asyncio.create_task(health_ticker())

        async def resolve_later():
            await asyncio.sleep(0.4)
            wrapper._mesh_update_dependency(0, proxy)

        resolver = asyncio.create_task(resolve_later())
        # Mirror FastMCP's dispatch: sync tools run via anyio.to_thread.
        result = await asyncio.to_thread(wrapper)
        await resolver
        ticker.cancel()

        assert result is proxy
        # The loop processed ticker iterations DURING the blocking wait —
        # the wait blocked only the worker thread, never the loop.
        assert ticks >= 3

    @pytest.mark.asyncio
    async def test_strict_di_does_not_interact(self, monkeypatch):
        """(g) Strict DI enabled + settle timeout → warning path only, no
        raise. The settle window is environmental, not a declaration
        mistake."""
        monkeypatch.setenv("MCP_MESH_STRICT_DI", "true")
        _reset_strict_di_cache()
        try:
            _set_budget(monkeypatch, "0.2")
            injector = DependencyInjector()
            wrapper = _make_async_wrapper(injector)

            result = await wrapper()  # must NOT raise StrictDIError
            assert result == "degraded"
        finally:
            monkeypatch.delenv("MCP_MESH_STRICT_DI", raising=False)
            _reset_strict_di_cache()

    @pytest.mark.asyncio
    async def test_steady_state_never_touches_wait_primitives(
        self, monkeypatch
    ):
        """(h) Once settled, the call path performs only the latch check —
        the per-dependency event primitives are never touched."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        wrapper._mesh_update_dependency(0, MagicMock(name="proxy"))

        state = get_settle_state()
        assert state.is_settled()
        baseline_wait_count = state.wait_count

        with patch.object(
            state, "_event_for", wraps=state._event_for
        ) as event_spy, patch.object(
            state, "wait_for", wraps=state.wait_for
        ) as wait_spy:
            for _ in range(3):
                await wrapper()

        event_spy.assert_not_called()
        wait_spy.assert_not_called()
        assert state.wait_count == baseline_wait_count

    @pytest.mark.asyncio
    async def test_caller_supplied_dep_never_waits(self, monkeypatch):
        """A slot the caller explicitly filled (documented mock contract,
        e.g. ``wrapper(db=mock)``) is skipped by the pending collection —
        no wait even though the agent is unsettled and the dep unresolved."""
        _set_budget(monkeypatch, "5")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        mock_dep = MagicMock(name="caller_supplied_mock")

        state = get_settle_state()
        assert not state.is_settled()

        start = time.monotonic()
        result = await wrapper(db=mock_dep)
        elapsed = time.monotonic() - start

        assert result is mock_dep  # injection preserved the caller's value
        assert elapsed < 0.1
        assert state.wait_count == 0

    @pytest.mark.asyncio
    async def test_window_anchored_at_first_declaration(self, monkeypatch):
        """The settle window starts at the FIRST register_declared call
        (startup wiring), not at module import / state construction —
        pre-declaration idle time never eats the grace budget."""
        _set_budget(monkeypatch, "0.3")
        # Idle past the would-be window BEFORE any dependency declaration.
        await asyncio.sleep(0.4)

        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        state = get_settle_state()
        # With an import-time anchor this would already be (incorrectly)
        # settled; the declaration-time anchor keeps the window open.
        assert not state.is_settled()

        start = time.monotonic()
        result = await wrapper()
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert elapsed >= 0.2  # waited toward the freshly-anchored budget

    @pytest.mark.asyncio
    async def test_sync_wrapper_on_running_loop_skips_wait(self, monkeypatch):
        """Defensive guard: a sync wrapper invoked ON a running event loop
        must skip the blocking wait — blocking would stall the loop that
        delivers the resolution events (a guaranteed dead wait)."""
        _set_budget(monkeypatch, "5")
        injector = DependencyInjector()

        def sync_tool(db: mesh.McpMeshTool = None):
            return db if db is not None else "degraded"

        wrapper = injector.create_injection_wrapper(sync_tool, ["db_cap"])
        assert not get_settle_state().is_settled()

        start = time.monotonic()
        result = wrapper()  # inline on the loop, NOT via to_thread
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert elapsed < 0.5
        assert get_settle_state().wait_count == 0

    @pytest.mark.asyncio
    async def test_async_wait_is_loop_native_and_thread_woken(
        self, monkeypatch
    ):
        """Async graced waits use loop-native asyncio.Event mirrors set via
        call_soon_threadsafe — no executor is touched, and a resolution
        arriving on a FOREIGN thread (the real heartbeat shape) wakes the
        waiter early."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_async_wrapper(injector)
        proxy = MagicMock(name="proxy")

        # Resolution fires from a plain thread, not the event loop.
        timer = threading.Timer(
            0.2, lambda: wrapper._mesh_update_dependency(0, proxy)
        )
        timer.start()

        with patch.object(
            asyncio,
            "to_thread",
            side_effect=AssertionError(
                "settle wait must not consume executor capacity"
            ),
        ):
            start = time.monotonic()
            result = await wrapper()
            elapsed = time.monotonic() - start
        timer.join()

        assert result is proxy
        assert elapsed < 5.0  # woken by the cross-thread event, not budget
        assert get_settle_state().wait_count >= 1

    def test_first_wait_logs_info_then_debug(self, monkeypatch, caplog):
        """One INFO line per dependency per process; later waits DEBUG.

        Subsequent waits on the same dependency only occur while it is
        still unresolved (i.e. concurrent calls), so the second waiter
        runs on the main thread while a timer resolves the dependency.
        """
        import logging
        import threading

        _set_budget(monkeypatch, "5")
        state = get_settle_state()
        state.register_declared("f:dep_0")

        log = logging.getLogger("test.settle.logging")
        with caplog.at_level(logging.DEBUG, logger="test.settle.logging"):
            first = threading.Thread(
                target=lambda: state.wait_for("f:dep_0", "db_cap", log)
            )
            first.start()
            # Wait until the first waiter has logged its INFO line.
            deadline = time.monotonic() + 2
            while (
                not any("db_cap" in r.getMessage() for r in caplog.records)
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)

            # Second concurrent waiter (main thread) — resolution arrives
            # via timer so the blocking wait ends promptly.
            threading.Timer(0.15, lambda: state.mark_resolved("f:dep_0")).start()
            state.wait_for("f:dep_0", "db_cap", log)
            first.join(timeout=2)

        records = [r for r in caplog.records if "db_cap" in r.getMessage()]
        assert len(records) == 2
        assert records[0].levelno == logging.INFO
        assert records[1].levelno == logging.DEBUG
        assert "waiting up to" in records[0].getMessage()
