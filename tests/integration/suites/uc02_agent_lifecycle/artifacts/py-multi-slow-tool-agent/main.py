#!/usr/bin/env python3
"""Test agent with two long-running tools (async-yielding and sync-blocking).

Used to characterise the trade-off of the v2.2.1 default
``MCP_MESH_TOOL_WORKERS=1`` (issue #1061):

* ``async_sleep_5``: awaits ``asyncio.sleep(5)``. Yields the loop.
  Two concurrent invocations under N=1 still interleave fine — both
  complete in ~5s wall clock.
* ``sync_sleep_5``: calls ``time.sleep(5)``. Blocks the loop. Two
  concurrent invocations under N=1 serialize — the second waits for
  the first, total ~10s. With ``MCP_MESH_TOOL_WORKERS=2`` they run
  on separate worker loops and both complete in ~5s.

The agent's purpose is to surface the structural cost of N=1 (sync
work that doesn't yield) and the structural win of opt-in N>1.
"""
import asyncio
import time

import mesh
from fastmcp import FastMCP


app = FastMCP("multi-slow-tool-agent")


@app.tool()
@mesh.tool(capability="async_sleep_5")
async def async_sleep_5() -> dict:
    """Yield the user loop for ~5s via ``asyncio.sleep``."""
    start = time.monotonic()
    await asyncio.sleep(5)
    return {"kind": "async", "elapsed_s": time.monotonic() - start}


@app.tool()
@mesh.tool(capability="sync_sleep_5")
async def sync_sleep_5() -> dict:
    """Block the running loop for ~5s via ``time.sleep`` (no yield)."""
    start = time.monotonic()
    time.sleep(5)
    return {"kind": "sync", "elapsed_s": time.monotonic() - start}


@mesh.agent(name="multi-slow-tool-agent", auto_run=True)
class MultiSlowToolAgent:
    pass
