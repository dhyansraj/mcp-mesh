#!/usr/bin/env python3
"""uc34 agent-a — provides a-cap with an OPTIONAL dep on b-cap (issue #1249).

The top of the tc01 chain. The A -> B edge is deliberately OPTIONAL: when
b-cap goes unavailable (because B's required c-cap edge broke), a-cap must
STAY available==true — optional edges never propagate unavailability. tc01
asserts exactly that contrast against the required B -> C edge.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentA Service")


@app.tool()
@mesh.tool(
    capability="a-cap",
    description="A reports whether the b proxy is present",
    dependencies=["b-cap"],
)
async def a_tool(b_dep: mesh.McpMeshTool = None) -> str:
    if b_dep is None:
        return "a: b proxy is None"
    result = await b_dep()
    return f"a: b proxy present, b said: {result}"


@mesh.agent(
    name="agent-a",
    version="1.0.0",
    description="uc34 provider of a-cap (optional dep on b-cap)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9103")),
    enable_http=True,
    auto_run=True,
)
class AgentA:
    pass
