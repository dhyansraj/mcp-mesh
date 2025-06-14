#!/usr/bin/env python3
"""
MCP vs MCP Mesh Demonstration: Hello World Server

This server perfectly demonstrates the difference between:
1. Plain MCP functions (no dependency injection)
2. MCP Mesh functions (automatic dependency injection)

Key Demonstration:
- greet_from_mcp: Plain MCP with @app.tool() only
- greet_from_mcp_mesh: MCP Mesh with @app.tool() + @mesh_agent()
- Both have SystemAgent parameter for dependency injection testing
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent, mesh_tool


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

    @server.tool()
    @mesh_agent(
        capability="greeting",  # Single capability
        dependencies=["SystemAgent_getDate"],  # Depend on flat function
        health_interval=30,
        fallback_mode=True,
        version="1.0.0",
        description="Greeting function with automatic date function dependency injection",
        tags=["demo", "dependency_injection"],
        enable_http=True,  # Enable HTTP transport
        http_port=8889,  # Different port from FastAPI DI tester
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

    @server.tool()
    @mesh_agent(
        capability="greeting",  # Single capability (new pattern)
        dependencies=[
            "SystemAgent_getDate",
            "SystemAgent_getInfo",
        ],  # Multiple flat functions
        version="2.0.0",
        tags=["demo", "kubernetes", "single-capability"],
        description="Single-capability greeting function optimized for Kubernetes",
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
            "demonstration_workflow": [
                "1. Test both endpoints (both return basic greetings)",
                "2. Start system_agent.py with mcp-mesh-dev",
                "3. Test greet_from_mcp (still basic greeting)",
                "4. Test greet_from_mcp_mesh (now with injected SystemAgent!)",
            ],
            "mesh_features": [
                "Interface-optional dependency injection",
                "Real-time service discovery",
                "Automatic parameter injection",
                "Graceful fallback behavior",
            ],
        }

    @server.tool()
    @mesh_agent(
        capability="dependency_validation",  # Single capability
        dependencies=["SystemAgent_getDate"],
        fallback_mode=True,
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

    # ===== NEW: MULTI-TOOL AGENT WITH @mesh_tool DECORATOR =====
    # This demonstrates the new @mesh_tool decorator for auto-discovery

    @mesh_agent(
        auto_discover_tools=True,  # Enable auto-discovery of @mesh_tool methods
        default_version="1.0.0",
        health_interval=30,
        description="Multi-tool greeting agent using @mesh_tool decorator",
        tags=["demo", "multi-tool", "auto-discovery"],
        enable_http=True,
        http_port=8890,
    )
    class GreetingAgent:
        """
        Multi-tool agent demonstrating @mesh_tool decorator.

        This showcases the new auto-discovery feature where tools are
        automatically found and registered from @mesh_tool decorated methods.
        """

        @server.tool()
        @mesh_tool(
            capability="personalized_greeting",
            version="2.0.0",
            dependencies=["SystemAgent_getDate"],
            tags=["greeting", "personalized"],
        )
        def greet_with_time(self, name: str, SystemAgent_getDate: Any = None) -> str:
            """Personalized greeting with current time."""
            if SystemAgent_getDate is None:
                return f"Hello {name}! (Time service unavailable)"

            try:
                current_time = SystemAgent_getDate()
                return f"Hello {name}! It's {current_time}"
            except Exception as e:
                return f"Hello {name}! (Time error: {e})"

        @server.tool()
        @mesh_tool(
            capability="farewell_message",
            dependencies=[],  # No dependencies
            tags=["farewell", "simple"],
        )
        def farewell(self, name: str) -> str:
            """Simple farewell message."""
            return f"Goodbye {name}! Thanks for trying MCP Mesh!"

        @server.tool()
        @mesh_tool(
            capability="greeting_stats",
            dependencies=["SystemAgent_getInfo"],
            tags=["stats", "info"],
        )
        def get_greeting_stats(self, SystemAgent_getInfo: Any = None) -> dict[str, Any]:
            """Get greeting statistics with system info."""
            stats = {
                "greeting_agent": "multi-tool-demo",
                "tools_available": [
                    "greet_with_time",
                    "farewell",
                    "get_greeting_stats",
                ],
                "auto_discovery": True,
                "mesh_tool_decorator": True,
            }

            if SystemAgent_getInfo is not None:
                try:
                    system_info = SystemAgent_getInfo()
                    stats["system_uptime"] = system_info.get(
                        "uptime_formatted", "unknown"
                    )
                    stats["system_date"] = system_info.get("date", "unknown")
                except Exception as e:
                    stats["system_error"] = str(e)
            else:
                stats["system_info"] = "SystemAgent not available"

            return stats

    return server


def main():
    """Run the Hello World demonstration server."""
    import asyncio
    import signal
    import threading
    import time

    # Global shutdown flag
    _shutdown_event = threading.Event()
    _fastapi_server = None

    # Setup signal handler
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        try:
            print(f"\n📍 Received signal {signum}")
            print("🛑 Shutting down gracefully...")
            print("Shutting down all services...")

            # Set shutdown flag
            _shutdown_event.set()

        except Exception:
            pass

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("🚀 Starting MCP vs MCP Mesh Demonstration Server...")

    # Create the server
    server = create_hello_world_server()

    # Start FastAPI server for DI testing in background thread
    def start_fastapi():
        """Start FastAPI server for dependency injection testing."""
        import asyncio

        import uvicorn
        from fastapi import FastAPI

        nonlocal _fastapi_server

        app = FastAPI(title="MCP Mesh DI Tester")

        @app.get("/")
        def root():
            return {
                "message": "MCP Mesh Dependency Injection Tester",
                "endpoint": "/check-di",
            }

        @app.get("/check-di")
        def check_dependency_injection():
            """Check the current state of dependency injection for all mesh functions."""
            results = {}

            # Check greet_from_mcp_mesh
            if hasattr(server, "_tool_manager") and hasattr(
                server._tool_manager, "_tools"
            ):
                for tool_name, tool_info in server._tool_manager._tools.items():
                    if tool_name in [
                        "greet_from_mcp_mesh",
                        "greet_single_capability",
                        "test_dependency_injection",
                    ]:
                        func = tool_info.fn

                        result = {
                            "has_dependencies": hasattr(
                                func, "_mesh_agent_dependencies"
                            ),
                            "dependencies_declared": getattr(
                                func, "_mesh_agent_dependencies", []
                            ),
                            "has_injection": hasattr(func, "_injected_deps"),
                            "injection_status": "not_configured",
                        }

                        if hasattr(func, "_injected_deps"):
                            deps = func._injected_deps
                            # Check for any injected dependencies (flat functions)
                            injected_deps = [
                                k for k, v in deps.items() if v is not None
                            ]

                            if injected_deps:
                                result["injection_status"] = "injected"
                                result["injected_dependencies"] = injected_deps
                                result["proxy_details"] = {}

                                # Show details for each injected dependency
                                for dep_name in injected_deps:
                                    proxy = deps[dep_name]
                                    result["proxy_details"][dep_name] = {
                                        "type": str(type(proxy).__name__),
                                        "endpoint": getattr(proxy, "_endpoint", "N/A"),
                                        "agent_id": getattr(proxy, "_agent_id", "N/A"),
                                        "status": getattr(proxy, "_status", "N/A"),
                                        "repr": str(proxy),
                                    }
                            else:
                                result["injection_status"] = "waiting_for_provider"

                        results[tool_name] = result

            # Add summary
            injected_count = sum(
                1 for r in results.values() if r.get("injection_status") == "injected"
            )

            # Test actual invocation on greet_from_mcp_mesh if it has injection
            invocation_test = None
            if (
                "greet_from_mcp_mesh" in results
                and results["greet_from_mcp_mesh"].get("injection_status") == "injected"
            ):
                try:
                    # Get the actual function
                    func = None
                    for tool_name, tool_info in server._tool_manager._tools.items():
                        if tool_name == "greet_from_mcp_mesh":
                            func = tool_info.fn
                            break

                    if func:
                        # Try to invoke it
                        result = func()
                        invocation_test = {
                            "status": "success",
                            "result": result,
                            "message": "Function successfully invoked with injected dependency!",
                        }
                except Exception as e:
                    invocation_test = {
                        "status": "error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "message": "Expected error: stdio transport cannot invoke remote services",
                        "explanation": "The SystemAgent proxy was injected, but stdio transport cannot make HTTP calls to invoke it",
                    }

            return {
                "summary": {
                    "total_functions_with_dependencies": len(results),
                    "injected": injected_count,
                    "waiting": len(results) - injected_count,
                    "message": (
                        "SystemAgent proxy is available!"
                        if injected_count > 0
                        else "No dependencies injected yet - start system_agent.py"
                    ),
                },
                "functions": results,
                "invocation_test": invocation_test,
            }

        @app.get("/health")
        def health():
            return {"status": "healthy", "service": "hello-world-di-tester"}

        # Wait a bit for MCP server to initialize
        time.sleep(2)

        print("\n🌐 Starting FastAPI DI Tester on http://localhost:8888")
        print("📍 Check dependency injection status at: http://localhost:8888/check-di")
        print(
            "💡 Refresh the endpoint after starting system_agent.py to see injection!\n"
        )

        # Create uvicorn config
        config = uvicorn.Config(
            app, host="0.0.0.0", port=8888, log_level="error", loop="asyncio"
        )
        _fastapi_server = uvicorn.Server(config)

        # Run server with graceful shutdown support
        try:
            asyncio.run(_fastapi_server.serve())
        except KeyboardInterrupt:
            pass

    # Start FastAPI in background thread
    fastapi_thread = threading.Thread(target=start_fastapi, daemon=False)
    fastapi_thread.start()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Demonstration Functions:")
    print("• greet_from_mcp - Plain MCP function (no dependency injection)")
    print("• greet_from_mcp_mesh - MCP Mesh function with dependency injection")
    print(
        "• greet_single_capability - Single capability function (Kubernetes-optimized)"
    )
    print("• greet_with_time - NEW: Multi-tool agent with @mesh_tool decorator")
    print("• farewell - NEW: Simple farewell from multi-tool agent")
    print("• get_greeting_stats - NEW: Stats with auto-discovered tools")
    print("\n🔧 Test Workflow:")
    print("1. Check DI status: curl http://localhost:8888/check-di")
    print("2. Start system_agent.py to see automatic dependency injection")
    print("3. Check again: curl http://localhost:8888/check-di")
    print("4. See SystemAgent proxy details!")
    print("\n📝 Server ready on stdio transport...")
    print("💡 Use MCP client to test functions.")
    print("🔧 Start with: mcp-mesh-dev start examples/hello_world.py")
    print("📊 Then add: mcp-mesh-dev start examples/system_agent.py")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        # Create a separate thread for the MCP server since it blocks
        def run_mcp_server():
            try:
                server.run(transport="stdio")
            except KeyboardInterrupt:
                pass
            except Exception as e:
                if not _shutdown_event.is_set():
                    print(f"❌ Server error: {e}")

        mcp_thread = threading.Thread(target=run_mcp_server, daemon=False)
        mcp_thread.start()

        # Wait for shutdown signal
        while not _shutdown_event.is_set():
            time.sleep(0.1)

        print("🛑 Shutdown signal received, stopping all services...")

        # Gracefully shutdown FastAPI server
        if _fastapi_server:
            print("Stopping FastAPI server...")
            try:
                # Create a new event loop for shutdown since we're in main thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_fastapi_server.shutdown())
                loop.close()
                print("✅ FastAPI server stopped")
            except Exception as e:
                print(f"Error stopping FastAPI server: {e}")

        # Wait for threads to complete with timeout
        print("Waiting for background threads...")
        if fastapi_thread.is_alive():
            fastapi_thread.join(timeout=2)
        if mcp_thread.is_alive():
            mcp_thread.join(timeout=2)

        print("✅ All services stopped gracefully")

    except KeyboardInterrupt:
        print("\n🛑 Hello World demo server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")
    finally:
        # Stop background event loop if still running
        try:
            from mcp_mesh.runtime.fastmcp_integration import stop_background_event_loop

            stop_background_event_loop()
            print("INFO     Stopping background event loop...")
        except Exception:
            pass


if __name__ == "__main__":
    main()
