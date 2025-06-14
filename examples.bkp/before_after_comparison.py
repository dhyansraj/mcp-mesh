#!/usr/bin/env python3
"""
Before/After Comparison: Converting MCP to MCP Mesh

This file shows exactly what changes when you convert existing MCP code to MCP Mesh.
The only changes needed are:
1. Import mcp_mesh
2. Add @mesh_agent decorator
3. Add dependency parameters to functions that need them

That's it! No signal handlers, no complex setup, no framework changes.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent  # 1. Add this import


def create_server() -> FastMCP:
    """Create a server showing before/after comparison."""

    server = FastMCP(name="before-after-demo")

    # ===== BEFORE: Plain MCP =====

    @server.tool()
    def calculate_basic(
        a: float = 5.0, b: float = 3.0, operation: str = "add"
    ) -> dict[str, Any]:
        """Basic calculator function - plain MCP, no dependencies."""
        if operation == "add":
            result = a + b
        elif operation == "multiply":
            result = a * b
        else:
            result = None

        return {
            "result": result,
            "operation": operation,
            "inputs": {"a": a, "b": b},
            "type": "standalone_calculation",
        }

    # ===== AFTER: MCP Mesh =====

    @server.tool()
    @mesh_agent(  # 2. Add this decorator
        agent_name="enhanced-calculator",
        dependencies=["SystemAgent"],  # 3. Declare dependencies
        description="Calculator with system integration",
    )
    def calculate_enhanced(
        a: float = 5.0,
        b: float = 3.0,
        operation: str = "add",
        SystemAgent: Any | None = None,  # 4. Add dependency parameters
    ) -> dict[str, Any]:
        """Enhanced calculator - same logic, but with dependency injection!"""
        # Same calculation logic as before
        if operation == "add":
            result = a + b
        elif operation == "multiply":
            result = a * b
        else:
            result = None

        # Enhanced response with dependency info
        response = {
            "result": result,
            "operation": operation,
            "inputs": {"a": a, "b": b},
            "type": "mesh_calculation_with_dependencies",
        }

        # The magic: now we can use injected dependencies!
        if SystemAgent is None:
            response["system_info"] = (
                "No system integration (SystemAgent not available)"
            )
            response["mesh_status"] = "standalone_mode"
        else:
            response["system_info"] = (
                f"System integration available: {repr(SystemAgent)}"
            )
            response["mesh_status"] = "connected_to_mesh"
            # Could make HTTP calls via SystemAgent proxy here!

        return response

    return server


# ===== MAIN FUNCTION: No changes needed! =====

if __name__ == "__main__":
    print("🚀 Before/After Comparison Demo")
    print("\n📋 This shows how simple it is to convert MCP to MCP Mesh:")
    print("• calculate_basic - Original MCP function (unchanged)")
    print("• calculate_enhanced - Same function + @mesh_agent decorator")
    print("\n💡 Only changes needed:")
    print("1. Import mcp_mesh")
    print("2. Add @mesh_agent decorator")
    print("3. Add dependency parameters to functions")
    print("4. No signal handlers, no complex setup!")

    server = create_server()
    print(f"\n📡 Server: {server.name}")
    print("🛑 Press Ctrl+C to stop.")
    server.run(transport="stdio")
