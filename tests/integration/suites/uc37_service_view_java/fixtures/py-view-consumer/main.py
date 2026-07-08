#!/usr/bin/env python3
"""uc37 py-view-consumer — PYTHON service view consuming the JAVA producer
(RFC #1280 cross-runtime seam, tc10).

The ``SvcView`` view binds the dotted svc.* capabilities published by
java-view-producer as explicit ``@MeshTool`` dotted capabilities. ``bravo`` carries
``required=True``: because a Python view is a TOOL-PARAMETER surface, its
edges are ordinary tool dependency slots, so the required edge participates
in the issue #1273 pre-invoke guard — calling ``py_view_report`` while
svc.bravo is unresolved is refused with the structured
``{"error":"dependency_unavailable","capability":"svc.bravo"}`` ToolError
BEFORE the handler runs (envelope parity with the Java tool-param path,
tc06).

The report tool mirrors the suite's flat shape: ``<method>_agent`` /
``<method>_cap`` on success, ``<method>_error`` / ``<method>_error_message``
on failure.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Py View Consumer (uc37)")


@mesh.service
class SvcView:
    """Consumer view over the Java producer's dotted svc.* capabilities."""

    @mesh.selector("svc.alpha")
    async def alpha(self) -> dict: ...

    @mesh.selector("svc.bravo", required=True)
    async def bravo(self) -> dict: ...


@app.tool()
@mesh.tool(
    capability="py_view_report",
    description="Call both SvcView methods (Java svc.* producer) and report which agent served each",
)
async def py_view_report(view: SvcView = None) -> dict:
    out: dict = {}
    for name in ("alpha", "bravo"):
        try:
            payload = await getattr(view, name)()
            out[f"{name}_agent"] = payload.get("agent")
            out[f"{name}_cap"] = payload.get("cap")
        except Exception as e:  # noqa: BLE001 — the report IS the observation surface
            out[f"{name}_error"] = type(e).__name__
            out[f"{name}_error_message"] = str(e)
    return out


@mesh.agent(
    name="py-view-consumer",
    version="1.0.0",
    description="uc37 Python consumer of the Java svc.* producer via a @mesh.service view",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9301")),
    enable_http=True,
    auto_run=True,
)
class PyViewConsumer:
    pass
