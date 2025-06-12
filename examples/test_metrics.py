#!/usr/bin/env python3
"""Test script to verify Prometheus metrics are working correctly."""


from fastmcp import FastMCP

# Create a simple MCP server with HTTP enabled
mcp = FastMCP("metrics-test-agent")


@mcp.tool()
def test_tool(message: str) -> str:
    """A simple test tool."""
    return f"Test response: {message}"


# Enable HTTP with metrics
if __name__ == "__main__":
    import os

    # Enable HTTP wrapper
    os.environ["MCP_MESH_HTTP_ENABLED"] = "true"
    os.environ["MCP_MESH_HTTP_PORT"] = "8899"
    os.environ["MCP_MESH_LOG_LEVEL"] = "DEBUG"

    print("Starting MCP server with metrics enabled...")
    print("Once started, you can check metrics at:")
    print("  http://localhost:8899/metrics")
    print("  http://localhost:8899/health")
    print("  http://localhost:8899/mesh/info")
    print("\nPress Ctrl+C to stop")

    # Run the server
    mcp.run()
