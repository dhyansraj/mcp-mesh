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
from mcp_mesh import mesh_agent, mesh_tool


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
            "capabilities": [
                "SystemAgent_getDate",
                "SystemAgent_getUptime",
                "SystemAgent_getInfo",
            ],
        }

    # ===== NEW: MULTI-TOOL SYSTEM AGENT WITH @mesh_tool DECORATOR =====
    # This demonstrates the new @mesh_tool decorator for modular system services

    @mesh_agent(
        auto_discover_tools=True,  # Enable auto-discovery of @mesh_tool methods
        default_version="2.0.0",
        health_interval=20,
        description="Advanced system agent using @mesh_tool decorator",
        tags=["system", "multi-tool", "advanced"],
        enable_http=True,
        http_port=8891,
    )
    class AdvancedSystemAgent:
        """
        Multi-tool system agent demonstrating @mesh_tool decorator.

        This showcases how to organize related system functions into
        a single agent with individual tool configurations.
        """

        def __init__(self):
            self.start_time = start_time
            self.call_count = 0

        @server.tool()
        @mesh_tool(
            capability="system_time", version="2.0.0", tags=["time", "date", "system"]
        )
        def get_current_time(self) -> dict[str, Any]:
            """Get current time with timezone info."""
            now = datetime.now()
            self.call_count += 1

            return {
                "current_time": now.isoformat(),
                "formatted_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "human_readable": now.strftime("%B %d, %Y at %I:%M %p"),
                "timezone": str(now.astimezone().tzinfo),
                "timestamp": now.timestamp(),
                "call_count": self.call_count,
            }

        @server.tool()
        @mesh_tool(
            capability="system_metrics",
            dependencies=["system_time"],  # Depends on time service
            tags=["metrics", "monitoring", "performance"],
        )
        def get_system_metrics(self, system_time: Any = None) -> dict[str, Any]:
            """Get comprehensive system metrics."""
            uptime = datetime.now() - self.start_time

            metrics = {
                "agent_uptime_seconds": uptime.total_seconds(),
                "agent_uptime_human": f"{uptime.total_seconds():.1f} seconds",
                "total_calls": self.call_count,
                "server_name": server.name,
                "metrics_version": "2.0.0",
            }

            # If time service is injected, get current time
            if system_time is not None:
                try:
                    time_info = system_time()
                    metrics["current_timestamp"] = time_info.get("timestamp")
                    metrics["time_service_available"] = True
                except Exception as e:
                    metrics["time_service_error"] = str(e)
                    metrics["time_service_available"] = False
            else:
                metrics["time_service_available"] = False

            return metrics

        @server.tool()
        @mesh_tool(
            capability="system_health",
            dependencies=[],  # Independent health check
            tags=["health", "status", "diagnostics"],
        )
        def check_system_health(self) -> dict[str, Any]:
            """Comprehensive system health check."""
            uptime = datetime.now() - self.start_time

            # Determine health status
            health_status = "healthy"
            if uptime.total_seconds() > 3600:  # Over 1 hour
                health_status = "excellent"
            elif uptime.total_seconds() < 10:  # Less than 10 seconds
                health_status = "starting"

            return {
                "status": health_status,
                "uptime_seconds": uptime.total_seconds(),
                "memory_usage": "simulated_low",  # In real app, use psutil
                "cpu_usage": "simulated_normal",
                "disk_space": "simulated_ok",
                "network_connectivity": "available",
                "last_check": datetime.now().isoformat(),
                "agent_version": "2.0.0",
                "multi_tool_support": True,
                "mesh_tool_decorator": True,
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
    print("🔧 Capabilities provided:")
    print("📦 Standard MCP flat functions:")
    print("• SystemAgent_getDate - Get current date and time")
    print("• SystemAgent_getUptime - Get agent uptime")
    print("• SystemAgent_getInfo - Get comprehensive system info")
    print("🆕 NEW: Multi-tool agent with @mesh_tool decorator:")
    print("• get_current_time - Advanced time with timezone info")
    print("• get_system_metrics - Comprehensive metrics with dependencies")
    print("• check_system_health - Health diagnostics")
    print("")
    print("🎯 This demonstrates both patterns:")
    print("📦 Standard MCP: Flat functions, separate tools, HTTP-enabled")
    print("🆕 Multi-tool: Class-based agents with @mesh_tool auto-discovery")
    print("• Each tool has individual capabilities and dependencies")
    print("• Automatic tool discovery from @mesh_tool decorators")
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
