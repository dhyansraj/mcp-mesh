"""
Python API Port Isolation Test App

A minimal FastAPI app with @mesh.route but NO @mesh.agent.
Used to verify MCP_MESH_HTTP_PORT does NOT override uvicorn port
for API-type apps (apps with @mesh.route but no @mesh.agent).

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/658
"""

import mesh
from fastapi import FastAPI, Request
from mesh.types import McpMeshTool

app = FastAPI(title="API Port Test")


@app.get("/ping")
async def ping():
    """Simple ping endpoint for port verification."""
    return {"message": "pong"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/greet")
@mesh.route(dependencies=["greeting"])
async def greet(request: Request, greeting: McpMeshTool = None):
    """Greet via mesh-injected greeting capability."""
    if greeting and greeting.is_available():
        return await greeting(name="test")
    return {"message": "fallback"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
