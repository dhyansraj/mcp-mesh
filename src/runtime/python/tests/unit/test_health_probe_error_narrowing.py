"""A defect in a health probe must not withdraw a working agent (#1477).

The scaffolded provider probes report a vendor OUTAGE as ``unhealthy``, which
is the whole point of the hook: it suppresses the heartbeat and the registry
takes the agent out of dependency resolution. Their handlers used to be
``except Exception``, so any defect inside the probe — a ``NameError`` from a
typo, an ``AttributeError`` from a renamed field — was reported as that same
outage. It recurs identically on every refresh, so the agent stays withdrawn
for as long as the typo lives, while the vendor is perfectly healthy.

The runtime already refuses to draw that conclusion: an exception that escapes
a health check is recorded as the indeterminate verdict, which keeps the agent
heartbeating. The probes have to LET it escape to get that, which is what
narrowing the handler to ``httpx.RequestError`` does.

These tests run the two probe shapes through the real health-check path and
follow the verdict all the way to what the Rust core is told, because that —
not the recorded status — is what actually suppresses a heartbeat.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from _mcp_mesh.shared import simple_shutdown
from _mcp_mesh.shared.health_check_manager import (
    clear_health_cache,
    get_health_status_with_cache,
    publish_health_status_to_core,
)
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

AGENT_CONFIG: dict[str, Any] = {
    "name": "probe-agent",
    "version": "1.0.0",
    "capabilities": ["llm"],
}


class FakeCoreHealthStatus:
    """Stand-in for the Rust ``mcp_mesh_core.HealthStatus`` pyclass enum."""

    Healthy = "core.Healthy"
    Degraded = "core.Degraded"
    Unhealthy = "core.Unhealthy"


class FakeHandle:
    def __init__(self) -> None:
        self.calls: list = []

    def update_health(self, status):
        self.calls.append(status)
        return True


@pytest.fixture
def core_handle(monkeypatch):
    """A live core handle, so the verdict has somewhere to be published."""
    monkeypatch.setitem(
        sys.modules, "mcp_mesh_core", SimpleNamespace(HealthStatus=FakeCoreHealthStatus)
    )
    handle = FakeHandle()
    monkeypatch.setattr(simple_shutdown, "_active_handles", [handle])
    return handle


@pytest.fixture(autouse=True)
def clear_cache():
    clear_health_cache()
    yield
    clear_health_cache()


async def run_check(check, agent_id: str) -> HealthStatus:
    return await get_health_status_with_cache(
        agent_id=agent_id,
        health_check_fn=check,
        agent_config=AGENT_CONFIG,
        startup_context={},
        ttl=15,
    )


# --------------------------------------------------------------------------
# The two probe shapes, written the way the templates write them.
# --------------------------------------------------------------------------


def narrowed_probe(fail_with: BaseException):
    """The scaffolded probe: it answers for transport failures only."""

    async def health_check() -> dict:
        checks: dict[str, Any] = {"anthropic_api_key_present": True}
        errors: list[str] = []
        try:
            raise fail_with
        except httpx.RequestError as e:
            checks["anthropic_api_reachable"] = False
            errors.append(f"Anthropic API unreachable: {e}")
            return {"status": "unhealthy", "checks": checks, "errors": errors}
        return {"status": "healthy", "checks": checks, "errors": errors}

    return health_check


def catch_all_probe(fail_with: BaseException):
    """The shape this test exists to keep out: it answers for everything."""

    async def health_check() -> dict:
        checks: dict[str, Any] = {"anthropic_api_key_present": True}
        try:
            raise fail_with
        except Exception as e:  # noqa: BLE001 - the defect being demonstrated
            checks["anthropic_api_reachable"] = False
            return {
                "status": "unhealthy",
                "checks": checks,
                "errors": [f"Anthropic API unreachable: {e}"],
            }

    return health_check


class TestADefectInTheProbeDoesNotWithdrawTheAgent:
    @pytest.mark.asyncio
    async def test_non_transport_error_propagates_to_the_indeterminate_verdict(self):
        """A ``NameError`` in the probe reaches the runtime, not the vendor branch."""
        probe = narrowed_probe(NameError("name 'reponse' is not defined"))

        result = await run_check(probe, "narrowed-defect")

        # The runtime's own verdict for a check it could not trust.
        assert result.status is HealthStatusType.DEGRADED
        assert result.checks == {"health_check_execution": False}
        assert "reponse" in result.errors[0]

    @pytest.mark.asyncio
    async def test_the_agent_keeps_heartbeating_through_that_defect(self, core_handle):
        """The verdict that reaches the core is not the one that withdraws."""
        probe = narrowed_probe(AttributeError("'NoneType' object has no attribute 'x'"))

        result = await run_check(probe, "narrowed-defect-publish")
        published = publish_health_status_to_core(result.status.value)

        assert published is True
        assert core_handle.calls == [FakeCoreHealthStatus.Degraded]
        # Unhealthy is what suppresses the heartbeat. Nothing else does.
        assert FakeCoreHealthStatus.Unhealthy not in core_handle.calls

    @pytest.mark.asyncio
    async def test_a_catch_all_handler_would_have_withdrawn_it(self, core_handle):
        """The regression, made explicit: same defect, same probe, wider handler.

        This is the outcome the narrowing prevents — and the reason it is not
        merely tidier. The verdict is indistinguishable from a real vendor
        outage, so the agent stays out of dependency resolution for as long as
        the typo lives.
        """
        probe = catch_all_probe(NameError("name 'reponse' is not defined"))

        result = await run_check(probe, "catch-all-defect")
        publish_health_status_to_core(result.status.value)

        assert result.status is HealthStatusType.UNHEALTHY
        assert core_handle.calls == [FakeCoreHealthStatus.Unhealthy]


class TestATransportFailureStillWithdrawsTheAgent:
    """The narrowing must not have cost the probe the case it exists for."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ConnectError("[Errno 8] nodename nor servname provided"),
            httpx.ReadTimeout("timed out"),
            httpx.ConnectTimeout("timed out"),
            httpx.RemoteProtocolError("server disconnected"),
        ],
        ids=["dns", "read-timeout", "connect-timeout", "protocol"],
    )
    async def test_transport_failures_report_unhealthy(self, failure, core_handle):
        probe = narrowed_probe(failure)

        result = await run_check(probe, f"transport-{type(failure).__name__}")
        publish_health_status_to_core(result.status.value)

        assert result.status is HealthStatusType.UNHEALTHY
        assert result.checks["anthropic_api_reachable"] is False
        assert core_handle.calls == [FakeCoreHealthStatus.Unhealthy]


class TestNonStringStatusIsUnknownNotAnException:
    """A status that is not a string is unreadable, not a failed check.

    ``{"status": 503}`` used to reach ``.strip()``, raise, and be recorded by
    the handler as a check that FAILED — the same routing outcome by accident,
    reported to the author as an exception they cannot find in their own code.
    It now takes the same verdict an unrecognized status STRING takes.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [503, 1, 0.0, ["unhealthy"], {"status": "unhealthy"}, object()],
        ids=["int", "one", "float", "list", "dict", "object"],
    )
    async def test_non_string_status_is_unknown(self, status):
        async def health_check() -> dict:
            return {"status": status, "checks": {"api": True}}

        result = await run_check(health_check, f"non-string-{type(status).__name__}")

        assert result.status is HealthStatusType.UNKNOWN
        # Not the throw path: the check ran and its `checks` survived.
        assert result.checks == {"api": True}
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_a_bool_status_is_not_read_as_a_verdict(self):
        """``{"status": False}`` is not ``False``.

        A bare ``False`` return withdraws the agent; wrapping it in a dict
        under ``status`` does not, because the value is not a status string.
        Unknown keeps the agent heartbeating, which is the safe reading of a
        result nobody can interpret.
        """

        async def health_check() -> dict:
            return {"status": False}

        result = await run_check(health_check, "bool-status")
        assert result.status is HealthStatusType.UNKNOWN
        assert result.status is not HealthStatusType.UNHEALTHY

    @pytest.mark.asyncio
    async def test_unknown_keeps_the_agent_heartbeating(self, core_handle):
        async def health_check() -> dict:
            return {"status": 503}

        result = await run_check(health_check, "non-string-publish")
        publish_health_status_to_core(result.status.value)

        assert core_handle.calls == [FakeCoreHealthStatus.Degraded]
        assert FakeCoreHealthStatus.Unhealthy not in core_handle.calls
