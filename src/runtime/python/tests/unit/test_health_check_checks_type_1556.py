"""A non-bool in ``checks`` must report, not disappear (#1556).

``HealthStatus.checks`` is ``dict[str, bool]``. Writing ``checks["disk"] = "ok"``
instead of ``True`` used to raise inside Pydantic while the result was being
BUILT — after the handler that catches a failing check, and inside the
``fastapi-server-setup`` pipeline step. That step was optional, so the pipeline
went "partial", auto-run found no app to serve, and the process stayed up
answering /livez and /startupz with 200 while never registering. The agent was
absent rather than unhealthy: nothing in the registry, nothing to restart it,
and the only explanation on stdout.

Three things are pinned here, matching the three places the failure travelled
through:

1. the value error never reaches the pipeline — the verdict survives, the
   unusable detail is dropped and reported (#1539's principle, applied to a
   wrong value type inside ``checks`` rather than a wrong return type);
2. the verdict is NOT overridden — an author who said ``unhealthy`` and also
   mistyped a check still withdraws;
3. ``fastapi-server-setup`` is required, so a failure that genuinely leaves no
   server is fatal rather than "partial" — and having nothing to mount still
   succeeds, which is the case the optional flag was written for.
"""

import os
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import pytest

from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import FastAPIServerSetupStep
from _mcp_mesh.pipeline.shared import PipelineStatus
from _mcp_mesh.pipeline.shared.health_refresh import refresh_health_once
from _mcp_mesh.shared.health_check_manager import (
    clear_health_cache,
    get_health_status_with_cache,
)
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

AGENT_CONFIG: dict[str, Any] = {
    "name": "checks-agent",
    "version": "1.0.0",
    "capabilities": ["test-capability"],
}


def _reset_warning() -> None:
    """Re-arm the once-per-process warning.

    Resolved through the module rather than imported at the top, so the tests
    that reproduce the reported failure fail on that failure — not on a missing
    private helper before any of them run.
    """
    from _mcp_mesh.shared import health_check_manager

    health_check_manager._reset_unusable_checks_warning()


@pytest.fixture(autouse=True)
def clean_state():
    clear_health_cache()
    yield
    clear_health_cache()


async def run_check(check, agent_id: str = "checks-agent") -> HealthStatus:
    """Run one uncached health check and return its recorded status."""
    return await get_health_status_with_cache(
        agent_id=agent_id,
        health_check_fn=check,
        agent_config=AGENT_CONFIG,
        startup_context={},
        ttl=15,
    )


class TestTheReproduction:
    """``checks["disk_space"] = "ok"`` — the reported one-character mistake."""

    @pytest.mark.asyncio
    async def test_string_check_value_does_not_raise(self):
        async def health_check() -> dict:
            return {
                "status": "healthy",
                "checks": {"env_key": True, "disk_space": "ok"},
                "errors": [],
            }

        status = await run_check(health_check)

        assert status.status == HealthStatusType.HEALTHY
        # The readable checks survive; the unusable one does not pretend to
        # have a verdict.
        assert status.checks["env_key"] is True
        assert "disk_space" not in status.checks
        assert status.checks["health_check_checks_type"] is False

    @pytest.mark.asyncio
    async def test_the_offending_check_is_named_on_health(self):
        """/health is the durable surface — the log warns once, this stays."""

        async def health_check() -> dict:
            return {"checks": {"disk_space": "ok"}}

        status = await run_check(health_check)

        reported = " ".join(status.errors)
        assert "disk_space" in reported
        assert "str" in reported
        assert "bool" in reported

    @pytest.mark.asyncio
    async def test_seed_refresh_stores_a_result(self):
        """The exact call the pipeline step makes at startup (the crash site).

        ``_add_k8s_endpoints`` seeds ``/health`` with this before anything is
        mounted; the raise here is what took ``fastapi-server-setup`` down.
        """

        async def health_check() -> dict:
            return {"status": "healthy", "checks": {"disk_space": "ok"}}

        result = await refresh_health_once(
            agent_name="checks-agent",
            health_check_fn=health_check,
            agent_config=AGENT_CONFIG,
            startup_context={},
            ttl_seconds=15,
            publish_to_core=False,
        )

        assert result["status"] == "healthy"
        assert result["checks"]["health_check_checks_type"] is False


class TestTheOperatorIsToldOnce:
    """The Pydantic traceback was the only explanation anywhere. Replace it.

    Once per process, like the neighbouring health-parse warnings: the check
    re-runs every TTL, so a per-tick line is thousands of copies of one typo a
    day. The durable copy is in the result's ``errors``, which /health serves on
    every request.
    """

    @pytest.mark.asyncio
    async def test_warns_once_not_every_refresh(self, caplog):
        import logging

        async def health_check() -> dict:
            return {"checks": {"disk_space": "ok"}}

        _reset_warning()
        try:
            with caplog.at_level(logging.WARNING):
                for _ in range(3):
                    clear_health_cache()
                    await run_check(health_check)
        finally:
            _reset_warning()

        lines = [r for r in caplog.records if "could not use" in r.getMessage()]
        assert len(lines) == 1
        assert "disk_space" in lines[0].getMessage()


class TestTheVerdictIsNotOverridden:
    """An unusable detail must not re-decide routing.

    #1539's indeterminate verdict is for when the runtime cannot READ a
    verdict. Here it can: ``status`` is parsed independently of ``checks``.
    Forcing degraded would keep an agent that declared itself unable to serve
    in dependency resolution because of a typo somewhere else in the payload.
    """

    @pytest.mark.asyncio
    async def test_unhealthy_still_withdraws(self):
        async def health_check() -> dict:
            return {
                "status": "unhealthy",
                "checks": {"vendor_api": "down"},
                "errors": ["vendor unreachable"],
            }

        status = await run_check(health_check)

        assert status.status == HealthStatusType.UNHEALTHY
        assert "vendor unreachable" in status.errors

    @pytest.mark.asyncio
    async def test_healthy_stays_healthy(self):
        async def health_check() -> dict:
            return {"status": "healthy", "checks": {"db": "yes-ish"}}

        assert (await run_check(health_check)).status == HealthStatusType.HEALTHY


class TestWhatAlreadyWorkedKeepsWorking:
    """Only the values the model REJECTED change behaviour.

    ``1``, ``0`` and ``"true"`` are values ``dict[str, bool]`` already coerces,
    so they are validated through Pydantic here rather than an isinstance test
    that would quietly start dropping them.
    """

    @pytest.mark.asyncio
    async def test_bools_are_untouched(self):
        async def health_check() -> dict:
            return {"checks": {"a": True, "b": False}}

        status = await run_check(health_check)

        assert status.checks == {"a": True, "b": False}
        assert "health_check_checks_type" not in status.checks
        assert status.errors == []

    @pytest.mark.asyncio
    async def test_coercible_values_still_coerce(self):
        async def health_check() -> dict:
            return {"checks": {"one": 1, "zero": 0, "text": "true"}}

        status = await run_check(health_check)

        assert status.checks == {"one": True, "zero": False, "text": True}
        assert "health_check_checks_type" not in status.checks

    @pytest.mark.asyncio
    async def test_no_checks_at_all(self):
        async def health_check() -> bool:
            return True

        status = await run_check(health_check)

        assert status.status == HealthStatusType.HEALTHY
        assert status.checks == {"health_check": True}


class TestTheOtherUnusableShapes:
    """The issue asks whether only ``str`` bites. It is not only ``str``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value",
        [None, {"nested": True}, ["a", "b"], object()],
    )
    async def test_every_unreadable_value_reports_instead_of_raising(self, value):
        async def health_check() -> dict:
            return {"checks": {"probe": value}}

        status = await run_check(health_check)

        assert status.status == HealthStatusType.HEALTHY
        assert "probe" not in status.checks
        assert status.checks["health_check_checks_type"] is False

    @pytest.mark.asyncio
    async def test_checks_that_is_not_a_dict(self):
        async def health_check() -> dict:
            return {"checks": ["db", "cache"]}

        status = await run_check(health_check)

        assert status.checks["health_check_checks_type"] is False
        assert any("expected a dict" in e for e in status.errors)

    @pytest.mark.asyncio
    async def test_non_string_check_name(self):
        async def health_check() -> dict:
            return {"checks": {7: True}}

        status = await run_check(health_check)

        assert status.checks == {"7": True}


class TestErrorsHasTheSameExposure:
    """``errors`` is ``list[StrictStr]`` and raised in the same place.

    Text is stringified rather than reported: unlike a check value, ``str()``
    of an exception is exactly what the author meant to put in the list.
    """

    @pytest.mark.asyncio
    async def test_exception_objects_in_errors(self):
        async def health_check() -> dict:
            return {"status": "unhealthy", "errors": [ValueError("boom")]}

        status = await run_check(health_check)

        assert status.status == HealthStatusType.UNHEALTHY
        assert status.errors == ["boom"]

    @pytest.mark.asyncio
    async def test_errors_given_as_a_bare_string(self):
        async def health_check() -> dict:
            return {"status": "unhealthy", "errors": "vendor unreachable"}

        status = await run_check(health_check)

        assert status.errors == ["vendor unreachable"]

    @pytest.mark.asyncio
    async def test_non_text_entries_are_stringified(self):
        async def health_check() -> dict:
            return {"errors": [503, None]}

        status = await run_check(health_check)

        assert status.errors == ["503", "None"]


class TestReadingThePayloadCanItselfRaise:
    """A ``checks``/``errors`` container that raises when it is READ.

    ``isinstance(raw, Mapping)`` and ``isinstance(raw, Iterable)`` pass for any
    subclass, so ``raw.items()`` and ``iter(raw)`` are user code — a mapping
    that computes its entries on demand, or one backed by something that can
    fail. Both sanitizers run OUTSIDE the handler that catches a failing check,
    so a raise there escaped into ``fastapi-server-setup`` exactly like the
    Pydantic one did: an absent agent from a health-check authoring problem,
    the thing this whole change exists to make impossible.
    """

    @pytest.mark.asyncio
    async def test_checks_mapping_whose_items_raises(self):
        class LazyChecks(Mapping):
            def items(self):
                raise RuntimeError("probe results were never computed")

            def __getitem__(self, key):
                raise RuntimeError("probe results were never computed")

            def __iter__(self):
                raise RuntimeError("probe results were never computed")

            def __len__(self):
                return 0

        async def health_check() -> dict:
            return {"status": "healthy", "checks": LazyChecks()}

        status = await run_check(health_check)

        assert status.status == HealthStatusType.HEALTHY
        assert status.checks == {"health_check_checks_type": False}
        reported = " ".join(status.errors)
        assert "LazyChecks" in reported
        assert "RuntimeError" in reported
        assert "never computed" in reported

    @pytest.mark.asyncio
    async def test_a_mapping_that_raises_part_way_loses_the_whole_map(self):
        """All-or-nothing, on purpose.

        What survived a half-finished enumeration is an artifact of iteration
        order, not a subset the author would recognise, and it would differ
        between one TTL and the next. "None of them, because your mapping
        raised" is a report; a nondeterministic subset is not.
        """

        class HalfChecks(Mapping):
            def items(self):
                yield ("db", True)
                raise RuntimeError("cursor died")

            def __getitem__(self, key):
                raise KeyError(key)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 1

        async def health_check() -> dict:
            return {"checks": HalfChecks()}

        status = await run_check(health_check)

        assert "db" not in status.checks
        assert status.checks == {"health_check_checks_type": False}

    @pytest.mark.asyncio
    async def test_one_unreadable_entry_costs_only_that_entry(self):
        """An entry is a boundary the author recognises, unlike iteration order.

        So a single bad entry is treated like a single non-bool value: dropped
        and named, with its neighbours untouched.
        """

        class MalformedItems(Mapping):
            def items(self):
                return [("db", True), ("cache",), ("queue", False)]

            def __getitem__(self, key):
                raise KeyError(key)

            def __iter__(self):
                return iter(("db", "cache", "queue"))

            def __len__(self):
                return 3

        async def health_check() -> dict:
            return {"checks": MalformedItems()}

        status = await run_check(health_check)

        assert status.checks["db"] is True
        assert status.checks["queue"] is False
        assert status.checks["health_check_checks_type"] is False
        assert len([e for e in status.errors if "Unusable check" in e]) == 1

    @pytest.mark.asyncio
    async def test_the_message_says_what_happened(self):
        """A raise is not a type mismatch, and must not be described as one."""

        class LazyChecks(Mapping):
            def items(self):
                raise ConnectionError("redis is down")

            def __getitem__(self, key):
                raise KeyError(key)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

        async def health_check() -> dict:
            return {"checks": LazyChecks()}

        status = await run_check(health_check)

        reported = " ".join(status.errors)
        assert "ConnectionError: redis is down" in reported
        assert "not a bool" not in reported

    @pytest.mark.asyncio
    async def test_errors_iterable_whose_iter_raises(self):
        class LazyErrors:
            def __iter__(self):
                raise RuntimeError("error log was rotated away")

        async def health_check() -> dict:
            return {"status": "unhealthy", "errors": LazyErrors()}

        status = await run_check(health_check)

        # The verdict still stands — an unreadable detail never re-decides it.
        assert status.status == HealthStatusType.UNHEALTHY
        reported = " ".join(status.errors)
        assert "LazyErrors" in reported
        assert "rotated away" in reported

    @pytest.mark.asyncio
    async def test_the_startup_seed_still_produces_a_result(self):
        """The crash site: the call ``_add_k8s_endpoints`` makes at startup.

        If this raises, the pipeline step dies and the agent never registers —
        which is the whole failure mode, reached through a different door.
        """

        class LazyChecks(Mapping):
            def items(self):
                raise RuntimeError("probe results were never computed")

            def __getitem__(self, key):
                raise KeyError(key)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

        async def health_check() -> dict:
            return {"status": "healthy", "checks": LazyChecks()}

        result = await refresh_health_once(
            agent_name="checks-agent",
            health_check_fn=health_check,
            agent_config=AGENT_CONFIG,
            startup_context={},
            ttl_seconds=15,
            publish_to_core=False,
        )

        assert result["status"] == "healthy"
        assert result["checks"]["health_check_checks_type"] is False


class TestTheStepIsRequired:
    """The class behind the symptom, not just the symptom.

    Any failure inside ``fastapi-server-setup`` left an agent that could not
    serve and did not stop — a health-check value error was one way in, not the
    only one.
    """

    def test_step_is_required(self):
        assert FastAPIServerSetupStep().required is True

    @pytest.mark.asyncio
    async def test_nothing_to_mount_still_prepares_an_app(self):
        """The case ``required=False`` was written for, and it is a SUCCESS.

        Zero FastMCP servers is not a failure here: the step still builds the
        app, with the minimal lifespan and the K8s endpoints. Making the step
        required must not change that.
        """
        step = FastAPIServerSetupStep()
        context: dict[str, Any] = {
            "agent_config": {"name": "empty-agent", "version": "1.0.0"},
            "fastmcp_servers": {},
        }

        with patch.dict(os.environ, {"MCP_MESH_HTTP_ENABLED": "true"}):
            result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert result.context["fastapi_app"] is not None
        assert result.context["mcp_wrappers"] == {}

    @pytest.mark.asyncio
    async def test_http_disabled_skips_and_says_so(self):
        """Skipped, not failed — and flagged, so no-app-to-run is explicable.

        The pipeline exempts SKIPPED from the required-step abort, which is why
        a deliberately server-less agent is unaffected by the flag change.
        """
        step = FastAPIServerSetupStep()

        with patch.dict(os.environ, {"MCP_MESH_HTTP_ENABLED": "false"}):
            result = await step.execute({"agent_config": {"name": "a"}})

        assert result.status == PipelineStatus.SKIPPED
        assert result.context["http_transport_disabled"] is True

    @pytest.mark.asyncio
    async def test_a_failing_setup_fails_the_pipeline(self):
        """It used to be "⚠️ Optional step 11 failed, continuing"."""
        from _mcp_mesh.pipeline.shared import MeshPipeline

        step = FastAPIServerSetupStep()
        pipeline = MeshPipeline(name="test")
        pipeline.add_step(step)

        with (
            patch.object(
                step, "_create_fastapi_app", side_effect=Exception("no fastapi")
            ),
            patch.dict(os.environ, {"MCP_MESH_HTTP_ENABLED": "true"}),
        ):
            result = await pipeline.execute()

        assert result.status == PipelineStatus.FAILED
        assert result.status != PipelineStatus.PARTIAL


class TestTheLogLineDoesNotLie:
    """ "exiting" now exits.

    The process kept running because the abort ran on the DebounceCoordinator's
    timer thread while the decorator's immediate uvicorn held a non-daemon
    thread of its own. A raise there kills the timer thread only.
    """

    def test_abort_terminates_the_process(self):
        from _mcp_mesh.pipeline.mcp_startup.startup_orchestrator import (
            abort_agent_process,
        )

        with patch("os._exit") as fake_exit:
            abort_agent_process("no FastAPI app was prepared")

        fake_exit.assert_called_once_with(1)
