"""Route-layer regression for empty-collection returns (issue #1039).

#1039 reported that a ``@mesh.route`` gateway returning a dependency's empty
list produced ``null`` on the HTTP wire (not ``[]``). Root cause: the consumer
proxy collapsed empty MCP content to ``None`` — fixed producer-side by #1251
(FastMCP now emits ``structuredContent {"result": []}`` for empty returns) and
consumer-side by #1250 (both proxy transports recover the value). Once the
proxy hands back ``[]``, a route handler that ``return await dep(...)`` yields
``[]`` and FastAPI serializes it as ``[]``.

These tests exercise the ACTUAL route layer end to end: a real ``@mesh.route``
handler mounted on a FastAPI app, driven by ``TestClient``, with the injected
dependency resolved (via the same ``_mesh_update_dependency`` funnel the
heartbeat uses) to a stub proxy that returns a fixed value. We assert the HTTP
wire body — ``[]`` for an empty-list return, and ``null`` preserved for a
genuine ``None`` return.
"""

from __future__ import annotations

from typing import Any

import mesh
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mesh.types import McpMeshTool


class _StubProxy:
    """Stand-in for the injected McpMeshTool proxy — returns a fixed value.

    Mirrors the shape the DI wrapper expects of a resolved dependency: an
    async-callable with an ``isAvailable()`` probe. Returning the value
    directly (rather than an MCP envelope) models the state AFTER the proxy's
    own #1250 recovery — i.e. the exact value a route handler awaits.
    """

    def __init__(self, value: Any):
        self._value = value
        self.endpoint = "http://stub:9000"

    def isAvailable(self) -> bool:  # noqa: N802 (mesh proxy contract)
        return True

    async def __call__(self, **kwargs: Any) -> Any:
        return self._value


def _build_route_app(return_value: Any) -> FastAPI:
    """A FastAPI app with one real @mesh.route handler whose dependency is
    resolved to a stub proxy returning ``return_value``."""
    app = FastAPI()

    # No return annotation: FastAPI serializes the raw value (no response_model
    # coercion), which isolates the wire-encoding contract #1039 is about —
    # [] → "[]", None → "null" — rather than response-model type validation.
    @mesh.route(dependencies=["list_notifications"])
    async def list_endpoint(list_notifications: McpMeshTool = None):
        return await list_notifications(user_id="alice")

    # Resolve the dependency exactly as a heartbeat would: index-based update
    # of the wrapper's injected-deps array with a live proxy.
    list_endpoint._mesh_update_dependency(0, _StubProxy(return_value))

    app.get("/api/notifications")(list_endpoint)
    return app


def test_route_empty_list_wire_body_is_empty_list_not_null():
    client = TestClient(_build_route_app([]))
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    # #1039 symptom: the body must be "[]", never "null".
    assert resp.text == "[]"
    assert resp.json() == []


def test_route_populated_list_wire_body_unchanged():
    client = TestClient(_build_route_app([{"id": 1}, {"id": 2}]))
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    assert resp.json() == [{"id": 1}, {"id": 2}]


def test_route_genuine_none_return_wire_body_is_null():
    client = TestClient(_build_route_app(None))
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    # The "no result" contract is preserved: None still serializes to null.
    assert resp.text == "null"
