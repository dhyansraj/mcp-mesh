#!/usr/bin/env python3
"""Orchestrator agent for parallel fan-out tests.

Exposes ``parallel_fanout`` which depends on the ``slow_leaf``
capability and issues three concurrent invocations via
``asyncio.gather`` inside a single tool body. Measures wall-clock
elapsed time so callers can assert the calls truly ran in parallel
(elapsed ~2s) rather than serially (elapsed ~6s).

This is the load-bearing claim from issue #1061 that the default
``MCP_MESH_TOOL_WORKERS=1`` does not hurt LLM-style parallel
tool-calling: parallelism on outbound calls comes from cooperative
async I/O on a single loop, not from multiple worker loops.
"""
import asyncio
import time

import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshTool


app = FastMCP("parallel-orchestrator-agent")


@app.tool()
@mesh.tool(
    capability="parallel_fanout",
    dependencies=["slow_leaf"],
)
async def parallel_fanout(slow_leaf: McpMeshTool = None) -> dict:
    """Fan out three ``slow_leaf`` calls concurrently and report elapsed time."""
    if slow_leaf is None:
        return {"error": "slow_leaf_dependency_unresolved"}

    start = time.monotonic()
    results = await asyncio.gather(
        slow_leaf(),
        slow_leaf(),
        slow_leaf(),
    )
    elapsed_ms = (time.monotonic() - start) * 1000
    return {
        "elapsed_ms": elapsed_ms,
        "results": results,
        "count": len(results),
    }


@mesh.agent(name="parallel-orchestrator-agent", auto_run=True)
class ParallelOrchestratorAgent:
    pass
