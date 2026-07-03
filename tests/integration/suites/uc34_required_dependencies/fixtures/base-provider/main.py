#!/usr/bin/env python3
"""uc34 base-provider — plain provider of base-cap (issue #1249).

Shared Python provider for the cross-language TCs: the Java route consumer
(tc04) and the TypeScript required-declaration consumer (tc05) both declare
required=true edges on base-cap. Killing/restarting THIS process drives
their unavailable -> recovered transitions. Returns a dict so the Java
McpMeshTool<Map<String, Object>> proxy deserializes naturally.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Base Provider (uc34)")


@app.tool()
@mesh.tool(capability="base-cap", description="Constant payload from the base provider")
async def base_tool() -> dict:
    return {"msg": "hello-from-base"}


@mesh.agent(
    name="base-provider",
    version="1.0.0",
    description="uc34 provider of base-cap for the Java/TS required-dep TCs",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class BaseProvider:
    pass
