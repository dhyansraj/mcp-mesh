#!/usr/bin/env python3
"""
Simple MCP client to test hello_world functions
"""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_hello_world():
    """Test the hello_world MCP server functions"""

    # Connect to hello_world server
    server_params = StdioServerParameters(
        command="python", args=["examples/hello_world.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()

            print("🔧 Connected to hello_world server!")

            # List available tools
            tools = await session.list_tools()
            print(f"📋 Available tools: {[tool.name for tool in tools.tools]}")

            # Test greet_from_mcp (plain MCP - should not have SystemAgent injected)
            print("\n🧪 Testing greet_from_mcp (Plain MCP):")
            try:
                result = await session.call_tool("greet_from_mcp", {})
                print(f"✅ Result: {result.content[0].text}")
            except Exception as e:
                print(f"❌ Error: {e}")

            # Test greet_from_mcp_mesh (with mesh enhancement - SystemAgent should be None without system_agent running)
            print("\n🧪 Testing greet_from_mcp_mesh (MCP Mesh):")
            try:
                result = await session.call_tool("greet_from_mcp_mesh", {})
                print(f"✅ Result: {result.content[0].text}")
            except Exception as e:
                print(f"❌ Error: {e}")

            # Test dependency injection status
            print("\n🧪 Testing test_dependency_injection:")
            try:
                result = await session.call_tool("test_dependency_injection", {})
                print(f"✅ Result: {result.content[0].text}")
            except Exception as e:
                print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_hello_world())
