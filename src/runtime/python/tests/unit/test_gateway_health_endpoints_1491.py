"""Probe endpoints on Python gateways — issue #1491.

``@mesh.route`` (api) and ``@mesh.a2a`` (a2a) gateways served none of
``/livez``, ``/ready`` or ``/health``: the builders were wired only from
``_start_uvicorn_immediately``, which only the ``@mesh.agent`` decorator calls.
The agent Helm chart probes ``/livez`` (startup, liveness) and ``/ready``
(readiness) since #1468, so a Python gateway 404'd every probe and the kubelet
restart-looped a working process.

These tests deliberately reach the step through the *real* pipelines
(``APIPipeline`` / ``A2APipeline``) by name rather than importing it, so the
file is red against the pre-fix tree for the reason that matters — nothing
registers the endpoints — rather than on an import error.

Semantics under test (TypeScript's ``express.ts`` is the reference):
  * ``/livez``  — unconditional 200, consults nothing
  * ``/ready``  — mesh runtime state only
  * ``/health`` — diagnostic, always 200, never consults ``health_check``
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _mcp_mesh.pipeline.a2a_startup.a2a_pipeline import A2APipeline
from _mcp_mesh.pipeline.api_startup.api_pipeline import APIPipeline

HEALTH_STEP_NAME = "health-endpoints"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _health_step(pipeline):
    """The wired health-endpoint step, or fail loudly if the pipeline lacks one."""
    for step in pipeline.steps:
        if step.name == HEALTH_STEP_NAME:
            return step
    raise AssertionError(
        f"'{HEALTH_STEP_NAME}' step is not wired into {pipeline.name} "
        f"(steps: {pipeline.list_steps()})"
    )


def _run_step(pipeline, app, title="Gateway App"):
    step = _health_step(pipeline)
    context = {
        "fastapi_apps": {
            "app-1": {"instance": app, "title": title},
        }
    }
    return asyncio.run(step.execute(context))


def _paths(app):
    return {route.path for route in app.router.routes}


@pytest.fixture
def api_app():
    app = FastAPI(title="Gateway App")
    _run_step(APIPipeline(), app)
    return app


@pytest.fixture
def runtime_up(monkeypatch):
    """Pretend a live Rust core handle exists (mesh runtime is up)."""
    from _mcp_mesh.shared import simple_shutdown

    monkeypatch.setattr(
        simple_shutdown, "get_active_rust_agent_handles", lambda: [object()]
    )
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: False)


@pytest.fixture
def runtime_down(monkeypatch):
    """No Rust core handle — the runtime has not started."""
    from _mcp_mesh.shared import simple_shutdown

    monkeypatch.setattr(simple_shutdown, "get_active_rust_agent_handles", list)
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: False)


@pytest.fixture
def declared_health_check(monkeypatch):
    """A gateway that declared a health check, and a failing stored result.

    Both of the things a health check produces: the callable itself (which must
    never be invoked from these endpoints) and the stored ``unhealthy`` verdict
    that ``build_health_response`` / ``build_ready_response`` would turn into a
    503. Neither may reach a gateway probe.
    """
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
    from _mcp_mesh.shared import health_check_manager

    calls = []

    async def never_called():
        calls.append(1)
        raise AssertionError("gateway probes must not run the user's health_check")

    monkeypatch.setattr(
        DecoratorRegistry,
        "_cached_agent_config",
        {
            "agent_id": "gateway-abcd1234",
            "name": "gateway",
            "health_check": never_called,
            "health_check_ttl": 15,
        },
    )
    health_check_manager.store_health_check_result(
        {
            "status": "unhealthy",
            "agent": "gateway",
            "errors": ["database down"],
        }
    )
    yield calls
    health_check_manager.clear_health_check_result()


# ---------------------------------------------------------------------------
# Wiring — both gateway pipelines
# ---------------------------------------------------------------------------


class TestPipelineWiring:
    def test_api_pipeline_wires_the_health_step(self):
        assert HEALTH_STEP_NAME in APIPipeline().list_steps()

    def test_a2a_pipeline_wires_the_health_step(self):
        assert HEALTH_STEP_NAME in A2APipeline().list_steps()

    def test_both_pipelines_share_one_step_implementation(self):
        assert type(_health_step(APIPipeline())) is type(_health_step(A2APipeline()))

    @pytest.mark.parametrize(
        "pipeline_cls,service_type",
        [(APIPipeline, "api"), (A2APipeline, "a2a")],
    )
    def test_all_three_registered_on_a_bare_app(
        self, pipeline_cls, service_type, runtime_up
    ):
        app = FastAPI(title="Bare Gateway")
        result = _run_step(pipeline_cls(), app)
        assert result.status.value != "failed", result.errors

        assert {"/livez", "/ready", "/health"} <= _paths(app)

        client = TestClient(app)
        assert client.get("/livez").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health").json()["service_type"] == service_type

    def test_step_is_skipped_without_a_discovered_app(self):
        step = _health_step(APIPipeline())
        result = asyncio.run(step.execute({}))
        assert result.status.value == "skipped"

    def test_registration_is_idempotent(self, runtime_up):
        """A second pass must not stack a duplicate handler per path."""
        app = FastAPI(title="Bare Gateway")
        _run_step(APIPipeline(), app)
        before = len(app.router.routes)
        _run_step(APIPipeline(), app)
        assert len(app.router.routes) == before
        assert TestClient(app).get("/livez").status_code == 200


# ---------------------------------------------------------------------------
# The app is the user's — collisions
# ---------------------------------------------------------------------------


class TestUserDefinedPathsWin:
    @pytest.mark.parametrize("owned", ["/livez", "/ready", "/health"])
    def test_user_route_is_kept_and_the_other_two_are_registered(
        self, owned, runtime_up
    ):
        app = FastAPI(title="Hand-rolled Gateway")

        @app.get(owned)
        async def user_endpoint():
            return {"mine": True}

        _run_step(APIPipeline(), app)

        client = TestClient(app)
        # The application's handler still answers, unmodified.
        assert client.get(owned).json() == {"mine": True}

        # The other two are mesh's, and they answer.
        for path in ("/livez", "/ready", "/health"):
            if path == owned:
                continue
            response = client.get(path)
            assert response.status_code == 200, path
            assert "mine" not in response.json(), path

    def test_mesh_api_example_shape_still_gets_livez_and_ready(self, runtime_up):
        """``examples/python/mesh-api/main.py`` hand-rolls ``/health``."""
        app = FastAPI(title="MCP Mesh FastAPI Example")

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "mesh-api"}

        _run_step(APIPipeline(), app)

        client = TestClient(app)
        assert client.get("/health").json() == {
            "status": "healthy",
            "service": "mesh-api",
        }
        assert client.get("/livez").json()["alive"] is True
        assert client.get("/ready").json()["ready"] is True

    def test_user_path_on_an_included_router_is_detected(self, runtime_up):
        """Collision detection must see through ``include_router()`` (#1396)."""
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/health")
        async def user_health():
            return {"mine": True}

        app = FastAPI(title="Router Gateway")
        app.include_router(router)

        _run_step(APIPipeline(), app)

        client = TestClient(app)
        assert client.get("/health").json() == {"mine": True}
        assert client.get("/livez").status_code == 200

    def test_prefixed_router_is_a_different_path_and_does_not_pre_empt(
        self, runtime_up
    ):
        """A router mounted at ``/ops`` serves ``/ops/health``, not ``/health``.

        The check compares *effective* paths — the paths the app actually
        serves — so a prefixed ``/health`` is a different endpoint and must not
        stop mesh registering the top-level one. Comparing the router's own
        unprefixed path instead would silently leave the gateway without a
        ``/health`` because of an unrelated ops route.
        """
        from fastapi import APIRouter

        router = APIRouter(prefix="/ops")

        @router.get("/health")
        async def ops_health():
            return {"mine": True}

        app = FastAPI(title="Prefixed Router Gateway")
        app.include_router(router)

        _run_step(APIPipeline(), app)

        client = TestClient(app)
        # The user's route keeps its own path...
        assert client.get("/ops/health").json() == {"mine": True}
        # ...and mesh still owns the top-level one.
        top_level = client.get("/health")
        assert top_level.status_code == 200
        assert top_level.json()["status"] == "healthy"
        assert top_level.json()["service_type"] == "api"

    def test_collision_is_reported_at_info_naming_the_path(self, caplog, runtime_up):
        app = FastAPI(title="Hand-rolled Gateway")

        @app.get("/health")
        async def user_health():
            return {"mine": True}

        with caplog.at_level("INFO"):
            _run_step(APIPipeline(), app)

        messages = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert any("/health" in m and "application" in m for m in messages), messages


# ---------------------------------------------------------------------------
# /livez — unconditional
# ---------------------------------------------------------------------------


class TestLivez:
    def test_200_while_the_runtime_is_up(self, api_app, runtime_up):
        response = TestClient(api_app).get("/livez")
        assert response.status_code == 200
        assert response.json()["alive"] is True

    def test_200_while_the_runtime_is_down(self, api_app, runtime_down):
        response = TestClient(api_app).get("/livez")
        assert response.status_code == 200
        assert response.json()["alive"] is True

    def test_200_while_shutting_down(self, api_app, monkeypatch):
        from _mcp_mesh.shared import simple_shutdown

        monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: True)
        assert TestClient(api_app).get("/livez").status_code == 200

    def test_200_with_a_failing_declared_health_check(
        self, api_app, runtime_down, declared_health_check
    ):
        assert TestClient(api_app).get("/livez").status_code == 200
        assert declared_health_check == []


# ---------------------------------------------------------------------------
# /ready — mesh runtime state, and nothing else
# ---------------------------------------------------------------------------


class TestReady:
    def test_200_when_the_runtime_is_up(self, api_app, runtime_up):
        response = TestClient(api_app).get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["runtime"] == "up"

    def test_503_before_the_runtime_starts(self, api_app, runtime_down):
        response = TestClient(api_app).get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["runtime"] == "starting"
        assert body["reason"]

    def test_503_while_shutting_down(self, api_app, monkeypatch):
        from _mcp_mesh.shared import simple_shutdown

        monkeypatch.setattr(
            simple_shutdown, "get_active_rust_agent_handles", lambda: [object()]
        )
        monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: True)

        response = TestClient(api_app).get("/ready")
        assert response.status_code == 503
        assert response.json()["runtime"] == "shutting_down"

    def test_ready_in_standalone_mode_without_any_handle(
        self, monkeypatch, runtime_down
    ):
        monkeypatch.setenv("MCP_MESH_STANDALONE", "true")
        app = FastAPI(title="Standalone Gateway")
        _run_step(APIPipeline(), app)

        response = TestClient(app).get("/ready")
        assert response.status_code == 200
        assert response.json()["runtime"] == "standalone"

    def test_a_failing_declared_health_check_does_not_make_it_unready(
        self, api_app, runtime_up, declared_health_check
    ):
        """#1473/#1488: a gateway is a fan-out point — its own check must not
        withdraw it. A stored ``unhealthy`` verdict would 503 through
        ``build_ready_response``; this endpoint must not consult it."""
        response = TestClient(api_app).get("/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True
        assert declared_health_check == []


# ---------------------------------------------------------------------------
# /health — diagnostic only
# ---------------------------------------------------------------------------


class TestHealth:
    def test_200_healthy_when_the_runtime_is_up(self, api_app, runtime_up):
        response = TestClient(api_app).get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["runtime"] == "up"
        assert body["mesh_ready"] is True

    def test_200_before_the_runtime_starts(self, api_app, runtime_down):
        """No probe points at /health, so it never 503s — it reports."""
        response = TestClient(api_app).get("/health")
        assert response.status_code == 200
        assert response.json()["mesh_ready"] is False
        assert response.json()["runtime"] == "starting"

    def test_never_consults_the_declared_health_check(
        self, api_app, runtime_up, declared_health_check
    ):
        response = TestClient(api_app).get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert "errors" not in body
        assert declared_health_check == []

    def test_declaring_a_health_check_changes_none_of_the_three(
        self, runtime_up, declared_health_check
    ):
        app = FastAPI(title="Gateway With Health Check")
        _run_step(APIPipeline(), app)

        client = TestClient(app)
        assert client.get("/livez").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200
        assert declared_health_check == []
