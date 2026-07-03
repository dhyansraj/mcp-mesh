#!/usr/bin/env python3
"""uc34 agent-c — leaf provider of c-cap (issue #1249).

The bottom of the tc01 chain (A -> B -> C) and the UNTAGGED c-cap provider
in tc02. It declares no dependencies of its own, so its availability is
purely its agent health: killing this process is what makes b-cap's
required edge break upstream.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentC Service")


@app.tool()
@mesh.tool(capability="c-cap", description="Constant from C")
async def c_tool() -> str:
    return "hello-from-c"


@mesh.agent(
    name="agent-c",
    version="1.0.0",
    description="uc34 leaf provider of c-cap",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class AgentC:
    pass
