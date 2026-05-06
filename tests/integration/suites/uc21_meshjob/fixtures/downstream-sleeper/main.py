#!/usr/bin/env python3
"""Downstream sleeper agent (uc21) — exercises cancel propagation.

Provides ``slow_downstream``, a regular (non-task) tool that sleeps
for the requested number of seconds. The producer agent's
``report_with_downstream_call`` invokes this via the mesh proxy; when
the producer's job is cancelled, the cancel token in the producer's
async-local context aborts the in-flight outbound HTTP — so this
sleeper never finishes its 30s timer for the cancel scenario.

The sleeper writes a marker line to stderr when it observes the
request being aborted (``asyncio.CancelledError``) so tests can
distinguish a true cancel propagation from "the downstream just took
too long and the test gave up".
"""

import asyncio
import os
import sys

import mesh
from fastmcp import FastMCP

app = FastMCP("Downstream Sleeper (uc21)")


@app.tool()
@mesh.tool(
    capability="slow_downstream",
    description="Sleeps for the requested number of seconds (regular tool, not task=True).",
)
async def slow_downstream(user_id: str, seconds: int = 30) -> dict:
    print(
        f"[downstream-sleeper] starting {seconds}s sleep for user={user_id}",
        file=sys.stderr,
        flush=True,
    )
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        # Loud marker the test grep's for. Re-raise so the wrapper
        # surfaces the abort to the caller as expected.
        print(
            f"[downstream-sleeper] sleep CANCELLED for user={user_id} "
            "(client closed / cancel token fired)",
            file=sys.stderr,
            flush=True,
        )
        raise
    print(
        f"[downstream-sleeper] sleep completed for user={user_id} (NOT cancelled)",
        file=sys.stderr,
        flush=True,
    )
    return {"user_id": user_id, "slept": seconds}


@mesh.agent(
    name="downstream-sleeper",
    version="1.0.0",
    description="Slow downstream tool used to verify mesh-job cancel propagation.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9102")),
    enable_http=True,
    auto_run=True,
)
class DownstreamSleeper:
    pass
