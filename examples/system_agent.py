#!/usr/bin/env python3
"""
System Agent for MCP Mesh Dependency Injection Demonstration

This agent provides a SystemAgent capability that can be automatically
discovered and injected into other MCP Mesh functions.

Key Features:
- Provides "SystemAgent" capability via @mesh_agent decorator
- Functions declaring SystemAgent dependency will receive this capability
- Demonstrates the new single-capability pattern
- Runnable as standalone MCP server
"""

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_system_agent_server() -> FastMCP:
    """Create a SystemAgent demonstration server with mesh integration."""

    # Create FastMCP server instance
    server = FastMCP(
        name="system-agent",
        instructions="System information agent providing SystemAgent capability for MCP Mesh dependency injection demonstration.",
    )

    # Store start time for uptime calculation
    start_time = datetime.now()

    # ===== SYSTEM AGENT CAPABILITIES =====
    # In standard MCP, we provide flat functions, not class methods
    # Each function is a separate tool that can be called independently

    @server.tool()
    @mesh_agent(
        capability="SystemAgent_getDate",  # Flat function naming convention
        enable_http=True,
        health_interval=30,
        version="1.0.0",
        description="Get current system date and time",
        tags=["system", "date", "time"],
    )
    def SystemAgent_getDate() -> str:
        """
        Get the current system date and time.
        
        This is a flat function following standard MCP patterns.
        In MCP, tools are always functions, not class methods.
        
        Returns:
            Formatted date and time string
        """
        now = datetime.now()
        return now.strftime("%B %d, %Y at %I:%M %p")

    @server.tool()
    @mesh_agent(
        capability="SystemAgent_getUptime",  # Flat function naming convention
        enable_http=True,
        health_interval=30,
        version="1.0.0",
        description="Get system agent uptime",
        tags=["system", "uptime", "monitoring"],
    )
    def SystemAgent_getUptime() -> str:
        """
        Get agent uptime information.
        
        Returns:
            String describing how long the agent has been running
        """
        uptime = datetime.now() - start_time
        return f"Agent running for {uptime.total_seconds():.1f} seconds"

    @server.tool()
    @mesh_agent(
        capability="SystemAgent_getInfo",  # Additional useful function
        enable_http=True,
        health_interval=30,
        version="1.0.0",
        description="Get comprehensive system information",
        tags=["system", "info"],
    )
    def SystemAgent_getInfo() -> dict[str, Any]:
        """
        Get comprehensive system information.
        
        Returns:
            Dictionary containing system date, uptime, and other info
        """
        uptime = datetime.now() - start_time
        return {
            "date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": f"{uptime.total_seconds():.1f} seconds",
            "server_name": server.name,
            "version": "1.0.0",
            "capabilities": ["SystemAgent_getDate", "SystemAgent_getUptime", "SystemAgent_getInfo"]
        }

    return server


def main():
    """Run the SystemAgent demonstration server."""
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

    print("🚀 Starting SystemAgent Server...")

    # Create the server
    server = create_system_agent_server()

    print(f"📡 Server name: {server.name}")
    print("🔧 Capabilities provided (standard MCP flat functions):")
    print("• SystemAgent_getDate - Get current date and time")
    print("• SystemAgent_getUptime - Get agent uptime")
    print("• SystemAgent_getInfo - Get comprehensive system info")
    print("")
    print("🎯 This demonstrates standard MCP architecture:")
    print("• Flat functions (no class methods)")
    print("• Each capability is a separate tool")
    print("• HTTP-enabled for cross-process communication")
    print("")
    print("📝 Server ready on stdio transport...")
    print("💡 Other agents can now call these functions via HTTP!")
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
