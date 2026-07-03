#!/usr/bin/env python3
"""uc34 agent-b2 — b2-cap REQUIRES c-cap narrowed by tag (issue #1249).

Constraint-mismatch fixture for tc02: the required edge demands c-cap WITH
tags=["needs-this-tag"]. A healthy but UNTAGGED c-cap provider must NOT
satisfy it — availability evaluation applies the same tag/version matching
as ordinary consumer resolution, and the unavailable_reason must name the
missing tag ("no provider matches tags=[needs-this-tag]") rather than blame
provider health.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("AgentB2 Service")


@app.tool()
@mesh.tool(
    capability="b2-cap",
    description="B2 calls tag-narrowed C",
    dependencies=[{"capability": "c-cap", "required": True, "tags": ["needs-this-tag"]}],
)
async def b2_tool(c_dep: mesh.McpMeshTool = None) -> str:
    if c_dep is None:
        return "b2: tagged c-cap NOT available"
    result = await c_dep()
    return f"b2 got: {result}"


@mesh.agent(
    name="agent-b2",
    version="1.0.0",
    description="uc34 provider of b2-cap (required tag-narrowed dep on c-cap)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9107")),
    enable_http=True,
    auto_run=True,
)
class AgentB2:
    pass
