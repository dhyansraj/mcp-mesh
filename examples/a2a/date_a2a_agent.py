#!/usr/bin/env python3
"""
A2A example agent — exposes the existing examples/simple/system_agent
``date_service`` capability via the A2A v1.0 protocol surface.

This demonstrates the user-controlled FastAPI mounting pattern with
``mesh.a2a.mount(app, ...)``. The user owns the FastAPI app AND owns
the uvicorn lifecycle — same shape as ``examples/simple/fastapi_app.py``
with ``@mesh.route``. The mesh ``api_startup`` pipeline picks up the
mounted A2A surface from the DecoratorRegistry and registers the agent
with the registry as ``agent_type=a2a`` (with the surfaces array
populated) on each heartbeat round-trip.

The helper wires both companion routes the A2A protocol requires:

    GET  /agents/date/.well-known/agent.json   (agent card)
    POST /agents/date                          (JSON-RPC tasks/* entry)

Phase 2 dispatches sync ``tasks/send`` into the user's handler and wraps
the return value in an A2A v1.0 ``Task`` envelope. Other ``tasks/*``
methods (``tasks/get``, ``tasks/cancel``, ``tasks/sendSubscribe``) and
``tasks/send`` for ``task=True`` underlying tools still return
``-32601 Method not implemented`` — Phase 3 territory.

Prereqs (in three terminals)
============================

  # 1) Registry
  meshctl start registry

  # 2) Provider — exposes date_service (from examples/simple)
  python examples/simple/system_agent.py

  # 3) This A2A surface — exposes date_service via A2A
  python examples/a2a/date_a2a_agent.py

Test the A2A surface
====================

  # Agent card — registry stamps the public ``url`` field when
  # MCP_MESH_PUBLIC_URL_PREFIX is set on the registry; otherwise the
  # card uses the local fallback http://localhost:9090/agents/date.
  curl http://localhost:9090/agents/date/.well-known/agent.json | jq

  # JSON-RPC tasks/send (Phase 2: dispatches into the handler and
  # returns an A2A v1.0 Task envelope under jsonrpc.result).
  curl -X POST http://localhost:9090/agents/date \\
       -H 'Content-Type: application/json' \\
       -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"id":"t1","message":{"role":"user","parts":[]}}}'
"""

import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh so the framework's
# display_config picks up the same port we'll bind uvicorn to. Without
# this, the agent card's `url` field falls back to the framework
# default (8080) instead of the actual uvicorn port (9090).
HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9090"))

import mesh
from fastapi import FastAPI
from mesh.types import McpMeshTool

# User-owned FastAPI app — same pattern as @mesh.route examples
# (see examples/simple/fastapi_app.py). NO @mesh.agent decorator;
# the user owns the uvicorn lifecycle (see __main__ below).
app = FastAPI(title="Date A2A Agent")


@mesh.a2a.mount(
    app,
    path="/agents/date",
    dependencies=["date_service"],
    description="Get current date/time via A2A protocol",
    skill_id="get-date",
    skill_name="Get Date",
    tags=["system", "date"],
)
async def date_a2a(payload: dict, date_service: McpMeshTool = None):
    """A2A handler. Phase 2's JSON-RPC entry dispatches ``tasks/send``
    into this body and wraps the return value in an A2A v1.0 ``Task``
    envelope (artifact 0 carries the JSON-stringified return). The
    ``payload`` argument is the A2A request ``message`` dict
    (``{"role": "user", "parts": [...]}``); for the date example we
    ignore it and just call the underlying mesh dependency.
    """
    if date_service is None:
        return {"error": "date_service not yet resolved"}
    result = await date_service()
    return {"date": result}


if __name__ == "__main__":
    import uvicorn

    print(f"🌐 Date A2A Agent on http://localhost:{HTTP_PORT}")
    print(f"    Card:     GET  http://localhost:{HTTP_PORT}/agents/date/.well-known/agent.json")
    print(f"    JSON-RPC: POST http://localhost:{HTTP_PORT}/agents/date")
    print()
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
