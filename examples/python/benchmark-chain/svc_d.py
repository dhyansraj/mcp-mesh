#!/usr/bin/env python3
"""
svc-d - MCP Mesh Agent

Chain service D - receives from C, calls E
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("SvcD Service")


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
    capability="process_d",
    description="Intermediate chain service D",
    tags=["benchmark", "chain", "intermediate"],
    dependencies=["generate_response"],
)
async def process_d(
    request: ChainRequest,
    generate_response: mesh.McpMeshTool = None,
) -> ChainResponse:
    if generate_response is None:
        return ChainResponse(data="degraded: generate_response dependency not available", service="svc-d")
    return await generate_response(request=request)


@app.tool()
@mesh.tool(
    capability="process_d_simple",
    description="Simple string chain service D",
    tags=["benchmark", "chain", "simple"],
    dependencies=["generate_response_simple"],
)
async def process_d_simple(
    message: str = "Hello World",
    generate_response_simple: mesh.McpMeshTool = None,
) -> str:
    if generate_response_simple is None:
        return "degraded: generate_response_simple dependency not available"
    return await generate_response_simple(message=message)


@mesh.agent(
    name="svc-d",
    version="1.0.0",
    description="Chain service D - receives from C, calls E",
    http_port=8084,
    enable_http=True,
    auto_run=True,
)
class SvcDAgent:
    pass
