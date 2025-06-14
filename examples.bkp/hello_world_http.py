#!/usr/bin/env python3
"""
Hello World with HTTP Endpoints Enabled

This is a modified version that enables HTTP endpoints for direct invocation.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create Hello World server with HTTP endpoints enabled."""

    server = FastMCP(
        name="hello-world-http",
        instructions="Hello World with HTTP endpoints for direct invocation",
    )

    # Plain MCP function (no HTTP)
    @server.tool()
    def greet_from_mcp(SystemAgent: Any | None = None) -> str:
        """Plain MCP function - no mesh, no HTTP."""
        if SystemAgent is None:
            return "Hello from MCP"
        else:
            return f"Hello, its {SystemAgent.getDate()} here, what about you?"

    # MCP Mesh function with HTTP enabled
    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=["SystemAgent"],
        enable_http=True,  # Enable HTTP wrapper!
        http_port=8081,  # Fixed port (or use 0 for auto)
        health_interval=30,
        version="1.0.0",
        description="HTTP-enabled greeting with dependency injection",
    )
    def greet_from_mcp_mesh(SystemAgent: Any | None = None) -> str:
        """HTTP-enabled mesh greeting function."""
        if SystemAgent is None:
            return "Hello from MCP Mesh (HTTP)"
        else:
            try:
                current_date = SystemAgent.getDate()
                return f"Hello, its {current_date} here, what about you?"
            except Exception as e:
                return f"Hello from MCP Mesh (Error: {e})"

    # Another HTTP-enabled function
    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=["SystemAgent"],
        enable_http=True,
        http_port=8082,  # Different port
        version="2.0.0",
    )
    def greet_single_capability(SystemAgent: Any | None = None) -> str:
        """Single capability HTTP function."""
        base = "Hello from HTTP-enabled function"
        if SystemAgent:
            try:
                return f"{base} - Date: {SystemAgent.getDate()}"
            except Exception as e:
                return f"{base} - Error: {e}"
        return f"{base} - No SystemAgent"

    return server


def main():
    """Run the HTTP-enabled server."""
    import os

    # Force HTTP mode
    os.environ["MCP_MESH_HTTP_ENABLED"] = "true"

    print("🚀 Starting Hello World with HTTP Endpoints")
    print("=" * 60)

    server = create_hello_world_server()

    print(f"📡 Server: {server.name}")
    print("\n🌐 HTTP Endpoints:")
    print("• greet_from_mcp_mesh: http://localhost:8081/mcp")
    print("• greet_single_capability: http://localhost:8082/mcp")
    print("\n💓 Health Checks:")
    print("• http://localhost:8081/health")
    print("• http://localhost:8082/health")
    print("\n📝 Ready on stdio transport...")
    print("🔧 HTTP endpoints starting automatically...")
    print("🛑 Press Ctrl+C to stop.\n")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")


if __name__ == "__main__":
    main()
