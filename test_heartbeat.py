#!/usr/bin/env python3
"""
Test script to verify heartbeat functionality with @mesh.tool decorators.
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


# Simple test functions with @mesh.tool decorator
@mesh.tool(capability="simple_greeting", description="Simple greeting function")
def hello_simple():
    """Simple hello function."""
    return "Hello, World!"


@mesh.tool(
    capability="personalized_greeting", description="Personalized greeting function"
)
def hello_personalized(name: str = "World"):
    """Personalized hello function."""
    return f"Hello, {name}!"


@mesh.tool(capability="time_greeting", description="Greeting with current time")
def hello_time():
    """Hello function with current time."""
    import datetime

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Hello! The current time is {now}"


if __name__ == "__main__":
    print("🚀 Starting MCP Mesh test with heartbeat monitoring...")
    print("📍 Registry URL:", os.environ.get("MCP_MESH_REGISTRY_URL"))

    # Import FastMCP and set up server
    from mcp.server.fastmcp import FastMCP

    # Create server
    server = FastMCP("test-heartbeat-agent")

    # Register tools with server (this should trigger heartbeat)
    server.tool()(hello_simple)
    server.tool()(hello_personalized)
    server.tool()(hello_time)

    print("🔧 Tools registered with FastMCP server")
    print("⏳ Waiting for heartbeat to start (should see health monitoring tasks > 0)")

    # Wait a bit to let heartbeat initialization happen
    time.sleep(5)

    print("✅ Test complete - check logs for heartbeat activity")

    # Keep running to observe heartbeat behavior
    print("🔄 Keeping script running to observe heartbeat behavior...")
    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(30)
            print("💓 Still running - heartbeat should be active...")
    except KeyboardInterrupt:
        print("\n🛑 Stopping test script")
