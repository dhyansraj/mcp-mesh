#!/usr/bin/env python3
"""
MCP vs MCP Mesh Demonstration: Hello World Server (Kubernetes version)

This is the Kubernetes-optimized version that runs without stdio transport.
The mesh decorators with enable_http=True will automatically create HTTP endpoints.
"""

import os
from typing import Any

import mesh
from mcp.server.fastmcp import FastMCP


def create_hello_world_server() -> FastMCP:
    """Create a Hello World demonstration server with MCP vs MCP Mesh functions."""

    # Create FastMCP server instance
    server = FastMCP(
        name="hello-world-demo",
        instructions="Demonstration server showing MCP vs MCP Mesh capabilities with automatic dependency injection.",
    )

    # ===== PLAIN MCP FUNCTION =====
    # This function uses ONLY @server.tool() decorator
    # No mesh integration, no dependency injection

    @server.tool()
    def greet_from_mcp(SystemAgent: Any | None = None) -> str:
        """
        Plain MCP greeting function.

        This function demonstrates standard MCP behavior:
        - No automatic dependency injection
        - SystemAgent parameter will always be None
        - Works with vanilla MCP protocol only

        Args:
            SystemAgent: Optional system agent (always None in plain MCP)

        Returns:
            Basic greeting message
        """
        if SystemAgent is None:
            return "Hello from MCP"
        else:
            # This should never happen in plain MCP
            return f"Hello, its {SystemAgent.getDate()} here, what about you?"

    # ===== MCP MESH FUNCTION =====
    # This function uses DUAL-DECORATOR pattern: @server.tool() + @mesh_agent()
    # Includes mesh integration with automatic dependency injection

    @mesh.tool(
        capability="greeting_with_date",  # Unique capability name
        dependencies=["SystemAgent_getDate"],  # Depend on flat function
        health_interval=30,
        fallback_mode=True,
        version="1.0.0",
        description="Greeting function with automatic date function dependency injection",
        tags=["demo", "dependency_injection"],
        enable_http=True,  # Enable HTTP transport
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    )
    def greet_from_mcp_mesh(SystemAgent_getDate: Any | None = None) -> str:
        """
        MCP Mesh greeting function with automatic dependency injection.

        This function demonstrates MCP Mesh's revolutionary capabilities:
        - Automatic dependency injection when services are available
        - Interface-optional pattern (no Protocol definitions required)
        - Real-time updates when dependencies become available/unavailable
        - Falls back gracefully when dependencies are not available

        Args:
            SystemAgent_getDate: Optional date function (automatically injected by mesh)

        Returns:
            Enhanced greeting with system information if date function is available
        """
        if SystemAgent_getDate is None:
            return "Hello from MCP Mesh"
        else:
            # SystemAgent_getDate was automatically injected by mesh when system_agent.py started
            try:
                # In flat function style, we call the function directly
                current_date = SystemAgent_getDate()
                return f"Hello, its {current_date} here, what about you?"
            except Exception as e:
                return f"Hello from MCP Mesh (Error getting date: {e})"

    # ===== NEW SINGLE CAPABILITY PATTERN (KUBERNETES-OPTIMIZED) =====
    # Each function provides exactly ONE capability for better organization

    @mesh.tool(
        capability="greeting_with_info",  # Unique capability name
        dependencies=[
            "SystemAgent_getDate",
            "SystemAgent_getInfo",
        ],  # Multiple flat functions
        version="2.0.0",
        tags=["demo", "kubernetes", "single-capability"],
        description="Single-capability greeting function optimized for Kubernetes",
        enable_http=True,
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    )
    def greet_single_capability(
        SystemAgent_getDate: Any | None = None, SystemAgent_getInfo: Any | None = None
    ) -> str:
        """
        Greeting function using new single-capability pattern.

        This demonstrates the preferred pattern for Kubernetes deployments:
        - Each function provides exactly ONE capability
        - Easier to scale (one pod can handle one capability)
        - Better organization in registry (capability tree structure)
        - More efficient service discovery

        Args:
            SystemAgent_getDate: Optional date function (automatically injected by mesh)
            SystemAgent_getInfo: Optional info function (automatically injected by mesh)

        Returns:
            Greeting message with system info if available
        """
        base_greeting = "Hello from single-capability function"

        # Demonstrate using multiple flat function dependencies
        parts = [base_greeting]

        if SystemAgent_getDate is not None:
            try:
                current_date = SystemAgent_getDate()
                parts.append(f"Date: {current_date}")
            except Exception as e:
                parts.append(f"Date error: {e}")

        if SystemAgent_getInfo is not None:
            try:
                info = SystemAgent_getInfo()
                parts.append(f"Uptime: {info.get('uptime_formatted', 'unknown')}")
            except Exception as e:
                parts.append(f"Info error: {e}")

        return " - ".join(parts)

    # ===== ADDITIONAL DEMO TOOLS =====

    @server.tool()
    def get_demo_status() -> dict[str, Any]:
        """
        Get current demonstration status.

        Returns:
            Dictionary containing demo server information
        """
        from datetime import datetime

        return {
            "server_name": server.name,
            "timestamp": datetime.now().isoformat(),
            "description": "MCP vs MCP Mesh demonstration server",
            "endpoints": {
                "greet_from_mcp": "Plain MCP function (no dependency injection)",
                "greet_from_mcp_mesh": "MCP Mesh function with dependency injection",
                "greet_single_capability": "Single capability function (Kubernetes-optimized)",
            },
            "mesh_features": [
                "Interface-optional dependency injection",
                "Real-time service discovery",
                "Automatic parameter injection",
                "Graceful fallback behavior",
            ],
        }

    @mesh.tool(
        capability="dependency_validation",  # Single capability
        dependencies=["SystemAgent_getDate"],
        fallback_mode=True,
        enable_http=True,
        http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    )
    def test_dependency_injection(
        SystemAgent_getDate: Any | None = None,
    ) -> dict[str, Any]:
        """
        Test and report current dependency injection status.

        Args:
            SystemAgent_getDate: Optional date function for testing

        Returns:
            Dictionary containing dependency injection test results
        """
        if SystemAgent_getDate is None:
            return {
                "dependency_injection_status": "inactive",
                "SystemAgent_getDate_available": False,
                "message": "No date function dependency injected",
                "recommendation": "Start system_agent.py to see dependency injection in action",
            }
        else:
            try:
                date_result = SystemAgent_getDate()
                return {
                    "dependency_injection_status": "active",
                    "SystemAgent_getDate_available": True,
                    "date_function_response": date_result,
                    "message": "Dependency injection working perfectly!",
                    "mesh_magic": "SystemAgent_getDate was automatically discovered and injected",
                }
            except Exception as e:
                return {
                    "dependency_injection_status": "error",
                    "SystemAgent_getDate_available": True,
                    "error": str(e),
                    "message": "Date function injected but call failed",
                }

    return server


def main():
    """Run the Hello World demonstration server in Kubernetes mode."""
    import logging
    import signal
    import sys
    import time

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

    logger.info("🚀 Starting MCP vs MCP Mesh Demonstration Server (Kubernetes mode)...")

    # Create the server
    server = create_hello_world_server()

    logger.info(f"📡 Server name: {server.name}")
    logger.info("🎯 Demonstration Functions:")
    logger.info("• greet_from_mcp - Plain MCP function (no dependency injection)")
    logger.info("• greet_from_mcp_mesh - MCP Mesh function with dependency injection")
    logger.info(
        "• greet_single_capability - Single capability function (Kubernetes-optimized)"
    )
    logger.info("• test_dependency_injection - Test dependency injection status")
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
