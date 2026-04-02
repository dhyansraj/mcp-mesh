#!/usr/bin/env python3
"""
svc-b - MCP Mesh Agent

Chain service B - receives from A, calls C
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("SvcB Service")


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
    capability="process_b",
    description="Intermediate chain service B",
    tags=["benchmark", "chain", "intermediate"],
    dependencies=["process_c"],
)
async def process_b(
    request: ChainRequest,
    process_c: mesh.McpMeshTool = None,
) -> ChainResponse:
    if process_c is None:
        return ChainResponse(data="degraded: process_c dependency not available", service="svc-b")
    return await process_c(request=request)


@app.tool()
@mesh.tool(
    capability="process_b_simple",
    description="Simple string chain service B",
    tags=["benchmark", "chain", "simple"],
    dependencies=["process_c_simple"],
)
async def process_b_simple(
    message: str = "Hello World",
    process_c_simple: mesh.McpMeshTool = None,
) -> str:
    if process_c_simple is None:
        return "degraded: process_c_simple dependency not available"
    return await process_c_simple(message=message)


@mesh.agent(
    name="svc-b",
    version="1.0.0",
    description="Chain service B - receives from A, calls C",
    http_port=8082,
    enable_http=True,
    auto_run=True,
)
class SvcBAgent:
    pass
