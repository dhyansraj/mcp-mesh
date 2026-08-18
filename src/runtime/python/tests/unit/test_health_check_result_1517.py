"""Health-check return-value parsing, and where it used to diverge (#1517).

Four independent divergences, each small, each reachable from ordinary user
code and none of them loud:

1. a ``def health_check()`` was awaited unguarded, so it raised ``TypeError``
   and was recorded as DEGRADED — a check that appeared to run and could never
   withdraw the agent;
2. a status string was lowercased but not stripped, so ``" degraded "`` became
   UNKNOWN;
3. an explicit ``{"status": None}`` called ``None.lower()``, raised, and landed
   on DEGRADED, while TypeScript read it as healthy;
4. the OpenAPI description had the UNKNOWN and DEGRADED cases the wrong way
   round.

DEGRADED vs UNHEALTHY is a behavioural difference, not a reporting one: only
``unhealthy`` suppresses the heartbeat, so a check that silently degrades is a
check that cannot do the one thing it exists for.
"""

import logging
import threading
from typing import Any

import pytest

from _mcp_mesh.shared.health_check_manager import (
    _reset_null_status_warning,
    clear_health_cache,
    get_health_status_with_cache,
)
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

AGENT_CONFIG: dict[str, Any] = {
    "name": "verdict-agent",
    "version": "1.0.0",
    "capabilities": ["test-capability"],
}


@pytest.fixture(autouse=True)
def clear_cache():
    clear_health_cache()
    _reset_null_status_warning()
    yield
    clear_health_cache()
    _reset_null_status_warning()


async def run_check(check, agent_id: str) -> HealthStatus:
    """Run one uncached health check and return its recorded status."""
    return await get_health_status_with_cache(
        agent_id=agent_id,
        health_check_fn=check,
        agent_config=AGENT_CONFIG,
        startup_context={},
        ttl=15,
    )


class TestSyncAndAsyncBothAccepted:
    """Divergence 1: a sync check must produce its real verdict.

    ``startup_check`` has accepted both since it shipped; the two hooks
    disagreeing is what made this a silent trap rather than a documented
    restriction.
    """

    @pytest.mark.asyncio
    async def test_sync_dict_check_withdraws(self):
        def health_check() -> dict:
            return {"status": "unhealthy", "errors": ["vendor down"]}

        result = await run_check(health_check, "sync-dict")

        # The assertion that fails if the unguarded await comes back: the
        # TypeError it raised was recorded as DEGRADED, which keeps
        # heartbeating.
        assert result.status == HealthStatusType.UNHEALTHY
        assert result.errors == ["vendor down"]

    @pytest.mark.asyncio
    async def test_sync_bool_check(self):
        assert (
            await run_check(lambda: True, "sync-true")
        ).status == HealthStatusType.HEALTHY
        assert (
            await run_check(lambda: False, "sync-false")
        ).status == HealthStatusType.UNHEALTHY

    @pytest.mark.asyncio
    async def test_sync_health_status_check(self):
        def health_check() -> HealthStatus:
            return HealthStatus(
                agent_name="verdict-agent",
                status=HealthStatusType.UNHEALTHY,
                capabilities=["test"],
            )

        result = await run_check(health_check, "sync-healthstatus")
        assert result.status == HealthStatusType.UNHEALTHY

    @pytest.mark.asyncio
    async def test_async_check_still_works(self):
        async def health_check() -> dict:
            return {"status": "unhealthy", "errors": ["vendor down"]}

        result = await run_check(health_check, "async-dict")
        assert result.status == HealthStatusType.UNHEALTHY
        assert result.errors == ["vendor down"]

    @pytest.mark.asyncio
    async def test_a_sync_check_that_raises_still_degrades(self):
        """The sync path keeps the "a broken probe does not withdraw" rule."""

        def health_check() -> dict:
            raise RuntimeError("boom")

        result = await run_check(health_check, "sync-raises")
        assert result.status == HealthStatusType.DEGRADED
        assert result.checks["health_check_execution"] is False
        assert "boom" in result.errors[0]

    @pytest.mark.asyncio
    async def test_a_sync_check_does_not_block_the_loop(self):
        """Accepting sync checks is what makes this necessary.

        The natural sync probe is a blocking ``requests.get(vendor,
        timeout=5)``. Unlike ``startup_check`` this runs every TTL forever,
        and on ``api``/``a2a`` gateways it runs on the HEARTBEAT thread's
        loop — so a slow probe run inline would delay the very heartbeats
        whose absence withdraws the agent.
        """
        ran_on: dict[str, int] = {}

        def health_check() -> dict:
            # A real blocking call would sleep here; the thread identity is
            # the whole assertion, so the sleep is not needed.
            ran_on["thread"] = threading.get_ident()
            return {"status": "healthy"}

        loop_thread = threading.get_ident()
        result = await run_check(health_check, "sync-offloaded")

        assert result.status == HealthStatusType.HEALTHY
        assert ran_on["thread"] != loop_thread, (
            "a sync health check must not run inline on the event loop — every "
            "TTL, for the life of the process"
        )

    @pytest.mark.asyncio
    async def test_an_async_check_still_runs_on_the_loop(self):
        """The offload is for sync checks only.

        An ``async def`` check is awaited on the calling loop, which is what
        lets the provider path see loop-affine resources (asyncpg pools,
        redis.asyncio clients) built in the user's ``lifespan``.
        """
        ran_on: dict[str, int] = {}

        async def health_check() -> dict:
            ran_on["thread"] = threading.get_ident()
            return {"status": "healthy"}

        loop_thread = threading.get_ident()
        await run_check(health_check, "async-on-loop")

        assert ran_on["thread"] == loop_thread


class TestStatusStringIsStripped:
    """Divergence 2: whitespace around a status is not a verdict change.

    TypeScript's ``toStatus`` and Java's ``MeshHealthStatus.fromWire`` both
    trim; Python lowercased only, so ``" unhealthy "`` mapped to UNKNOWN and
    the agent kept heartbeating.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (" unhealthy ", HealthStatusType.UNHEALTHY),
            ("\tunhealthy\n", HealthStatusType.UNHEALTHY),
            (" degraded ", HealthStatusType.DEGRADED),
            (" healthy ", HealthStatusType.HEALTHY),
            (" UNHEALTHY ", HealthStatusType.UNHEALTHY),
        ],
    )
    @pytest.mark.asyncio
    async def test_surrounding_whitespace_and_case(self, raw, expected):
        async def health_check() -> dict:
            return {"status": raw}

        result = await run_check(
            health_check, f"strip-{raw.strip().lower()}-{len(raw)}"
        )
        assert result.status == expected


class TestNullStatusIsHealthyAndWarns:
    """Divergence 3: an explicit null status reads as an absent one.

    An absent ``status`` already defaults to healthy in Python and TypeScript,
    so making ``None`` mean something else would be surprising. It warns
    because ``{"status": None}`` is far likelier to be an unset variable than
    an intent — and a warning separates the two cases without changing routing.
    """

    @pytest.mark.asyncio
    async def test_null_status_is_healthy_and_warns(self, caplog):
        async def health_check() -> dict:
            return {"status": None, "checks": {"api_reachable": True}}

        with caplog.at_level(
            logging.WARNING, logger="_mcp_mesh.shared.health_check_manager"
        ):
            result = await run_check(health_check, "null-status")

        assert result.status == HealthStatusType.HEALTHY
        # Not DEGRADED: that was the old outcome, reached by raising on
        # None.lower() rather than by any decision.
        assert result.status != HealthStatusType.DEGRADED
        assert result.checks == {"api_reachable": True}
        assert any("null status" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_absent_status_is_healthy_and_silent(self, caplog):
        async def health_check() -> dict:
            return {"checks": {"api_reachable": True}}

        with caplog.at_level(
            logging.WARNING, logger="_mcp_mesh.shared.health_check_manager"
        ):
            result = await run_check(health_check, "absent-status")

        assert result.status == HealthStatusType.HEALTHY
        assert not [r for r in caplog.records if "null status" in r.message]

    @pytest.mark.asyncio
    async def test_the_null_status_warning_is_once_per_process(self, caplog):
        """Same repetition profile as the `degraded` deprecation, same dedup.

        A null status recurs identically on every refresh, so an
        undeduplicated line is ~5,760 a day at the 15s default TTL — which
        trains an operator to filter it rather than read it.
        """

        async def health_check() -> dict:
            return {"status": None}

        with caplog.at_level(
            logging.WARNING, logger="_mcp_mesh.shared.health_check_manager"
        ):
            for i in range(5):
                # Distinct agent ids: the TTL cache would otherwise serve the
                # first verdict and the check would run once regardless.
                result = await run_check(health_check, f"null-repeat-{i}")
                assert result.status == HealthStatusType.HEALTHY

        assert len([r for r in caplog.records if "null status" in r.message]) == 1


class TestUnknownIsAStatusStringNotAReturnType:
    """Divergence 4: what the shared OpenAPI schema now says.

    ``AgentHealthResponse.status`` described ``unknown`` as the verdict for an
    unrecognized return TYPE. It is the opposite, and the two cases behave
    differently, so the description mattered: a bad type degrades with an error
    naming the type, while a bad status string is recorded as UNKNOWN.
    """

    @pytest.mark.asyncio
    async def test_unrecognized_status_string_is_unknown(self):
        async def health_check() -> dict:
            return {"status": "down"}

        result = await run_check(health_check, "unknown-status-string")
        assert result.status == HealthStatusType.UNKNOWN

    @pytest.mark.asyncio
    async def test_unrecognized_return_type_is_degraded(self):
        async def health_check() -> Any:
            return 42

        result = await run_check(health_check, "bad-return-type")
        assert result.status == HealthStatusType.DEGRADED
        assert result.checks["health_check_return_type"] is False
        assert "int" in result.errors[0]
