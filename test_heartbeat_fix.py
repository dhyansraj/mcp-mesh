#!/usr/bin/env python3
"""Test script to verify heartbeat fix."""

import asyncio
import logging

from fastmcp import FastMCP
from mcp_mesh import mesh_agent

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Create MCP server
server = FastMCP("test-heartbeat")


@server.tool()
@mesh_agent(
    agent_name="custom_agent_name",  # Custom name different from function name
    enable_http=True,
    health_interval=5,
)
async def test_function(message: str) -> str:
    """Test function with custom agent name."""
    return f"Hello {message}"


async def main():
    """Run the test."""
    print("Starting test server...")
    print("Function name: test_function")
    print("Agent name: custom_agent_name")
    print("Watch the logs to see if heartbeats use the correct agent name")

    # Keep running for 30 seconds to see multiple heartbeats
    await asyncio.sleep(30)
    print("Test complete")


if __name__ == "__main__":
    asyncio.run(main())
