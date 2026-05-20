#!/usr/bin/env python3
"""Test agent with a tool that holds the user loop for ~10s.

Used to prove that the framework loop (uvicorn) remains responsive
to /health / /ready / /livez probes even when the user loop is busy
servicing a long tool call. See issue #1061.
"""
import asyncio

import mesh
from fastmcp import FastMCP


app = FastMCP("long-tool-agent")


@app.tool()
@mesh.tool(capability="long.slow_tool")
async def slow_tool() -> dict:
    """Sleep on the user loop for ~10s, then return."""
    await asyncio.sleep(10)
    return {"status": "done"}


@mesh.agent(name="long-tool-agent", auto_run=True)
class LongToolAgent:
    pass
