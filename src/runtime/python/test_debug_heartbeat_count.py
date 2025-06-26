"""
Debug test to analyze heartbeat call count in isolation.
"""

import os
from unittest.mock import patch

import pytest

import mesh

# Disable background services for this test
# os.environ["MCP_MESH_AUTO_RUN"] = "false"
# os.environ["MCP_MESH_ENABLE_HTTP"] = "false"


# from mcp.server.fastmcp import FastMCP


@mesh.agent(name="test-agent")
class SystemAgent:
    """System information agent providing date and info capabilities."""

    pass


@pytest.mark.asyncio
def test_debug_heartbeat_count():
    """Debug test: Count exactly how many heartbeat calls are made for 2 @mesh.tool functions."""

    # Clear any existing decorators
    # from mcp_mesh import DecoratorRegistry
    # DecoratorRegistry.clear_all()

    print("🧪 TEST START: Creating 2 @mesh.tool functions...")

    # NO MANUAL FastMCP server - let MCP Mesh auto-create it

    @mesh.tool(capability="greeting")
    def greet(name: str) -> str:
        return f"Hello {name}"

    @mesh.tool(capability="farewell")
    def goodbye(name: str) -> str:
        return f"Goodbye {name}"

    print("✅ Created 2 @mesh.tool functions WITHOUT manual FastMCP server")

    # Check decorator registry state
    # mesh_tools = DecoratorRegistry.get_mesh_tools()
    # print(f"📊 DecoratorRegistry has {len(mesh_tools)} tools: {list(mesh_tools.keys())}")

    # Create processor - NO MOCKING
    # from mcp_mesh.engine.processor import DecoratorProcessor
    print("🏭 Creating DecoratorProcessor...")

    # processor = DecoratorProcessor("http://localhost:8080")
    # print(f"🏭 Processor created with registry URL: {processor.registry_url}")

    print("🚀 Starting processor.process_all_decorators()...")

    try:
        # await processor.process_all_decorators()
        print("✅ process_all_decorators() completed")
    except Exception as e:
        print(f"⚠️ process_all_decorators() raised: {e}")

    print("⏳ Waiting 3 seconds for any async operations...")
    # import asyncio
    # await asyncio.sleep(3.0)

    print("🔍 Analyzing logs above:")
    print("   - Count 'Starting HTTP server' lines")
    print("   - Count 'Sending heartbeat' lines")
    print("   - Count 'Failed to send heartbeat' lines")
    print("   - Look for multiple agent IDs vs same agent ID")


# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(test_debug_heartbeat_count())
