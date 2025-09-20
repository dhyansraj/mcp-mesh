#!/usr/bin/env python3
"""
Test only the ping_remote_server tool that we know is registered.
"""

import asyncio
import logging
from fastmcp import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_ping_tool():
    """Test the ping_remote_server tool that is successfully registered."""
    endpoint = "http://localhost:8081/mcp"

    logger.info(f"🏓 Testing ping_remote_server tool at: {endpoint}")

    try:
        async with Client(endpoint) as client:
            logger.info("✅ Connected to MCP Mesh-like server")

            # List tools to confirm
            tools = await client.list_tools()
            logger.info(f"📋 Available tools: {[tool.name for tool in tools]}")

            # Test the ping tool
            result = await client.call_tool("ping_remote_server")
            logger.info(f"📥 ping_remote_server result: {result}")

            logger.info("✅ Ping test completed successfully!")

    except Exception as e:
        logger.error(f"❌ Failed to test ping tool: {e}")

if __name__ == "__main__":
    asyncio.run(test_ping_tool())