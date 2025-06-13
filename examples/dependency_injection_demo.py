#!/usr/bin/env python3
"""
Dependency Injection Demo

This example shows how to actually USE injected dependencies to make calls
to other agents via HTTP proxies.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_di_demo_server() -> FastMCP:
    """Create a server that demonstrates actual dependency injection usage."""

    server = FastMCP(name="di-demo")

    @server.tool()
    @mesh_agent(
        agent_name="calculator-client",
        dependencies=["SystemAgent"],  # Depends on SystemAgent
        description="Calculator that uses SystemAgent for operations",
    )
    def calculate_with_system(
        operation: str = "add",
        a: float = 5.0,
        b: float = 3.0,
        SystemAgent: Any | None = None,
    ) -> dict[str, Any]:
        """
        Perform calculations using the injected SystemAgent dependency.

        This shows how dependency injection actually works:
        1. When SystemAgent is None: No dependency available yet
        2. When SystemAgent is a proxy: Can make HTTP calls to SystemAgent
        """
        result = {
            "operation": operation,
            "a": a,
            "b": b,
            "dependency_status": (
                "not_available" if SystemAgent is None else "available"
            ),
        }

        if SystemAgent is None:
            # No dependency injection yet
            result["message"] = (
                "SystemAgent not available - dependency injection not working yet"
            )
            result["note"] = "Start system_agent.py to enable dependency injection"

            # Fall back to local calculation
            if operation == "add":
                result["result"] = a + b
                result["calculated_by"] = "local_fallback"
            elif operation == "multiply":
                result["result"] = a * b
                result["calculated_by"] = "local_fallback"
            else:
                result["result"] = None
                result["error"] = f"Unsupported operation: {operation}"
        else:
            # SystemAgent is injected! Try to use it
            result["message"] = "SystemAgent available - attempting to use dependency"
            result["system_agent_info"] = repr(SystemAgent)

            try:
                # Try to call a method on the SystemAgent proxy
                # Note: This will only work if SystemAgent actually has these methods
                # and the HTTP proxy is working correctly
                if hasattr(SystemAgent, "calculate") and callable(
                    SystemAgent.calculate
                ):
                    # Make the actual HTTP call via the proxy
                    system_result = SystemAgent.calculate(operation=operation, a=a, b=b)
                    result["result"] = system_result
                    result["calculated_by"] = "system_agent_via_http"
                elif hasattr(SystemAgent, "add") and operation == "add":
                    # Try individual operation methods
                    system_result = SystemAgent.add(a=a, b=b)
                    result["result"] = system_result
                    result["calculated_by"] = "system_agent_add_via_http"
                else:
                    # SystemAgent is available but doesn't have the methods we need
                    result["result"] = a + b if operation == "add" else a * b
                    result["calculated_by"] = "local_fallback"
                    result["note"] = (
                        "SystemAgent available but doesn't have calculation methods"
                    )

            except Exception as e:
                # HTTP call failed or other error
                result["error"] = f"Failed to call SystemAgent: {e}"
                result["result"] = a + b if operation == "add" else a * b
                result["calculated_by"] = "local_fallback_after_error"

        return result

    @server.tool()
    @mesh_agent(
        agent_name="system-info-client",
        dependencies=["SystemAgent"],
        description="Client that gets system information via dependency injection",
    )
    def get_system_info_via_di(SystemAgent: Any | None = None) -> dict[str, Any]:
        """
        Get system information using the injected SystemAgent.

        This demonstrates how to actually make calls through the dependency injection proxy.
        """
        if SystemAgent is None:
            return {
                "status": "no_dependency",
                "message": "SystemAgent not injected - start system_agent.py",
                "system_info": None,
            }

        try:
            # Try different methods that SystemAgent might have
            info = {}

            # Try to get system information via the proxy
            if hasattr(SystemAgent, "get_system_info"):
                info["system_info"] = SystemAgent.get_system_info()

            if hasattr(SystemAgent, "get_uptime"):
                info["uptime"] = SystemAgent.get_uptime()

            if hasattr(SystemAgent, "get_memory_usage"):
                info["memory"] = SystemAgent.get_memory_usage()

            # If we got any info, dependency injection is working!
            if info:
                return {
                    "status": "dependency_injection_working",
                    "message": "Successfully called SystemAgent via HTTP proxy",
                    "proxy_info": repr(SystemAgent),
                    "data": info,
                }
            else:
                return {
                    "status": "dependency_available_no_methods",
                    "message": "SystemAgent proxy available but no known methods found",
                    "proxy_info": repr(SystemAgent),
                    "available_methods": [
                        attr for attr in dir(SystemAgent) if not attr.startswith("_")
                    ],
                }

        except Exception as e:
            return {
                "status": "dependency_injection_error",
                "message": f"SystemAgent available but call failed: {e}",
                "proxy_info": repr(SystemAgent),
                "error": str(e),
            }

    return server


def main():
    """Run the dependency injection demo."""
    print("🚀 Starting Dependency Injection Demo...")

    server = create_di_demo_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Demo Functions:")
    print("• calculate_with_system - Shows DI with fallback behavior")
    print("• get_system_info_via_di - Shows actual HTTP proxy calls")

    print("\n🔧 Test Workflow:")
    print(
        "1. Start this demo: mcp-mesh-dev start examples/dependency_injection_demo.py"
    )
    print("2. Test functions (they'll show 'no dependency' state)")
    print("3. Start system agent: mcp-mesh-dev start examples/system_agent.py")
    print("4. Test functions again (they'll show dependency injection working!)")
    print("5. Watch HTTP calls being made via the injected proxies")

    print("\n📝 Server ready. Press Ctrl+C to stop.\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
