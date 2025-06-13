#!/usr/bin/env python3
"""Test that agent ID is used consistently for registration and heartbeats."""

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="test-agent-id")


@server.tool()
@mesh_agent(capability="test", enable_http=True, http_port=9000)
def test_function():
    """Test function to verify agent ID consistency."""
    return "Agent ID test successful!"


if __name__ == "__main__":
    print("Starting test agent...")
    print("This agent should use a generated agent ID like 'agent-xxxxxxxx'")
    print("Both registration and heartbeats should use the same ID")
    server.run(transport="stdio")
