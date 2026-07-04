#!/usr/bin/env python3
"""MeshJob submitter for uc36 (issues #1265/#1267).

Submit-only driver (uc33's ``gate-driver`` shape): the tool submits
``admin_gated`` and returns ``{job_id}`` immediately. The test driver then
sequences the scenario itself — running ``meshctl job reclaim`` /
``meshctl registry drain|resume|status``, posting ``finish`` events, and
reading job status + the event log via the registry HTTP API — because
blocking on ``proxy.wait()`` inside a tool would hide exactly the mid-flight
signal (claims, forced reclaims, drained queues) these tests exist to observe.
"""

import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Admin Driver (uc36)")


@app.tool()
@mesh.tool(
    capability="submit_admin_gated",
    dependencies=["admin_gated"],
    description="Submit admin_gated (finish-gated, poll-liveness-renewing) and return the job_id.",
)
async def submit_admin_gated(
    max_duration: int = 60,
    max_retries: int = 2,
    admin_gated: MeshJob = None,
) -> dict[str, Any]:
    if admin_gated is None:
        return {"error": "admin_gated submitter not injected"}
    # max_duration sizes the lease window LONG (>= 45s) — with 2s poll rounds
    # the gate renews the lease dozens of times per window, so the ONLY way
    # the owner is ever evicted in these tests is the admin surface itself.
    proxy = await admin_gated.submit(
        max_duration=max_duration,
        max_retries=max_retries,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


@mesh.agent(
    name="admin-driver",
    version="1.0.0",
    description="Submit-only MeshJob driver (uc36) — admin reclaim/drain fixture.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9160")),
    enable_http=True,
    auto_run=True,
)
class AdminDriver:
    pass
