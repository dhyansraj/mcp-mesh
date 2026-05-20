#!/usr/bin/env python3
"""Test agent for the per-loop dict workaround pattern (issue #1061).

When ``MCP_MESH_TOOL_WORKERS`` is set above 1, tool invocations are
dispatched across multiple worker loops. A common pattern to deal with
loop-affine resources in that environment is to key a dict by
``id(asyncio.get_running_loop())`` and lazily build one resource per
loop. The structural side effect is one resource per worker loop — for
a real DB this is a connection-pool multiplier.

This agent exposes ``use_per_loop_pool`` so a test can drive many
concurrent calls and observe ``total_pools_created`` grow with the
number of distinct worker loops.
"""
import asyncio
import threading

import mesh
from fastmcp import FastMCP


app = FastMCP("per-loop-dict-agent")


_pools: dict[int, "FakePool"] = {}
_pools_lock = threading.Lock()
_total_pools_created = 0


class FakePool:
    """Loop-affine resource stand-in (no real I/O)."""

    def __init__(self):
        self._loop_id = id(asyncio.get_running_loop())

    async def acquire(self) -> str:
        return "conn"


async def get_pool() -> FakePool:
    global _total_pools_created
    loop_id = id(asyncio.get_running_loop())
    with _pools_lock:
        existing = _pools.get(loop_id)
    if existing is not None:
        return existing
    new_pool = FakePool()
    with _pools_lock:
        if loop_id not in _pools:
            _pools[loop_id] = new_pool
            _total_pools_created += 1
    return _pools[loop_id]


@app.tool()
@mesh.tool(capability="use_per_loop_pool")
async def use_per_loop_pool() -> dict:
    """Acquire a connection from the per-loop pool and report state."""
    pool = await get_pool()
    _ = await pool.acquire()
    with _pools_lock:
        return {
            "this_call_loop_id": id(asyncio.get_running_loop()),
            "total_pools_created": _total_pools_created,
            "pool_loops": sorted(_pools.keys()),
        }


@mesh.agent(name="per-loop-dict-agent", auto_run=True)
class PerLoopDictAgent:
    pass
