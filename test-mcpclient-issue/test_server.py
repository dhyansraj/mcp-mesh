#!/usr/bin/env python3
"""
Vanilla FastMCP Server for DNS Resolution Testing

This is a pure FastMCP implementation without any MCP Mesh dependencies.
Used to establish the baseline working pattern for DNS service resolution.
"""

import os
import logging
from fastapi import FastAPI
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastMCP instance
app = FastMCP("Test Server")

@app.tool()
def ping() -> str:
    """Simple ping tool for testing connectivity."""
    logger.info("🏓 Ping tool called")
    return "pong"

@app.tool()
def echo(message: str) -> str:
    """Echo back the provided message."""
    logger.info(f"📢 Echo tool called with message: {message}")
    return f"Echo: {message}"

@app.tool()
async def slow_task() -> dict:
    """Slow task that takes 30 seconds to complete (tests async behavior)."""
    import asyncio
    import time
    logger.info("🐌 Slow task started - will take 30 seconds")

    start_time = time.time()
    await asyncio.sleep(30)  # Use async sleep to not block the event loop
    end_time = time.time()

    logger.info(f"🐌 Slow task completed after {end_time - start_time:.1f} seconds")
    return {
        "task": "slow_task",
        "duration_seconds": round(end_time - start_time, 1),
        "message": "Slow task completed successfully"
    }

@app.tool()
def fast_task() -> dict:
    """Fast task that returns immediately (tests concurrent async behavior)."""
    import time
    logger.info("⚡ Fast task called - returning immediately")

    return {
        "task": "fast_task",
        "timestamp": time.time(),
        "message": "Fast task completed immediately"
    }

@app.tool()
def get_server_info() -> dict:
    """Get server information."""
    import socket
    hostname = socket.gethostname()
    logger.info(f"ℹ️ Server info requested from {hostname}")

    return {
        "hostname": hostname,
        "port": int(os.getenv("PORT", "8080")),
        "message": "Hello from vanilla FastMCP server!",
        "status": "running"
    }

# Get the FastMCP HTTP app
mcp_http_app = app.http_app()

# Create FastAPI app for HTTP transport with FastMCP lifespan
fastapi_app = FastAPI(
    title="Test FastMCP Server",
    description="Vanilla FastMCP server for DNS resolution testing",
    version="1.0.0",
    lifespan=mcp_http_app.lifespan  # This is required for FastMCP to work properly!
)

# Add a simple health check endpoint
@fastapi_app.get("/health")
async def health():
    return {"status": "healthy", "service": "test-fastmcp-server"}

# Mount FastMCP directly at root - FastMCP handles its own /mcp routing
fastapi_app.mount("", mcp_http_app)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    logger.info(f"🚀 Starting vanilla FastMCP server on port {port}")
    logger.info(f"📍 MCP endpoint will be available at: http://localhost:{port}/mcp")
    logger.info(f"🏥 Health endpoint available at: http://localhost:{port}/health")

    uvicorn.run(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )