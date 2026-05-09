#!/usr/bin/env python3
"""
A2A consumer fixture for uc25 (issue #908) — bridges the existing
date_a2a_agent.py get-date skill into the mesh as a regular
current-date capability.

Adapted from examples/a2a/consumer_date_agent.py — all agents in
the tsuite container share the network namespace, so the upstream
A2A endpoint is reachable on localhost (NOT a docker service name).

Decorator order matters: @mesh.agent MUST be the LAST decorator so
auto_run=True triggers the mcp_startup pipeline (uvicorn + registry
handshake) AFTER the consumer is registered. The @mesh.a2a_consumer
self-tag (agent name) is resolved lazily via the
__MESH_CONSUMER_SELF__ sentinel so the consumer can be declared
above the agent class without crashing the import.
"""

import json
import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh so the framework's
# display_config picks up the same port we'll bind to.
HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9201"))

import mesh
from fastmcp import FastMCP

app = FastMCP("Date Consumer Bridge")


@app.tool()
@mesh.a2a_consumer(
    capability="current-date",
    a2a_url="http://localhost:9090/agents/date",
    a2a_skill_id="get-date",
    tags=["a2a-bridge"],
)
async def current_date(_a2a: mesh.A2AClient = None) -> dict:
    """Return today's date by calling the upstream A2A get-date skill.

    The producer-side handler returns {"date": "<iso-string>"} and the
    A2A surface JSON-stringifies it into the artifact text part — so
    we json.loads on the consumer side to recover the dict.
    """
    response = await _a2a.send(
        message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
    )
    return json.loads(response.artifact_text)


# @mesh.agent MUST be last — see module docstring.
@mesh.agent(name="date-consumer", http_port=HTTP_PORT)
class DateConsumer:
    """Mesh agent that bridges the date_a2a_agent's get-date skill."""

    pass
