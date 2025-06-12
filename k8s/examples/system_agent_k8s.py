#!/usr/bin/env python3
"""
SystemAgent Server - Kubernetes Version

Provides standard date/time capabilities that other agents can use.
This is the Kubernetes-optimized version that runs without stdio transport.

Key Features:
- Provides SystemAgent_getDate, SystemAgent_getUptime, SystemAgent_getInfo capabilities
- Functions are automatically discoverable via mesh
- HTTP-enabled for cross-process communication
- No stdio transport needed
"""

import os
import time
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
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
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
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
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
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
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

    return server


def main():
    """Run the SystemAgent server in Kubernetes mode."""
    import logging
    import signal
    import sys

    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Setup signal handler
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        try:
            logger.info(f"📍 Received signal {signum}")
            logger.info("🛑 Shutting down gracefully...")
        except Exception:
            pass
        sys.exit(0)

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("🚀 Starting SystemAgent Server (Kubernetes mode)...")

    # Create the server
    server = create_system_agent_server()

    logger.info(f"📡 Server name: {server.name}")
    logger.info("🔧 Capabilities provided (standard MCP flat functions):")
    logger.info("• SystemAgent_getDate - Get current date and time")
    logger.info("• SystemAgent_getUptime - Get agent uptime")
    logger.info("• SystemAgent_getInfo - Get comprehensive system info")
    logger.info("")
    logger.info("💡 HTTP endpoints are automatically created by enable_http=True")
    logger.info(
        f"🌐 HTTP Server: http://{os.environ.get('MCP_MESH_HTTP_HOST', '0.0.0.0')}:{os.environ.get('MCP_MESH_HTTP_PORT', '8080')}"
    )
    logger.info(
        "📊 Registry URL: "
        + os.environ.get("MCP_MESH_REGISTRY_URL", "http://mcp-mesh-registry:8080")
    )
    logger.info("")
    logger.info("✅ Server running in Kubernetes mode (no stdio transport)")
    logger.info(
        "🔄 The decorators will handle registration and HTTP setup automatically"
    )

    # Keep the service running
    # Let the decorators handle everything - just sleep forever
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("🛑 Server shutdown requested")
    except SystemExit:
        pass  # Clean exit


if __name__ == "__main__":
    main()
