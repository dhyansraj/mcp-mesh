"""Unit tests for the @mesh.route SSE adapter (P3 of issue #645).

Covers:
- Routes whose user function returns ``mesh.Stream[str]`` are SSE-wrapped:
  ``StreamingResponse`` with ``text/event-stream`` and the buffer-bypass
  headers (``X-Accel-Buffering: no`` etc.).
- Chunks are framed as ``data: <chunk>\\n\\n``.
- Successful streams terminate with ``data: [DONE]\\n\\n``.
- Exceptions surface as ``event: error`` SSE events with a JSON
  ``{"error": <msg>, "type": <exc class>}`` payload.
- Non-streaming routes are left unchanged (no SSE wrap).
- Multi-line chunks emit one ``data:`` line per line.
- ``__signature__`` is preserved so FastAPI's parameter binding still works.
- Cancellation propagates ``aclose()`` to the underlying generator.
- TestClient end-to-end: a streaming endpoint returns the expected SSE body.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.api_startup.route_integration import (
    RouteIntegrationStep,
    _build_sse_endpoint,
    _frame_chunk_as_sse,
    _resolve_user_function,
)

# Production-shaped @mesh.route handlers for issue #1037 regression tests.
# Defined in a sibling module that does NOT use `from __future__ import
# annotations`, so FastAPI sees real type objects (not PEP 563 strings) on
# parameters like `request: Request` and `dep: McpMeshTool`.
from ._route_sse_gateway_handlers import (
    chat_single_fn as _gw_chat_single_fn,
    chat_two_fn_outer as _gw_chat_two_fn_outer,
)


# ---------------------------------------------------------------------------
# _resolve_user_function
# ---------------------------------------------------------------------------


class TestResolveUserFunction:
    def test_unwrapped_handler_returned_as_is(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield prompt

        assert _resolve_user_function(chat) is chat

    def test_wrapped_handler_unwraps_to_original(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield prompt

        def wrapper(*a, **kw):
            return None

        wrapper._mesh_original_func = chat
        assert _resolve_user_function(wrapper) is chat


# ---------------------------------------------------------------------------
# _frame_chunk_as_sse — protocol compliance
# ---------------------------------------------------------------------------


class TestFrameChunkAsSSE:
    def test_single_line_chunk(self):
        assert _frame_chunk_as_sse("hello") == "data: hello\n\n"

    def test_multi_line_chunk_emits_one_data_per_line(self):
        framed = _frame_chunk_as_sse("line1\nline2\nline3")
        assert framed == "data: line1\ndata: line2\ndata: line3\n\n"

    def test_empty_chunk_still_emits_data_record(self):
        assert _frame_chunk_as_sse("") == "data: \n\n"

    def test_trailing_newline_does_not_create_phantom_line(self):
        # splitlines("a\n") == ["a"] — same framing as plain "a"
        assert _frame_chunk_as_sse("a\n") == "data: a\n\n"


# ---------------------------------------------------------------------------
# _build_sse_endpoint
# ---------------------------------------------------------------------------


async def _drain(streaming_response: StreamingResponse) -> str:
    chunks: list[str] = []
    async for piece in streaming_response.body_iterator:
        if isinstance(piece, bytes):
            piece = piece.decode("utf-8")
        chunks.append(piece)
    return "".join(chunks)


class TestBuildSseEndpointBasics:
    @pytest.mark.asyncio
    async def test_returns_streaming_response_with_sse_media_type(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "x"

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_includes_no_buffering_headers(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "x"

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")

        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("x-accel-buffering") == "no"
        assert response.headers.get("connection") == "keep-alive"

    @pytest.mark.asyncio
    async def test_chunks_emitted_as_sse_data_frames_with_done_terminator(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "chunk1"
            yield "chunk2"
            yield "chunk3"

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")
        body = await _drain(response)

        assert body == (
            "data: chunk1\n\n"
            "data: chunk2\n\n"
            "data: chunk3\n\n"
            "data: [DONE]\n\n"
        )

    @pytest.mark.asyncio
    async def test_multi_line_chunk_emits_one_data_per_line(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "first\nsecond\nthird"

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")
        body = await _drain(response)

        assert "data: first\ndata: second\ndata: third\n\n" in body
        assert body.endswith("data: [DONE]\n\n")

    @pytest.mark.asyncio
    async def test_signature_preserved_for_fastapi_param_binding(self):
        async def chat(prompt: str, top_k: int = 5) -> mesh.Stream[str]:
            yield prompt

        endpoint = _build_sse_endpoint(chat, chat)
        sig = inspect.signature(endpoint)

        assert "prompt" in sig.parameters
        assert "top_k" in sig.parameters
        assert sig.parameters["top_k"].default == 5
        # ctx must not leak into the HTTP-facing signature
        assert "ctx" not in sig.parameters


class TestBuildSseEndpointErrorHandling:
    @pytest.mark.asyncio
    async def test_mid_stream_exception_emits_event_error(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "ok-1"
            raise RuntimeError("boom")

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")
        body = await _drain(response)

        assert "data: ok-1\n\n" in body
        assert "event: error\n" in body
        # Find the error payload and assert its JSON shape
        err_marker = "event: error\ndata: "
        idx = body.index(err_marker) + len(err_marker)
        end = body.index("\n\n", idx)
        payload = json.loads(body[idx:end])
        assert payload == {"error": "boom", "type": "RuntimeError"}
        # On error, [DONE] is NOT emitted
        assert "[DONE]" not in body

    @pytest.mark.asyncio
    async def test_non_str_chunk_surfaces_as_event_error(self):
        async def bad(prompt: str) -> mesh.Stream[str]:
            yield 42  # type: ignore[misc]

        endpoint = _build_sse_endpoint(bad, bad)
        response = await endpoint(prompt="hi")
        body = await _drain(response)

        assert "event: error\n" in body
        idx = body.index("data: ", body.index("event: error")) + len("data: ")
        end = body.index("\n\n", idx)
        payload = json.loads(body[idx:end])
        assert payload["type"] == "TypeError"
        assert "non-str chunk" in payload["error"]


class TestBuildSseEndpointCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_calls_aclose_on_underlying_generator(self):
        finally_ran: list[bool] = []

        async def chat(prompt: str) -> mesh.Stream[str]:
            try:
                for i in range(100):
                    yield f"chunk-{i}"
                    await asyncio.sleep(0.01)
            finally:
                finally_ran.append(True)

        endpoint = _build_sse_endpoint(chat, chat)
        response = await endpoint(prompt="hi")
        body_iter = response.body_iterator

        # Pull one chunk so the generator has produced something
        first = await body_iter.__anext__()
        assert b"chunk-0" in (first if isinstance(first, bytes) else first.encode())

        # Simulate Starlette's cleanup on client disconnect
        await body_iter.aclose()

        # The user generator's finally block must have run
        assert finally_ran == [True]


class TestBuildSseEndpointDependencyInjection:
    @pytest.mark.asyncio
    async def test_dependencies_pulled_from_wrapper_state_when_present(self):
        captured: dict[str, object] = {}

        async def chat(prompt: str, helper=None) -> mesh.Stream[str]:
            captured["helper"] = helper
            yield prompt

        wrapper = MagicMock()
        wrapper._mesh_original_func = chat
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["helper-cap"]
        wrapper._mesh_injected_deps = ["the-helper-instance"]
        wrapper._mesh_route_metadata = {}

        endpoint = _build_sse_endpoint(wrapper, chat)
        response = await endpoint(prompt="hi")
        body = await _drain(response)

        assert captured["helper"] == "the-helper-instance"
        assert "data: hi\n\n" in body


# ---------------------------------------------------------------------------
# RouteIntegrationStep — detection + replacement
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_decorator_registry():
    """Each test starts with a clean DecoratorRegistry."""
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _build_route_info(handler, path, methods=("POST",), deps=None):
    return {
        "endpoint": handler,
        "endpoint_name": handler.__name__,
        "path": path,
        "methods": list(methods),
        "dependencies": deps or [],
    }


class TestRouteIntegrationStreamDetection:
    @pytest.mark.asyncio
    async def test_streaming_route_with_no_deps_gets_sse_wrapped(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "a"
            yield "b"

        app = FastAPI()
        # response_model=None mirrors what @mesh.route does to the wrapper it
        # returns; the annotation-strip logic in @mesh.route makes this implicit
        # for the real decorator path.
        app.post("/api/chat", response_model=None)(chat)

        step = RouteIntegrationStep()
        route_info = _build_route_info(chat, "/api/chat")
        result = step._integrate_single_route(app, route_info, MagicMock())

        assert result["status"] == "integrated"
        assert result.get("sse") is True

        # The route's endpoint is now the SSE wrapper
        sse_endpoint = next(
            r.endpoint for r in app.router.routes if getattr(r, "path", "") == "/api/chat"
        )
        assert getattr(sse_endpoint, "_mesh_is_sse_endpoint", False) is True

        # Calling it returns a StreamingResponse
        response = await sse_endpoint(prompt="hi")
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_non_streaming_route_with_no_deps_is_skipped(self):
        async def info() -> dict:
            return {"ok": True}

        app = FastAPI()
        app.get("/info")(info)

        step = RouteIntegrationStep()
        route_info = _build_route_info(info, "/info", methods=("GET",))
        result = step._integrate_single_route(app, route_info, MagicMock())

        assert result["status"] == "skipped"

        # Endpoint left unchanged
        endpoint = next(
            r.endpoint for r in app.router.routes if getattr(r, "path", "") == "/info"
        )
        assert endpoint is info
        assert not getattr(endpoint, "_mesh_is_sse_endpoint", False)

    @pytest.mark.asyncio
    async def test_invalid_stream_annotation_logs_warning_and_skips(self):
        async def bad(prompt: str) -> mesh.Stream[int]:  # type: ignore[type-var]
            yield 1

        app = FastAPI()
        app.post("/bad", response_model=None)(bad)

        step = RouteIntegrationStep()
        route_info = _build_route_info(bad, "/bad")
        result = step._integrate_single_route(app, route_info, MagicMock())

        # No deps + invalid stream annotation → still skipped, no crash
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_mesh_route_decorator_strips_stream_return_annotation(self):
        """Real-world flow: @app.post + @mesh.route + Stream[str] must register."""

        @mesh.route()
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield prompt

        app = FastAPI()
        # No response_model=None hint required — @mesh.route stripped the return
        # annotation from the wrapper it returned, so FastAPI accepts it.
        app.post("/api/chat")(chat)

        registered = next(
            r for r in app.router.routes if getattr(r, "path", "") == "/api/chat"
        )
        # FastAPI built no response_field because there's no return annotation
        assert registered.response_field is None


# ---------------------------------------------------------------------------
# TestClient end-to-end SSE smoke
# ---------------------------------------------------------------------------


class TestSseEndpointEndToEnd:
    def test_test_client_receives_full_sse_body(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "chunk1"
            yield "chunk2"
            yield "chunk3"

        app = FastAPI()
        app.post("/api/chat", response_model=None)(chat)

        step = RouteIntegrationStep()
        route_info = _build_route_info(chat, "/api/chat")
        result = step._integrate_single_route(app, route_info, MagicMock())
        assert result["status"] == "integrated"
        assert result["sse"] is True

        client = TestClient(app)
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers.get("x-accel-buffering") == "no"
            body = response.read().decode("utf-8")

        assert body == (
            "data: chunk1\n\n"
            "data: chunk2\n\n"
            "data: chunk3\n\n"
            "data: [DONE]\n\n"
        )

    def test_test_client_receives_event_error_on_exception(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "ok"
            raise ValueError("kaboom")

        app = FastAPI()
        app.post("/api/chat", response_model=None)(chat)

        step = RouteIntegrationStep()
        route_info = _build_route_info(chat, "/api/chat")
        step._integrate_single_route(app, route_info, MagicMock())

        client = TestClient(app)
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            body = response.read().decode("utf-8")

        assert "data: ok\n\n" in body
        assert "event: error\n" in body
        idx = body.index("event: error\ndata: ") + len("event: error\ndata: ")
        end = body.index("\n\n", idx)
        payload = json.loads(body[idx:end])
        assert payload == {"error": "kaboom", "type": "ValueError"}
        assert "[DONE]" not in body

    def test_real_decorator_chain_emits_sse_end_to_end(self):
        """Full @app.post + @mesh.route + integration step flow."""

        @mesh.route()
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "alpha"
            yield "beta"

        app = FastAPI()
        app.post("/api/chat")(chat)

        step = RouteIntegrationStep()
        # @mesh.route stores metadata under a different attribute path; the
        # collection step normally builds route_info — we synthesize equivalent
        # input here, matching what RouteCollectionStep produces in production.
        route_info = _build_route_info(chat, "/api/chat")
        result = step._integrate_single_route(app, route_info, MagicMock())
        assert result["status"] == "integrated"
        assert result["sse"] is True

        client = TestClient(app)
        with client.stream("POST", "/api/chat?prompt=hi") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = response.read().decode("utf-8")

        assert body == (
            "data: alpha\n\n"
            "data: beta\n\n"
            "data: [DONE]\n\n"
        )


# ---------------------------------------------------------------------------
# Issue #1037: production-natural @mesh.route SSE shape
# ---------------------------------------------------------------------------


class FakeStreamingDep:
    """Stand-in for an injected McpMeshTool whose remote tool streams chunks."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.last_kwargs = None

    async def stream(self, **kwargs):
        self.last_kwargs = kwargs
        for c in self.chunks:
            yield c


class TestSseGatewayShape:
    """Regression coverage for issue #1037.

    Probes the single-function, user-natural gateway shape combining:
      * async-gen handler (`yield` in body)
      * `mesh.Stream[str]` return annotation
      * `request: Request` parameter (FastAPI request injection)
      * `await request.json()` as the first async operation INSIDE the gen body
      * mesh-DI'd McpMeshTool consumed via `async for chunk in dep.stream(...)`
      * early-error branch with `yield "..."; return` when dep is missing

    Findings (May 2026):

    * The `_build_sse_endpoint` machinery handles the user-natural shape
      correctly when driven directly with an async-iter response (see
      ``test_async_gen_with_request_body_inside_works_at_wrapper_level``).
    * Routing the same shape through TestClient (and, by extension, any real
      ASGI server) **deadlocks** because Starlette parses the request body
      lazily: the StreamingResponse iterator must yield its first chunk
      before the request body is available, but the iterator is itself
      ``await``-ing ``request.json()``. This is the production bug that
      issue #1037 reproduces.
    * The early-error branch (``yield "..."; return`` BEFORE
      ``await request.json()``) does work end-to-end — it never touches the
      request body, so the deadlock never forms. It surfaces as HTTP 200
      with an SSE body, NOT as an HTTP-level error.
    * The canonical two-function shape (parse + validate up-front in a
      coroutine handler, ``return`` an async-gen helper) works cleanly
      end-to-end, including HTTP 503 on the missing-dep path.
    """

    @pytest.mark.asyncio
    async def test_async_gen_with_request_body_inside_works_at_wrapper_level(self):
        """The mesh SSE wrapper itself handles the user-natural shape fine.

        The bug (issue #1037) is NOT in ``_build_sse_endpoint`` — when driven
        with an awaitable Request stand-in, all the chunks flow correctly,
        ``dep.stream(**kwargs)`` is called with the right kwargs, and the
        ``[DONE]`` terminator is emitted. The deadlock surfaces only when the
        Request is a real Starlette request being parsed by an ASGI server
        (see the next test for that production-path failure).
        """
        fake_dep = FakeStreamingDep(["alpha", "beta", "gamma"])
        wrapper = MagicMock()
        wrapper._mesh_original_func = _gw_chat_single_fn
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["dep-cap-name"]
        wrapper._mesh_injected_deps = [fake_dep]
        wrapper._mesh_route_metadata = {}

        sse_endpoint = _build_sse_endpoint(wrapper, _gw_chat_single_fn)

        class _FakeReq:
            async def json(self):
                return {"text": "hello"}

        response = await sse_endpoint(request=_FakeReq())
        body = await _drain(response)
        assert body == (
            "data: alpha\n\n"
            "data: beta\n\n"
            "data: gamma\n\n"
            "data: [DONE]\n\n"
        )
        assert fake_dep.last_kwargs == {"text": "hello"}

    @pytest.mark.filterwarnings("ignore::ResourceWarning")
    def test_async_gen_with_request_body_deadlocks_over_http(self):
        """**Regression guard for issue #1037.**

        ``await request.json()`` placed INSIDE an async-gen body that's
        wrapped in a StreamingResponse deadlocks under a real ASGI driver
        (TestClient here, but the same applies to uvicorn). Starlette only
        starts feeding the response generator after the request body has
        been fully delivered — but the generator is suspended on
        ``await request.json()``, which is itself waiting for the body.
        Neither side can progress.

        This test runs the call in a background thread and asserts the
        thread does NOT finish within a generous timeout — i.e. the
        deadlock IS reproducible. The day this test fails (i.e. the call
        returns), the upstream framework deadlock has been fixed and the
        single-function shape can be promoted to first-class.
        """
        import threading

        fake_dep = FakeStreamingDep(["alpha", "beta", "gamma"])
        wrapper = MagicMock()
        wrapper._mesh_original_func = _gw_chat_single_fn
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["dep-cap-name"]
        wrapper._mesh_injected_deps = [fake_dep]
        wrapper._mesh_route_metadata = {}

        sse_endpoint = _build_sse_endpoint(wrapper, _gw_chat_single_fn)
        app = FastAPI()
        app.post("/api/chat")(sse_endpoint)

        result: dict = {}

        def _call():
            try:
                with TestClient(app) as client:
                    r = client.post("/api/chat", json={"text": "hello"})
                    result["status"] = r.status_code
                    result["body"] = r.text
            except Exception as e:
                result["error"] = repr(e)

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=8.0)
        assert t.is_alive(), (
            "Expected the single-function gateway shape to deadlock over HTTP "
            f"(issue #1037), but the call returned: result={result!r}. "
            "If this test now passes-as-non-deadlock, the upstream Starlette/"
            "FastAPI body-parsing flow has been fixed and docs should be "
            "updated to promote the single-function shape."
        )

    def test_early_error_yield_before_request_body_works_over_http(self):
        """The missing-dep branch (`yield "..."; return` BEFORE
        ``await request.json()``) does NOT touch the request body, so the
        deadlock never forms. It surfaces as HTTP 200 with an SSE body —
        NOT HTTP 503. That's the contract trade-off users need to understand
        when they pick the single-function shape.
        """
        wrapper = MagicMock()
        wrapper._mesh_original_func = _gw_chat_single_fn
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["dep-cap-name"]
        wrapper._mesh_injected_deps = [None]
        wrapper._mesh_route_metadata = {}

        sse_endpoint = _build_sse_endpoint(wrapper, _gw_chat_single_fn)
        app = FastAPI()
        app.post("/api/chat")(sse_endpoint)

        client = TestClient(app)
        with client.stream("POST", "/api/chat", json={}) as response:
            status = response.status_code
            ct = response.headers.get("content-type", "")
            body = response.read().decode("utf-8")

        # Status is 200 with SSE framing — NOT 503. Once the SSE wrapper
        # returns a StreamingResponse, response headers flush before the
        # user gen runs, so HTTP-level errors are unreachable from inside
        # the gen body.
        assert status == 200
        assert ct.startswith("text/event-stream")
        assert body == "data: no dep\n\ndata: [DONE]\n\n"

    def test_canonical_two_function_shape_streams_and_503s_correctly(self):
        """The canonical fix for issue #1037: a coroutine handler that
        validates + parses the body up-front and ``return``s an async-gen
        helper. The helper does the streaming; the outer coroutine can
        ``raise HTTPException`` cleanly because the response status hasn't
        been committed yet.

        Happy path: stream all chunks + [DONE].
        Error path: clean HTTP 503, no SSE framing.
        """
        fake_dep = FakeStreamingDep(["alpha", "beta", "gamma"])

        # Outer coroutine (NOT an async-gen) defined at module scope so
        # annotations resolve under `from __future__ import annotations`.
        outer = _gw_chat_two_fn_outer

        # Happy path
        wrapper_ok = MagicMock()
        wrapper_ok._mesh_original_func = outer
        wrapper_ok._mesh_positions = [1]
        wrapper_ok._mesh_dependencies = ["dep-cap-name"]
        wrapper_ok._mesh_injected_deps = [fake_dep]
        wrapper_ok._mesh_route_metadata = {}

        sse_endpoint_ok = _build_sse_endpoint(wrapper_ok, outer)
        app_ok = FastAPI()
        app_ok.post("/api/chat")(sse_endpoint_ok)

        client_ok = TestClient(app_ok)
        with client_ok.stream(
            "POST", "/api/chat", json={"text": "hello"}
        ) as response:
            assert response.status_code == 200
            assert response.headers.get("content-type", "").startswith(
                "text/event-stream"
            )
            body = response.read().decode("utf-8")
        assert body == (
            "data: alpha\n\n"
            "data: beta\n\n"
            "data: gamma\n\n"
            "data: [DONE]\n\n"
        )

        # Error path — dep is None: outer raises HTTPException up-front,
        # before any StreamingResponse is constructed, so FastAPI returns
        # a clean HTTP 503.
        wrapper_err = MagicMock()
        wrapper_err._mesh_original_func = outer
        wrapper_err._mesh_positions = [1]
        wrapper_err._mesh_dependencies = ["dep-cap-name"]
        wrapper_err._mesh_injected_deps = [None]
        wrapper_err._mesh_route_metadata = {}

        sse_endpoint_err = _build_sse_endpoint(wrapper_err, outer)
        app_err = FastAPI()
        app_err.post("/api/chat")(sse_endpoint_err)

        client_err = TestClient(app_err)
        r = client_err.post("/api/chat", json={})
        assert r.status_code == 503
        assert "dep unavailable" in r.text
