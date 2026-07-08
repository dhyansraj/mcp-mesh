#!/usr/bin/env python3
"""uc37 provider-alpha — self-identifying provider of view-cap-alpha (RFC #1280).

One of THREE independent providers backing a single Java @MeshService
view: each view method must resolve to a DIFFERENT provider agent. The
payload names both the agent and the capability so the consumer's report
tool can prove per-method binding (agent identity AND capability routing).
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Provider Alpha (uc37)")


@app.tool()
@mesh.tool(capability="view-cap-alpha", description="Self-identifying payload from provider-alpha")
async def alpha_tool() -> dict:
    return {"agent": "provider-alpha", "cap": "view-cap-alpha", "msg": "hello-from-alpha"}


# RFC #1280 phase 2 (tc06/tc07): same provider also backs the tp-cap-*
# namespace consumed by the Java view_tool_param tool's view PARAMETER —
# deliberately distinct from view-cap-* so the consumer's two dependency
# carriers (per-tool edges vs the __mesh_service_deps synthetic) stay
# independently observable in the registry.
@app.tool()
@mesh.tool(capability="tp-cap-alpha", description="Self-identifying tool-param payload from provider-alpha")
async def tp_alpha_tool() -> dict:
    return {"agent": "provider-alpha", "cap": "tp-cap-alpha", "msg": "hello-from-alpha-tp"}


@mesh.agent(
    name="provider-alpha",
    version="1.0.0",
    description="uc37 provider of view-cap-alpha for the Java service-view TCs",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class ProviderAlpha:
    pass
