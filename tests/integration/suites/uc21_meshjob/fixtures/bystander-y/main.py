#!/usr/bin/env python3
"""Bystander Y (uc21) — used by tc16 to verify third-party status reads.

Mirror of bystander-x in every way except agent name; deployed
alongside X so the test can prove BOTH agents (each with no
involvement in the job) can read its state via the framework's
helper tools.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Bystander Y (uc21)")


@app.tool()
@mesh.tool(
    capability="bystander_y_ping",
    description="Trivial tool — keeps bystander Y alive in the registry.",
)
async def bystander_y_ping() -> dict:
    return {"ok": True, "agent": "bystander-y"}


@mesh.agent(
    name="bystander-y",
    version="1.0.0",
    description="Bystander agent Y — verifies third-party status reads (tc16).",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9105")),
    enable_http=True,
    auto_run=True,
)
class BystanderY:
    pass
