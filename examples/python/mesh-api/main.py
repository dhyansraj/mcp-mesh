#!/usr/bin/env python3
"""
py-mesh-api - MCP Mesh API Route Example

A FastAPI app with @mesh.route integration that exposes REST endpoints
consuming mesh agent capabilities via dependency injection.
Used for UC06 observability tracing tests.

Started with: meshctl start mesh-api/main.py
"""

import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(
    title="Py Mesh API",
    description="FastAPI app with @mesh.route dependency injection",
    version="1.0.0",
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/add")
@mesh.route(dependencies=["add"])
async def api_add(request: Request, add: McpMeshTool = None):
    """
    Add two numbers via mesh-injected add capability.

    Dependencies:
    - add: Math add tool from mesh agent
    """
    body = await request.json()
    if not add:
        return {"error": "add service unavailable"}
    result = await add(a=body["a"], b=body["b"])
    return {"operation": "add", "a": body["a"], "b": body["b"], "result": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
