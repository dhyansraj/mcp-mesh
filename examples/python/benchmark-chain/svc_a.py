#!/usr/bin/env python3
"""
svc-a - MCP Mesh Agent

Entry service - receives request, calls svc-b
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("SvcA Service")


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
    capability="call_chain",
    description="Entry point for benchmark chain",
    tags=["benchmark", "chain", "entry"],
    dependencies=["process_b"],
)
async def call_chain(
    request: ChainRequest,
    process_b: mesh.McpMeshTool = None,
) -> ChainResponse:
    if process_b is None:
        return ChainResponse(data="degraded: process_b dependency not available", service="svc-a")
    return await process_b(request=request)


@app.tool()
@mesh.tool(
    capability="call_chain_simple",
    description="Simple string chain entry point",
    tags=["benchmark", "chain", "simple"],
    dependencies=["process_b_simple"],
)
async def call_chain_simple(
    message: str = "Hello World",
    process_b_simple: mesh.McpMeshTool = None,
) -> str:
    if process_b_simple is None:
        return "degraded: process_b_simple dependency not available"
    return await process_b_simple(message=message)


@mesh.agent(
    name="svc-a",
    version="1.0.0",
    description="Entry service - receives request, calls svc-b",
    http_port=8081,
    enable_http=True,
    auto_run=True,
)
class SvcAAgent:
    pass
