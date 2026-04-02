#!/usr/bin/env python3
"""
svc-e - MCP Mesh Agent

Terminal service - generates response payload
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("SvcE Service")


class ChainRequest(BaseModel):
    mode: str = "baseline"
    payload: str = ""
    payload_size: str = "1kb"


class ChainResponse(BaseModel):
    data: str = ""
    service: str = ""
    hops: int = 0


PAYLOAD_SIZES = {
    "1kb": 1024,
    "10kb": 10240,
    "100kb": 102400,
    "1mb": 1048576,
}


def generate_payload(size_key: str) -> str:
    target_bytes = PAYLOAD_SIZES.get(size_key, 1024)
    pattern = "abcdefghijklmnopqrstuvwxyz0123456789"
    repetitions = (target_bytes // len(pattern)) + 1
    return (pattern * repetitions)[:target_bytes]


@app.tool()
@mesh.tool(
    capability="generate_response",
    description="Terminal service that generates benchmark response",
    tags=["benchmark", "chain", "terminal"],
)
async def generate_response(
    request: ChainRequest,
) -> ChainResponse:
    if request.mode == "baseline":
        return ChainResponse(data="Hello World", service="svc-e", hops=0)
    return ChainResponse(data=generate_payload(request.payload_size), service="svc-e", hops=0)


@app.tool()
@mesh.tool(
    capability="generate_response_simple",
    description="Simple string terminal service",
    tags=["benchmark", "chain", "simple"],
)
async def generate_response_simple(
    message: str = "Hello World",
) -> str:
    return message


@mesh.agent(
    name="svc-e",
    version="1.0.0",
    description="Terminal service - generates response payload",
    http_port=8085,
    enable_http=True,
    auto_run=True,
)
class SvcEAgent:
    pass
