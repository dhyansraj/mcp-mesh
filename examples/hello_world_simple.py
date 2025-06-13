#!/usr/bin/env python3
"""
MCP vs MCP Mesh Demonstration: Hello World Server (Simplified)

This server demonstrates the difference between:
1. Plain MCP functions (no dependency injection)
2. MCP Mesh functions (automatic dependency injection + HTTP wrapper)

Key Demonstration:
- greet_from_mcp: Plain MCP with @server.tool() only
- greet_from_mcp_mesh: MCP Mesh with @server.tool() + @mesh_agent()
- Multi-tool agent: Multiple tools in one agent with @mesh_tool decorators

The HTTP wrapper is automatically created (enable_http=True by default)
because dependency injection requires HTTP endpoints for inter-agent communication.
stdio-based agents cannot directly communicate with each other.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent, mesh_tool


def create_hello_world_server() -> FastMCP:
    """Create a simplified Hello World demonstration server."""

    # Create FastMCP server instance
    server = FastMCP(
        name="hello-world-demo",
        instructions="Simplified demonstration server showing MCP vs MCP Mesh capabilities.",
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
        """
        if SystemAgent is None:
            return "👋 Hello from plain MCP! (No dependency injection - SystemAgent is None)"
        else:
            return f"👋 Hello from plain MCP! SystemAgent: {SystemAgent}"

    # ===== MCP MESH FUNCTION =====
    # This function uses BOTH @server.tool() AND @mesh_agent() decorators
    # Enables automatic dependency injection

    @server.tool()
    @mesh_agent(
        agent_name="hello-mesh-agent",
        capability="greeting",  # Legacy format for single capability
        dependencies=["SystemAgent"],  # Request SystemAgent dependency
        description="MCP Mesh greeting function with dependency injection",
        version="1.0.0",
        tags=["demo", "greeting"],
    )
    def greet_from_mcp_mesh(SystemAgent: Any | None = None) -> str:
        """
        MCP Mesh greeting function with dependency injection.

        This function demonstrates MCP Mesh behavior:
        - Automatic dependency injection when available
        - SystemAgent will be a proxy when dependency is resolved
        - Works with both MCP protocol and HTTP endpoints
        """
        if SystemAgent is None:
            return "👋 Hello from MCP Mesh! (SystemAgent dependency not yet available)"
        else:
            # SystemAgent is now a proxy that can make calls to the system agent
            return f"👋 Hello from MCP Mesh! SystemAgent injected: {repr(SystemAgent)}"

    # ===== MULTI-TOOL AGENT WITH DEPENDENCY INJECTION =====
    # Demonstrates multiple tools in a single agent that actually USE dependency injection
    # Auto-discovery is enabled by default, so @mesh_tool functions are automatically found

    @server.tool()
    @mesh_agent(
        agent_name="multi-tool-demo",
        dependencies=["SystemAgent"],  # This agent depends on SystemAgent
        description="Multi-tool agent with dependency injection demonstration",
        version="1.0.0",
    )
    def get_system_stats(SystemAgent: Any | None = None) -> dict[str, Any]:
        """Get system statistics using injected SystemAgent dependency."""
        base_stats = {
            "agent_type": "multi-tool-demo",
            "capabilities": ["system_info", "system_greeting", "system_farewell"],
            "status": "active",
        }

        if SystemAgent is None:
            base_stats["system_info"] = (
                "SystemAgent not available - no dependency injection yet"
            )
            base_stats["note"] = (
                "Start system_agent.py to see dependency injection work"
            )
        else:
            # Try to use the injected SystemAgent to get real system info
            try:
                # SystemAgent should have system-related capabilities
                base_stats["system_info"] = f"SystemAgent injected: {repr(SystemAgent)}"
                base_stats["dependency_status"] = "injected_successfully"
            except Exception as e:
                base_stats["system_info"] = f"SystemAgent available but error: {e}"
                base_stats["dependency_status"] = "injected_with_errors"

        return base_stats

    @server.tool()
    @mesh_tool(
        capability="system_greeting",
        description="Multi-tool greeting that uses system information",
        version="1.0.0",
    )
    def greet_with_system_info(SystemAgent: Any | None = None) -> str:
        """Provide a greeting with system information from dependency injection."""
        import datetime

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if SystemAgent is None:
            return f"👋 Hello from multi-tool agent! Time: {now} (No system info - SystemAgent not injected)"
        else:
            # Try to get system information from the injected dependency
            try:
                return f"👋 Hello from multi-tool agent! Time: {now} | SystemAgent: {repr(SystemAgent)}"
            except Exception as e:
                return f"👋 Hello from multi-tool agent! Time: {now} | SystemAgent error: {e}"

    @server.tool()
    @mesh_tool(
        capability="system_farewell",
        description="Farewell message with system uptime if available",
        version="1.0.0",
    )
    def farewell_with_system_info(SystemAgent: Any | None = None) -> str:
        """Provide a farewell message with system information."""
        if SystemAgent is None:
            return "👋 Goodbye from multi-tool agent! (No system info available - start system_agent.py to see dependency injection)"
        else:
            try:
                # Try to use SystemAgent to get system info for farewell
                return f"👋 Goodbye from multi-tool agent! SystemAgent was available: {repr(SystemAgent)}"
            except Exception as e:
                return f"👋 Goodbye from multi-tool agent! SystemAgent error: {e}"

    return server


def main():
    """Run the simplified Hello World demonstration server."""
    print("🚀 Starting MCP vs MCP Mesh Demonstration Server...")

    # Create the server
    server = create_hello_world_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Available Functions:")
    print("• greet_from_mcp - Plain MCP function (no dependency injection)")
    print("• greet_from_mcp_mesh - MCP Mesh function with dependency injection")
    print("• get_system_stats - Multi-tool agent with SystemAgent dependency")
    print("• greet_with_system_info - Multi-tool greeting using SystemAgent")
    print("• farewell_with_system_info - Multi-tool farewell using SystemAgent")

    print("\n🌐 HTTP Endpoints (auto-created by default):")
    print("• All @mesh_agent functions get HTTP endpoints automatically")
    print("• HTTP is required for dependency injection between agents")
    print("• Check logs for HTTP endpoint URLs after startup")
    print(
        "• Example: curl -X POST http://localhost:PORT/mcp -H 'Content-Type: application/json' \\"
    )
    print(
        '    -d \'{"method": "tools/call", "params": {"name": "greet_from_mcp_mesh", "arguments": {}}}\''
    )

    print("\n🔧 Test Workflow:")
    print("1. Start this server: mcp-mesh-dev start examples/hello_world_simple.py")
    print("2. Start system agent: mcp-mesh-dev start examples/system_agent.py")
    print("3. Test via HTTP endpoints or MCP clients")
    print("4. See automatic dependency injection in action!")

    print("\n📝 Server ready on stdio transport...")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
