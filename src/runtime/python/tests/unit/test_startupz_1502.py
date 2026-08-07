"""``startup_check`` and ``/startupz`` — RFC #1502, step 1.

``health_check`` answers "can I serve right now" and a failing one pauses the
heartbeat until it recovers. ``startup_check`` answers "is this agent
configured such that it can ever serve", and the chart's ``startupProbe`` will
poll ``/startupz`` for it, so a check that never passes means the pod never
becomes ready and lands in CrashLoopBackOff where it is visible.

Both Python sites that serve ``/livez`` are covered:

* ``mesh/decorators.py`` — the ``@mesh.agent`` (MCP provider) path, whose app
  is built by ``_start_uvicorn_immediately``;
* ``_mcp_mesh/pipeline/shared/health_endpoints.py`` — the ``@mesh.route`` /
  ``@mesh.a2a`` gateway path (#1491), where a user-defined path wins.

The verdict rules are the OPPOSITE of ``health_check``'s and are asserted as
such: a throw fails (it does not degrade), and anything short of a clean pass
fails. See ``_mcp_mesh.shared.startup_check_manager`` for why.
"""

import asyncio
import socket
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _mcp_mesh.pipeline.a2a_startup.a2a_pipeline import A2APipeline
from _mcp_mesh.pipeline.api_startup.api_pipeline import APIPipeline
from _mcp_mesh.shared.startup_check_manager import (
    STARTUPZ_PATH,
    build_startupz_response,
    get_startup_check,
    run_startup_check,
)

BIND_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def declared_startup_check(monkeypatch):
    """Install a ``startup_check`` into the resolved agent config.

    Returns a setter so each test declares its own check (or none) through the
    same path ``@mesh.agent(startup_check=...)`` uses.
    """
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    def declare(check):
        monkeypatch.setattr(
            DecoratorRegistry,
            "_cached_agent_config",
            {
                "agent_id": "agent-abcd1234",
                "name": "agent",
                "startup_check": check,
            },
        )

    return declare


def _gateway_app(pipeline_cls=APIPipeline, app=None):
    app = app if app is not None else FastAPI(title="Gateway App")
    step = next(s for s in pipeline_cls().steps if s.name == "health-endpoints")
    result = asyncio.run(
        step.execute({"fastapi_apps": {"app-1": {"instance": app, "title": "G"}}})
    )
    assert result.status.value != "failed", result.errors
    return app


async def _async_true():
    """The async half of the sync/async parametrisation below."""
    return True


@pytest.fixture(autouse=True)
def _no_leaked_verdict(monkeypatch):
    """Pin the stored ``health_check`` verdict to "none".

    A gateway's ``/health`` reports it since RFC #1502 step 3, and the store
    is a module global that a background refresh loop leaked by a sibling
    test file republishes into on its own timer (#1225). These tests are
    about ``/startupz``; they must not read another agent's verdict.
    """
    from _mcp_mesh.shared import health_check_manager

    monkeypatch.setattr(health_check_manager, "_health_check_result", None)


@pytest.fixture
def runtime_up(monkeypatch):
    from _mcp_mesh.shared import simple_shutdown

    monkeypatch.setattr(
        simple_shutdown, "get_active_rust_agent_handles", lambda: [object()]
    )
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: False)


# ---------------------------------------------------------------------------
# The hook itself
# ---------------------------------------------------------------------------


class TestStartupCheckHook:
    def test_mesh_agent_accepts_startup_check_next_to_health_check(self):
        import inspect

        import mesh

        params = inspect.signature(mesh.agent).parameters
        assert "startup_check" in params
        assert params["startup_check"].default is None

    def test_declared_check_reaches_the_resolved_config(self, monkeypatch):
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        def check():
            return True

        monkeypatch.setattr(DecoratorRegistry, "_cached_agent_config", None)

        @mesh.agent(name="startupz-hook-agent", auto_run=False, startup_check=check)
        class _Agent:
            pass

        assert _Agent._mesh_agent_metadata["startup_check"] is check

    def test_a_non_callable_is_rejected_at_decoration(self):
        import mesh

        with pytest.raises(ValueError, match="startup_check must be a callable"):

            @mesh.agent(name="bad-startup-agent", auto_run=False, startup_check="nope")
            class _Agent:
                pass

    def test_no_check_declared_resolves_to_none(self, declared_startup_check):
        declared_startup_check(None)
        assert get_startup_check() is None

    def test_a_non_callable_in_config_is_ignored(self, declared_startup_check):
        declared_startup_check("not callable")
        assert get_startup_check() is None


class TestRunStartupCheck:
    def test_absent_check_passes(self):
        passed, checks, errors = asyncio.run(run_startup_check(None))
        assert passed is True
        assert errors == []

    @pytest.mark.parametrize(
        "check",
        [
            pytest.param(lambda: True, id="sync"),
            pytest.param(_async_true, id="async"),
        ],
    )
    def test_true_passes_sync_and_async(self, check):
        passed, _, errors = asyncio.run(run_startup_check(check))
        assert passed is True
        assert errors == []

    def test_false_fails(self):
        passed, checks, errors = asyncio.run(run_startup_check(lambda: False))
        assert passed is False
        assert errors == ["Startup check returned False"]
        assert checks == {"startup_check": False}

    def test_a_throw_fails_rather_than_degrading(self):
        """The opposite of ``health_check``, deliberately.

        A throwing ``health_check`` is DEGRADED and keeps heartbeating — a
        buggy probe must not withdraw a working provider. Here the question is
        whether a possibly-misconfigured agent may come up at all, so an
        indeterminate boot-time answer fails.
        """

        def boom():
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        passed, checks, errors = asyncio.run(run_startup_check(boom))
        assert passed is False
        assert checks == {"startup_check_execution": False}
        assert "ANTHROPIC_API_KEY is not set" in errors[0]

    def test_an_async_throw_also_fails(self):
        async def boom():
            raise RuntimeError("vendor returned 401")

        passed, _, errors = asyncio.run(run_startup_check(boom))
        assert passed is False
        assert "vendor returned 401" in errors[0]

    def test_dict_verdicts(self):
        passed, _, _ = asyncio.run(run_startup_check(lambda: {"status": "healthy"}))
        assert passed is True

        passed, checks, errors = asyncio.run(
            run_startup_check(
                lambda: {
                    "status": "unhealthy",
                    "checks": {"api_key": False},
                    "errors": ["no key"],
                }
            )
        )
        assert passed is False
        assert checks == {"api_key": False}
        assert errors == ["no key"]

    def test_degraded_fails_there_is_no_partial_credit(self):
        passed, _, errors = asyncio.run(
            run_startup_check(lambda: {"status": "degraded"})
        )
        assert passed is False
        assert errors == ["Startup check reported 'degraded'"]

    def test_health_status_object(self):
        from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType

        healthy = HealthStatus(
            agent_name="a", status=HealthStatusType.HEALTHY, capabilities=["c"]
        )
        passed, _, _ = asyncio.run(run_startup_check(lambda: healthy))
        assert passed is True

        unhealthy = HealthStatus(
            agent_name="a", status=HealthStatusType.UNHEALTHY, capabilities=["c"]
        )
        passed, _, errors = asyncio.run(run_startup_check(lambda: unhealthy))
        assert passed is False
        assert errors

    def test_an_unrecognized_return_type_fails(self):
        passed, checks, errors = asyncio.run(run_startup_check(lambda: "yes"))
        assert passed is False
        assert checks == {"startup_check_return_type": False}
        assert "str" in errors[0]

    def test_none_return_fails(self):
        passed, _, _ = asyncio.run(run_startup_check(lambda: None))
        assert passed is False

    def test_a_dict_whose_lookup_raises_fails_rather_than_propagating(self):
        """Fail-closed covers reducing the return value, not just calling it.

        A check that hands back a dict-like config object — one lazily backed
        by a vendor client that is the very thing missing — must fail the probe
        the same way a throwing check does, not 500 the endpoint.
        """

        class HostileDict(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("config not loaded")

        passed, _, errors = asyncio.run(run_startup_check(lambda: HostileDict()))
        assert passed is False
        assert "config not loaded" in errors[0]

    def test_a_health_status_with_an_unvalidated_status_fails_closed(self):
        """``raw.status.value`` is only safe while validation has run.

        ``model_construct`` bypasses it, and formatting the *value* rather than
        the type into a message is the hazard ``health_check_manager``'s
        ``_for_warning`` exists for.
        """
        from _mcp_mesh.shared.support_types import HealthStatus

        raw = HealthStatus.model_construct(
            agent_name="a", status="not-an-enum", capabilities=["c"]
        )

        passed, _, errors = asyncio.run(run_startup_check(lambda: raw))
        assert passed is False
        assert errors

    def test_an_unrepresentable_return_type_still_fails_closed(self):
        """The invalid-type path names the TYPE, never ``repr`` of the value."""

        class Unprintable:
            def __repr__(self):
                raise RuntimeError("cannot repr")

        passed, _, errors = asyncio.run(run_startup_check(lambda: Unprintable()))
        assert passed is False
        assert "Unprintable" in errors[0]

    def test_the_check_runs_on_every_call_there_is_no_cache(self):
        calls = []

        def check():
            calls.append(1)
            return True

        for _ in range(3):
            asyncio.run(run_startup_check(check))
        assert len(calls) == 3


class TestStartupzBody:
    def test_pass_body(self):
        body, status = asyncio.run(build_startupz_response("agent-x", lambda: True))
        assert status == 200
        assert body["started"] is True
        assert body["agent"] == "agent-x"
        assert "timestamp" in body

    def test_failure_body_mirrors_ready(self):
        """``/ready``'s failure shape: a boolean, a reason and errors."""
        body, status = asyncio.run(
            build_startupz_response(
                "agent-x", lambda: {"status": "unhealthy", "errors": ["no key"]}
            )
        )
        assert status == 503
        assert body["started"] is False
        assert body["reason"] == "Startup check failed"
        assert body["errors"] == ["no key"]

    def test_extra_keys_are_carried(self):
        body, _ = asyncio.run(
            build_startupz_response("gw", lambda: True, service_type="api")
        )
        assert body["service_type"] == "api"


# ---------------------------------------------------------------------------
# Site 1: the @mesh.agent provider path (mesh/decorators.py)
# ---------------------------------------------------------------------------


class TestProviderEndpoint:
    """Exercises the app ``_start_uvicorn_immediately`` actually builds.

    ``uvicorn.Server.run`` is stubbed out so no socket is served, but the
    FastAPI app under test is the real one, with the real route registrations.
    """

    @pytest.fixture
    def immediate_app(self, monkeypatch):
        import uvicorn

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.shared import simple_shutdown
        from mesh import decorators

        started = threading.Event()

        def fake_run(self, sockets=None):
            self.started = True
            started.wait(timeout=5)

        monkeypatch.setattr(uvicorn.Server, "run", fake_run)
        # `_start_uvicorn_immediately` ends by JOINING the server thread, which
        # here is parked in `fake_run` — without this the fixture blocks for the
        # full 5s budget before yielding (8 tests x 5s), and the real function
        # installs process-wide SIGINT/SIGTERM handlers on its way there.
        monkeypatch.setattr(
            decorators, "start_blocking_loop_with_shutdown_support", lambda thread: None
        )
        saved = list(simple_shutdown._simple_shutdown_coordinator._uvicorn_servers)
        try:
            decorators._start_uvicorn_immediately(BIND_HOST, 0)
            record = DecoratorRegistry.get_immediate_uvicorn_server()
            assert record is not None
            yield record["app"]
        finally:
            started.set()
            DecoratorRegistry.clear_immediate_uvicorn_server()
            simple_shutdown._simple_shutdown_coordinator._uvicorn_servers = saved

    def test_startupz_is_served(self, immediate_app):
        assert STARTUPZ_PATH in {r.path for r in immediate_app.router.routes}

    def test_no_check_declared_answers_200(self, immediate_app, declared_startup_check):
        declared_startup_check(None)
        response = TestClient(immediate_app).get(STARTUPZ_PATH)
        assert response.status_code == 200
        assert response.json()["started"] is True

    def test_passing_check_answers_200(self, immediate_app, declared_startup_check):
        declared_startup_check(lambda: True)
        assert TestClient(immediate_app).get(STARTUPZ_PATH).status_code == 200

    def test_failing_check_answers_503(self, immediate_app, declared_startup_check):
        declared_startup_check(lambda: False)
        response = TestClient(immediate_app).get(STARTUPZ_PATH)
        assert response.status_code == 503
        assert response.json()["started"] is False

    def test_throwing_check_answers_503_not_500(
        self, immediate_app, declared_startup_check
    ):
        def boom():
            raise RuntimeError("no key")

        declared_startup_check(boom)
        assert TestClient(immediate_app).get(STARTUPZ_PATH).status_code == 503

    @pytest.mark.parametrize(
        "check,expected", [(lambda: True, 200), (lambda: False, 503)]
    )
    def test_head_matches_get(
        self, immediate_app, declared_startup_check, check, expected
    ):
        declared_startup_check(check)
        client = TestClient(immediate_app)
        assert client.head(STARTUPZ_PATH).status_code == expected
        assert client.get(STARTUPZ_PATH).status_code == expected

    def test_livez_stays_unconditional(self, immediate_app, declared_startup_check):
        """Nothing about #1502 may make liveness consult anything."""

        def boom():
            raise RuntimeError("no key")

        declared_startup_check(boom)
        assert TestClient(immediate_app).get("/livez").status_code == 200


# ---------------------------------------------------------------------------
# Site 2: the gateway path (pipeline/shared/health_endpoints.py)
# ---------------------------------------------------------------------------


class TestGatewayEndpoint:
    @pytest.mark.parametrize("pipeline_cls", [APIPipeline, A2APipeline])
    def test_registered_on_both_gateway_pipelines(self, pipeline_cls, runtime_up):
        app = _gateway_app(pipeline_cls)
        assert STARTUPZ_PATH in {r.path for r in app.router.routes}
        assert TestClient(app).get(STARTUPZ_PATH).status_code == 200

    def test_service_type_is_reported(self, runtime_up):
        app = _gateway_app(A2APipeline)
        assert TestClient(app).get(STARTUPZ_PATH).json()["service_type"] == "a2a"

    def test_no_check_declared_answers_200(self, declared_startup_check, runtime_up):
        declared_startup_check(None)
        app = _gateway_app()
        response = TestClient(app).get(STARTUPZ_PATH)
        assert response.status_code == 200
        assert response.json()["started"] is True

    def test_passing_check_answers_200(self, declared_startup_check, runtime_up):
        declared_startup_check(lambda: True)
        app = _gateway_app()
        assert TestClient(app).get(STARTUPZ_PATH).status_code == 200

    def test_failing_check_answers_503(self, declared_startup_check, runtime_up):
        declared_startup_check(lambda: False)
        app = _gateway_app()
        response = TestClient(app).get(STARTUPZ_PATH)
        assert response.status_code == 503
        assert response.json()["started"] is False
        assert response.json()["errors"]

    def test_throwing_check_answers_503_not_500(
        self, declared_startup_check, runtime_up
    ):
        async def boom():
            raise RuntimeError("MODEL_ENDPOINT is not set")

        declared_startup_check(boom)
        app = _gateway_app()
        response = TestClient(app).get(STARTUPZ_PATH)
        assert response.status_code == 503
        assert "MODEL_ENDPOINT is not set" in response.json()["errors"][0]

    @pytest.mark.parametrize(
        "check,expected", [(lambda: True, 200), (lambda: False, 503)]
    )
    def test_head_matches_get(
        self, declared_startup_check, runtime_up, check, expected
    ):
        declared_startup_check(check)
        app = _gateway_app()
        client = TestClient(app)
        assert client.head(STARTUPZ_PATH).status_code == expected
        assert client.get(STARTUPZ_PATH).status_code == expected

    def test_a_user_defined_startupz_wins(self, declared_startup_check, runtime_up):
        """Same per-path rule as ``/livez``/``/ready``/``/health`` (#1491)."""
        declared_startup_check(lambda: False)

        app = FastAPI(title="Hand-rolled Gateway")

        @app.get(STARTUPZ_PATH)
        async def user_startupz():
            return {"mine": True}

        _gateway_app(app=app)

        response = TestClient(app).get(STARTUPZ_PATH)
        assert response.status_code == 200
        assert response.json() == {"mine": True}

    def test_the_other_paths_are_still_registered_when_startupz_is_taken(
        self, runtime_up
    ):
        app = FastAPI(title="Hand-rolled Gateway")

        @app.get(STARTUPZ_PATH)
        async def user_startupz():
            return {"mine": True}

        _gateway_app(app=app)

        client = TestClient(app)
        assert client.get("/livez").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200

    def test_registration_is_idempotent(self, runtime_up):
        app = _gateway_app()
        before = len(app.router.routes)
        _gateway_app(app=app)
        assert len(app.router.routes) == before

    def test_livez_stays_unconditional(self, declared_startup_check, runtime_up):
        declared_startup_check(lambda: False)
        app = _gateway_app()
        assert TestClient(app).get("/livez").status_code == 200

    def test_ready_is_unchanged_by_a_failing_startup_check(
        self, declared_startup_check, runtime_up
    ):
        """Step 1 is additive: ``/ready`` keeps reporting the runtime only."""
        declared_startup_check(lambda: False)
        app = _gateway_app()
        assert TestClient(app).get("/ready").status_code == 200


def test_bind_host_is_free():
    """Guard for the provider fixture: it binds an ephemeral port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((BIND_HOST, 0))
    s.close()
