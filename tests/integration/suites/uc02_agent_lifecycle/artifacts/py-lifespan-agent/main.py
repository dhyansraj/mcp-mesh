#!/usr/bin/env python3
"""Test agent that verifies FastMCP lifespan extraction.

The lifespan sets a global flag on startup. The tool reports the flag's value.
If lifespan extraction works, the flag will be True after agent startup.
"""
from contextlib import asynccontextmanager

import mesh
from fastmcp import FastMCP

_lifespan_started = False


@asynccontextmanager
async def _lifespan(server):
    global _lifespan_started
    _lifespan_started = True
    yield
    _lifespan_started = False


app = FastMCP("lifespan-agent", lifespan=_lifespan)


@app.tool()
@mesh.tool(capability="lifespan.status")
def lifespan_status() -> dict:
    """Returns whether the lifespan startup code has executed."""
    return {"lifespan_started": _lifespan_started}


@mesh.agent(name="lifespan-agent", auto_run=True)
class LifespanAgent:
    pass
