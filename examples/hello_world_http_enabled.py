#!/usr/bin/env python3
"""
MCP vs MCP Mesh Demonstration: Hello World Server with HTTP Enabled

This version has enable_http=True on the mesh decorators, allowing direct HTTP invocation.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_hello_world_server() -> FastMCP:
    """Create a Hello World demonstration server with HTTP-enabled mesh functions."""

    # Create FastMCP server instance
    server = FastMCP(
        name="hello-world-demo",
        instructions="Demonstration server with HTTP-enabled MCP Mesh functions.",
    )

    # ===== PLAIN MCP FUNCTION =====
    # This function uses ONLY @server.tool() decorator
    # No mesh integration, no dependency injection, no HTTP

    @server.tool()
    def greet_from_mcp(SystemAgent: Any | None = None) -> str:
        """
        Plain MCP greeting function.

        This function demonstrates standard MCP behavior:
        - No automatic dependency injection
        - SystemAgent parameter will always be None
        - Works with vanilla MCP protocol only
        - No HTTP endpoint

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

    # ===== MCP MESH FUNCTION WITH HTTP =====
    # This function uses DUAL-DECORATOR pattern: @server.tool() + @mesh_agent()
    # Includes mesh integration with automatic dependency injection AND HTTP endpoint

    @server.tool()
    @mesh_agent(
        capability="greeting",  # Single capability
        dependencies=["SystemAgent"],  # Will be automatically injected when available
        health_interval=30,
        fallback_mode=True,
        enable_http=True,  # Enable HTTP endpoint!
        http_port=8081,  # Fixed port for this function
        version="1.0.0",
        description="HTTP-enabled greeting function with automatic SystemAgent dependency injection",
        tags=["demo", "dependency_injection", "http"],
    )
    def greet_from_mcp_mesh(SystemAgent: Any | None = None) -> str:
        """
        HTTP-enabled MCP Mesh greeting function with automatic dependency injection.

        This function demonstrates MCP Mesh capabilities with HTTP:
        - Automatic dependency injection when services are available
        - HTTP endpoint at http://localhost:8081/mcp
        - Health check at http://localhost:8081/health
        - Real-time updates when dependencies become available/unavailable
        - Falls back gracefully when dependencies are not available

        Args:
            SystemAgent: Optional system agent (automatically injected by mesh)

        Returns:
            Enhanced greeting with system information if agent is available
        """
        if SystemAgent is None:
            return "Hello from MCP Mesh (HTTP-enabled)"
        else:
            # SystemAgent was automatically injected by mesh when system_agent.py started
            try:
                current_date = SystemAgent.getDate()
                return f"Hello, its {current_date} here, what about you?"
            except Exception as e:
                return f"Hello from MCP Mesh (Error getting date: {e})"

    # ===== SINGLE CAPABILITY PATTERN WITH HTTP =====
    # Each function provides exactly ONE capability with HTTP endpoint

    @server.tool()
    @mesh_agent(
        capability="greeting",  # Single capability (new pattern)
        dependencies=["SystemAgent"],
        enable_http=True,  # Enable HTTP endpoint!
        http_port=8082,  # Different port for this function
        version="2.0.0",
        tags=["demo", "kubernetes", "single-capability", "http"],
        description="HTTP-enabled single-capability greeting function",
    )
    def greet_single_capability(SystemAgent: Any | None = None) -> str:
        """
        HTTP-enabled greeting function using new single-capability pattern.

        This demonstrates:
        - Single capability pattern
        - HTTP endpoint at http://localhost:8082/mcp
        - Health check at http://localhost:8082/health
        - Automatic dependency injection

        Args:
            SystemAgent: Optional system agent (automatically injected by mesh)

        Returns:
            Greeting message with system info if available
        """
        base_greeting = "Hello from HTTP-enabled single-capability function"

        if SystemAgent is not None:
            try:
                current_date = SystemAgent.getDate()
                return f"{base_greeting} - Date from SystemAgent: {current_date}"
            except Exception as e:
                return f"{base_greeting} - SystemAgent error: {e}"
        else:
            return f"{base_greeting} - No SystemAgent available"

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
            "description": "MCP vs MCP Mesh demonstration server with HTTP endpoints",
            "endpoints": {
                "greet_from_mcp": "Plain MCP function (no HTTP)",
                "greet_from_mcp_mesh": "HTTP-enabled at http://localhost:8081/mcp",
                "greet_single_capability": "HTTP-enabled at http://localhost:8082/mcp",
            },
            "health_checks": {
                "greet_from_mcp_mesh": "http://localhost:8081/health",
                "greet_single_capability": "http://localhost:8082/health",
            },
            "demonstration_workflow": [
                "1. Functions are accessible via stdio AND HTTP",
                "2. Test HTTP: curl http://localhost:8081/health",
                "3. Start system_agent.py to see dependency injection",
                "4. Both stdio and HTTP calls will have SystemAgent injected!",
            ],
        }

    @server.tool()
    @mesh_agent(
        capability="dependency_validation",  # Single capability
        dependencies=["SystemAgent"],
        fallback_mode=True,
        enable_http=True,  # Enable HTTP endpoint!
        http_port=8083,  # Another port
    )
    def test_dependency_injection(SystemAgent: Any | None = None) -> dict[str, Any]:
        """
        Test and report current dependency injection status (HTTP-enabled).

        Args:
            SystemAgent: Optional system agent for testing

        Returns:
            Dictionary containing dependency injection test results
        """
        if SystemAgent is None:
            return {
                "dependency_injection_status": "inactive",
                "SystemAgent_available": False,
                "message": "No SystemAgent dependency injected",
                "recommendation": "Start system_agent.py to see dependency injection in action",
                "http_endpoint": "http://localhost:8083/mcp",
            }
        else:
            try:
                date_result = SystemAgent.getDate()
                return {
                    "dependency_injection_status": "active",
                    "SystemAgent_available": True,
                    "SystemAgent_response": date_result,
                    "message": "Dependency injection working perfectly!",
                    "mesh_magic": "SystemAgent was automatically discovered and injected",
                    "http_endpoint": "http://localhost:8083/mcp",
                }
            except Exception as e:
                return {
                    "dependency_injection_status": "error",
                    "SystemAgent_available": True,
                    "error": str(e),
                    "message": "SystemAgent injected but method call failed",
                }

    return server


def main():
    """Run the Hello World demonstration server with HTTP endpoints."""
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

    print("🚀 Starting MCP vs MCP Mesh Demonstration Server with HTTP Endpoints...")

    # Create the server
    server = create_hello_world_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Demonstration Functions:")
    print("• greet_from_mcp - Plain MCP function (no HTTP)")
    print("• greet_from_mcp_mesh - HTTP-enabled MCP Mesh function")
    print("• greet_single_capability - HTTP-enabled single capability function")
    print("\n🌐 HTTP Endpoints:")
    print("• http://localhost:8081/mcp - greet_from_mcp_mesh")
    print("• http://localhost:8082/mcp - greet_single_capability")
    print("• http://localhost:8083/mcp - test_dependency_injection")
    print("\n💓 Health Checks:")
    print("• http://localhost:8081/health")
    print("• http://localhost:8082/health")
    print("• http://localhost:8083/health")
    print("\n🔧 Test HTTP endpoints:")
    print("curl http://localhost:8081/health")
    print(
        "curl -X POST http://localhost:8081/mcp -H 'Content-Type: application/json' -d '{...}'"
    )
    print("\n📝 Server ready on stdio transport AND HTTP...")
    print("💡 Use MCP client for stdio or HTTP client for direct invocation.")
    print("🔧 Start with: python examples/hello_world_http_enabled.py")
    print("📊 Then add: python examples/system_agent.py (also with HTTP if desired)")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        try:
            print("\n🛑 Hello World demo server stopped by user.")
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
