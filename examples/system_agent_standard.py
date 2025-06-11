#!/usr/bin/env python3
"""
System Agent - Standard MCP Implementation

This is a proper MCP server that exposes individual tools,
not objects with methods. Each capability is a separate tool.
"""

import platform
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_system_agent_server() -> FastMCP:
    """Create a SystemAgent server with standard MCP tools."""

    server = FastMCP(
        name="system-agent",
        instructions="System information agent providing various system utilities.",
    )

    # Store start time for uptime calculation
    start_time = datetime.now()

    @server.tool()
    @mesh_agent(
        capability="SystemAgent.getDate",
        enable_http=True,
        health_interval=30,
        version="1.0.0",
        description="Get current system date and time",
        tags=["system", "date", "time"],
    )
    def SystemAgent_getDate() -> str:
        """
        Get the current system date and time.

        Returns:
            Formatted date string
        """
        now = datetime.now()
        return now.strftime("%B %d, %Y at %I:%M %p")

    @server.tool()
    @mesh_agent(
        capability="SystemAgent.getUptime",
        enable_http=True,
        version="1.0.0",
        description="Get agent uptime information",
        tags=["system", "uptime"],
    )
    def SystemAgent_getUptime() -> str:
        """
        Get agent uptime information.

        Returns:
            Uptime string
        """
        uptime = datetime.now() - start_time
        return f"Agent running for {uptime.total_seconds():.1f} seconds"

    @server.tool()
    @mesh_agent(
        capability="SystemAgent.getSystemInfo",
        enable_http=True,
        version="1.0.0",
        description="Get system information",
        tags=["system", "info"],
    )
    def SystemAgent_getSystemInfo() -> dict[str, Any]:
        """
        Get system information.

        Returns:
            Dictionary with system details
        """
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "timestamp": datetime.now().isoformat(),
        }

    @server.tool()
    def get_status() -> dict[str, Any]:
        """Get agent status (not mesh-enabled, just for testing)."""
        return {
            "agent": "system-agent",
            "status": "healthy",
            "capabilities": [
                "SystemAgent.getDate",
                "SystemAgent.getUptime",
                "SystemAgent.getSystemInfo",
            ],
            "start_time": start_time.isoformat(),
        }

    return server


def main():
    """Run the SystemAgent server."""
    import signal
    import sys

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n📍 Received signal {signum}")
        print("🛑 Shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("🚀 Starting SystemAgent Server (Standard MCP)...")

    server = create_system_agent_server()

    print(f"📡 Server name: {server.name}")
    print("🔧 Available tools:")
    print("  • SystemAgent_getDate - Get current date/time")
    print("  • SystemAgent_getUptime - Get agent uptime")
    print("  • SystemAgent_getSystemInfo - Get system information")
    print("  • get_status - Get agent status")
    print("")
    print("📝 This is a standard MCP server with flat tools.")
    print("💡 Each tool can be called independently by MCP clients.")
    print("🛑 Press Ctrl+C to stop.")
    print("")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 SystemAgent server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")


if __name__ == "__main__":
    main()
