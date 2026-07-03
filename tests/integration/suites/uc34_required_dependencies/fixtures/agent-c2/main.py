#!/usr/bin/env python3
"""uc34 agent-c2 — provides c-cap WITH the tag needs-this-tag (issue #1249).

The tc02 resolution flip: once this tagged provider registers, agent-b2's
tag-narrowed required edge finally matches and b2-cap must flip to
available==true — proving availability is re-derived live as matching
providers arrive, not frozen at registration.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentC2 Service")


@app.tool()
@mesh.tool(
    capability="c-cap",
    description="Tagged constant from C2",
    tags=["needs-this-tag"],
)
async def c2_tool() -> str:
    return "hello-from-c2-tagged"


@mesh.agent(
    name="agent-c2",
    version="1.0.0",
    description="uc34 provider of tagged c-cap",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9108")),
    enable_http=True,
    auto_run=True,
)
class AgentC2:
    pass
