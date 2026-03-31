#!/usr/bin/env python3
"""Test agent with a lifespan that starts a background asyncio.Task.

Mimics the real-world pattern where agents use lifespan to start
Redis listeners or other long-running background jobs.
"""
import asyncio
from contextlib import asynccontextmanager

import mesh
from fastmcp import FastMCP

_lifespan_started = False
_task_tick_count = 0
_background_task = None


async def _background_worker():
    """Simulates a long-running background job (like a Redis listener)."""
    global _task_tick_count
    while True:
        _task_tick_count += 1
        await asyncio.sleep(1)


@asynccontextmanager
async def _lifespan(server):
    global _lifespan_started, _background_task
    _lifespan_started = True
    _background_task = asyncio.create_task(_background_worker())
    try:
        yield
    finally:
        _lifespan_started = False
        if _background_task and not _background_task.done():
            _background_task.cancel()
            try:
                await _background_task
            except asyncio.CancelledError:
                pass


app = FastMCP("lifespan-task-agent", lifespan=_lifespan)


@app.tool()
@mesh.tool(capability="lifespan.task_status")
def task_status() -> dict:
    """Returns lifespan and background task state."""
    return {
        "lifespan_started": _lifespan_started,
        "task_running": _background_task is not None and not _background_task.done(),
        "tick_count": _task_tick_count,
    }


@mesh.agent(name="lifespan-task-agent", auto_run=True)
class LifespanTaskAgent:
    pass
