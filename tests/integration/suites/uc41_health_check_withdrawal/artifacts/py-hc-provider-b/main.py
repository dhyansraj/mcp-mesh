#!/usr/bin/env python3
"""py-hc-provider-b — the survivor (issue #1480).

Second provider of ``hc_probe_py``. Deliberately has NO health check: it is
the control. Two things depend on that:

  - it must keep heartbeating throughout, so a run where BOTH providers go
    unhealthy is distinguishable from a genuine withdrawal of A (a dead
    registry, a stalled sweep or a container-wide stall would take both down);
  - it is the failover target the consumer must land on.

Loses the resolver tiebreak to A while A is healthy: equal tag score, equal
version, and the last tiebreak is agent ID ASC — ``hc-provider-a-py-<uuid>``
sorts before ``hc-provider-b-py-<uuid>``. So the consumer deterministically
starts on A, and any answer naming B is a real re-resolution.
"""

import os

import mesh
from fastmcp import FastMCP

AGENT_NAME = "hc-provider-b-py"

app = FastMCP("HC Provider B (python)")


@app.tool()
@mesh.tool(
    capability="hc_probe_py",
    description="Report which provider instance served this call",
    tags=["hc-withdrawal"],
)
async def probe_b() -> dict:
    return {"served_by": AGENT_NAME, "pid": os.getpid()}


@mesh.agent(
    name=AGENT_NAME,
    version="1.0.0",
    description="Survivor provider that the consumer fails over to (#1480)",
    http_port=0,  # actual port comes from MCP_MESH_HTTP_PORT
    enable_http=True,
    auto_run=True,
)
class HcProviderB:
    pass
