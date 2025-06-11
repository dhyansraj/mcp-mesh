#!/usr/bin/env python3
"""Test script to verify mcp-mesh installation."""

import sys

try:
    # Test basic imports
    print("Testing mcp-mesh imports...")

    from mcp_mesh import mesh_agent

    print("✓ Successfully imported mesh_agent decorator")

    from mcp_mesh import DecoratorRegistry

    print("✓ Successfully imported DecoratorRegistry")

    from mcp_mesh.runtime.shared.exceptions import MCPError, MCPErrorCode

    print("✓ Successfully imported exception classes")

    from mcp_mesh.runtime.shared.types import HealthStatus

    print("✓ Successfully imported type classes")

    # Test decorator functionality
    @mesh_agent(
        capability="test_function",
        description="Test function for installation verification",
    )
    def test_function(name: str) -> str:
        return f"Hello, {name}!"

    print("✓ Successfully decorated a function with @mesh_agent")

    # Test function execution
    result = test_function("World")
    print(f"✓ Function executed successfully: {result}")

    # Check registry
    agents = DecoratorRegistry.get_mesh_agents()
    print(f"✓ Found {len(agents)} registered mesh agents")

    print("\n✅ All tests passed! mcp-mesh is installed correctly.")

except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
