#!/usr/bin/env python3
"""
rewire-provider - Provides the `rewire_probe` capability.

The tool returns the HTTP port this instance is serving on (read from
MCP_MESH_HTTP_PORT). That port is the *instance fingerprint*: when this
provider "moves" to a new endpoint (started again on a different port),
the consumer's call result reveals WHICH provider instance answered.

Identity is pinned via MCP_MESH_AGENT_ID (set by the test) so that the
moved instance keeps the SAME agent_id and only its endpoint (port)
changes. That is the precise scenario the dependency re-wire invariant
(#1314/#1315) must survive: an idempotency guard that keys on
agent_id/function/kwargs but forgets the endpoint would over-skip the
rebuild and leave the consumer wired to the OLD port.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Rewire Provider")


@app.tool()
@mesh.tool(
    capability="rewire_probe",
    description="Report the HTTP port this provider instance is serving on",
    tags=["rewire"],
)
async def rewire_probe() -> dict:
    """Return the serving port so callers can tell which instance answered."""
    return {"port": os.environ.get("MCP_MESH_HTTP_PORT", "unknown")}


@mesh.agent(
    name="rewire-provider",
    version="1.0.0",
    description="Provider whose endpoint moves to test consumer re-wire",
    http_port=0,  # Actual port comes from MCP_MESH_HTTP_PORT env
    enable_http=True,
    auto_run=True,
)
class RewireProvider:
    pass
