#!/usr/bin/env python3
"""uc37 provider-charlie — self-identifying provider of view-cap-charlie (RFC #1280).

The REQUIRED edge target: the Java consumer's view binds view-cap-charlie
with @Selector(required = true). tc03 kills and restarts THIS provider to
drive the required-edge unavailable -> recovered transitions (issue #1249
availability derivation on the synthetic __mesh_service_deps capability +
the tool-boundary refusal contract).
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Provider Charlie (uc37)")


@app.tool()
@mesh.tool(capability="view-cap-charlie", description="Self-identifying payload from provider-charlie")
async def charlie_tool() -> dict:
    return {"agent": "provider-charlie", "cap": "view-cap-charlie", "msg": "hello-from-charlie"}


# RFC #1280 phase 2 (tc06/tc07): tp-cap-charlie is the REQUIRED edge of the
# Java view_tool_param tool's view PARAMETER — killing THIS process drives
# the tool's structured dependency_unavailable refusal (tc06). Namespace is
# distinct from view-cap-* (see provider-alpha).
@app.tool()
@mesh.tool(capability="tp-cap-charlie", description="Self-identifying tool-param payload from provider-charlie")
async def tp_charlie_tool() -> dict:
    return {"agent": "provider-charlie", "cap": "tp-cap-charlie", "msg": "hello-from-charlie-tp"}


@mesh.agent(
    name="provider-charlie",
    version="1.0.0",
    description="uc37 provider of view-cap-charlie (required edge) for the Java service-view TCs",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9103")),
    enable_http=True,
    auto_run=True,
)
class ProviderCharlie:
    pass
