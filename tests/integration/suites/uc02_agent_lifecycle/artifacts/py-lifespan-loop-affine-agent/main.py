#!/usr/bin/env python3
"""Test agent: lifespan creates a loop-affine resource, tool tries to use it.

Reproduces the cross-loop failure mode that bites real apps using
asyncpg.Pool / redis.asyncio.Redis / aiohttp.ClientSession when the
resource is created in lifespan startup (uvicorn loop) and used from
a tool body (worker loop). See issue #1061.

The LoopAffineResource here is a minimal stand-in - it records the
loop it was constructed on and raises on use from a different loop.
asyncpg.Pool exhibits the exact same affinity via its internal
Future caching; we don't need a real Postgres to exercise the bug.
"""
import asyncio
from contextlib import asynccontextmanager

import mesh
from fastmcp import FastMCP


class LoopAffineResource:
    """Mimics asyncpg.Pool / redis.asyncio loop-affinity behavior."""

    def __init__(self):
        loop = asyncio.get_running_loop()
        self._owner_loop_id = id(loop)
        self._owner_loop_name = repr(loop)

    async def use(self) -> dict:
        current = asyncio.get_running_loop()
        if id(current) != self._owner_loop_id:
            raise RuntimeError(
                f"LoopAffineResource bound to loop {self._owner_loop_id} "
                f"({self._owner_loop_name!r}); called from loop {id(current)} "
                f"({current!r}). This is the same shape of failure asyncpg.Pool "
                f"would raise via 'Task got Future attached to a different loop'."
            )
        return {
            "ok": True,
            "owner_loop_id": self._owner_loop_id,
            "called_from_loop_id": id(current),
        }


_resource: LoopAffineResource | None = None
_lifespan_loop_id: int | None = None


@asynccontextmanager
async def _lifespan(server):
    global _resource, _lifespan_loop_id
    _lifespan_loop_id = id(asyncio.get_running_loop())
    _resource = LoopAffineResource()
    try:
        yield
    finally:
        # Nothing async to close on the resource; the close pattern would
        # face the same cross-loop hazard if we tried to call it from a
        # worker loop. See issue #1061 for the structural fix.
        pass


app = FastMCP("lifespan-loop-affine-agent", lifespan=_lifespan)


@app.tool()
@mesh.tool(capability="lifespan.use_resource")
async def use_resource() -> dict:
    """Try to use the lifespan-created resource from a tool body."""
    if _resource is None:
        return {"error": "resource_not_initialized"}
    tool_loop_id = id(asyncio.get_running_loop())
    try:
        result = await _resource.use()
        return {
            "tool_loop_id": tool_loop_id,
            "lifespan_loop_id": _lifespan_loop_id,
            "same_loop": tool_loop_id == _lifespan_loop_id,
            "resource_result": result,
        }
    except RuntimeError as exc:
        return {
            "tool_loop_id": tool_loop_id,
            "lifespan_loop_id": _lifespan_loop_id,
            "same_loop": tool_loop_id == _lifespan_loop_id,
            "error": str(exc),
        }


@mesh.agent(name="lifespan-loop-affine-agent", auto_run=True)
class LifespanLoopAffineAgent:
    pass
