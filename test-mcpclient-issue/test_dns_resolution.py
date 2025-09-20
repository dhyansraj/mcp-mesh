#!/usr/bin/env python3
"""
Test DNS resolution in MCP Mesh-like architecture.

This is the critical test - FastMCP client calling another agent
from within the decorator-driven MCP Mesh-like context.
"""

import asyncio
import logging
from fastmcp import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_dns_resolution():
    """Test calling the tool that uses FastMCP client internally - DNS resolution test."""
    # In Docker, connect to the service name; locally use localhost
    import os
    import time

    # Give servers time to start up in Docker
    if os.getenv("MESH_HOST"):
        logger.info("🕐 Waiting for servers to start up in Docker...")
        time.sleep(3)

    mesh_host = os.getenv("MESH_HOST", "localhost:8081")
    endpoint = f"http://{mesh_host}/mcp"

    logger.info(f"🔍 Testing DNS resolution in MCP Mesh-like context")
    logger.info(f"📍 Connecting to: {endpoint}")

    try:
        async with Client(endpoint) as client:
            logger.info("✅ Connected to MCP Mesh-like server")

            # List tools to confirm what's available
            tools = await client.list_tools()
            logger.info(f"📋 Available tools: {[tool.name for tool in tools]}")

            # Test the DNS resolution tool
            logger.info("🎯 Calling call_remote_server_via_localhost (tests DNS resolution)...")
            result = await client.call_tool("call_remote_server_via_localhost")
            logger.info(f"📥 DNS resolution test result: {result}")

            # Check if it was successful
            if hasattr(result, 'structured_content') and result.structured_content:
                status = result.structured_content.get('status', 'unknown')
                if status == 'success':
                    logger.info("🎉 DNS RESOLUTION TEST PASSED!")
                    logger.info("✅ FastMCP client successfully called remote server via localhost from MCP Mesh-like context")
                else:
                    logger.error(f"❌ DNS resolution test failed: {result.structured_content}")
            else:
                logger.warning(f"⚠️ Unexpected result format: {result}")

    except Exception as e:
        logger.error(f"❌ Failed to test DNS resolution: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(test_dns_resolution())