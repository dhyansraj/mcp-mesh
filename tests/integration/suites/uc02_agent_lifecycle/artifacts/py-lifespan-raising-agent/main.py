#!/usr/bin/env python3
"""Test agent: lifespan startup raises — exercises Gap 2 exception propagation.

The user's ``__aenter__`` raises a synthetic ``RuntimeError``. With the
v2.2.1 hijack, the exception must propagate cleanly through the wrap +
``run_coroutine_threadsafe`` + ``wrap_future`` chain back to uvicorn,
which then surfaces it as a startup failure. The WARNING log emitted by
the wrap site must also appear, naming the startup phase and pointing
at ``@mesh.on_startup`` / ``@mesh.on_shutdown`` as the forward-looking
escape hatch. See issue #1061.
"""
import asyncio
from contextlib import asynccontextmanager

import mesh
from fastmcp import FastMCP


@asynccontextmanager
async def _lifespan(server):
    # Force a synthetic failure on startup. The exact string must surface
    # in the agent logs so the test can assert the user-visible error
    # text wasn't swallowed by the hijack layer.
    raise RuntimeError("synthetic startup failure")
    yield  # pragma: no cover


app = FastMCP("lifespan-raising-agent", lifespan=_lifespan)


@app.tool()
@mesh.tool(capability="lifespan.never_reached")
async def never_reached() -> dict:
    """This tool should never be callable — startup must fail first."""
    return {"unreachable": True}


@mesh.agent(name="lifespan-raising-agent", auto_run=True)
class LifespanRaisingAgent:
    pass
