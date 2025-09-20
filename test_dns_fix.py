#!/usr/bin/env python3
"""
Test the DNS fix in real MCP Mesh environment.

This tests the generate_comprehensive_report tool which should call
other services via DNS names.
"""

import asyncio
import logging
from fastmcp import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_dns_fix():
    """Test DNS resolution in actual MCP Mesh environment."""
    endpoint = "http://localhost:8084/mcp"  # dependent-agent

    logger.info(f"🔍 Testing DNS fix with MCP Mesh dependent-agent")
    logger.info(f"📍 Connecting to: {endpoint}")

    try:
        async with Client(endpoint) as client:
            logger.info("✅ Connected to dependent-agent")

            # Test the comprehensive report tool that calls other services
            logger.info("🎯 Calling generate_comprehensive_report (tests DNS to system service)...")
            result = await client.call_tool("generate_comprehensive_report", {
                "report_title": "DNS Test Report",
                "include_system_data": True
            })

            logger.info(f"📥 Result: {result}")

            if hasattr(result, 'is_error') and not result.is_error:
                logger.info("🎉 DNS RESOLUTION FIX SUCCESSFUL!")
                logger.info("✅ MCP Mesh agents can now communicate via service names!")
            else:
                logger.error("❌ DNS resolution test failed")

    except Exception as e:
        logger.error(f"❌ Failed to test DNS fix: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(test_dns_fix())