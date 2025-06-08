#!/usr/bin/env python3
"""
System Agent for MCP Mesh Dependency Injection Demonstration

This agent provides a SystemAgent class with getDate() method that can be
automatically discovered and injected into other MCP Mesh functions.

Key Features:
- SystemAgent class decorated with @mesh_agent for automatic discovery
- getDate() method returning current system date
- Registers with MCP Mesh registry for dependency injection
- Runnable as standalone MCP server
"""

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_system_agent_server() -> FastMCP:
    """Create a SystemAgent server for dependency injection demonstration."""

    # Create FastMCP server instance
    server = FastMCP(
        name="system-agent",
        instructions="System information agent providing SystemAgent class for MCP Mesh dependency injection demonstration.",
    )

    # ===== SYSTEM AGENT CLASS =====
    # This class will be automatically discovered and injected into other mesh functions

    @mesh_agent(
        capabilities=["system_info", "date_time", "dependency_injection_demo"],
        health_interval=30,
        version="1.0.0",
        description="System information agent for dependency injection demonstration",
        tags=["system", "demo", "dependency_provider"],
        performance_profile={"response_time_ms": 10.0},
    )
    class SystemAgent:
        """
        System information agent that provides date/time services.

        This agent demonstrates MCP Mesh's automatic dependency injection:
        - Decorated with @mesh_agent for automatic discovery
        - Provides getDate() method that other agents can use
        - Automatically registers with mesh registry when started
        - Can be injected into functions that declare SystemAgent dependency
        """

        def __init__(self):
            """Initialize the SystemAgent."""
            self.agent_name = "SystemAgent"
            self.start_time = datetime.now()
            print(f"🤖 SystemAgent initialized at {self.start_time}")

        def getDate(self) -> str:
            """
            Get the current system date and time.

            This method will be called by other mesh functions that have
            SystemAgent as a dependency parameter.

            Returns:
                Current date and time as formatted string
            """
            now = datetime.now()
            return now.strftime("%B %d, %Y at %I:%M %p")

        def getUptime(self) -> str:
            """
            Get agent uptime information.

            Returns:
                Uptime since agent started
            """
            uptime = datetime.now() - self.start_time
            return f"Agent running for {uptime.total_seconds():.1f} seconds"

        def getSystemInfo(self) -> dict[str, Any]:
            """
            Get comprehensive system information.

            Returns:
                Dictionary containing system details
            """
            import os
            import platform

            return {
                "current_date": self.getDate(),
                "uptime": self.getUptime(),
                "platform": platform.system(),
                "platform_version": platform.version(),
                "python_version": platform.python_version(),
                "working_directory": os.getcwd(),
                "process_id": os.getpid(),
            }

    # Create global SystemAgent instance for mesh registration and MCP tools
    system_agent = SystemAgent()

    # ===== MCP TOOLS FOR DIRECT ACCESS =====
    # These tools provide direct access to SystemAgent functionality

    @server.tool()
    def get_current_date() -> str:
        """
        Get current system date and time via SystemAgent.

        Returns:
            Current date and time as formatted string
        """
        return system_agent.getDate()

    @server.tool()
    def get_agent_uptime() -> str:
        """
        Get SystemAgent uptime information.

        Returns:
            Uptime since agent started
        """
        return system_agent.getUptime()

    @server.tool()
    def get_full_system_info() -> dict[str, Any]:
        """
        Get comprehensive system information.

        Returns:
            Dictionary containing complete system details
        """
        return system_agent.getSystemInfo()

    @server.tool()
    def get_agent_status() -> dict[str, Any]:
        """
        Get SystemAgent status and demonstration information.

        Returns:
            Dictionary containing agent status and demo info
        """
        return {
            "agent_name": system_agent.agent_name,
            "status": "running",
            "current_date": system_agent.getDate(),
            "uptime": system_agent.getUptime(),
            "mesh_capabilities": [
                "system_info",
                "date_time",
                "dependency_injection_demo",
            ],
            "dependency_injection": {
                "provides": "SystemAgent instance",
                "available_methods": ["getDate()", "getUptime()", "getSystemInfo()"],
                "injection_target": "Functions with SystemAgent parameter",
                "demonstration": "Check hello_world.py greet_from_mcp_mesh after starting this agent",
            },
            "mesh_features": [
                "Automatic service registration",
                "Real-time dependency injection",
                "Interface-optional pattern",
                "Health monitoring with heartbeats",
            ],
        }

    # Store SystemAgent instance for access by mesh system
    # This allows the mesh registry to inject this instance into other functions
    server._system_agent = system_agent

    return server


def main():
    """Run the SystemAgent demonstration server."""
    print("🤖 Starting SystemAgent for MCP Mesh Dependency Injection Demo...")

    # Create the server
    server = create_system_agent_server()

    print(f"📡 Server name: {server.name}")
    print("🕐 SystemAgent initialized")
    print("\n🎯 SystemAgent Features:")
    print("• Automatic mesh registry registration")
    print("• Real-time dependency injection into other agents")
    print("• Provides date/time services via getDate() method")
    print("• Demonstrates interface-optional dependency pattern")
    print("\n🔗 Dependency Injection Magic:")
    print("1. This agent registers SystemAgent class with mesh registry")
    print("2. Other agents with 'SystemAgent' parameter get automatic injection")
    print(
        "3. hello_world.py greet_from_mcp_mesh will change behavior when this starts!"
    )
    print("4. Watch real-time dependency injection in action")
    print("\n📝 Available Tools:")
    print("• get_current_date - Get current date/time")
    print("• get_agent_uptime - Get agent uptime")
    print("• get_full_system_info - Get comprehensive system info")
    print("• get_agent_status - Get agent status and demo info")
    print("\n📝 Server ready on stdio transport...")
    print("💡 Test with MCP client tool calls.")
    print("🔧 Start hello_world.py first, then this agent to see injection")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print(f"\n🛑 SystemAgent stopped by user at {datetime.now()}")
    except Exception as e:
        print(f"❌ SystemAgent error: {e}")


if __name__ == "__main__":
    main()
