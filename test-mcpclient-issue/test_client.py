#!/usr/bin/env python3
"""
Vanilla FastMCP Client for DNS Resolution Testing

This is a pure FastMCP client implementation without any MCP Mesh dependencies.
Used to establish the baseline working pattern for DNS service resolution.
"""

import os
import asyncio
import logging
from fastmcp import Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_connection():
    """Test connection to FastMCP server."""
    target_host = os.getenv("TARGET_HOST", "localhost:8080")
    endpoint = f"http://{target_host}/mcp"

    logger.info(f"🎯 Testing connection to: {endpoint}")

    try:
        # Create FastMCP client
        async with Client(endpoint) as client:
            logger.info("✅ FastMCP client connected successfully")

            # Test 1: Simple ping
            logger.info("🏓 Testing ping...")
            result = await client.call_tool("ping")
            logger.info(f"📥 Ping result: {result}")

            # Test 2: Echo with message
            logger.info("📢 Testing echo...")
            result = await client.call_tool("echo", {"message": "Hello from vanilla FastMCP client!"})
            logger.info(f"📥 Echo result: {result}")

            # Test 3: Get server info
            logger.info("ℹ️ Testing server info...")
            result = await client.call_tool("get_server_info")
            logger.info(f"📥 Server info result: {result}")

            # Test 4: List all available tools
            logger.info("📋 Listing available tools...")
            tools = await client.list_tools()
            logger.info(f"📥 Available tools: {[tool.name for tool in tools]}")

            logger.info("✅ All tests completed successfully!")

    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        logger.error(f"🔍 Target endpoint was: {endpoint}")
        raise

async def test_connectivity_loop():
    """Test connectivity in a loop for debugging."""
    target_host = os.getenv("TARGET_HOST", "localhost:8080")
    endpoint = f"http://{target_host}/mcp"

    logger.info(f"🔄 Starting connectivity loop test to: {endpoint}")

    for i in range(3):
        logger.info(f"🔄 Test iteration {i+1}/3")
        try:
            await test_connection()
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"❌ Iteration {i+1} failed: {e}")
            if i == 2:  # Last attempt
                raise
            await asyncio.sleep(2)

if __name__ == "__main__":
    # Get target host from environment
    target_host = os.getenv("TARGET_HOST", "localhost:8080")

    logger.info(f"🚀 Starting vanilla FastMCP client")
    logger.info(f"📍 Target server: {target_host}")
    logger.info(f"🌐 Full endpoint: http://{target_host}/mcp")

    # Check if we should run in loop mode
    if os.getenv("LOOP_TEST", "false").lower() == "true":
        asyncio.run(test_connectivity_loop())
    else:
        asyncio.run(test_connection())