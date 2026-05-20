#!/usr/bin/env python3
"""Test agent for the lazy-init-pool pattern under the user-loop default.

A common workaround for the cross-loop hazard (issue #1061) is to skip
``lifespan`` startup entirely and instead lazily construct loop-bound
resources on first tool invocation. Under the v2.2.1 default
``MCP_MESH_TOOL_WORKERS=1`` there is a single shared user loop, so the
lazy pool gets constructed once and reused across all subsequent tool
calls.

The ``FakePool`` stand-in mirrors the loop-affinity invariant of real
resources like ``asyncpg.Pool`` without requiring a database.
"""
import asyncio

import mesh
from fastmcp import FastMCP


app = FastMCP("lazy-pool-agent")


_pool = None
_pool_created_count = 0
_pool_loop_id: int | None = None


class FakePool:
    """Loop-affine resource mirroring asyncpg.Pool semantics."""

    def __init__(self):
        self._loop_id = id(asyncio.get_running_loop())

    async def acquire(self) -> str:
        if id(asyncio.get_running_loop()) != self._loop_id:
            raise RuntimeError("cross-loop pool access")
        return "conn"


async def get_pool() -> FakePool:
    global _pool, _pool_created_count, _pool_loop_id
    if _pool is None:
        _pool = FakePool()
        _pool_created_count += 1
        _pool_loop_id = _pool._loop_id
    return _pool


@app.tool()
@mesh.tool(capability="use_lazy_pool")
async def use_lazy_pool() -> dict:
    """Lazily create-or-reuse the pool on the current loop and acquire a conn."""
    pool = await get_pool()
    conn = await pool.acquire()
    return {
        "conn": conn,
        "pool_created_count": _pool_created_count,
        "pool_loop_id": _pool_loop_id,
        "this_call_loop_id": id(asyncio.get_running_loop()),
    }


@mesh.agent(name="lazy-pool-agent", auto_run=True)
class LazyPoolAgent:
    pass
