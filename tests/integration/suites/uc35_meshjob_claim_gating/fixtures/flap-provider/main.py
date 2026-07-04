#!/usr/bin/env python3
"""uc35 flap-provider — the required dependency that flaps DOWN→UP (issue #1268).

Provides ``flap_data``, the capability flap-worker's ``checked_task`` declares
``required=True``. The test stops and restarts THIS agent to open the
gate/injection race window #1268 closes: the registry-side claim gate flips
available the moment this provider re-registers, while the worker's injected
proxy slot refills only on the worker's next heartbeat. Pre-fix, a claim
granted inside that window invoked the handler with a null required proxy.

The tool returns a fixed marker so the test can prove — from the completed
job's ``result`` — that the handler really called THIS provider (a null
injection would instead die loudly on the unguarded call).
"""

import os
from typing import Any

import mesh
from fastmcp import FastMCP

app = FastMCP("Flap Provider (uc35)")


@app.tool()
@mesh.tool(
    capability="flap_data",
    description="Returns a fixed liveness marker; the required dep that flaps DOWN->UP.",
)
def get_flap_data() -> dict[str, Any]:
    return {"marker": "flap-provider-live"}


@mesh.agent(
    name="flap-provider",
    version="1.0.0",
    description="uc35 required-dep provider that the test flaps DOWN->UP (issue #1268)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class FlapProvider:
    pass
