#!/usr/bin/env python3
"""uc39 host-provider — advertises the ``host_probe`` capability (issue #1312).

Deliberately trivial: a single tool returning a constant. The point of this UC
is NOT what the tool computes but WHERE the provider is advertised. The test
starts this agent with ``MCP_MESH_HTTP_HOST`` set to a NON-loopback but
pod-reachable host, so a consumer's mesh call carries ``Host: <non-loopback>``
against this agent's ``/mcp`` endpoint.

FastMCP's DNS-rebinding guard (``host_origin_protection``) would 421 any
non-localhost Host header. #1312 fixes that by passing
``host_origin_protection=False`` when mesh builds the http_app. This provider
exists so the consumer's cross-agent call actually exercises that path — every
other suite co-locates agents on loopback, so ``Host: localhost`` is always
allowed and the regression slips through.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("HostProbe Provider")


@app.tool()
@mesh.tool(
    capability="host_probe",
    description="Trivial probe that returns a constant, used to exercise the /mcp Host guard",
)
def host_probe() -> dict:
    return {"ok": True}


@mesh.agent(
    name="host-provider",
    version="1.0.0",
    description="uc39 provider of host_probe (advertised on a non-loopback host)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9201")),
    enable_http=True,
    auto_run=True,
)
class HostProvider:
    pass
