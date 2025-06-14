#!/usr/bin/env python3
"""
MCP Mesh Hello World Example - FIXED VERSION

This example demonstrates the core concepts of MCP Mesh using string dependencies
that work with the current implementation (like FileOperations does).
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import McpMeshAgent, mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create a simple Hello World server demonstrating MCP Mesh features."""

    server = FastMCP(
        name="hello-world-fixed",
        instructions="Fixed demonstration of MCP vs MCP Mesh capabilities with dependency injection.",
    )

    # ===== PLAIN MCP FUNCTION =====
    # Uses only @server.tool() - no mesh features

    @server.tool()
    def hello_mcp() -> str:
        """Basic MCP greeting with no dependency injection."""
        return "👋 Hello from plain MCP!"

    # ===== MESH FUNCTION WITH SIMPLE TYPING =====
    # Uses string dependencies like the working FileOperations

    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=["date_service"],  # ✅ String dependency - like FileOperations
        description="Simple greeting with date dependency",
    )
    def hello_mesh_simple(date_service: Any = None) -> str:
        """
        MCP Mesh greeting with simple typing.

        Uses Any type for maximum flexibility - works with any proxy implementation.
        Great for prototyping and simple use cases.
        """
        if date_service is None:
            return "👋 Hello from MCP Mesh! (Date service not available yet)"

        try:
            # Call the injected function - proxy implements __call__()
            current_date = date_service()
            return f"👋 Hello from MCP Mesh! Today is {current_date}"
        except Exception as e:
            return f"👋 Hello from MCP Mesh! (Error getting date: {e})"

    # ===== MESH FUNCTION WITH TYPED INTERFACE =====
    # Uses string dependencies only (no dict dependencies)

    @server.tool()
    @mesh_agent(
        capability="advanced_greeting",
        dependencies=["info_service"],  # ✅ Simple string dependency
        description="Advanced greeting with info service dependency",
    )
    def hello_mesh_typed(info_service: McpMeshAgent | None = None) -> str:
        """
        MCP Mesh greeting with info service dependency.

        Uses simple string dependency that works with current implementation.
        """
        if info_service is None:
            return "👋 Hello from MCP Mesh! (info service not available yet)"

        try:
            # This will call the injected info service
            system_info = info_service.call()
            if isinstance(system_info, dict):
                uptime = system_info.get("uptime_formatted", "unknown")
                server_name = system_info.get("server_name", "unknown")
                return (
                    f"👋 Hello from MCP Mesh! Server: {server_name}, Uptime: {uptime}"
                )
            else:
                return f"👋 Hello from MCP Mesh! Info: {system_info}"
        except Exception as e:
            return f"👋 Hello from MCP Mesh! (Error getting info: {e})"

    # ===== DEPENDENCY TEST FUNCTION =====
    # Uses only string dependencies like FileOperations

    @server.tool()
    @mesh_agent(
        capability="dependency_test",
        dependencies=["date_service", "info_service"],  # ✅ Only string dependencies
        description="Test multiple string dependencies",
    )
    def test_dependencies(
        date_service: Any = None,
        info_service: McpMeshAgent | None = None,
    ) -> dict[str, Any]:
        """
        Test function showing multiple string dependencies.

        Uses the same pattern as working FileOperations with string dependencies.
        """
        result = {
            "test_name": "string_dependency_demo",
            "date_service": "not_available",
            "info_service": "not_available",
        }

        # Test simple Any type dependency
        if date_service is not None:
            try:
                date = date_service()  # Direct call
                result["date_service"] = f"available: {date}"
            except Exception as e:
                result["date_service"] = f"error: {e}"

        # Test typed dependency
        if info_service is not None:
            try:
                info = info_service.call()
                result["info_service"] = f"available: {info}"
            except Exception as e:
                result["info_service"] = f"error: {e}"

        return result

    return server


def main():
    """Run the Hello World server."""
    print("🚀 Starting Hello World MCP Mesh Server (FIXED)...")

    server = create_hello_world_server()

    print(f"📡 Server: {server.name}")
    print("\n🎯 Available Functions:")
    print("• hello_mcp - Plain MCP (no dependencies)")
    print("• hello_mesh_simple - Simple dependency (Any typing)")
    print("• hello_mesh_typed - Info service dependency")
    print("• test_dependencies - Multiple string dependencies")

    print("\n🔧 Fixed Implementation:")
    print("✅ Uses string dependencies like working FileOperations")
    print("✅ No dictionary dependencies (fixes unhashable dict error)")
    print("✅ Same pattern as successful unit tests")

    print("\n📝 Ready on stdio transport...")
    print("🛑 Press Ctrl+C to stop.\n")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Hello World server stopped.")


if __name__ == "__main__":
    main()
