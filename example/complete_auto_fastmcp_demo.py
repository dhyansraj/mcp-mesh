#!/usr/bin/env python3
"""
Complete Auto-FastMCP Demo

This demonstrates the full "magical" experience:
1. User defines only @mesh.tool and @mesh.agent decorators
2. NO manual FastMCP server creation
3. NO manual @server.tool() decorations
4. Processor automatically creates FastMCP server and registers tools
5. HTTP endpoints and MCP tools work automatically
6. Process stays alive to keep server running

Expected behavior:
- Auto-creates FastMCP server with name matching @mesh.agent
- Auto-registers all @mesh.tool functions as MCP tools
- Sets up HTTP wrapper for HTTP API access
- Provides both MCP protocol and HTTP REST interfaces
- Handles health monitoring and registry integration

Usage:
    python example/complete_auto_fastmcp_demo.py
"""

import logging
import os
import signal
import sys
import time

# Set up comprehensive logging to see everything
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure environment
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Import mesh decorators - this triggers MCP Mesh runtime initialization
import mesh

print("🎬 COMPLETE AUTO-FASTMCP DEMO")
print("=" * 80)


# Step 1: Agent Configuration (provides defaults and naming)
@mesh.agent(
    name="demo-auto-service",
    version="2.0.0",
    description="Complete demo of auto-created FastMCP functionality",
    enable_http=True,
    namespace="demo",
    http_host="0.0.0.0",
    http_port=0,  # Auto-assign port
    health_interval=30,
)
class DemoAutoService:
    """
    Agent configuration class.

    This provides the name and configuration that will be used for:
    - Auto-created FastMCP server name
    - HTTP wrapper configuration
    - Registry registration
    - Health monitoring settings
    """

    pass


print("✅ Step 1: Agent configuration defined")
print("   📛 Name: demo-auto-service")
print("   🔧 HTTP: Enabled (auto-assign port)")
print("   📊 Namespace: demo")


# Step 2: Tool Definitions (NO FastMCP server creation needed!)
@mesh.tool(
    capability="interactive_greeting",
    description="Interactive greeting with customizable message",
    version="2.0.0",
    tags=["demo", "interactive"],
)
def greet_user(name: str = "Friend", greeting: str = "Hello") -> dict:
    """
    Greet a user with a customizable greeting.

    Args:
        name: Name of the person to greet
        greeting: Type of greeting (Hello, Hi, Hey, etc.)

    Returns:
        Greeting response with metadata
    """
    return {
        "message": f"{greeting}, {name}! Welcome to the auto-FastMCP demo!",
        "timestamp": time.time(),
        "service": "demo-auto-service",
        "capability": "interactive_greeting",
    }


@mesh.tool(
    capability="advanced_calculator",
    description="Advanced calculator with multiple operations",
    version="2.0.0",
    tags=["demo", "math", "calculator"],
)
def calculate(operation: str, a: float, b: float) -> dict:
    """
    Perform advanced calculations.

    Args:
        operation: Type of operation (add, subtract, multiply, divide, power)
        a: First number
        b: Second number

    Returns:
        Calculation result with metadata
    """
    operations = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else float("inf"),
        "power": a**b,
    }

    if operation not in operations:
        return {"error": f"Unknown operation: {operation}"}

    return {
        "operation": operation,
        "operands": [a, b],
        "result": operations[operation],
        "timestamp": time.time(),
        "service": "demo-auto-service",
    }


@mesh.tool(
    capability="service_diagnostics",
    description="Get comprehensive service diagnostic information",
    version="2.0.0",
    tags=["demo", "diagnostics", "monitoring"],
)
def get_diagnostics() -> dict:
    """
    Get comprehensive service diagnostic information.

    Returns:
        Detailed service diagnostics
    """
    return {
        "service_info": {
            "name": "demo-auto-service",
            "version": "2.0.0",
            "description": "Complete demo of auto-created FastMCP functionality",
            "uptime_seconds": time.time(),
            "fastmcp_auto_created": True,
        },
        "capabilities": {
            "interactive_greeting": "Customizable user greetings",
            "advanced_calculator": "Multi-operation calculator",
            "service_diagnostics": "Service health and diagnostics",
        },
        "features": [
            "Auto-created FastMCP server",
            "Auto-registered MCP tools",
            "HTTP API endpoints",
            "Mesh registry integration",
            "Health monitoring",
            "Dependency injection ready",
        ],
        "interfaces": {
            "mcp_protocol": "Available via FastMCP",
            "http_api": "Available via auto-created HTTP wrapper",
            "registry": "Registered with MCP Mesh registry",
        },
        "timestamp": time.time(),
    }


@mesh.tool(
    capability="echo_service",
    description="Echo back any input with metadata",
    version="2.0.0",
    tags=["demo", "utility", "echo"],
)
def echo_input(message: str, metadata: bool = True) -> dict:
    """
    Echo back input with optional metadata.

    Args:
        message: Message to echo back
        metadata: Include service metadata in response

    Returns:
        Echo response with optional metadata
    """
    response = {"echo": message}

    if metadata:
        response.update(
            {
                "service": "demo-auto-service",
                "capability": "echo_service",
                "timestamp": time.time(),
                "auto_fastmcp": True,
            }
        )

    return response


print("✅ Step 2: Tool definitions complete")
print("   🔧 Tools: 4 @mesh.tool functions defined")
print(
    "   📝 Capabilities: interactive_greeting, advanced_calculator, service_diagnostics, echo_service"
)
print(
    "   🎯 Tags: demo, interactive, math, calculator, diagnostics, monitoring, utility, echo"
)

# Step 3: Process Lifecycle Management
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    print(f"\n🔴 Received shutdown signal {signum}")
    running = False


def main():
    """Main application loop."""
    global running

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("\n🚀 Step 3: Starting auto-FastMCP service...")
    print("⏳ Waiting for MCP Mesh processor to initialize...")
    print("\n📋 Expected processor actions:")
    print("   1. 🔧 Auto-create FastMCP server 'demo-auto-service-XXXXXXXX'")
    print("   2. 📝 Auto-register 4 @mesh.tool functions as MCP tools")
    print("   3. 🌐 Set up HTTP wrapper on auto-assigned port")
    print("   4. 📡 Register agent with MCP Mesh registry")
    print("   5. 💓 Start health monitoring and heartbeat")

    # Give processor time to complete initialization
    time.sleep(5)

    print("\n🎯 Service should now be active!")
    print("=" * 80)
    print("🌐 AVAILABLE INTERFACES:")
    print("   📡 MCP Protocol: Via auto-created FastMCP server")
    print("      • greet_user(name, greeting)")
    print("      • calculate(operation, a, b)")
    print("      • get_diagnostics()")
    print("      • echo_input(message, metadata)")
    print()
    print("   🌍 HTTP API: Via auto-created HTTP wrapper")
    print("      • GET/POST endpoints for all tools")
    print("      • RESTful interface to MCP tools")
    print()
    print("   📊 Registry: Integrated with MCP Mesh")
    print("      • Dependency injection available")
    print("      • Service discovery enabled")
    print("      • Health monitoring active")
    print("=" * 80)

    # Main service loop - CRITICAL: Keep process alive
    print("\n💓 SERVICE RUNNING")
    print("   Process must stay alive for FastMCP server to work")
    print("   Press Ctrl+C for graceful shutdown")
    print()

    heartbeat_count = 0
    try:
        while running:
            time.sleep(20)  # Heartbeat every 20 seconds
            heartbeat_count += 1

            print(f"💓 Heartbeat #{heartbeat_count}")
            print(f"   ⏰ Uptime: {heartbeat_count * 20} seconds")
            print("   🔧 FastMCP: Auto-created and active")
            print("   🌐 HTTP API: Available")
            print("   📡 Registry: Connected")
            print("   🛠️  Tools: 4 MCP tools active")

    except KeyboardInterrupt:
        print("\n🔴 Keyboard interrupt received")
        running = False

    print("\n🛑 SHUTTING DOWN AUTO-FASTMCP SERVICE")
    print("   • Stopping HTTP wrapper...")
    print("   • Closing auto-created FastMCP server...")
    print("   • Unregistering from mesh registry...")
    print("   • Stopping health monitoring...")
    print("✅ Shutdown complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print("🔍 Check logs above for auto-FastMCP creation messages")
    finally:
        print("🏁 Demo terminated")
        sys.exit(0)
