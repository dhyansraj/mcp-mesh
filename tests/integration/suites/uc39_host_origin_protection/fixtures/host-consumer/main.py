#!/usr/bin/env python3
"""uc39 host-consumer — calls host_probe across the mesh (issue #1312).

Depends on the ``host_probe`` capability and, when invoked, makes a real
cross-agent call to the provider's ``/mcp`` endpoint. Because the provider is
advertised on a NON-loopback host (see host-provider + test.yaml), this call
carries ``Host: <non-loopback>`` — the exact condition FastMCP's DNS-rebinding
guard rejects with 421 on a pre-#1312 build.

On this branch (fix present: ``host_origin_protection=False``) the downstream
call succeeds and this tool returns the provider's result. A 421 would make
``await probe()`` raise, so a successful, well-formed return is the regression
guard the test asserts on.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("HostProbe Consumer")


@app.tool()
@mesh.tool(
    capability="host_probe_consume",
    description="Calls host_probe across the mesh and returns the provider's result verbatim",
    dependencies=["host_probe"],
)
async def consume_host_probe(probe: mesh.McpMeshTool = None) -> dict:
    if probe is None:
        # Dependency never resolved — distinct from a 421 so failures are legible.
        return {"error": "host_probe proxy is None (dependency unresolved)"}
    # This is the load-bearing hop: a cross-agent /mcp call to the provider's
    # non-loopback advertised host. Pre-#1312 this 421s and raises.
    result = await probe()
    return {"provider_result": result}


@mesh.agent(
    name="host-consumer",
    version="1.0.0",
    description="uc39 consumer that calls host_probe on a non-loopback provider",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9202")),
    enable_http=True,
    auto_run=True,
)
class HostConsumer:
    pass
