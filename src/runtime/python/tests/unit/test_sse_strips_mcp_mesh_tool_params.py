"""Unit tests for issue #645 bug 5: the SSE wrapper must hide
``McpMeshTool``-typed parameters from FastAPI's signature inspection.

When a streaming route handler combines a Pydantic body model AND a mesh
dependency::

    @app.post("/api/chat")
    @mesh.route(dependencies=["chat"])
    async def chat_endpoint(
        body: ChatRequest,
        chat: McpMeshTool = None,
    ) -> mesh.Stream[str]: ...

FastAPI sees two non-trivial parameters and switches to *embed mode* body
parsing — expecting ``{"body": {...}}`` instead of ``{...}``. The result is
a 422 ``missing field "body"`` for plain ``{"prompt": "..."}`` payloads.

Mesh deps are framework-injected — never bound from the request body — so
they must not influence FastAPI's parameter binding. The SSE adapter strips
them from the ``__signature__`` it exposes to FastAPI.
"""

import inspect
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.api_startup.route_integration import (
    RouteIntegrationStep,
    _build_sse_endpoint,
)


@pytest.fixture(autouse=True)
def _reset_decorator_registry():
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


class TestSseStripsMcpMeshToolFromSignature:
    def test_signature_excludes_mcp_mesh_tool_params(self):
        """The SSE-wrapped endpoint hides McpMeshTool params from FastAPI."""

        async def chat(
            prompt: str,
            chat: mesh.McpMeshTool = None,
        ) -> mesh.Stream[str]:
            yield prompt

        wrapper = MagicMock()
        wrapper._mesh_original_func = chat
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["chat"]
        wrapper._mesh_injected_deps = [None]
        wrapper._mesh_route_metadata = {}

        endpoint = _build_sse_endpoint(wrapper, chat)
        sig = inspect.signature(endpoint)

        assert "prompt" in sig.parameters
        # The mesh dep MUST NOT appear in the FastAPI-facing signature.
        assert "chat" not in sig.parameters, (
            "McpMeshTool-typed param leaked into FastAPI signature; this "
            "triggers embed-mode body parsing when a Pydantic body model is "
            "present (issue #645 bug 5)."
        )

    def test_signature_excludes_mcp_mesh_tool_when_combined_with_body_model(self):
        """Even with a Pydantic body model, the mesh dep stays stripped."""

        class ChatRequest(BaseModel):
            prompt: str

        async def chat_endpoint(
            body: ChatRequest,
            chat: mesh.McpMeshTool = None,
        ) -> mesh.Stream[str]:
            yield body.prompt

        wrapper = MagicMock()
        wrapper._mesh_original_func = chat_endpoint
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["chat"]
        wrapper._mesh_injected_deps = [None]
        wrapper._mesh_route_metadata = {}

        endpoint = _build_sse_endpoint(wrapper, chat_endpoint)
        sig = inspect.signature(endpoint)

        assert "body" in sig.parameters
        assert sig.parameters["body"].annotation is ChatRequest
        assert "chat" not in sig.parameters

    def test_annotations_dict_also_drops_mcp_mesh_tool_param(self):
        """``__annotations__`` is what get_type_hints() walks. Strip it too."""

        async def chat(
            prompt: str,
            chat: mesh.McpMeshTool = None,
        ) -> mesh.Stream[str]:
            yield prompt

        endpoint = _build_sse_endpoint(chat, chat)
        anns = getattr(endpoint, "__annotations__", {})
        assert "prompt" in anns
        assert "chat" not in anns
        assert "return" not in anns


class TestSseEndToEndPydanticBody:
    """End-to-end: TestClient calls a Pydantic-body streaming route with a mesh
    dep, expects normal (non-embed) JSON body parsing and SSE response."""

    def test_pydantic_body_with_mesh_dep_no_embed_mode(self):
        class ChatRequest(BaseModel):
            prompt: str

        async def chat_endpoint(
            body: ChatRequest,
            chat: mesh.McpMeshTool = None,
        ) -> mesh.Stream[str]:
            for word in body.prompt.split():
                yield word + " "

        # Fake mesh dep wrapper preserving DI state.
        wrapper = MagicMock()
        wrapper._mesh_original_func = chat_endpoint
        wrapper._mesh_positions = [1]
        wrapper._mesh_dependencies = ["chat"]
        wrapper._mesh_injected_deps = [None]
        wrapper._mesh_route_metadata = {}
        wrapper._mesh_is_injection_wrapper = True

        # Build the SSE endpoint and hand it to FastAPI directly. We bypass
        # RouteIntegrationStep here because that path requires a real
        # injector + DecoratorRegistry route registration, but we're testing
        # the wrapper's signature interaction with FastAPI specifically.
        endpoint = _build_sse_endpoint(wrapper, chat_endpoint)

        app = FastAPI()
        app.post("/api/chat", response_model=None)(endpoint)

        client = TestClient(app)
        # Plain body (NOT embed-mode wrapped): {"prompt": "..."} not
        # {"body": {"prompt": "..."}}.
        with client.stream(
            "POST",
            "/api/chat",
            json={"prompt": "hi there"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = response.read().decode("utf-8")

        assert "data: hi \n\n" in body
        assert "data: there \n\n" in body
        assert body.endswith("data: [DONE]\n\n")

    def test_full_route_integration_with_pydantic_body_and_mesh_dep(self):
        """Run through RouteIntegrationStep so the route.dependant rebuild is
        also exercised for the McpMeshTool-stripping case."""

        class ChatRequest(BaseModel):
            prompt: str

        @mesh.route(dependencies=["chat"])
        async def chat_endpoint(
            body: ChatRequest,
            chat: mesh.McpMeshTool = None,
        ) -> mesh.Stream[str]:
            yield body.prompt

        app = FastAPI()
        app.post("/api/chat")(chat_endpoint)

        step = RouteIntegrationStep()
        route_info = _build_route_info(
            chat_endpoint, "/api/chat", deps=[{"capability": "chat"}]
        )
        result = step._integrate_single_route(app, route_info, MagicMock())
        assert result["status"] == "integrated"
        assert result["sse"] is True

        # After integration, the route's endpoint signature must NOT include
        # the McpMeshTool param — otherwise FastAPI rebuilds the dependant
        # in embed-mode and rejects flat JSON.
        registered = next(
            r for r in app.router.routes if getattr(r, "path", "") == "/api/chat"
        )
        sig = inspect.signature(registered.endpoint)
        assert "body" in sig.parameters
        assert "chat" not in sig.parameters

        client = TestClient(app)
        response = client.post("/api/chat", json={"prompt": "hello"})
        if response.status_code != 200:
            pytest.fail(
                f"expected 200, got {response.status_code}: {response.text!r}"
            )
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text
        assert "data: hello\n\n" in body
        assert body.endswith("data: [DONE]\n\n")
