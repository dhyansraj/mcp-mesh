#!/usr/bin/env python3
"""
Test MCP Mesh-like Architecture with FastMCP Client

This tests the call_remote_server tool within the MCP Mesh-like decorator-driven architecture.
"""

import os
import asyncio
import logging
from fastmcp import Client

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_mesh_architecture():
    """Test calling the MCP Mesh-like architecture that calls the remote server."""
    target_host = "localhost:8081"  # Our MCP Mesh-like server
    endpoint = f"http://{target_host}/mcp"

    logger.info(f"📍 Testing MCP Mesh-like architecture at: {endpoint}")
    logger.info(f"🎯 This will test the call_remote_server tool that uses FastMCP client internally")

    try:
        async with Client(endpoint) as client:
            logger.info("✅ Connected to MCP Mesh-like server")

            # List available tools
            tools = await client.list_tools()
            logger.info(f"📋 Available tools: {[tool.name for tool in tools]}")

            # Test the call_remote_server tool - this should call test-server via FastMCP client
            logger.info("🔄 Calling call_remote_server tool (tests DNS resolution in MCP context)...")
            result = await client.call_tool("call_remote_server")
            logger.info(f"📥 call_remote_server result: {result}")

            # Test ping tool as well
            logger.info("🔄 Calling ping_remote_server tool...")
            ping_result = await client.call_tool("ping_remote_server")
            logger.info(f"📥 ping_remote_server result: {ping_result}")

            # Test get_client_info tool
            logger.info("🔄 Calling get_client_info tool...")
            info_result = await client.call_tool("get_client_info")
            logger.info(f"📥 get_client_info result: {info_result}")

            logger.info("✅ All MCP Mesh-like architecture tests completed!")

    except Exception as e:
        logger.error(f"❌ Failed to test MCP Mesh-like architecture: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(test_mesh_architecture())