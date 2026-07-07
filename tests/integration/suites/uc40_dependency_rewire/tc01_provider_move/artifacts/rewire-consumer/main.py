#!/usr/bin/env python3
"""
rewire-consumer - Depends on `rewire_probe` and reports which provider answered.

`which_provider` injects the `rewire_probe` capability, calls it, and returns
the provider's result verbatim ({"port": <provider's serving port>}). The
consumer process is started ONCE and never restarted during the test: the only
way its result can flip from the old provider port to the new one is if the
runtime re-wires the injected proxy to the moved provider on its own.
"""

import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshTool

app = FastMCP("Rewire Consumer")


@app.tool()
@mesh.tool(
    capability="which_provider",
    description="Call rewire_probe and return which provider instance answered",
    tags=["rewire"],
    dependencies=["rewire_probe"],
)
async def which_provider(probe: McpMeshTool = None) -> dict:
    """Return the provider's self-reported serving port."""
    if probe is None:
        return {"error": "rewire_probe dependency not injected"}
    return await probe()


@mesh.agent(
    name="rewire-consumer",
    version="1.0.0",
    description="Consumer that must re-wire when the provider moves endpoints",
    http_port=0,  # Actual port comes from MCP_MESH_HTTP_PORT env
    enable_http=True,
    auto_run=True,
)
class RewireConsumer:
    pass
