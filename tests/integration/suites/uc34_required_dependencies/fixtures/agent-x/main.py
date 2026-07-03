#!/usr/bin/env python3
"""uc34 agent-x — x-cap REQUIRES y-cap (one half of the tc03 cycle).

Started FIRST in tc03: with no y-cap edges registered yet, x's required edge
is merely unresolved, so x registers fine — its x-cap simply sits at
available==false ("required dep 'y-cap' unresolved"). agent-y then arrives
declaring y-cap -> x-cap and closes the loop; y is the one the registry
rejects.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentX Service")


@app.tool()
@mesh.tool(
    capability="x-cap",
    description="X requires Y",
    dependencies=[{"capability": "y-cap", "required": True}],
)
async def x_tool(y_dep: mesh.McpMeshTool = None) -> str:
    return "x" if y_dep is None else "x with y"


@mesh.agent(
    name="agent-x",
    version="1.0.0",
    description="uc34 provider of x-cap (required dep on y-cap)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9105")),
    enable_http=True,
    auto_run=True,
)
class AgentX:
    pass
