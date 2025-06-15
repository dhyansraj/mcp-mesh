#!/usr/bin/env python3
"""
Test script to verify the new @mesh.agent parameters: enable_http and namespace.
"""

import logging
import os
import sys
import time

# Set up logging first
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Add the source directory to Python path
sys.path.insert(0, "src/runtime/python/src")

# Set registry URL environment variable
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Import mesh decorators
import mesh


# Test with @mesh.agent that has enable_http=True and custom namespace
@mesh.agent(
    name="test-http-agent",
    version="2.0.0",
    namespace="testing",
    enable_http=True,
    http_port=0,  # Auto-assign port
)
class TestAgent:
    pass


@mesh.tool(capability="http_greeting", description="HTTP enabled greeting function")
def hello_http():
    """HTTP-enabled hello function."""
    return "Hello from HTTP!"


@mesh.tool(capability="http_status", description="HTTP status function")
def status_check():
    """HTTP status check function."""
    return {"status": "HTTP enabled!", "timestamp": time.time()}


if __name__ == "__main__":
    print("🚀 Starting MCP Mesh test with new @mesh.agent parameters...")
    print("📍 Registry URL:", os.environ.get("MCP_MESH_REGISTRY_URL"))
    print(
        "🔧 Agent config: enable_http=True, namespace='testing', http_port=0 (auto-assign)"
    )

    # Import FastMCP and set up server
    from mcp.server.fastmcp import FastMCP

    # Create server
    server = FastMCP("test-http-enabled-agent")

    # Register tools with server (this should trigger HTTP setup)
    server.tool()(hello_http)
    server.tool()(status_check)

    print("🔧 Tools registered with FastMCP server")
    print("⏳ Waiting for HTTP setup and heartbeat to start...")

    # Wait a bit to let setup happen
    time.sleep(8)

    print("✅ Test complete - check logs for HTTP wrapper and heartbeat activity")
    print("🔍 Expected: HTTP endpoint should be http://0.0.0.0:PORT (not stdio://)")

    # Keep running to observe behavior
    print("🔄 Keeping script running to observe HTTP and heartbeat behavior...")
    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(30)
            print("💓 Still running - HTTP endpoint should be active...")
    except KeyboardInterrupt:
        print("\n🛑 Stopping test script")
