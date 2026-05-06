#!/usr/bin/env python3
"""Orchestrator agent (uc21) — has NO task=True tools and NO mesh deps.

Used by tc14_helpers_on_every_agent to prove the three framework
helper tools (``__mesh_job_status`` / ``__mesh_job_result`` /
``__mesh_job_cancel``) auto-register on every mesh agent regardless
of whether that agent participates in the job lifecycle.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Orchestrator (uc21)")


@app.tool()
@mesh.tool(
    capability="orchestrator_ping",
    description="Trivial tool — only purpose is to keep the agent alive in the registry.",
)
async def orchestrator_ping() -> dict:
    return {"ok": True, "agent": "orchestrator-agent"}


@mesh.agent(
    name="orchestrator-agent",
    version="1.0.0",
    description="Agent with no task tools and no mesh deps — verifies helper-tool auto-registration is universal.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9103")),
    enable_http=True,
    auto_run=True,
)
class OrchestratorAgent:
    pass
