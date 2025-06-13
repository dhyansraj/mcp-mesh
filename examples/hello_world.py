#!/usr/bin/env python3
"""
MCP Mesh Hello World Example

This example demonstrates the core concepts of MCP Mesh:
1. Basic MCP tools (no dependency injection)
2. MCP Mesh tools with automatic dependency injection
3. Hybrid typing support for development flexibility

Start this agent, then start system_agent.py to see dependency injection in action!
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import McpMeshAgent, mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create a simple Hello World server demonstrating MCP Mesh features."""

    server = FastMCP(
        name="hello-world",
        instructions="Simple demonstration of MCP vs MCP Mesh capabilities with dependency injection.",
    )

    # ===== PLAIN MCP FUNCTION =====
    # Uses only @server.tool() - no mesh features

    @server.tool()
    def hello_mcp() -> str:
        """Basic MCP greeting with no dependency injection."""
        return "👋 Hello from plain MCP!"

    # ===== MESH FUNCTION WITH SIMPLE TYPING =====
    # Uses Any type for maximum simplicity and flexibility

    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=["date_service"],
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
    # Uses McpMeshAgent type for better IDE support and type safety

    @server.tool()
    @mesh_agent(
        capability="advanced_greeting",
        dependencies=[
            {
                "capability": "info",
                "tags": ["system", "general"],
            }  # Tag-based dependency!
        ],
        description="Advanced greeting with smart tag-based dependency resolution",
    )
    def hello_mesh_typed(info: McpMeshAgent | None = None) -> str:
        """
        MCP Mesh greeting with smart tag-based dependency resolution.

        This requests "info" capability with "system" + "general" tags.
        Registry will match SystemAgent_getInfo (not get_disk_info) based on tags!
        """
        if info is None:
            return "👋 Hello from smart MCP Mesh! (info service not available yet)"

        try:
            # This will call the general system info (not disk info) due to smart tag matching!
            system_info = info.call()
            uptime = system_info.get("uptime_formatted", "unknown")
            server_name = system_info.get("server_name", "unknown")
            return (
                f"👋 Hello from smart MCP Mesh! Server: {server_name}, Uptime: {uptime}"
            )
        except Exception as e:
            return f"👋 Hello from smart MCP Mesh! (Error getting info: {e})"

    # ===== DEPENDENCY TEST FUNCTION =====
    # Shows multiple dependencies with different typing approaches

    @server.tool()
    @mesh_agent(
        capability="dependency_test",
        dependencies=[
            "date_service",  # Simple string dependency
            {
                "capability": "info",
                "tags": ["system", "disk"],
            },  # Tag-based: will get DISK info!
        ],
        description="Test hybrid dependencies: simple + tag-based resolution",
    )
    def test_dependencies(
        date_service: Any = None,
        info: McpMeshAgent | None = None,  # This will get the DISK info service!
    ) -> dict[str, Any]:
        """
        Test function showing hybrid dependency resolution.

        Demonstrates both simple string and tag-based dependencies:
        - date_service: simple string dependency
        - info with [system,disk] tags: will get disk info (not general info)!
        """
        result = {
            "test_name": "smart_dependency_demo",
            "date_service": "not_available",
            "disk_info_service": "not_available",  # This should get DISK info, not general info!
        }

        # Test simple Any type dependency
        if date_service is not None:
            try:
                date = date_service()  # Direct call
                result["date_service"] = f"available: {date}"
            except Exception as e:
                result["date_service"] = f"error: {e}"

        # Test tag-based dependency - should get DISK info service
        if info is not None:
            try:
                disk_info = (
                    info.call()
                )  # This should return disk/OS info, not general system info
                info_type = disk_info.get("info_type", "unknown")
                result["disk_info_service"] = (
                    f"available: {info_type} (smart tag matching worked!)"
                )
            except Exception as e:
                result["disk_info_service"] = f"error: {e}"

        return result

    return server


def main():
    """Run the Hello World server."""
    print("🚀 Starting Hello World MCP Mesh Server...")

    server = create_hello_world_server()

    print(f"📡 Server: {server.name}")
    print("\n🎯 Available Functions:")
    print("• hello_mcp - Plain MCP (no dependencies)")
    print("• hello_mesh_simple - Simple dependency (Any typing)")
    print("• hello_mesh_typed - Smart tag-based dependency [system,general]")
    print("• test_dependencies - Mixed: simple + tag-based [system,disk]")

    print("\n🔧 Smart Matching Demo:")
    print("1. Start this: mcp-mesh-dev start examples/hello_world.py")
    print("2. Start system: mcp-mesh-dev start examples/system_agent.py")
    print("3. hello_mesh_typed gets general info (tags: [system,general])")
    print("4. test_dependencies gets disk info (tags: [system,disk])")
    print("5. Same 'info' capability, different services based on tags!")

    print("\n📝 Ready on stdio transport...")
    print("🛑 Press Ctrl+C to stop.\n")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Hello World server stopped.")


if __name__ == "__main__":
    main()
