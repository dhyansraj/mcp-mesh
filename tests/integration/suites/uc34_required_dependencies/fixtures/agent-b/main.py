#!/usr/bin/env python3
"""uc34 agent-b — provides b-cap with a REQUIRED dep on c-cap (issue #1249).

The middle of the tc01 chain: because the c-cap edge is required, the
registry marks b-cap available==false (unavailable_reason naming c-cap)
whenever no available c-cap provider resolves — while THIS agent stays
registered and healthy. That derived-state split (agent healthy, capability
unavailable) is the core #1249 guarantee tc01 asserts.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentB Service")


@app.tool()
@mesh.tool(
    capability="b-cap",
    description="B calls C",
    dependencies=[{"capability": "c-cap", "required": True}],
)
async def b_tool(c_dep: mesh.McpMeshTool = None) -> str:
    if c_dep is None:
        return "b: c-cap NOT available"
    result = await c_dep()
    return f"b got: {result}"


@mesh.agent(
    name="agent-b",
    version="1.0.0",
    description="uc34 provider of b-cap (required dep on c-cap)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9102")),
    enable_http=True,
    auto_run=True,
)
class AgentB:
    pass
