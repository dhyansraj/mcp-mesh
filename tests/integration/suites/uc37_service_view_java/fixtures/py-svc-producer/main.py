#!/usr/bin/env python3
"""uc37 py-svc-producer — PYTHON producer sugar (RFC #1280 phase 3, tc12).

``@mesh.service("pysvc")`` publishes each public method as a DOTTED
capability (pysvc.alpha, pysvc.bravo) through the normal ``@mesh.tool``
machinery — the Python twin of java-view-producer's
``@McpMeshService("svc")`` and ts-svc-producer's ``addService("tssvc")``.

Payloads are self-identifying (agent + capability) so tc12's direct
``meshctl call pysvc.<m>`` assertions prove serving + routing, not just
registration. Methods are deliberately no-arg (mirrors the other producers)
so ``'{}'`` calls work.

NOTE: no ``@app.tool`` anywhere by design — the sugar must publish AND serve
on its own. If pysvc.* shows in the registry but ``tools/call`` answers
"Unknown tool", that is the SDK gap tc12 exists to surface (sugar registered
the capability for the wire but not on the served FastMCP instance).
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Py Svc Producer (uc37)")


@mesh.service("pysvc")
class PySvcTools:
    """Publishes pysvc.alpha and pysvc.bravo — nothing else."""

    async def alpha(self) -> dict:
        return {"agent": "py-svc-producer", "cap": "pysvc.alpha", "msg": "hello-from-pysvc-alpha"}

    async def bravo(self) -> dict:
        return {"agent": "py-svc-producer", "cap": "pysvc.bravo", "msg": "hello-from-pysvc-bravo"}


@mesh.agent(
    name="py-svc-producer",
    version="1.0.0",
    description="uc37 Python producer of pysvc.* dotted capabilities via @mesh.service sugar",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9302")),
    enable_http=True,
    auto_run=True,
)
class PySvcProducer:
    pass
