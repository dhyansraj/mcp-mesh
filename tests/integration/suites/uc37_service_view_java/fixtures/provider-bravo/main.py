#!/usr/bin/env python3
"""uc37 provider-bravo — self-identifying provider of view-cap-bravo (RFC #1280).

The OPTIONAL rebinding target: tc02 kills and restarts THIS provider to
prove the corresponding view method degrades and heals independently of
the other methods, with no consumer restart. tc05 kills it to drive the
FlooredService view below its minAvailable=2 floor.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Provider Bravo (uc37)")


@app.tool()
@mesh.tool(capability="view-cap-bravo", description="Self-identifying payload from provider-bravo")
async def bravo_tool() -> dict:
    return {"agent": "provider-bravo", "cap": "view-cap-bravo", "msg": "hello-from-bravo"}


# RFC #1280 phase 2 (tc06/tc07): tp-cap-* namespace for the Java
# view_tool_param tool's view PARAMETER — see provider-alpha for why the
# namespace is distinct from view-cap-*.
@app.tool()
@mesh.tool(capability="tp-cap-bravo", description="Self-identifying tool-param payload from provider-bravo")
async def tp_bravo_tool() -> dict:
    return {"agent": "provider-bravo", "cap": "tp-cap-bravo", "msg": "hello-from-bravo-tp"}


@mesh.agent(
    name="provider-bravo",
    version="1.0.0",
    description="uc37 provider of view-cap-bravo for the Java service-view TCs",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9102")),
    enable_http=True,
    auto_run=True,
)
class ProviderBravo:
    pass
