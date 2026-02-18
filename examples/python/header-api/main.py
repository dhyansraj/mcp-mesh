#!/usr/bin/env python3
"""
header-api - FastAPI app that forwards headers to mesh agents via @mesh.route
"""

import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(title="Header API", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/echo-headers")
@mesh.route(dependencies=["echo_headers"])
async def echo_headers_api(request: Request, echo_headers: McpMeshTool = None):
    """Call echo_headers capability via mesh — headers should propagate."""
    if not echo_headers:
        return {"error": "echo_headers capability unavailable"}
    result = await echo_headers()
    return {"source": "mesh-route", "headers": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
