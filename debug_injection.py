#!/usr/bin/env python3
"""
Debug why dependency injection isn't working
"""

import os

os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8080"
os.environ["MCP_MESH_DEBUG"] = "true"

# Force import of runtime
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

# Create a test to see what happens
server = FastMCP(name="debug-test")

print("=== Debugging Dependency Injection ===\n")


# Create a simple test function
@server.tool()
@mesh_agent(capability="test", dependencies=["SystemAgent"], health_interval=5)
def test_function(SystemAgent=None):
    """Test function to debug injection."""
    print(f"test_function called with SystemAgent={SystemAgent}")
    if SystemAgent:
        return f"Got SystemAgent: {type(SystemAgent)}"
    else:
        return "No SystemAgent injected"


print("1. Function created and decorated")
print(f"   Function object: {test_function}")
print(f"   Function name: {test_function.__name__}")

# Check if it's wrapped
if hasattr(test_function, "__wrapped__"):
    print(f"   Has __wrapped__: {test_function.__wrapped__}")

# Check mesh metadata
if hasattr(test_function, "_mesh_decorator_instance"):
    print("   Has mesh decorator instance: Yes")
    decorator = test_function._mesh_decorator_instance
    print(f"   Dependencies: {decorator.dependencies}")

# Check what FastMCP sees
print("\n2. What FastMCP registered:")
if hasattr(server, "_tools"):
    for tool_name, tool_info in server._tools.items():
        print(f"   Tool: {tool_name}")
        print(f"   Function: {tool_info['func']}")
        print(f"   Is same as decorated?: {tool_info['func'] is test_function}")

# The issue might be that @server.tool() is applied BEFORE @mesh_agent
# So FastMCP registers the unwrapped function!

print("\n3. Testing with reversed decorator order...")

# Create another test with decorators reversed
server2 = FastMCP(name="debug-test2")


@mesh_agent(capability="test2", dependencies=["SystemAgent"], health_interval=5)
@server2.tool()  # Apply server.tool AFTER mesh_agent
def test_function2(SystemAgent=None):
    """Test with reversed decorators."""
    print(f"test_function2 called with SystemAgent={SystemAgent}")
    if SystemAgent:
        return f"Got SystemAgent: {type(SystemAgent)}"
    else:
        return "No SystemAgent injected"


print("\n4. Checking reversed decorator function:")
print(f"   Function object: {test_function2}")

if hasattr(server2, "_tools"):
    for tool_name, tool_info in server2._tools.items():
        print(f"   Tool: {tool_name}")
        print(f"   Function: {tool_info['func']}")

print("\n💡 INSIGHT: The decorator order matters!")
print("   @server.tool() captures the function BEFORE @mesh_agent wraps it")
print("   So FastMCP calls the original function, not the wrapped one!")
