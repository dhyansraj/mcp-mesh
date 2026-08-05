"""MCP_MESH_HEALTH_CHECK_TTL resolution (issue #1492).

Parity with TypeScript's ``resolveHealthCheckTtl`` and Java's
``MeshHealthCheckRegistry.ttlSeconds``: env > decorator argument > 15, with
every rejected value warning and falling through to the next source instead
of raising.

The resolution rules are driven through the ``override`` parameter so they
are exercised without mutating ``os.environ``; only the thin env-reading
wrapper needs a monkeypatched environment.
"""

import logging

import pytest
from _mcp_mesh.shared.health_check_manager import (
    DEFAULT_HEALTH_CHECK_TTL_SECONDS,
    HEALTH_CHECK_TTL_ENV,
    resolve_health_check_ttl,
    resolve_health_check_ttl_from_env,
)


@pytest.fixture
def warnings(caplog):
    """Live view of the warning records emitted by the resolver.

    ``caplog.records`` is per-phase, so the list is read inside the test
    body rather than captured here during setup.
    """
    caplog.set_level(logging.WARNING, logger="_mcp_mesh.shared.health_check_manager")

    class _Warnings:
        @property
        def records(self):
            return [r for r in caplog.records if r.levelno >= logging.WARNING]

        def __len__(self):
            return len(self.records)

        def __getitem__(self, index):
            return self.records[index]

        def __eq__(self, other):
            return self.records == other

        def __repr__(self):
            return repr([r.getMessage() for r in self.records])

    return _Warnings()


class TestResolveHealthCheckTtl:
    """The env-free core."""

    def test_defaults_to_15s(self, warnings):
        assert resolve_health_check_ttl() == DEFAULT_HEALTH_CHECK_TTL_SECONDS
        assert resolve_health_check_ttl(None, None) == 15
        assert warnings == []

    @pytest.mark.parametrize("configured", [30, 1, 3600])
    def test_takes_a_valid_configured_value(self, configured, warnings):
        assert resolve_health_check_ttl(configured) == configured
        assert warnings == []

    @pytest.mark.parametrize(
        "label,configured",
        [
            ("zero", 0),
            ("negative", -5),
            ("sub-second", 0.5),
            ("non-integer", 2.5),
            ("string", "30"),
            ("bool", True),
            ("nan", float("nan")),
            ("inf", float("inf")),
        ],
    )
    def test_rejects_an_invalid_configured_value_and_warns(
        self, label, configured, warnings
    ):
        assert resolve_health_check_ttl(configured) == 15
        assert len(warnings) == 1

    # --- env wins over the decorator argument -----------------------------

    def test_env_overrides_the_configured_value(self, warnings):
        assert resolve_health_check_ttl(30, "5") == 5
        assert resolve_health_check_ttl(30, "  7  ") == 7
        assert resolve_health_check_ttl(30, "+9") == 9
        assert warnings == []

    def test_env_overrides_the_default_with_no_configured_value(self, warnings):
        assert resolve_health_check_ttl(None, "45") == 45
        assert resolve_health_check_ttl(override="45") == 45
        assert warnings == []

    # --- rejected env forms fall through to the next source ---------------

    @pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
    def test_blank_env_is_not_set_rather_than_an_error(self, raw, warnings):
        assert resolve_health_check_ttl(30, raw) == 30
        assert resolve_health_check_ttl(None, raw) == 15
        assert warnings == []

    @pytest.mark.parametrize(
        "label,raw",
        [
            ("duration suffix", "15s"),
            ("float", "1.5"),
            ("hex", "0x10"),
            ("words", "fifteen"),
            ("trailing junk", "10 seconds"),
            ("underscored int", "1_0"),
            ("unicode digit", "١٥"),
        ],
    )
    def test_rejects_a_non_integer_env_value(self, label, raw, warnings):
        assert resolve_health_check_ttl(30, raw) == 30
        assert len(warnings) == 1
        assert "not an integer" in warnings[0].getMessage()

    @pytest.mark.parametrize("raw", ["0", "-3", "-1"])
    def test_rejects_a_sub_1s_env_value(self, raw, warnings):
        assert resolve_health_check_ttl(30, raw) == 30
        assert len(warnings) == 1
        assert "below the 1s minimum" in warnings[0].getMessage()

    def test_rejected_env_falls_back_to_the_default_without_a_configured_value(
        self, warnings
    ):
        assert resolve_health_check_ttl(None, "0") == 15
        assert resolve_health_check_ttl(None, "15s") == 15
        assert len(warnings) == 2

    def test_falls_back_to_the_default_when_both_sources_are_invalid(self, warnings):
        assert resolve_health_check_ttl(0, "0") == 15
        assert len(warnings) == 2

    def test_warns_with_the_value_that_wins(self, warnings):
        """A warning must name the TTL the agent actually runs with."""
        assert resolve_health_check_ttl(0, "7") == 7
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "health_check_ttl=0" in message
        assert "using 7s" in message
        assert "using 15s" not in message

    def test_never_raises_on_a_malformed_value(self):
        """A malformed TTL must not stop an agent from booting."""
        assert resolve_health_check_ttl(object(), object()) == 15


class TestResolveHealthCheckTtlFromEnv:
    """The thin env-reading wrapper."""

    def test_env_absent_uses_the_configured_value(self, monkeypatch, warnings):
        monkeypatch.delenv(HEALTH_CHECK_TTL_ENV, raising=False)
        assert resolve_health_check_ttl_from_env(30) == 30
        assert resolve_health_check_ttl_from_env() == 15
        assert warnings == []

    def test_env_present_wins(self, monkeypatch, warnings):
        monkeypatch.setenv(HEALTH_CHECK_TTL_ENV, "3")
        assert resolve_health_check_ttl_from_env(30) == 3
        assert resolve_health_check_ttl_from_env() == 3
        assert warnings == []

    def test_invalid_env_falls_back_to_the_configured_value(self, monkeypatch):
        monkeypatch.setenv(HEALTH_CHECK_TTL_ENV, "15s")
        assert resolve_health_check_ttl_from_env(30) == 30


class TestHealthEndpointWiring:
    """The resolver is actually wired into the TTL the agent runs with."""

    @staticmethod
    async def _run(agent_config):
        from unittest.mock import AsyncMock, MagicMock, patch

        from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import (
            FastAPIServerSetupStep,
        )

        with (
            patch(
                "_mcp_mesh.shared.health_check_manager.get_health_status_with_cache",
                new_callable=AsyncMock,
            ) as mock_cache,
            patch("_mcp_mesh.shared.tool_executor._start_workers"),
            patch("_mcp_mesh.shared.tool_executor.get_worker_loops", return_value=[]),
        ):
            mock_cache.return_value = _healthy_status()
            await FastAPIServerSetupStep()._add_k8s_endpoints(
                MagicMock(), agent_config, {}, {}
            )
        return mock_cache.await_args.kwargs["ttl"]

    @pytest.mark.asyncio
    async def test_env_overrides_the_decorator_argument(self, monkeypatch):
        monkeypatch.setenv(HEALTH_CHECK_TTL_ENV, "42")
        ttl = await self._run(
            {
                "name": "ttl-agent",
                "health_check": _health_check_fn,
                "health_check_ttl": 30,
            }
        )
        assert ttl == 42

    @pytest.mark.asyncio
    async def test_decorator_argument_without_env(self, monkeypatch):
        monkeypatch.delenv(HEALTH_CHECK_TTL_ENV, raising=False)
        ttl = await self._run(
            {
                "name": "ttl-agent",
                "health_check": _health_check_fn,
                "health_check_ttl": 30,
            }
        )
        assert ttl == 30


async def _health_check_fn():
    return True


def _healthy_status():
    from datetime import UTC, datetime

    from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

    return HealthStatus(
        agent_name="ttl-agent",
        status=HealthStatusType.HEALTHY,
        capabilities=["ttl"],
        timestamp=datetime.now(UTC),
        checks={},
        errors=[],
    )
