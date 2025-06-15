#!/usr/bin/env python3
"""
Example: Auto-created FastMCP server with @mesh.tool only

This demonstrates the "magical" experience where:
1. User only defines @mesh.tool and @mesh.agent
2. MCP Mesh processor automatically creates FastMCP server
3. All @mesh.tool functions become MCP tools + HTTP endpoints
4. Process stays alive to keep the server running

Usage:
    python example_auto_fastmcp.py

Then the processor will:
- Create FastMCP server automatically
- Register tools with mesh registry
- Set up HTTP wrapper for HTTP API
- Keep running with heartbeat monitoring
"""

import logging
import signal
import sys
import time

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Import mesh decorators
import mesh


# Step 1: Define agent configuration
@mesh.agent(
    name="auto-fastmcp-service",
    version="1.0.0",
    description="Service with automatically created FastMCP server",
    enable_http=True,
    namespace="demo",
    http_host="0.0.0.0",
    http_port=0,  # Auto-assign port
)
class AutoFastMCPAgent:
    """Agent configuration for auto-created FastMCP service."""

    pass


# Step 2: Define tools - NO manual FastMCP server creation needed!
@mesh.tool(capability="greeting", description="Say hello to someone", version="1.0.0")
def hello_world(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}! This came from an auto-created FastMCP server."


@mesh.tool(capability="math_add", description="Add two numbers", version="1.0.0")
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@mesh.tool(capability="status_check", description="Get service status", version="1.0.0")
def get_status() -> dict:
    """Get the current service status."""
    return {
        "service": "auto-fastmcp-service",
        "status": "running",
        "timestamp": time.time(),
        "fastmcp_auto_created": True,
        "tools_count": 3,
    }


@mesh.tool(
    capability="service_info",
    description="Get detailed service information",
    version="1.0.0",
)
def get_service_info() -> dict:
    """Get detailed information about this service."""
    return {
        "name": "auto-fastmcp-service",
        "version": "1.0.0",
        "description": "Service with automatically created FastMCP server",
        "capabilities": ["greeting", "math_add", "status_check", "service_info"],
        "features": [
            "Auto-created FastMCP server",
            "HTTP API endpoints",
            "MCP tool interface",
            "Mesh registry integration",
            "Dependency injection ready",
            "Health monitoring",
        ],
    }


# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
    running = False


if __name__ == "__main__":
    print("🚀 Starting Auto-FastMCP Example Service...")
    print("=" * 60)
    print("📋 Configuration:")
    print("   • Agent Name: auto-fastmcp-service")
    print("   • Tools: 4 (@mesh.tool functions)")
    print("   • FastMCP: Auto-created by processor")
    print("   • HTTP: Enabled (auto-assigned port)")
    print("   • Registry: Will register automatically")
    print("=" * 60)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination

    print("⏳ Waiting for MCP Mesh processor to initialize...")
    print("   The processor will:")
    print("   1. 🔧 Auto-create FastMCP server 'auto-fastmcp-service-XXXXXXXX'")
    print("   2. 📝 Register all @mesh.tool functions as MCP tools")
    print("   3. 🌐 Set up HTTP wrapper with auto-assigned port")
    print("   4. 📡 Register with mesh registry")
    print("   5. 💓 Start health monitoring/heartbeat")
    print()

    # Give the processor time to initialize and setup everything
    time.sleep(3)

    print("✅ Service should now be running!")
    print("🔍 What to expect in the logs:")
    print("   • 'Auto-created FastMCP server' message")
    print("   • HTTP wrapper started on 0.0.0.0:PORT")
    print("   • Agent registered with mesh registry")
    print("   • Health monitoring tasks created")
    print()
    print("🌐 Available interfaces:")
    print("   • MCP tools: hello_world, add_numbers, get_status, get_service_info")
    print("   • HTTP API: Available on auto-assigned port")
    print("   • Registry: Registered with dependency injection support")
    print()
    print("📍 Service Status: RUNNING (Press Ctrl+C to stop)")
    print("=" * 60)

    # Keep the process alive so FastMCP server doesn't die
    heartbeat_counter = 0
    while running:
        try:
            time.sleep(30)  # Wait 30 seconds between status updates
            heartbeat_counter += 1

            print(f"💓 Heartbeat #{heartbeat_counter} - Service still running...")
            print(f"   ⏰ Uptime: {heartbeat_counter * 30} seconds")
            print("   🔧 FastMCP server: Active")
            print("   🌐 HTTP endpoints: Available")
            print("   📡 Registry connection: Active")

        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            signal_handler(signal.SIGINT, None)
            break

    print("\n🛑 Shutting down Auto-FastMCP Example Service...")
    print("   • Stopping HTTP wrapper...")
    print("   • Closing FastMCP server...")
    print("   • Unregistering from mesh registry...")
    print("✅ Shutdown complete.")

    # Exit cleanly
    sys.exit(0)
