#!/usr/bin/env python3
"""
Simple Example: Auto-FastMCP with @mesh.tool only

This shows the magical experience:
- NO manual FastMCP server creation
- NO manual tool registration
- Just @mesh.tool + keep process alive
- Processor does everything automatically

Run: python example/hello_auto_fastmcp.py
"""

import logging
import os
import time

# Set up logging to see the magic happen
logging.basicConfig(level=logging.INFO)

# Set registry URL (adjust as needed)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Import mesh
import mesh


# Define agent (optional but recommended for naming)
@mesh.agent(name="hello-auto")
class HelloAgent:
    pass


# Define tools - NO FastMCP server needed!
@mesh.tool(capability="simple_greeting")
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mesh.tool(capability="math")
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    print("🚀 Starting Hello Auto-FastMCP Example")
    print("📝 Defined 2 @mesh.tool functions")
    print("⏳ Waiting for processor to auto-create FastMCP server...")

    # Keep process alive - CRITICAL for FastMCP server to survive
    print("💓 Process running (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(10)
            print("📡 Still alive - FastMCP server active")
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
