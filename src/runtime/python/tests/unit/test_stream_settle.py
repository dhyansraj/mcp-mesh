"""Settling-window grace on the streaming invocation paths (issue #1206).

The #1193 grace already covered the non-streaming DI wrappers; these tests
pin the same matrix on BOTH streaming wrapper shapes:

* the decorator stream wrapper (``_make_stream_wrapper`` — async-generator
  ``@mesh.tool`` functions, e.g. the multi-hop passthrough agent), and
* the ``@mesh.route`` SSE endpoint (``_build_sse_endpoint``).

Matrix per shape (mirrors ``test_settle_window.py``):

(a) resolution mid-wait → the stream proceeds with the REAL proxy;
(b) window timeout → today's behavior (the user's defensive branch runs:
    ``yield "degraded"`` for tools, a clean ``HTTPException(503)`` for the
    canonical two-function route shape — never a raw 500);
(c) settled → zero wait (steady state never touches the wait primitives).

Plus the #1206 root-cause regression: ``@mesh.route`` streaming handlers get
their SSE endpoint built at DECORATION time, so FastAPI registers the correct
streaming endpoint at ``@app.post()`` time. Before the fix, the SSE swap only
happened in the debounced route-integration pipeline step — a request
arriving before that step (or HELD across it by the settle grace) completed
inside the plain DI wrapper, whose raw async-generator return value FastAPI
cannot serialize → gateway 500.
"""

import asyncio
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import mesh
from _mcp_mesh.engine import settle
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.dependency_injector import DependencyInjector
from _mcp_mesh.engine.settle import get_settle_state
from _mcp_mesh.pipeline.api_startup import route_integration
from _mcp_mesh.pipeline.api_startup.route_integration import (
    RouteIntegrationStep,
    _build_sse_endpoint,
)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Isolate every test: fresh settle state + clean DecoratorRegistry."""
    monkeypatch.delenv("MCP_MESH_SETTLE_TIMEOUT", raising=False)
    settle._reset_settle_state_for_tests()
    DecoratorRegistry.clear_all()
    yield
    settle._reset_settle_state_for_tests()
    DecoratorRegistry.clear_all()


def _set_budget(monkeypatch, value: str) -> None:
    monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", value)
    settle._reset_settle_state_for_tests()


class FakeStreamingDep:
    """Stand-in for an injected McpMeshTool whose remote tool streams."""

    def __init__(self, chunks):
        self.chunks = chunks

    async def stream(self, **kwargs):
        for c in self.chunks:
            yield c


def _make_stream_tool_wrapper(injector):
    """Async-generator @mesh.tool shape (the multi-hop passthrough agent)."""

    async def passthrough(prompt: str, chat: mesh.McpMeshTool = None) -> mesh.Stream[str]:
        # Defensive user idiom — must keep working unchanged on timeout.
        if chat is None:
            yield "degraded"
            return
        async for chunk in chat.stream(prompt=prompt):
            yield chunk

    return injector.create_injection_wrapper(passthrough, ["chat_cap"])


def _make_canonical_route_handler():
    """The canonical two-function @mesh.route streaming shape (gateway)."""

    async def _stream(prompt, chat):
        async for chunk in chat.stream(prompt=prompt):
            yield chunk

    async def chat_endpoint(
        prompt: str, chat: mesh.McpMeshTool = None
    ) -> mesh.Stream[str]:
        if chat is None:
            raise HTTPException(
                status_code=503, detail="chat capability unavailable"
            )
        return _stream(prompt, chat)

    return chat_endpoint


async def _drain(streaming_response: StreamingResponse) -> str:
    chunks: list[str] = []
    async for piece in streaming_response.body_iterator:
        if isinstance(piece, bytes):
            piece = piece.decode("utf-8")
        chunks.append(piece)
    return "".join(chunks)


# ---------------------------------------------------------------------------
# Shape 1: decorator stream wrapper (_make_stream_wrapper)
# ---------------------------------------------------------------------------


class TestStreamToolWrapperSettle:
    @pytest.mark.asyncio
    async def test_resolution_mid_wait_streams_with_real_proxy(self, monkeypatch):
        """(a) Event arriving mid-wait → the stream proceeds with the proxy."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_stream_tool_wrapper(injector)
        dep = FakeStreamingDep(["alpha", " beta"])

        async def resolve_later():
            await asyncio.sleep(0.2)
            wrapper._mesh_update_dependency(0, dep)

        resolver = asyncio.create_task(resolve_later())
        start = time.monotonic()
        result = await wrapper(prompt="hi")
        elapsed = time.monotonic() - start
        await resolver

        assert result == "alpha beta"  # real proxy, chunks accumulated
        assert elapsed < 5.0  # woken by the event, not the budget ceiling
        assert get_settle_state().wait_count >= 1

    @pytest.mark.asyncio
    async def test_timeout_runs_defensive_branch(self, monkeypatch):
        """(b) No event → proceeds at budget with None; the user's
        defensive ``if chat is None`` branch runs (today-behavior)."""
        _set_budget(monkeypatch, "0.3")
        injector = DependencyInjector()
        wrapper = _make_stream_tool_wrapper(injector)

        start = time.monotonic()
        result = await wrapper(prompt="hi")
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert elapsed >= 0.2  # actually waited toward the budget

    @pytest.mark.asyncio
    async def test_settled_streams_with_zero_wait(self, monkeypatch):
        """(c) Dep resolved before the call → no wait primitives touched."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper = _make_stream_tool_wrapper(injector)
        wrapper._mesh_update_dependency(0, FakeStreamingDep(["x"]))

        state = get_settle_state()
        assert state.is_settled()

        with patch.object(
            state, "wait_for_async", wraps=state.wait_for_async
        ) as wait_spy:
            start = time.monotonic()
            result = await wrapper(prompt="hi")
            elapsed = time.monotonic() - start

        assert result == "x"
        assert elapsed < 0.5
        wait_spy.assert_not_called()
        assert state.wait_count == 0


# ---------------------------------------------------------------------------
# Shape 2: @mesh.route SSE endpoint (_build_sse_endpoint)
# ---------------------------------------------------------------------------


class TestSseEndpointSettle:
    def _build(self, injector):
        handler = _make_canonical_route_handler()
        wrapper = injector.create_injection_wrapper(handler, ["chat_cap"])
        return wrapper, _build_sse_endpoint(wrapper, handler)

    @pytest.mark.asyncio
    async def test_resolution_mid_wait_streams_with_real_proxy(self, monkeypatch):
        """(a) Event arriving mid-wait → SSE stream proceeds with the proxy."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper, endpoint = self._build(injector)
        dep = FakeStreamingDep(["alpha", "beta"])

        async def resolve_later():
            await asyncio.sleep(0.2)
            wrapper._mesh_update_dependency(0, dep)

        resolver = asyncio.create_task(resolve_later())
        start = time.monotonic()
        response = await endpoint(prompt="hi")
        elapsed = time.monotonic() - start
        await resolver

        assert isinstance(response, StreamingResponse)
        body = await _drain(response)
        assert body == "data: alpha\n\ndata: beta\n\ndata: [DONE]\n\n"
        assert elapsed < 5.0
        assert get_settle_state().wait_count >= 1

    @pytest.mark.asyncio
    async def test_timeout_raises_users_clean_503(self, monkeypatch):
        """(b) No event → None injected at budget; the canonical shape's
        defensive branch raises a clean HTTPException(503) — the degraded
        contract — NOT a raw 500."""
        _set_budget(monkeypatch, "0.3")
        injector = DependencyInjector()
        _, endpoint = self._build(injector)

        start = time.monotonic()
        with pytest.raises(HTTPException) as exc_info:
            await endpoint(prompt="hi")
        elapsed = time.monotonic() - start

        assert exc_info.value.status_code == 503
        assert elapsed >= 0.2

    @pytest.mark.asyncio
    async def test_settled_streams_with_zero_wait(self, monkeypatch):
        """(c) Dep resolved before the call → no wait primitives touched."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        wrapper, endpoint = self._build(injector)
        wrapper._mesh_update_dependency(0, FakeStreamingDep(["x"]))

        state = get_settle_state()
        assert state.is_settled()

        start = time.monotonic()
        response = await endpoint(prompt="hi")
        body = await _drain(response)
        elapsed = time.monotonic() - start

        assert body == "data: x\n\ndata: [DONE]\n\n"
        assert elapsed < 0.5
        assert state.wait_count == 0

    @pytest.mark.asyncio
    async def test_caller_supplied_dep_never_waits(self, monkeypatch):
        """Mock contract: a caller-supplied slot skips the wait entirely."""
        _set_budget(monkeypatch, "5")
        injector = DependencyInjector()
        _, endpoint = self._build(injector)
        assert not get_settle_state().is_settled()

        start = time.monotonic()
        response = await endpoint(prompt="hi", chat=FakeStreamingDep(["m"]))
        body = await _drain(response)
        elapsed = time.monotonic() - start

        assert body == "data: m\n\ndata: [DONE]\n\n"
        assert elapsed < 0.5
        assert get_settle_state().wait_count == 0


# ---------------------------------------------------------------------------
# Issue #1206 root cause: decoration-time SSE endpoint
# ---------------------------------------------------------------------------


class TestDecorationTimeSseEndpoint:
    def test_route_decorator_returns_sse_endpoint_for_stream_routes(self):
        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        assert getattr(decorated, "_mesh_is_sse_endpoint", False) is True
        inner = decorated._mesh_inner_wrapper
        assert callable(getattr(inner, "_mesh_update_dependency", None))
        assert decorated._mesh_original_func is handler

    def test_non_stream_route_unaffected(self):
        async def plain(payload: dict, db: mesh.McpMeshTool = None) -> dict:
            return {"ok": db is not None}

        decorated = mesh.route(dependencies=["db"])(plain)
        assert not getattr(decorated, "_mesh_is_sse_endpoint", False)

    def test_pre_integration_request_streams_instead_of_500(self):
        """THE #1206 regression: a request served BEFORE the route-integration
        pipeline step runs must hit the SSE endpoint (registered at
        @app.post() time), not the plain DI wrapper whose raw
        async-generator return FastAPI cannot serialize (the observed
        gateway 500)."""
        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        app = FastAPI()
        app.post("/api/chat")(decorated)

        # Resolve the dependency, but deliberately do NOT run
        # RouteIntegrationStep — this is the pre-integration window.
        decorated._mesh_inner_wrapper._mesh_update_dependency(
            0, FakeStreamingDep(["alpha", "beta"])
        )

        client = TestClient(app)
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(
                "text/event-stream"
            )
            body = response.read().decode("utf-8")

        assert body == "data: alpha\n\ndata: beta\n\ndata: [DONE]\n\n"

    def test_pre_integration_request_held_then_streams(self, monkeypatch):
        """The full failure shape from the uc18 migration: a request that
        arrives during settling is HELD by the grace and must complete in
        the SSE endpoint once the dependency resolves mid-wait."""
        _set_budget(monkeypatch, "10")
        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        app = FastAPI()
        app.post("/api/chat")(decorated)

        assert not get_settle_state().is_settled()

        # Resolution arrives from a foreign thread while the request is
        # held — the real heartbeat shape.
        timer = threading.Timer(
            0.3,
            lambda: decorated._mesh_inner_wrapper._mesh_update_dependency(
                0, FakeStreamingDep(["held", "ok"])
            ),
        )
        timer.start()

        client = TestClient(app)
        start = time.monotonic()
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            body = response.read().decode("utf-8")
        elapsed = time.monotonic() - start
        timer.join()

        assert body == "data: held\n\ndata: ok\n\ndata: [DONE]\n\n"
        assert elapsed < 5.0  # woken by the event, not the 10s ceiling
        assert get_settle_state().wait_count >= 1

    def test_unresolved_after_window_returns_clean_503(self, monkeypatch):
        """Degraded contract preserved: window expired + dep unresolved →
        the user's defensive branch produces a clean 503 over HTTP."""
        _set_budget(monkeypatch, "0.05")
        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        app = FastAPI()
        app.post("/api/chat")(decorated)
        time.sleep(0.1)  # let the window expire

        client = TestClient(app)
        response = client.post("/api/chat?prompt=hi")
        assert response.status_code == 503
        assert "chat capability unavailable" in response.text

    def test_integration_step_keeps_decorator_built_endpoint(self):
        """RouteIntegrationStep must not re-wrap a decoration-built SSE
        endpoint — it only registers the inner wrapper for heartbeat
        dependency updates."""
        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        app = FastAPI()
        app.post("/api/chat")(decorated)

        step = RouteIntegrationStep()
        route_info = {
            "endpoint": decorated,
            "endpoint_name": decorated.__name__,
            "path": "/api/chat",
            "methods": ["POST"],
            "dependencies": [{"capability": "chat"}],
        }
        result = step._integrate_single_route(app, route_info, None)

        assert result["status"] == "integrated"
        assert result["sse"] is True

        # Endpoint identity unchanged on the app route.
        endpoint = next(
            r.endpoint
            for r in app.router.routes
            if getattr(r, "path", "") == "/api/chat"
        )
        assert endpoint is decorated

        # Heartbeat updates target the INNER wrapper (whose injected-deps
        # array the SSE endpoint reads by reference).
        registered = DecoratorRegistry.get_route_wrapper("POST:/api/chat")
        assert registered is not None
        assert registered["wrapper"] is decorated._mesh_inner_wrapper

    def test_dual_import_convergence_repoints_sse_endpoint(self, monkeypatch):
        """Dual-import scenario (``python main.py`` + ``from main import X``):
        decoration fires twice, producing TWO DI wrapper instances. The SSE
        endpoint is closure-built against wrapper A (the __main__ instance),
        but heartbeat updates land on wrapper B (the named-module instance,
        last-write-wins under the METHOD:path registry key). Integration must
        converge: re-point the endpoint's dynamic ``_mesh_inner_wrapper`` to
        B and register B — so an update on B is visible to the SERVED
        endpoint. Wrapper A's orphaned settle keys must be retired so the
        eager settle latch still flips (no per-request budget-long holds)."""
        _set_budget(monkeypatch, "10")
        injector = DependencyInjector()
        monkeypatch.setattr(
            route_integration, "get_global_injector", lambda: injector
        )

        # Two evaluations of the same source function under different
        # module names — same qualname, same code location.
        handler_a = _make_canonical_route_handler()
        handler_a.__module__ = "__main__"
        handler_b = _make_canonical_route_handler()
        handler_b.__module__ = "chat_agent"
        wrapper_a = injector.create_injection_wrapper(handler_a, ["chat_cap"])
        wrapper_b = injector.create_injection_wrapper(handler_b, ["chat_cap"])

        # uvicorn serves the endpoint bound (at decoration time) to A.
        endpoint = _build_sse_endpoint(wrapper_a, handler_a)
        assert endpoint._mesh_inner_wrapper is wrapper_a

        app = FastAPI()
        app.post("/api/chat")(endpoint)

        step = RouteIntegrationStep()
        route_info = {
            "endpoint": endpoint,
            "endpoint_name": endpoint.__name__,
            "path": "/api/chat",
            "methods": ["POST"],
            "dependencies": [{"capability": "chat_cap"}],
        }
        result = step._integrate_single_route(app, route_info, None)
        assert result["status"] == "integrated"
        assert result["sse"] is True

        # Convergence: endpoint re-pointed to B; B registered for heartbeats.
        assert endpoint._mesh_inner_wrapper is wrapper_b
        registered = DecoratorRegistry.get_route_wrapper("POST:/api/chat")
        assert registered is not None
        assert registered["wrapper"] is wrapper_b

        # Heartbeat resolves the dep on B (the registered wrapper)...
        registered["wrapper"]._mesh_update_dependency(
            0, FakeStreamingDep(["converged"])
        )

        # ...and A's orphaned declared key was retired, so resolving B's
        # last key flips the eager latch — the window doesn't stay pinned
        # open until timeout.
        state = get_settle_state()
        assert state.is_settled()

        # The SERVED endpoint (built against A) reads the dep through its
        # dynamic inner-wrapper reference — and with the latch settled it
        # never touches the wait primitives.
        client = TestClient(app)
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            body = response.read().decode("utf-8")
        assert body == "data: converged\n\ndata: [DONE]\n\n"
        assert state.wait_count == 0

    def test_sse_build_failure_falls_back_to_integration_time_wrapping(
        self, monkeypatch
    ):
        """Graceful degradation: when the decoration-time SSE build fails,
        @mesh.route returns the DI wrapper with the streaming return
        annotation stripped (the pre-#1206 flow) so FastAPI registration
        still succeeds and the integration step can do the SSE swap."""

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic SSE build failure")

        monkeypatch.setattr(route_integration, "_build_sse_endpoint", _boom)

        handler = _make_canonical_route_handler()
        decorated = mesh.route(dependencies=["chat"])(handler)

        assert not getattr(decorated, "_mesh_is_sse_endpoint", False)
        assert getattr(decorated, "_mesh_is_injection_wrapper", False) is True
        assert "return" not in (getattr(decorated, "__annotations__", {}) or {})

        # Registration must not crash (no Stream[str] response_field).
        app = FastAPI()
        app.post("/api/chat")(decorated)
