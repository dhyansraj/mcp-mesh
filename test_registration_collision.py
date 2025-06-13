#!/usr/bin/env python3
"""Test to demonstrate the registration collision issue."""

import os

from fastmcp import FastMCP
from mcp_mesh import mesh_agent
from mcp_mesh.decorators import _SHARED_AGENT_ID

# Set test agent name
os.environ["MCP_MESH_AGENT_NAME"] = "test_agent"

server = FastMCP("collision-test")


@server.tool()
@mesh_agent(capability="cap1", version="1.0.0")
def function1():
    """First function with cap1."""
    return "Function 1"


@server.tool()
@mesh_agent(capability="cap2", version="1.0.0")
def function2():
    """Second function with cap2."""
    return "Function 2"


@server.tool()
@mesh_agent(capability="cap1", version="2.0.0")
def function3():
    """Third function also with cap1 but different version."""
    return "Function 3"


# Check what agent ID was generated
print(f"Shared agent ID: {_SHARED_AGENT_ID}")
print("\nExpected issue:")
print("- All 3 functions share the same agent_id")
print("- Each registration might overwrite the previous one")
print("- The registry would only see the last registered function")
print("\nThis breaks the capability model where:")
print("- Multiple functions can provide different capabilities")
print("- Multiple functions can provide the same capability with different versions")
