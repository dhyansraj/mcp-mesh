#!/usr/bin/env python3
"""
Hello World with HTTP - Working Version

This version ensures mcp_mesh_runtime is imported to enable HTTP features.
"""

import sys

# WORKAROUND: Force import of mcp_mesh_runtime to enable HTTP features
# This should happen automatically but currently doesn't
try:
    import mcp_mesh_runtime

    print("✅ mcp_mesh_runtime imported - HTTP features enabled")
except ImportError:
    print("❌ mcp_mesh_runtime not available - HTTP features disabled")
    print("   Install with: pip install -e packages/mcp_mesh_runtime")
    sys.exit(1)

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create a Hello World server with HTTP endpoints."""

    server = FastMCP(
        name="hello-world-http-demo",
        instructions="Hello World with working HTTP endpoints",
    )

    @server.tool()
    @mesh_agent(
        capability="greeting",
        dependencies=["SystemAgent"],
        enable_http=True,
        http_port=8081,
        health_interval=30,
        version="1.0.0",
        description="HTTP-enabled greeting with dependency injection",
    )
    def greet_from_mcp_mesh(SystemAgent: Any | None = None) -> str:
        """HTTP-enabled greeting function."""
        if SystemAgent is None:
            return "Hello from MCP Mesh (HTTP enabled)"
        else:
            try:
                current_date = SystemAgent.getDate()
                return f"Hello, its {current_date} here, what about you?"
            except Exception as e:
                return f"Hello from MCP Mesh (Error: {e})"

    @server.tool()
    def get_status() -> dict[str, Any]:
        """Get server status."""
        return {
            "server": "hello-world-http-demo",
            "http_endpoint": "http://localhost:8081",
            "health_check": "http://localhost:8081/health",
            "mcp_endpoint": "http://localhost:8081/mcp",
        }

    return server


def main():
    """Run the server."""
    print("🚀 Starting Hello World with HTTP Endpoints (Working Version)")
    print("=" * 60)

    server = create_hello_world_server()

    print(f"📡 Server: {server.name}")
    print("\n⏳ Waiting for HTTP server to start...")
    print("   (The HTTP server starts in a background thread)")

    # Give the HTTP server time to start
    import time

    time.sleep(2)

    print("\n🌐 HTTP Endpoints (if successfully started):")
    print("• Health check: http://localhost:8081/health")
    print("• MCP endpoint: http://localhost:8081/mcp")
    print("\n🔧 Test with:")
    print("curl http://localhost:8081/health")

    print("\n📝 Starting stdio server...")
    print("🛑 Press Ctrl+C to stop.\n")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")


if __name__ == "__main__":
    main()
