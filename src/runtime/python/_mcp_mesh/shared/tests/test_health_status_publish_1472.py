"""Unit tests for publishing the health-check verdict to the Rust core.

Issue #1472 — a failing ``health_check`` used to affect only the ``/health``
and ``/ready`` responses; the heartbeat hardcoded HEALTHY, so the registry
kept routing to the agent. The verdict now travels to the Rust core, which
stops heartbeating while the agent is unhealthy.

These cover the Python half of that channel: the status mapping, the
startup no-op, and the "never break the refresh loop" guarantees.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from _mcp_mesh.shared import health_check_manager, simple_shutdown


class FakeHealthStatus:
    """Stand-in for the Rust ``mcp_mesh_core.HealthStatus`` pyclass enum."""

    Healthy = "core.Healthy"
    Degraded = "core.Degraded"
    Unhealthy = "core.Unhealthy"


class FakeHandle:
    """Records what the core was told, and how often."""

    def __init__(self, accepted: bool = True, raises: bool = False):
        self.calls: list = []
        self._accepted = accepted
        self._raises = raises

    def update_health(self, status):
        self.calls.append(status)
        if self._raises:
            raise RuntimeError("command channel closed")
        return self._accepted


@pytest.fixture
def fake_core(monkeypatch):
    """Install a fake ``mcp_mesh_core`` module for the duration of a test.

    The publisher imports the core lazily inside the function, so patching
    ``sys.modules`` is enough — no import-time coupling.
    """
    module = SimpleNamespace(HealthStatus=FakeHealthStatus)
    monkeypatch.setitem(sys.modules, "mcp_mesh_core", module)
    return module


@pytest.fixture
def no_handles(monkeypatch):
    """Start every test from an empty process-wide handle registry."""
    monkeypatch.setattr(simple_shutdown, "_active_handles", [])
    yield


@pytest.fixture
def one_handle(no_handles, monkeypatch):
    handle = FakeHandle()
    monkeypatch.setattr(simple_shutdown, "_active_handles", [handle])
    return handle


class TestStatusMapping:
    """Each health-check verdict maps onto the core's HealthStatus."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("healthy", FakeHealthStatus.Healthy),
            ("degraded", FakeHealthStatus.Degraded),
            ("unhealthy", FakeHealthStatus.Unhealthy),
        ],
    )
    def test_known_statuses_map_directly(self, fake_core, one_handle, status, expected):
        assert health_check_manager.publish_health_status_to_core(status) is True
        assert one_handle.calls == [expected]

    def test_status_is_case_insensitive(self, fake_core, one_handle):
        # ``HealthStatusType`` is a str-Enum whose ``.value`` is lowercase, but
        # the stored dict is user-reachable — don't let casing withdraw an agent.
        health_check_manager.publish_health_status_to_core("UNHEALTHY")
        assert one_handle.calls == [FakeHealthStatus.Unhealthy]

    def test_unknown_status_degrades_rather_than_withdraws(self, fake_core, one_handle):
        # "unknown" is what ``_parse_health_result`` produces for a dict with an
        # unrecognized status string. Withdrawing an agent from the mesh because
        # its status was unparseable is a worse failure than keeping it, so this
        # must map to Degraded (which heartbeats normally), never Unhealthy.
        health_check_manager.publish_health_status_to_core("unknown")
        assert one_handle.calls == [FakeHealthStatus.Degraded]


class TestStartupOrdering:
    """Before the heartbeat task starts there is no handle — and that is the
    intended behaviour, not an accident: the agent registers and becomes
    visible first, then goes silent if the check is genuinely failing.
    """

    def test_no_handle_is_a_silent_noop(self, fake_core, no_handles):
        assert health_check_manager.publish_health_status_to_core("unhealthy") is False

    def test_missing_rust_core_is_a_noop(self, monkeypatch, no_handles):
        # Pure-Python environments (unit tests, standalone mode) have no core.
        monkeypatch.setitem(sys.modules, "mcp_mesh_core", None)
        assert health_check_manager.publish_health_status_to_core("unhealthy") is False


class TestFailureIsolation:
    """Health reporting must never break the refresh loop that calls it."""

    def test_handle_exception_is_swallowed(self, fake_core, no_handles, monkeypatch):
        exploding = FakeHandle(raises=True)
        monkeypatch.setattr(simple_shutdown, "_active_handles", [exploding])

        assert health_check_manager.publish_health_status_to_core("unhealthy") is False
        assert exploding.calls == [FakeHealthStatus.Unhealthy]

    def test_rejected_command_reports_false(self, fake_core, no_handles, monkeypatch):
        # ``update_health`` returns False when the command channel is full.
        rejecting = FakeHandle(accepted=False)
        monkeypatch.setattr(simple_shutdown, "_active_handles", [rejecting])

        assert health_check_manager.publish_health_status_to_core("unhealthy") is False

    def test_one_bad_handle_does_not_block_the_others(
        self, fake_core, no_handles, monkeypatch
    ):
        exploding = FakeHandle(raises=True)
        good = FakeHandle()
        monkeypatch.setattr(simple_shutdown, "_active_handles", [exploding, good])

        assert health_check_manager.publish_health_status_to_core("unhealthy") is True
        assert good.calls == [FakeHealthStatus.Unhealthy]


class TestRealCoreSurface:
    """Guard the actual native surface the publisher depends on.

    The fakes above deliberately don't exercise ``mcp_mesh_core`` itself, and
    that blind spot is real: ``HealthStatus`` was registered on the pymodule
    but missing from the package's ``__init__`` re-exports, so
    ``mcp_mesh_core.HealthStatus`` raised AttributeError at runtime while
    every mocked test stayed green.
    """

    def test_core_exposes_health_status_and_update_health(self):
        core = pytest.importorskip(
            "mcp_mesh_core", reason="native core not built in this environment"
        )

        # Reached as attributes on the package, which is how the publisher
        # (and any SDK author) gets at them.
        assert core.HealthStatus.Healthy is not None
        assert core.HealthStatus.Degraded is not None
        assert core.HealthStatus.Unhealthy is not None
        assert hasattr(core.AgentHandle, "update_health")


class TestHandleRegistryAccessor:
    """``get_active_rust_agent_handles`` is the late-bound route from the
    health refresh loop back to the handle created inside the lifespan task.
    """

    def test_returns_registered_handles(self, no_handles):
        handle = FakeHandle()
        simple_shutdown.register_rust_agent_handle(handle)
        assert simple_shutdown.get_active_rust_agent_handles() == [handle]

    def test_returns_a_copy(self, no_handles):
        handle = FakeHandle()
        simple_shutdown.register_rust_agent_handle(handle)

        snapshot = simple_shutdown.get_active_rust_agent_handles()
        snapshot.clear()

        assert simple_shutdown.get_active_rust_agent_handles() == [handle]

    def test_unregistered_handle_is_dropped(self, no_handles):
        handle = FakeHandle()
        simple_shutdown.register_rust_agent_handle(handle)
        simple_shutdown.unregister_rust_agent_handle(handle)
        assert simple_shutdown.get_active_rust_agent_handles() == []
