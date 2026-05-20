#!/usr/bin/env python3
"""Leaf agent for parallel fan-out tests.

Exposes a single ``slow_leaf`` capability that sleeps ~2s on its
caller's event loop and returns. Used to prove that ``asyncio.gather``
over outbound mesh calls inside one tool body delivers full parallelism
regardless of how many tool-worker loops the framework runs.

See issue #1061 for the broader lifespan/loop-affinity context.
"""
import asyncio

import mesh
from fastmcp import FastMCP


app = FastMCP("slow-leaf-agent")


@app.tool()
@mesh.tool(capability="slow_leaf")
async def slow_leaf() -> dict:
    """Sleep ~2s and return."""
    await asyncio.sleep(2)
    return {"ms": 2000}


@mesh.agent(name="slow-leaf-agent", auto_run=True)
class SlowLeafAgent:
    pass
