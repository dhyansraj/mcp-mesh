#!/usr/bin/env python3
"""
svc-c - MCP Mesh Agent

Chain service C - receives from B, calls D
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("SvcC Service")


class ChainRequest(BaseModel):
    mode: str = "baseline"
    payload: str = ""
    payload_size: str = "1kb"


class ChainResponse(BaseModel):
    data: str = ""
    service: str = ""
    hops: int = 0


@app.tool()
@mesh.tool(
    capability="process_c",
    description="Intermediate chain service C",
    tags=["benchmark", "chain", "intermediate"],
    dependencies=["process_d"],
)
async def process_c(
    request: ChainRequest,
    process_d: mesh.McpMeshTool = None,
) -> ChainResponse:
    if process_d is None:
        return ChainResponse(data="degraded: process_d dependency not available", service="svc-c")
    return await process_d(request=request)


@app.tool()
@mesh.tool(
    capability="process_c_simple",
    description="Simple string chain service C",
    tags=["benchmark", "chain", "simple"],
    dependencies=["process_d_simple"],
)
async def process_c_simple(
    message: str = "Hello World",
    process_d_simple: mesh.McpMeshTool = None,
) -> str:
    if process_d_simple is None:
        return "degraded: process_d_simple dependency not available"
    return await process_d_simple(message=message)


@mesh.agent(
    name="svc-c",
    version="1.0.0",
    description="Chain service C - receives from B, calls D",
    http_port=8083,
    enable_http=True,
    auto_run=True,
)
class SvcCAgent:
    pass
