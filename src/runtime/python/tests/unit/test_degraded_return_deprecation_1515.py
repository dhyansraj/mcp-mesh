"""`degraded` as a health-check RETURN VALUE is deprecated (#1515).

The question a health check answers is binary: stay in dependency resolution,
or withdraw. ``degraded`` and ``healthy`` are the same answer to it — both keep
the heartbeat alive and both keep consumers routing here — so the third word
buys a 503 on an endpoint nothing probes and costs the failure rate of a name
that reads like withdrawal to everyone who picks it when their upstream is
down.

Two things are pinned here, and the second matters more than the first:

1. selecting ``degraded`` warns, naming the CONSEQUENCE rather than the value;
2. **behaviour is unchanged.** An agent returning ``degraded`` still records
   DEGRADED, still heartbeats and still resolves. Remapping it to ``unhealthy``
   would fix the common intent and silently withdraw every agent whose author
   used the word correctly, so the deprecation warns and waits.

The runtime's OWN degraded verdicts — a check that raised, an unusable return
type — must NOT warn: nothing the author can act on happened, and a warning
there would tell them to change code that is already right.
"""

import logging
from typing import Any

import pytest

from _mcp_mesh.shared.health_check_manager import (
    _reset_degraded_return_warning,
    clear_health_cache,
    get_health_status_with_cache,
)
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

AGENT_CONFIG: dict[str, Any] = {
    "name": "deprecation-agent",
    "version": "1.0.0",
    "capabilities": ["test-capability"],
}

# The consequence, not the value. An author who reads "degraded is deprecated"
# learns nothing; one who reads "consumers will keep routing to it" learns
# whether they meant it.
WARNING_FRAGMENTS = (
    "stays in dependency resolution",
    "consumers will keep routing to it",
    "Return `False` to withdraw",
)


@pytest.fixture(autouse=True)
def fresh_state():
    clear_health_cache()
    _reset_degraded_return_warning()
    yield
    clear_health_cache()
    _reset_degraded_return_warning()


async def run_check(check, agent_id: str) -> HealthStatus:
    """Run one uncached health check and return its recorded status."""
    return await get_health_status_with_cache(
        agent_id=agent_id,
        health_check_fn=check,
        agent_config=AGENT_CONFIG,
        startup_context={},
        ttl=15,
    )


def degraded_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "keep routing to it" in r.getMessage()
    ]


class TestSelectingDegradedWarns:
    """A verdict the AUTHOR chose is the only one that warns."""

    @pytest.mark.asyncio
    async def test_dict_status_degraded_warns(self, caplog):
        async def check():
            return {"status": "degraded", "errors": ["upstream slow"]}

        with caplog.at_level(logging.WARNING):
            await run_check(check, "dict-degraded")

        warnings = degraded_warnings(caplog)
        assert len(warnings) == 1, f"expected one deprecation warning, got {warnings}"
        for fragment in WARNING_FRAGMENTS:
            assert fragment in warnings[0], (
                f"the warning must name the consequence: {fragment!r} missing from "
                f"{warnings[0]!r}"
            )

    @pytest.mark.asyncio
    async def test_case_and_whitespace_variants_still_warn(self, caplog):
        """The parser strips and lowercases, so the warning must follow it.

        A deprecation that only fires on the exact literal would let
        ``" DEGRADED "`` through silently while routing it identically.
        """

        async def check():
            return {"status": "  DeGrAdEd  "}

        with caplog.at_level(logging.WARNING):
            status = await run_check(check, "spaced-degraded")

        assert status.status == HealthStatusType.DEGRADED
        assert len(degraded_warnings(caplog)) == 1

    @pytest.mark.asyncio
    async def test_health_status_object_degraded_warns(self, caplog):
        """A returned ``HealthStatus`` is a selection too, not an internal path."""

        async def check():
            return HealthStatus(
                agent_name="deprecation-agent",
                status=HealthStatusType.DEGRADED,
                capabilities=["test-capability"],
                checks={},
                errors=[],
            )

        with caplog.at_level(logging.WARNING):
            await run_check(check, "object-degraded")

        assert len(degraded_warnings(caplog)) == 1


class TestBehaviourIsUnchanged:
    """The whole point of warning rather than remapping.

    An author who used ``degraded`` correctly — impaired, still serving — must
    keep serving. If any of these flip to UNHEALTHY, the deprecation has
    silently withdrawn working agents from the mesh.
    """

    @pytest.mark.asyncio
    async def test_degraded_still_records_degraded(self):
        async def check():
            return {"status": "degraded", "checks": {"cache_warm": False}}

        status = await run_check(check, "still-degraded")

        assert status.status == HealthStatusType.DEGRADED, (
            "remapping degraded to unhealthy would withdraw every agent whose "
            "author used the word correctly"
        )
        assert status.checks == {"cache_warm": False}

    @pytest.mark.asyncio
    async def test_degraded_is_not_a_withdrawal(self):
        """The routing question, asked directly.

        ``unhealthy`` is the only verdict the core suppresses the heartbeat on,
        so a degraded agent stays in dependency resolution — which is exactly
        what the warning tells its author.
        """

        async def check():
            return {"status": "degraded"}

        status = await run_check(check, "not-withdrawn")

        assert status.status != HealthStatusType.UNHEALTHY


class TestRuntimeAssignedDegradedIsSilent:
    """The four indeterminate paths keep the internal state and say nothing."""

    @pytest.mark.asyncio
    async def test_a_raising_check_does_not_warn(self, caplog):
        async def check():
            raise RuntimeError("probe blew up")

        with caplog.at_level(logging.WARNING):
            status = await run_check(check, "raising")

        assert status.status == HealthStatusType.DEGRADED
        assert degraded_warnings(caplog) == [], (
            "the author did not choose this verdict — the runtime assigned it "
            "because the probe reached no conclusion"
        )

    @pytest.mark.asyncio
    async def test_an_unusable_return_type_does_not_warn(self, caplog):
        async def check():
            return 42

        with caplog.at_level(logging.WARNING):
            status = await run_check(check, "bad-type")

        assert status.status == HealthStatusType.DEGRADED
        assert degraded_warnings(caplog) == []

    @pytest.mark.asyncio
    async def test_healthy_and_unhealthy_do_not_warn(self, caplog):
        async def healthy():
            return {"status": "healthy"}

        async def unhealthy():
            return False

        with caplog.at_level(logging.WARNING):
            assert (await run_check(healthy, "ok")).status == HealthStatusType.HEALTHY
            assert (
                await run_check(unhealthy, "down")
            ).status == HealthStatusType.UNHEALTHY

        assert degraded_warnings(caplog) == []


class TestWarnedOncePerProcess:
    """A check re-runs every TTL; a per-tick warning is not a warning.

    At the 15s default that is ~5,760 identical lines a day from an agent doing
    exactly what its author intended, which trains an operator to filter the
    line rather than read it.
    """

    @pytest.mark.asyncio
    async def test_repeated_degraded_warns_once(self, caplog):
        async def check():
            return {"status": "degraded"}

        with caplog.at_level(logging.WARNING):
            for i in range(5):
                # Distinct agent ids: the TTL cache would otherwise serve the
                # first result and the check would run once regardless, so the
                # test would pass without the dedup being there at all.
                status = await run_check(check, f"repeat-{i}")
                assert status.status == HealthStatusType.DEGRADED

        assert len(degraded_warnings(caplog)) == 1
