#!/usr/bin/env python3
"""py-hc-consumer — reports which provider the mesh routed it to (issue #1480).

``who_served`` injects ``hc_probe_py`` and returns the provider's payload
verbatim. The consumer process is started ONCE and never restarted, so the
only way its answer can move from provider A to provider B and back is if
the runtime re-resolved the dependency on its own — which is exactly the
withdrawal / recovery chain under test.
"""

import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshTool

app = FastMCP("HC Consumer (python)")


@app.tool()
@mesh.tool(
    capability="who_served_py",
    description="Call hc_probe_py and report which provider answered",
    tags=["hc-withdrawal"],
    dependencies=["hc_probe_py"],
)
async def who_served(probe: McpMeshTool = None) -> dict:
    if probe is None:
        return {"error": "hc_probe_py dependency not injected"}
    return await probe()


@mesh.agent(
    name="hc-consumer-py",
    version="1.0.0",
    description="Consumer that must fail over when provider A withdraws (#1480)",
    http_port=0,  # actual port comes from MCP_MESH_HTTP_PORT
    enable_http=True,
    auto_run=True,
)
class HcConsumer:
    pass
