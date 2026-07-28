"""Regression tests for issue #1396 — @mesh.route through ``include_router()``.

FastAPI 0.139 stopped flattening an included ``APIRouter``'s ``APIRoute``
objects into ``app.router.routes``; the app now holds a single entry that
derives the served routes from the router lazily. Every mesh site that walked
``app.router.routes`` went blind to those handlers, so ``@mesh.route`` on an
``APIRouter`` — a documented pattern, and what
``examples/simple/simple_fastapi_router.py`` demonstrates — was discovered as
nothing at all: no DI wrapper registered, no dependency ever injected, the
handler serving as a plain FastAPI endpoint.

Nothing in the suite covered discovery or integration through
``include_router()``, which is why it survived several releases. These tests
close that gap at both ends of the range (the walk must also still work on
0.136.x, which flattens) and at nesting depth.
"""

import inspect

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.api_startup.route_integration import (
    RouteIntegrationStep,
    RouteRebuildError,
)
from _mcp_mesh.shared import fastapi_routes
from _mcp_mesh.shared.fastapi_routes import (
    RouteRef,
    invalidate_route_caches,
    iter_app_routes,
)
from _mcp_mesh.shared.server_discovery import ServerDiscoveryUtil


@pytest.fixture(autouse=True)
def _clean_route_wrapper_registry():
    """Keep the process-wide route-wrapper registry out of other tests.

    Every ``_integrate_single_route`` call in this file registers wrappers
    there. Clearing on the way in and out unconditionally means a failing
    assertion cannot leak entries into whatever runs next.
    """
    DecoratorRegistry._route_wrapper_registry.clear()
    yield
    DecoratorRegistry._route_wrapper_registry.clear()


def _build_route_info(handler, path, methods=("POST",), deps=None):
    return {
        "endpoint": handler,
        "endpoint_name": handler.__name__,
        "path": path,
        "methods": list(methods),
        "dependencies": deps or [],
    }


def _paths(app):
    return [ref.path for ref in iter_app_routes(app)]


def _flattens_included_routers(app) -> bool:
    """True on FastAPI < 0.139, where include_router() copies routes over."""
    return not any(hasattr(entry, "original_router") for entry in app.router.routes)


# ---------------------------------------------------------------------------
# iter_app_routes — the shared walk
# ---------------------------------------------------------------------------


class TestIterAppRoutes:
    def test_included_router_routes_are_reachable(self):
        router = APIRouter(prefix="/api/v1")

        @router.get("/time")
        async def get_time():
            return {}

        app = FastAPI()
        app.include_router(router)

        assert "/api/v1/time" in _paths(app)

    def test_top_level_routes_are_still_reachable(self):
        app = FastAPI()

        @app.get("/top")
        async def top():
            return {}

        ref = next(r for r in iter_app_routes(app) if r.path == "/top")
        assert ref.endpoint is top
        assert ref.included is False
        assert ref.container is app.router.routes
        assert ref.container[ref.index] is ref.route

    def test_nested_include_yields_the_composed_path(self):
        """A router included into a router keeps its own unprefixed path; the
        app serves it under the combined prefix, and that is what mesh must
        record (it becomes the ``METHOD:path`` id shipped to the registry)."""
        inner = APIRouter(prefix="/inner")

        @inner.get("/deep")
        async def deep():
            return {}

        outer = APIRouter(prefix="/api/v1")
        outer.include_router(inner)

        app = FastAPI()
        app.include_router(outer)

        assert "/api/v1/inner/deep" in _paths(app)
        # ...and the app really serves it there.
        assert TestClient(app).get("/api/v1/inner/deep").status_code == 200

    def test_container_points_at_the_list_that_owns_an_included_route(self):
        router = APIRouter(prefix="/api/v1")

        @router.get("/time")
        async def get_time():
            return {}

        app = FastAPI()
        app.include_router(router)

        ref = next(r for r in iter_app_routes(app) if r.path == "/api/v1/time")
        assert ref.route.endpoint is get_time
        assert ref.container is not None
        assert ref.container[ref.index] is ref.route
        if _flattens_included_routers(app):
            assert ref.container is app.router.routes
        else:
            assert ref.included is True
            assert ref.container is router.routes

    def test_mounted_sub_applications_are_not_traversed(self):
        """A Mount is a separate ASGI app — its routes are not this app's
        @mesh.route surface, and mesh itself mounts FastMCP as a catch-all."""
        sub = FastAPI()

        @sub.get("/inside")
        async def inside():
            return {}

        app = FastAPI()
        app.mount("/mounted", sub)

        assert not [p for p in _paths(app) if "inside" in p]

    def test_methods_and_endpoint_are_reported_for_included_routes(self):
        router = APIRouter(prefix="/api/v1")

        @router.post("/echo")
        async def echo():
            return {}

        app = FastAPI()
        app.include_router(router)

        ref = next(r for r in iter_app_routes(app) if r.path == "/api/v1/echo")
        assert ref.methods == ["POST"]
        assert ref.endpoint is echo

    def test_app_without_a_router_is_tolerated(self):
        assert list(iter_app_routes(object())) == []

    def test_invalidate_route_caches_is_a_noop_without_routers(self):
        invalidate_route_caches(object())  # must not raise

    def test_no_fastapi_import_in_the_walk(self):
        """The walk is pure duck-typing: it recognises an include_router()
        entry by its ``original_router`` link, never by a (private) class, and
        never imports anything out of fastapi. That is what makes it work
        unchanged from 0.136 through latest."""
        source = inspect.getsource(fastapi_routes)
        assert "import fastapi" not in source
        assert "from fastapi" not in source
        assert "_IncludedRouter" not in source


# ---------------------------------------------------------------------------
# Discovery (server_discovery._extract_route_info)
# ---------------------------------------------------------------------------


class TestDiscoveryThroughIncludeRouter:
    def test_mesh_route_on_a_router_is_discovered(self):
        @mesh.route(dependencies=["time_service"])
        async def get_time(time_agent: mesh.McpMeshTool = None) -> dict:
            return {"dep": time_agent}

        router = APIRouter(prefix="/api/v1")
        router.get("/time")(get_time)

        app = FastAPI()
        app.include_router(router)

        routes = ServerDiscoveryUtil._extract_route_info(app)
        found = [r for r in routes if r["endpoint_name"] == "get_time"]
        assert len(found) == 1
        assert found[0]["path"] == "/api/v1/time"
        assert found[0]["methods"] == ["GET"]
        assert found[0]["has_mesh_route"] is True

    def test_discovery_covers_nested_routers(self):
        @mesh.route(dependencies=["time_service"])
        async def deep_handler(time_agent: mesh.McpMeshTool = None) -> dict:
            return {"dep": time_agent}

        inner = APIRouter(prefix="/inner")
        inner.get("/deep")(deep_handler)
        outer = APIRouter(prefix="/api/v1")
        outer.include_router(inner)

        app = FastAPI()
        app.include_router(outer)

        routes = ServerDiscoveryUtil._extract_route_info(app)
        found = next(r for r in routes if r["endpoint_name"] == "deep_handler")
        assert found["path"] == "/api/v1/inner/deep"
        assert found["has_mesh_route"] is True

    def test_top_level_routes_are_not_regressed(self):
        @mesh.route(dependencies=["time_service"])
        async def plain(time_agent: mesh.McpMeshTool = None) -> dict:
            return {"dep": time_agent}

        app = FastAPI()
        app.get("/plain")(plain)

        routes = ServerDiscoveryUtil._extract_route_info(app)
        found = next(r for r in routes if r["endpoint_name"] == "plain")
        assert found["path"] == "/plain"
        assert found["has_mesh_route"] is True


# ---------------------------------------------------------------------------
# Route integration through include_router()
# ---------------------------------------------------------------------------


class TestIntegrationThroughIncludeRouter:
    @staticmethod
    def _app_with_included_stream_route(prefix="/api/v1"):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "a"

        router = APIRouter(prefix=prefix)
        router.post("/chat", response_model=None)(chat)
        app = FastAPI()
        app.include_router(router)
        return app, chat

    def test_included_route_handler_is_replaced_and_served(self):
        """The endpoint swap must reach the route the app actually
        dispatches. An SSE route proves it end to end: without the swap
        FastAPI keeps auto-streaming the raw async generator and answers
        ``application/jsonl``."""
        app, chat = self._app_with_included_stream_route()

        step = RouteIntegrationStep()
        result = step._integrate_single_route(
            app, _build_route_info(chat, "/api/v1/chat"), None
        )
        assert result["status"] == "integrated"
        assert result["sse"] is True

        client = TestClient(app)
        with client.stream("POST", "/api/v1/chat?prompt=hi") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = response.read().decode("utf-8")
        assert body == "data: a\n\ndata: [DONE]\n\n"

    def test_included_route_replacement_survives_a_warm_route_cache(self):
        """FastAPI caches the effective routes an include_router() entry
        serves, keyed on a counter that only add/remove bumps. Substituting
        into the router's list is invisible to it, so a cache warmed by an
        earlier request would keep serving the pre-wrap handler — the same
        looks-healthy/wrong-wire-contract shape as #1387."""
        app, chat = self._app_with_included_stream_route()
        client = TestClient(app)

        # Warm the cache before integration runs.
        warm = client.post("/api/v1/chat?prompt=hi")
        assert warm.status_code == 200

        step = RouteIntegrationStep()
        assert (
            step._integrate_single_route(
                app, _build_route_info(chat, "/api/v1/chat"), None
            )["status"]
            == "integrated"
        )

        with client.stream("POST", "/api/v1/chat?prompt=hi") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.read().decode("utf-8") == "data: a\n\ndata: [DONE]\n\n"

    def test_nested_included_route_is_integrated(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "a"

        inner = APIRouter(prefix="/inner")
        inner.post("/chat", response_model=None)(chat)
        outer = APIRouter(prefix="/api/v1")
        outer.include_router(inner)
        app = FastAPI()
        app.include_router(outer)

        step = RouteIntegrationStep()
        result = step._integrate_single_route(
            app, _build_route_info(chat, "/api/v1/inner/chat"), None
        )
        assert result["status"] == "integrated"

        client = TestClient(app)
        with client.stream("POST", "/api/v1/inner/chat?prompt=hi") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.read().decode("utf-8") == "data: a\n\ndata: [DONE]\n\n"

    def test_rebuild_that_does_not_take_effect_is_loud(self, monkeypatch):
        """If mesh can no longer tell FastAPI its route lists changed, the
        swap silently does not reach dispatch. That must abort startup, not
        report a successful integration (#1387's rule)."""
        app, chat = self._app_with_included_stream_route()
        if _flattens_included_routers(app):
            pytest.skip("FastAPI flattens included routers; no cache to go stale")

        client = TestClient(app)
        client.post("/api/v1/chat?prompt=hi")  # warm the cache

        monkeypatch.setattr(fastapi_routes, "invalidate_route_caches", lambda app: None)

        step = RouteIntegrationStep()
        with pytest.raises(RouteRebuildError) as exc:
            step._integrate_single_route(
                app, _build_route_info(chat, "/api/v1/chat"), None
            )
        assert "did not take effect" in str(exc.value)

    def test_route_that_is_not_an_api_route_is_loud(self, monkeypatch):
        """Only an APIRoute carries the dispatch state mesh rebuilds. Anything
        else matched at that path must abort startup rather than be left
        serving with a handler mesh could not install."""

        class SomeOtherRoute:
            pass

        async def handler():
            return {}

        app = FastAPI()
        ref = RouteRef(
            route=SomeOtherRoute(),
            path="/x",
            methods=["POST"],
            endpoint=handler,
            container=[None],
            index=0,
            included=False,
        )
        monkeypatch.setattr(fastapi_routes, "iter_app_routes", lambda app: iter([ref]))

        step = RouteIntegrationStep()
        with pytest.raises(RouteRebuildError) as exc:
            step._replace_route_handler(app, "/x", ["POST"], handler, handler)
        message = str(exc.value)
        assert "SomeOtherRoute" in message
        assert "not a FastAPI" in message
        assert "/x" in message and "POST" in message

    def test_route_whose_owning_list_is_unknown_is_loud(self, monkeypatch):
        """Without the list that owns the route there is nowhere to put the
        rebuilt one, so the route would keep dispatching the unwrapped
        handler — fail instead of reporting a successful integration."""

        async def handler():
            return {}

        app = FastAPI()
        app.post("/x")(handler)
        api_route = next(r.route for r in iter_app_routes(app) if r.path == "/x")

        ref = RouteRef(
            route=api_route,
            path="/x",
            methods=["POST"],
            endpoint=handler,
            container=None,
            index=None,
            included=True,
        )
        monkeypatch.setattr(fastapi_routes, "iter_app_routes", lambda app: iter([ref]))

        step = RouteIntegrationStep()
        with pytest.raises(RouteRebuildError) as exc:
            step._replace_route_handler(app, "/x", ["POST"], handler, handler)
        message = str(exc.value)
        assert "could not be located" in message
        assert "/x" in message and "POST" in message

    def test_same_handler_registered_under_two_verbs_wraps_the_right_route(self):
        """One function registered twice at one path produces two APIRoutes
        that path+endpoint alone cannot tell apart. Without the verbs in the
        match, which one gets the wrapper is iteration-order dependent — a GET
        integration could wrap the POST registration, leaving the verb mesh
        actually registered serving the unwrapped handler."""

        async def handler():
            return {"wrapped": False}

        async def wrapper():
            return {"wrapped": True}

        app = FastAPI()
        app.add_api_route("/x", handler, methods=["GET"], response_model=None)
        app.add_api_route("/x", handler, methods=["POST"], response_model=None)

        step = RouteIntegrationStep()
        assert step._replace_route_handler(app, "/x", ["POST"], handler, wrapper)

        client = TestClient(app)
        assert client.post("/x").json() == {"wrapped": True}
        assert client.get("/x").json() == {"wrapped": False}

    def test_every_covered_registration_of_a_handler_is_rebuilt(self):
        """A call covering both verbs must rebuild both registrations, not
        stop at the first match."""

        async def handler():
            return {"wrapped": False}

        async def wrapper():
            return {"wrapped": True}

        app = FastAPI()
        app.add_api_route("/x", handler, methods=["GET"], response_model=None)
        app.add_api_route("/x", handler, methods=["POST"], response_model=None)

        step = RouteIntegrationStep()
        assert step._replace_route_handler(app, "/x", ["GET", "POST"], handler, wrapper)

        client = TestClient(app)
        assert client.get("/x").json() == {"wrapped": True}
        assert client.post("/x").json() == {"wrapped": True}

    def test_no_matching_verb_is_reported_as_not_found(self):
        """Nothing matched means nothing was modified — the caller reports the
        route as not integrated rather than raising."""

        async def handler():
            return {}

        async def wrapper():
            return {}

        app = FastAPI()
        app.add_api_route("/x", handler, methods=["GET"], response_model=None)

        step = RouteIntegrationStep()
        assert (
            step._replace_route_handler(app, "/x", ["DELETE"], handler, wrapper)
            is False
        )


# ---------------------------------------------------------------------------
# The documented example: discovery -> integration -> injection
# ---------------------------------------------------------------------------


class TestIncludeRouterEndToEnd:
    def test_dependency_is_injected_into_an_included_mesh_route(self):
        """``examples/simple/simple_fastapi_router.py`` in miniature: the
        handler is registered on an APIRouter, mounted with include_router(),
        and must end up wired to the mesh dependency funnel."""

        @mesh.route(dependencies=["time_service"])
        async def get_time(time_agent: mesh.McpMeshTool = None) -> dict:
            if time_agent is None:
                return {"dependency_injected": False}
            return {"dependency_injected": True, "time": await time_agent()}

        router = APIRouter(prefix="/api/v1")
        router.get("/time")(get_time)
        app = FastAPI()
        app.include_router(router)

        discovered = ServerDiscoveryUtil._extract_route_info(app)
        route_info = next(r for r in discovered if r["endpoint_name"] == "get_time")
        route_info["dependencies"] = [{"capability": "time_service"}]

        step = RouteIntegrationStep()
        assert step._integrate_single_route(app, route_info, None)["status"] == (
            "integrated"
        )

        # The wrapper is registered under the EFFECTIVE path, which is the
        # route id the heartbeat ships to the registry.
        wrappers = DecoratorRegistry.get_all_route_wrappers()
        assert "GET:/api/v1/time" in wrappers

        # Push a resolved dependency the way the heartbeat funnel does.
        class FakeTool:
            async def __call__(self, **kwargs):
                return "2026-07-28T00:00:00Z"

        wrappers["GET:/api/v1/time"]["wrapper"]._mesh_update_dependency(0, FakeTool())

        response = TestClient(app).get("/api/v1/time")
        assert response.status_code == 200
        assert response.json() == {
            "dependency_injected": True,
            "time": "2026-07-28T00:00:00Z",
        }
