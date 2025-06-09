#!/usr/bin/env python3
"""
MCP vs MCP Mesh Demonstration: Hello World Server

This server perfectly demonstrates the difference between:
1. Plain MCP functions (no dependency injection)
2. MCP Mesh functions (automatic dependency injection)

Key Demonstration:
- greet_from_mcp: Plain MCP with @app.tool() only
- greet_from_mcp_mesh: MCP Mesh with @app.tool() + @mesh_agent()
- Both have SystemAgent parameter for dependency injection testing
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create a Hello World demonstration server with MCP vs MCP Mesh functions."""

    # Create FastMCP server instance
    server = FastMCP(
        name="hello-world-demo",
        instructions="Demonstration server showing MCP vs MCP Mesh capabilities with automatic dependency injection.",
    )

    # ===== PLAIN MCP FUNCTION =====
    # This function uses ONLY @server.tool() decorator
    # No mesh integration, no dependency injection

    @server.tool()
    def greet_from_mcp(SystemAgent: Any | None = None) -> str:
        """
        Plain MCP greeting function.

        This function demonstrates standard MCP behavior:
        - No automatic dependency injection
        - SystemAgent parameter will always be None
        - Works with vanilla MCP protocol only

        Args:
            SystemAgent: Optional system agent (always None in plain MCP)

        Returns:
            Basic greeting message
        """
        if SystemAgent is None:
            return "Hello from MCP"
        else:
            # This should never happen in plain MCP
            return f"Hello, its {SystemAgent.getDate()} here, what about you?"

    # ===== MCP MESH FUNCTION =====
    # This function uses DUAL-DECORATOR pattern: @server.tool() + @mesh_agent()
    # Includes mesh integration with automatic dependency injection

    @server.tool()
    @mesh_agent(
        capabilities=["greeting", "mesh_integration"],
        dependencies=["SystemAgent"],  # Will be automatically injected when available
        health_interval=30,
        fallback_mode=True,
        version="1.0.0",
        description="Greeting function with automatic SystemAgent dependency injection",
        tags=["demo", "dependency_injection"],
    )
    def greet_from_mcp_mesh(SystemAgent: Any | None = None) -> str:
        """
        MCP Mesh greeting function with automatic dependency injection.

        This function demonstrates MCP Mesh's revolutionary capabilities:
        - Automatic dependency injection when services are available
        - Interface-optional pattern (no Protocol definitions required)
        - Real-time updates when dependencies become available/unavailable
        - Falls back gracefully when dependencies are not available

        Args:
            SystemAgent: Optional system agent (automatically injected by mesh)

        Returns:
            Enhanced greeting with system information if agent is available
        """
        if SystemAgent is None:
            return "Hello from MCP Mesh"
        else:
            # SystemAgent was automatically injected by mesh when system_agent.py started
            try:
                current_date = SystemAgent.getDate()
                return f"Hello, its {current_date} here, what about you?"
            except Exception as e:
                return f"Hello from MCP Mesh (Error getting date: {e})"

    # ===== ADDITIONAL DEMO TOOLS =====

    @server.tool()
    def get_demo_status() -> dict[str, Any]:
        """
        Get current demonstration status.

        Returns:
            Dictionary containing demo server information
        """
        from datetime import datetime

        return {
            "server_name": server.name,
            "timestamp": datetime.now().isoformat(),
            "description": "MCP vs MCP Mesh demonstration server",
            "endpoints": {
                "greet_from_mcp": "Plain MCP function (no dependency injection)",
                "greet_from_mcp_mesh": "MCP Mesh function (automatic dependency injection)",
            },
            "demonstration_workflow": [
                "1. Test both endpoints (both return basic greetings)",
                "2. Start system_agent.py with mcp-mesh-dev",
                "3. Test greet_from_mcp (still basic greeting)",
                "4. Test greet_from_mcp_mesh (now with injected SystemAgent!)",
            ],
            "mesh_features": [
                "Interface-optional dependency injection",
                "Real-time service discovery",
                "Automatic parameter injection",
                "Graceful fallback behavior",
            ],
        }

    @server.tool()
    @mesh_agent(
        capabilities=["testing", "dependency_validation"],
        dependencies=["SystemAgent"],
        fallback_mode=True,
    )
    def test_dependency_injection(SystemAgent: Any | None = None) -> dict[str, Any]:
        """
        Test and report current dependency injection status.

        Args:
            SystemAgent: Optional system agent for testing

        Returns:
            Dictionary containing dependency injection test results
        """
        if SystemAgent is None:
            return {
                "dependency_injection_status": "inactive",
                "SystemAgent_available": False,
                "message": "No SystemAgent dependency injected",
                "recommendation": "Start system_agent.py to see dependency injection in action",
            }
        else:
            try:
                date_result = SystemAgent.getDate()
                return {
                    "dependency_injection_status": "active",
                    "SystemAgent_available": True,
                    "SystemAgent_response": date_result,
                    "message": "Dependency injection working perfectly!",
                    "mesh_magic": "SystemAgent was automatically discovered and injected",
                }
            except Exception as e:
                return {
                    "dependency_injection_status": "error",
                    "SystemAgent_available": True,
                    "error": str(e),
                    "message": "SystemAgent injected but method call failed",
                }

    return server


def main():
    """Run the Hello World demonstration server."""
    print("🚀 Starting MCP vs MCP Mesh Demonstration Server...")

    # Create the server
    server = create_hello_world_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Demonstration Functions:")
    print("• greet_from_mcp - Plain MCP function (no dependency injection)")
    print("• greet_from_mcp_mesh - MCP Mesh function (automatic dependency injection)")
    print("\n🔧 Test Workflow:")
    print("1. Both functions return basic greetings initially")
    print("2. Start system_agent.py to see automatic dependency injection")
    print("3. greet_from_mcp_mesh behavior changes automatically!")
    print("4. greet_from_mcp remains unchanged (plain MCP)")
    print("\n📝 Server ready on stdio transport...")
    print("💡 Use MCP client to test functions.")
    print("🔧 Start with: mcp_mesh_dev start examples/hello_world.py")
    print("📊 Then add: mcp_mesh_dev start examples/system_agent.py")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Hello World demo server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")


if __name__ == "__main__":
    main()
