#!/usr/bin/env python3
"""
Minimal MCP Mesh Example

Just one simple function to test that MCP Mesh decorators work.
"""

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_minimal_server() -> FastMCP:
    """Create a minimal MCP server for testing."""

    server = FastMCP(name="minimal-demo")

    @server.tool()
    @mesh_agent(
        agent_name="minimal-agent",
        capability="greeting",
        description="Minimal test function",
    )
    def hello() -> str:
        """Simple hello function."""
        return "👋 Hello from MCP Mesh!"

    return server


if __name__ == "__main__":
    print("🚀 Starting minimal MCP Mesh server...")
    server = create_minimal_server()
    print("📡 Server ready. Press Ctrl+C to stop.")
    server.run(transport="stdio")
