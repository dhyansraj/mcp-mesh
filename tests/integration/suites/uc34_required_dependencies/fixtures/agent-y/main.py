#!/usr/bin/env python3
"""uc34 agent-y — y-cap REQUIRES x-cap (the cycle-closing half of tc03).

With agent-x already registered (x-cap -> y-cap required), this agent's
registration would close a required-edge cycle. The registry rejects it
semantically (HTTP 200 + status:"error"), the Rust core surfaces the message
loudly ("Registry rejected agent ...: required dependency cycle: ...") and
keeps retrying with bounded backoff — so agent-y NEVER appears in /agents
while the loop stands. tc03 asserts the absence + the log line.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentY Service")


@app.tool()
@mesh.tool(
    capability="y-cap",
    description="Y requires X",
    dependencies=[{"capability": "x-cap", "required": True}],
)
async def y_tool(x_dep: mesh.McpMeshTool = None) -> str:
    return "y" if x_dep is None else "y with x"


@mesh.agent(
    name="agent-y",
    version="1.0.0",
    description="uc34 provider of y-cap (required dep on x-cap — closes the cycle)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9106")),
    enable_http=True,
    auto_run=True,
)
class AgentY:
    pass
