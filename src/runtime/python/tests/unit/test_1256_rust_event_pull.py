"""Issue #1256: Rust event-pull loop must be cancel-safe and self-healing.

These tests cover the Python side of the fix:

1. The consumer loop uses the plain-await pull pattern: ``next_event()``
   returns ``None`` as a liveness tick (internal Rust timeout) instead of the
   old ``asyncio.wait_for(..., timeout=1.0)`` wrapper, whose cancellation could
   drop a dequeued event. A ``None`` must be skipped, real events dispatched,
   and a ``shutdown`` event must break the loop.

2. Shutdown still terminates promptly (what the old 1s timeout protected).

3. Re-applying the same dependency endpoint is idempotent — the reconcile
   re-emit (Rust side) relies on the Python apply being a no-op storm-free
   overwrite.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import _mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat as rh


class _FakeEvent:
    def __init__(self, event_type: str):
        self.event_type = event_type


class _FakeHandle:
    """Fake AgentHandle whose ``next_event`` replays a scripted sequence.

    After the script is exhausted it yields ``None`` (liveness ticks), matching
    the real Rust handle's internal-timeout contract.
    """

    def __init__(self, script):
        self._script = list(script)
        self.shutdown_called = 0

    async def next_event(self):
        await asyncio.sleep(0)  # yield control like the real awaitable
        if self._script:
            return self._script.pop(0)
        return None

    def shutdown(self):
        self.shutdown_called += 1


@pytest.mark.asyncio
async def test_pull_skips_none_dispatches_events_and_breaks_on_shutdown():
    """None ticks are skipped, real events dispatched, shutdown breaks."""
    handle = _FakeHandle(
        [
            None,  # liveness tick — must be skipped
            _FakeEvent("dependency_available"),  # dispatched
            None,  # another tick
            _FakeEvent("shutdown"),  # breaks the loop
        ]
    )
    core = MagicMock()
    core.start_agent.return_value = handle
    handle_event = AsyncMock()

    with (
        patch.object(rh, "_get_rust_core", return_value=core),
        patch.object(rh, "_build_agent_spec", return_value=MagicMock()),
        patch.object(
            rh, "_start_claim_dispatchers_on_heartbeat_loop", return_value=[]
        ),
        patch.object(rh, "_handle_mesh_event", handle_event),
        patch(
            "_mcp_mesh.shared.simple_shutdown.should_stop_heartbeat",
            return_value=False,
        ),
        patch("_mcp_mesh.shared.simple_shutdown.register_rust_agent_handle"),
        patch("_mcp_mesh.shared.simple_shutdown.unregister_rust_agent_handle"),
    ):
        await asyncio.wait_for(
            rh.rust_heartbeat_task(
                {"agent_id": "a", "context": {}, "standalone_mode": False}
            ),
            timeout=5.0,
        )

    # Exactly one real event dispatched (the None ticks were skipped).
    assert handle_event.await_count == 1
    dispatched = handle_event.await_args.args[0]
    assert dispatched.event_type == "dependency_available"
    # Graceful shutdown of the Rust core in the finally block.
    assert handle.shutdown_called >= 1


@pytest.mark.asyncio
async def test_shutdown_signal_terminates_loop_promptly():
    """A Python shutdown signal breaks the loop before any event is handled."""
    handle = _FakeHandle([_FakeEvent("dependency_available")])
    core = MagicMock()
    core.start_agent.return_value = handle
    handle_event = AsyncMock()

    with (
        patch.object(rh, "_get_rust_core", return_value=core),
        patch.object(rh, "_build_agent_spec", return_value=MagicMock()),
        patch.object(
            rh, "_start_claim_dispatchers_on_heartbeat_loop", return_value=[]
        ),
        patch.object(rh, "_handle_mesh_event", handle_event),
        patch(
            "_mcp_mesh.shared.simple_shutdown.should_stop_heartbeat",
            return_value=True,
        ),
        patch("_mcp_mesh.shared.simple_shutdown.register_rust_agent_handle"),
        patch("_mcp_mesh.shared.simple_shutdown.unregister_rust_agent_handle"),
    ):
        # Must return well within the timeout — promptness is the property the
        # old 1s wait_for was protecting.
        await asyncio.wait_for(
            rh.rust_heartbeat_task(
                {"agent_id": "a", "context": {}, "standalone_mode": False}
            ),
            timeout=3.0,
        )

    assert handle_event.await_count == 0
    assert handle.shutdown_called >= 1


@pytest.mark.asyncio
async def test_dependency_apply_is_idempotent():
    """Re-registering the same dep key/endpoint is a storm-free overwrite.

    The Rust reconcile pass (#1256) re-emits already-applied edges; the Python
    apply must tolerate that without accumulating state or raising.
    """
    from _mcp_mesh.engine.dependency_injector import DependencyInjector

    injector = DependencyInjector()
    proxy_a = MagicMock(name="proxy-endpoint-9000")
    proxy_b = MagicMock(name="proxy-endpoint-9000-again")

    dep_key = "pkg.mod.consumer:dep_0"
    await injector.register_dependency(dep_key, proxy_a)
    await injector.register_dependency(dep_key, proxy_b)

    # Single entry, latest instance wins — no accumulation, no error.
    assert injector.get_dependency(dep_key) is proxy_b
