#!/usr/bin/env python3
"""
A2A consumer example — bridges the existing ``date_a2a_agent.py``
``get-date`` skill into the mesh as a regular ``current-date``
capability. This is the consumer side of the A2A bridge (issue #908):
a mesh agent that calls OUT to an external A2A endpoint and
re-publishes the skill as a normal mesh tool.

The downstream mesh tool depending on ``current-date`` does not need
to know it is talking to an A2A backend — mesh's existing
capability+tag failover applies the moment a SECOND consumer
(e.g. ``accuweather-bridge``) registers the same ``current-date``
capability with a different consumer-name tag.

Each consumer auto-tags its capability with the agent name (here
``date-consumer``) so downstream resolvers can pin a specific
backend via the dependency tag selector.

Decorator order matters
=======================

``@mesh.agent`` MUST be the LAST decorator in the file. Its
``auto_run=True`` path triggers the mcp_startup pipeline INLINE
(uvicorn boot, registry handshake), which blocks the importing
thread before any module-level code below it can run. Anything
decorated AFTER ``@mesh.agent`` will silently fail to register.
The ``@mesh.a2a_consumer`` self-tag is resolved lazily so the
consumer can be declared above the agent without crashing the import.

Prereqs (in three terminals)
============================

  # 1) Registry
  meshctl start registry

  # 2) Producer — the existing A2A surface
  python examples/a2a/date_a2a_agent.py

  # 3) This consumer — wraps the producer above, exposes mesh capability
  python examples/a2a/consumer_date_agent.py

Test
====

A downstream mesh tool consumes the capability normally:

    @mesh.tool(capability="report", dependencies=[
        {"capability": "current-date", "tags": ["date-consumer"]},
    ])
    async def report(current_date: McpMeshTool = None):
        return await current_date()

The dependency resolver routes the call to this consumer, which
issues an outbound A2A ``tasks/send`` to the producer and returns
the producer's artifact text.
"""

import json
import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh so the framework's
# display_config picks up the same port we'll bind to. Avoids the
# producer's port (9090) and the registry's port (8000).
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

    The producer-side handler returns ``{"date": "<iso-string>"}`` and
    the A2A surface JSON-stringifies it into the artifact text part —
    so we ``json.loads`` on the consumer side to recover the dict.
    """
    response = await _a2a.send(
        message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
    )
    return json.loads(response.artifact_text)


# @mesh.agent MUST be last — see module docstring for why.
@mesh.agent(name="date-consumer", http_port=HTTP_PORT)
class DateConsumer:
    """Mesh agent that bridges the date_a2a_agent's get-date skill."""

    pass
