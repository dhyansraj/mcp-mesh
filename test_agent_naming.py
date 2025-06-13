#!/usr/bin/env python3
"""Test script to demonstrate agent naming behavior in mcp-mesh-dev"""

import os

from mcp_mesh import mesh_agent


# Test 1: Default agent name (uses function name)
@mesh_agent(capability="test_default")
def my_function():
    """This agent will be named 'my_function'"""
    return "Hello from my_function"


# Test 2: Explicit agent name in decorator
@mesh_agent(capability="test_explicit", agent_name="custom_agent_name")
def another_function():
    """This agent will be named 'custom_agent_name'"""
    return "Hello from custom_agent_name"


# Test 3: Check if environment variable is used (it's not)
print(
    f"Environment variable MCP_MESH_AGENT_NAME: {os.environ.get('MCP_MESH_AGENT_NAME', 'NOT SET')}"
)

# Show the actual agent names from metadata
print("\nAgent names from metadata:")
print(
    f"my_function._mesh_metadata['agent_name'] = {my_function._mesh_metadata['agent_name']}"
)
print(
    f"another_function._mesh_metadata['agent_name'] = {another_function._mesh_metadata['agent_name']}"
)

if __name__ == "__main__":
    print(
        "\nNote: The --agent-name flag sets MCP_MESH_AGENT_NAME env var, but it's not used by the Python runtime."
    )
    print(
        "To override agent names, use the agent_name parameter in the @mesh_agent decorator."
    )
