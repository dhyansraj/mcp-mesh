#!/usr/bin/env python3
"""
Test to verify FastMCP server creation and tool registration
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🔍 FASTMCP VERIFICATION TEST")
print("=" * 50)

import mesh


@mesh.agent(name="verification-service")
class VerificationAgent:
    pass


@mesh.tool(capability="test1")
def test_tool_1() -> str:
    return "Tool 1 response"


@mesh.tool(capability="test2")
def test_tool_2(message: str) -> str:
    return f"Tool 2 says: {message}"


print("✅ Decorators defined")
print("⏳ Waiting 6 seconds for FastMCP server creation...")

import time

time.sleep(6)

# Try to access the FastMCP server directly
try:
    from mcp_mesh.decorator_registry import DecoratorRegistry

    mesh_tools = DecoratorRegistry.get_mesh_tools()
    print(f"📊 Found {len(mesh_tools)} @mesh.tool functions registered")

    # Check if FastMCP servers exist
    for func_name, decorated_func in mesh_tools.items():
        func = decorated_func.function
        if hasattr(func, "_mcp_server"):
            server = func._mcp_server
            print(f"✅ Function '{func_name}' has FastMCP server: {server.name}")

            # Check tools in server
            if hasattr(server, "_tool_manager") and hasattr(
                server._tool_manager, "_tools"
            ):
                tools = server._tool_manager._tools
                print(f"   📝 Server has {len(tools)} tools: {list(tools.keys())}")
        else:
            print(f"❌ Function '{func_name}' has no _mcp_server attribute")

except Exception as e:
    print(f"❌ Error checking FastMCP servers: {e}")

print("🔚 Verification complete")
