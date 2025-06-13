#!/usr/bin/env python3
"""Test how multiple functions with same capability are handled."""

import asyncio
import logging

from fastmcp import FastMCP
from mcp_mesh import mesh_agent

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG, format="%(levelname)s - %(name)s - %(message)s"
)

# Create MCP server
server = FastMCP("multi-capability-test")


@server.tool()
@mesh_agent(capability="greeting", version="1.0.0", health_interval=10)
async def greet_formal(name: str) -> str:
    """Formal greeting function."""
    return f"Good day, {name}. How may I assist you?"


@server.tool()
@mesh_agent(capability="greeting", version="1.0.0", health_interval=10)
async def greet_casual(name: str) -> str:
    """Casual greeting function."""
    return f"Hey {name}! What's up?"


@server.tool()
@mesh_agent(capability="farewell", version="1.0.0", health_interval=10)
async def say_goodbye(name: str) -> str:
    """Farewell function."""
    return f"Goodbye {name}, see you later!"


async def main():
    """Run the test."""
    print("=== Testing Multiple Functions with Same Capability ===")
    print("Expected behavior:")
    print("- All 3 functions should register under the same agent ID")
    print("- greet_formal and greet_casual both provide 'greeting' capability")
    print("- say_goodbye provides 'farewell' capability")
    print("- Registry should track both capabilities")
    print("- Heartbeats should use the shared agent ID")
    print("")
    print("Watch the logs to see actual behavior...")

    # Let it run for 30 seconds to see registration and heartbeats
    await asyncio.sleep(30)
    print("\nTest complete")


if __name__ == "__main__":
    asyncio.run(main())
