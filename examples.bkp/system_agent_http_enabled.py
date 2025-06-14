#!/usr/bin/env python3
"""
System Agent for MCP Mesh Dependency Injection with HTTP Enabled

This version enables HTTP endpoints for direct invocation.
"""

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_system_agent_server() -> FastMCP:
    """Create a SystemAgent demonstration server with HTTP enabled."""

    # Create FastMCP server instance
    server = FastMCP(
        name="system-agent",
        instructions="System information agent providing SystemAgent capability via HTTP.",
    )

    # Store start time for uptime calculation
    start_time = datetime.now()

    # ===== SYSTEM AGENT CAPABILITY WITH HTTP =====
    # This function provides the "SystemAgent" capability that other functions depend on

    @server.tool()
    @mesh_agent(
        capability="SystemAgent",  # This matches the dependency name in hello_world.py
        health_interval=30,
        enable_http=True,  # Enable HTTP endpoint!
        http_port=8090,  # Fixed port for SystemAgent
        version="1.0.0",
        description="HTTP-enabled system information provider for dependency injection",
        tags=["system", "demo", "dependency_provider", "http"],
    )
    def SystemAgent() -> Any:
        """
        Provide SystemAgent functionality as a capability via HTTP.

        This function returns an object-like structure that other mesh functions
        can use when they declare SystemAgent as a dependency. The returned object
        has getDate() method that dependent functions expect.

        HTTP endpoint: http://localhost:8090/mcp
        Health check: http://localhost:8090/health

        Returns:
            Object with system agent methods
        """

        class _SystemAgent:
            """Internal SystemAgent implementation."""

            def getDate(self) -> str:
                """Get the current system date and time."""
                now = datetime.now()
                return now.strftime("%B %d, %Y at %I:%M %p")

            def getUptime(self) -> str:
                """Get agent uptime information."""
                uptime = datetime.now() - start_time
                return f"Agent running for {uptime.total_seconds():.1f} seconds"

        # Return an instance that dependent functions can use
        return _SystemAgent()

    return server


def main():
    """Run the SystemAgent demonstration server with HTTP endpoints."""
    import signal
    import sys

    # Try to use improved stdio signal handler if available
    try:
        from mcp_mesh_runtime.utils.stdio_signal_handler import setup_stdio_shutdown

        setup_stdio_shutdown()
    except ImportError:
        # Fallback to basic signal handler
        def signal_handler(signum, frame):
            """Handle shutdown signals gracefully."""
            try:
                print(f"\n📍 Received signal {signum}")
                print("🛑 Shutting down gracefully...")
            except Exception:
                pass
            sys.exit(0)

        # Install signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    print("🚀 Starting SystemAgent Server with HTTP Endpoint...")

    # Create the server
    server = create_system_agent_server()

    print(f"📡 Server name: {server.name}")
    print("🔧 Capability: SystemAgent")
    print("\n🌐 HTTP Endpoint: http://localhost:8090/mcp")
    print("💓 Health Check: http://localhost:8090/health")
    print("")
    print("🎯 This agent provides:")
    print("• SystemAgent capability for dependency injection")
    print("• getDate() method that returns formatted date/time")
    print("• Automatic injection into functions declaring SystemAgent dependency")
    print("• Direct HTTP access for testing and debugging")
    print("")
    print("🔧 Test the HTTP endpoint:")
    print("curl http://localhost:8090/health")
    print("")
    print("📝 Server ready on stdio transport AND HTTP...")
    print("💡 Functions in hello_world.py will automatically receive this capability!")
    print("🛑 Press Ctrl+C to stop.")
    print("")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        try:
            print("\n🛑 SystemAgent server stopped by user.")
        except Exception:
            pass
    except SystemExit:
        pass  # Clean exit
    except Exception as e:
        try:
            print(f"❌ Server error: {e}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
