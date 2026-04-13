#!/usr/bin/env python3
"""
py-slow-agent - Sleeps 70s then calls TypeScript agent.

First link in the timeout chain propagation test: py -> ts -> java.
Each hop sleeps 70s; without X-Mesh-Timeout propagation the default
60s proxy timeout would kill the chain at the first hop.
"""

import asyncio

import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshTool

app = FastMCP("Slow Python Agent")


@app.tool()
@mesh.tool(
    capability="slow_py",
    description="Sleeps 70s then calls the TypeScript agent",
    tags=["slow", "chain"],
    dependencies=["slow_ts"],
)
async def slow_chain_py(message: str, slow_ts_svc: McpMeshTool = None) -> dict:
    """Sleep 70s, then forward to TypeScript agent."""
    await asyncio.sleep(70)
    if slow_ts_svc:
        result = await slow_ts_svc(message=f"{message} -> py")
        return {"chain": f"py -> {result.get('chain', '?')}", "data": result.get("data", "")}
    return {"chain": "py (no ts)", "data": "chain broken"}


@mesh.agent(
    name="py-slow-agent",
    version="1.0.0",
    description="Slow agent for timeout chain test",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class PySlowAgent:
    pass
