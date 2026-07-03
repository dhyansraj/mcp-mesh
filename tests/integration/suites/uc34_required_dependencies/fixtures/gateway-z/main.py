#!/usr/bin/env python3
"""uc34 gateway-z — FastAPI perimeter gateway; /z has a REQUIRED dep on b-cap.

Issue #1249 route perimeter (Python): external HTTP callers never traverse a
mesh proxy, so the required predicate is enforced at the route boundary by
the framework's own @mesh.route wrapper — when the b-cap proxy is unavailable
at call time (after the settle window), /z answers 503 with
{"error":"dependency_unavailable","capability":"b-cap"} BEFORE user code runs.
The handler body therefore calls b_dep unguarded: reaching it with a None
proxy would crash with a 500, so a clean 503 is proof the perimeter fired.
"""

import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(title="GatewayZ", description="uc34 gateway for /z", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway-z"}


@app.get("/z")
@mesh.route(dependencies=[{"capability": "b-cap", "required": True}])
async def z_endpoint(request: Request, b_dep: McpMeshTool = None):
    result = await b_dep()
    return {"status": "ok", "b_said": result}


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9104")),
        log_level="info",
    )
