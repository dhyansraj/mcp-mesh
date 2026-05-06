#!/usr/bin/env python3
"""Bystander X (uc21) — used by tc16 to verify third-party status reads.

Has no MeshJob deps and no task=True tools. The framework still
auto-registers ``__mesh_job_status`` / ``__mesh_job_result`` /
``__mesh_job_cancel`` on every mesh agent, so the test can read
job state from this agent for a job_id it did not submit.

Distinct fixture file (separate from bystander-y) so meshctl's
"is this agent already running" check (which keys off the
``@mesh.agent(name=...)`` decorator) doesn't conflate the two
instances.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Bystander X (uc21)")


@app.tool()
@mesh.tool(
    capability="bystander_x_ping",
    description="Trivial tool — keeps bystander X alive in the registry.",
)
async def bystander_x_ping() -> dict:
    return {"ok": True, "agent": "bystander-x"}


@mesh.agent(
    name="bystander-x",
    version="1.0.0",
    description="Bystander agent X — verifies third-party status reads (tc16).",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9104")),
    enable_http=True,
    auto_run=True,
)
class BystanderX:
    pass
