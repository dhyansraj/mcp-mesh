#!/usr/bin/env python3
"""MeshJob submitter for uc33 (issue #1252 Phase 4).

Submit-only driver: each tool submits one of the gated-worker capabilities
and returns ``{job_id}`` immediately. The test driver then sequences the
scenario itself — posting ``go`` / ``finish`` events and reading job status
and the event log directly via the registry HTTP API — because blocking on
``proxy.wait()`` inside a tool would hide exactly the mid-flight signal
(claims, reclaims, fenced writes) these tests exist to observe. Mirrors
uc21's ``commission_submit_only`` shape.
"""

import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Gate Driver (uc33)")


@app.tool()
@mesh.tool(
    capability="submit_gated",
    dependencies=["gated_phases"],
    description="Submit gated_phases (sequential recv_event gates) and return the job_id.",
)
async def submit_gated(
    phases: int = 3,
    max_duration: int = 15,
    max_retries: int = 2,
    gated_phases: MeshJob = None,
) -> dict[str, Any]:
    if gated_phases is None:
        return {"error": "gated_phases submitter not injected"}
    # Small max_duration sizes the LEASE window (leaseWindowFor derives the
    # lease from it) so the quiet-gate silence in tc01 comfortably exceeds
    # it. max_retries > 0 so a pre-fix lease lapse would RECLAIM (the field
    # corruption shape) rather than terminally fail — either divergence
    # from attempt_count == 1 fails the test.
    proxy = await gated_phases.submit(
        phases=phases,
        max_duration=max_duration,
        max_retries=max_retries,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


@app.tool()
@mesh.tool(
    capability="submit_sleepy",
    dependencies=["sleepy_phases"],
    description="Submit sleepy_phases (attempt 1 wedges past the lease) and return the job_id.",
)
async def submit_sleepy(
    sleep_secs: int = 35,
    max_duration: int = 6,
    max_retries: int = 1,
    sleepy_phases: MeshJob = None,
) -> dict[str, Any]:
    if sleepy_phases is None:
        return {"error": "sleepy_phases submitter not injected"}
    # max_duration=6 makes the lease lapse ~6s into attempt 1's wedged
    # sleep; max_retries=1 budgets exactly the one reclaim tc02 needs (a
    # second lapse would mark the job failed and the test would catch it).
    proxy = await sleepy_phases.submit(
        sleep_secs=sleep_secs,
        max_duration=max_duration,
        max_retries=max_retries,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


@mesh.agent(
    name="gate-driver",
    version="1.0.0",
    description="Submit-only MeshJob driver (uc33) — multi-replica execution integrity fixture.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9110")),
    enable_http=True,
    auto_run=True,
)
class GateDriver:
    pass
