#!/usr/bin/env python3
"""
MCP Mesh Hello World Example with FastMCP Integration

This example demonstrates the hybrid FastMCP + MCP Mesh approach:
1. FastMCP decorators (@app.tool) for familiar MCP development
2. MCP Mesh decorators (@mesh.tool) for dependency injection and orchestration
3. Hybrid typing support for development flexibility
4. Pure simplicity - just dual decorators, no manual setup!

Start this agent, then start system_agent.py to see dependency injection in action!
"""

from typing import Any

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Hello World Service")


# ===== MESH FUNCTION WITH SIMPLE TYPING =====
# Uses Any type for maximum simplicity and flexibility


@app.tool()
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],
    description="Simple greeting with date dependency",
)
async def hello_mesh_simple(date_service: Any = None) -> str:
    """
    MCP Mesh greeting with simple typing.

    Uses Any type for maximum flexibility - works with any proxy implementation.
    Great for prototyping and simple use cases.
    """
    if date_service is None:
        return "👋 Hello from MCP Mesh! (Date service not available yet)"

    try:
        # Call the injected function - proxy implements __call__()
        current_date = await date_service()
        return f"👋 Hello from MCP Mesh! Today is {current_date}"
    except Exception as e:
        return f"👋 Hello from MCP Mesh! (Error getting date: {e})"


# ===== MESH FUNCTION WITH TYPED INTERFACE =====
# Uses mesh.McpMeshAgent type for better IDE support and type safety


@app.tool()
@mesh.tool(
    capability="advanced_greeting",
    dependencies=[
        {
            "capability": "info",
            "tags": ["system", "general"],
        }  # Tag-based dependency!
    ],
    description="Advanced greeting with smart tag-based dependency resolution",
)
async def hello_mesh_typed(info: mesh.McpMeshAgent | None = None) -> str:
    """
    MCP Mesh greeting with smart tag-based dependency resolution.

    This requests "info" capability with "system" + "general" tags.
    Registry will match SystemAgent_getInfo (not get_disk_info) based on tags!
    """
    if info is None:
        return "👋 Hello from smart MCP Mesh! (info service not available yet)"

    try:
        # This will call the general system info (not disk info) due to smart tag matching!
        system_info = await info()
        uptime = system_info.get("uptime_formatted", "unknown")
        server_name = system_info.get("server_name", "unknown")
        return f"👋 Hello from smart MCP Mesh! Server: {server_name}, Uptime: {uptime}"
    except Exception as e:
        return f"👋 Hello from smart MCP Mesh! (Error getting info: {e})"


# ===== SELF-DEPENDENCY TEST =====
# Tests that self-dependencies properly inject nested cross-agent dependencies


@app.tool()
@mesh.tool(
    capability="self_dep_test",
    dependencies=["advanced_greeting"],  # Self-dependency: same agent!
    description="Test self-dependency with nested cross-agent dependency",
)
async def test_self_dependency(
    advanced_greeting: mesh.McpMeshAgent | None = None,
) -> dict[str, Any]:
    """
    Test self-dependency injection with nested dependencies.

    This tool depends on 'advanced_greeting' which is in the SAME agent (hello_world).
    'advanced_greeting' in turn depends on 'info' from system_agent (cross-agent).

    Test chain:
        test_self_dependency (hello_world)
            → [SELF-DEP via wrapper] advanced_greeting (hello_world)
                → [CROSS-DEP via HTTP] info (system_agent)

    If self-dependency uses the WRAPPER (not original function), then:
    - advanced_greeting's 'info' parameter will be injected
    - The call to system_agent will work

    If self-dependency uses the ORIGINAL function:
    - advanced_greeting's 'info' parameter will be None
    - The response will say "info service not available"
    """
    result = {
        "test_name": "self_dependency_with_nested_cross_agent",
        "self_dep_target": "advanced_greeting",
        "nested_dep": "info (from system_agent)",
        "advanced_greeting_result": "not_available",
        "test_passed": False,
    }

    if advanced_greeting is None:
        result["error"] = "advanced_greeting not injected (self-dep failed)"
        return result

    try:
        # Call advanced_greeting - this goes through SelfDependencyProxy
        # If wrapper is used: info will be injected, we get system info
        # If original is used: info will be None, we get "not available" message
        greeting = await advanced_greeting()
        result["advanced_greeting_result"] = greeting

        # Check if the nested dependency worked
        if "not available" in greeting.lower():
            result["test_passed"] = False
            result["diagnosis"] = (
                "FAIL: Nested 'info' dependency was not injected. SelfDependencyProxy may be using original function instead of wrapper."
            )
        elif "Server:" in greeting and "Uptime:" in greeting:
            result["test_passed"] = True
            result["diagnosis"] = (
                "PASS: Nested 'info' dependency was properly injected via wrapper!"
            )
        else:
            result["test_passed"] = False
            result["diagnosis"] = f"UNKNOWN: Unexpected response format: {greeting}"

    except Exception as e:
        result["error"] = str(e)
        result["diagnosis"] = f"FAIL: Exception during self-dep call: {e}"

    return result


# ===== DEPENDENCY TEST FUNCTION =====
# Shows multiple dependencies with different typing approaches


@app.tool()
@mesh.tool(
    capability="dependency_test",
    dependencies=[
        "date_service",  # Simple string dependency
        {
            "capability": "info",
            "tags": ["system", "disk"],
        },  # Tag-based: will get DISK info!
    ],
    description="Test hybrid dependencies: simple + tag-based resolution",
)
async def test_dependencies(
    date_service: Any = None,
    info: mesh.McpMeshAgent | None = None,  # This will get the DISK info service!
) -> dict[str, Any]:
    """
    Test function showing hybrid dependency resolution.

    Demonstrates both simple string and tag-based dependencies:
    - date_service: simple string dependency
    - info with [system,disk] tags: will get disk info (not general info)!
    """
    result = {
        "test_name": "smart_dependency_demo",
        "date_service": "not_available",
        "disk_info_service": "not_available",  # This should get DISK info, not general info!
    }

    # Test simple Any type dependency
    if date_service is not None:
        try:
            date = await date_service()  # Direct call
            result["date_service"] = f"available: {date}"
        except Exception as e:
            result["date_service"] = f"error: {e}"

    # Test tag-based dependency - should get DISK info service
    if info is not None:
        try:
            disk_info = (
                await info()
            )  # This should return disk/OS info, not general system info
            info_type = disk_info.get("info_type", "unknown")
            result["disk_info_service"] = (
                f"available: {info_type} (smart tag matching worked!)"
            )
        except Exception as e:
            result["disk_info_service"] = f"error: {e}"

    return result


# AGENT configuration - this tells mesh how to run the FastMCP server
@mesh.agent(
    name="hello-world",
    version="1.0.0",
    description="Hello World service with FastMCP and mesh integration",
    http_port=9090,
    enable_http=True,
    auto_run=True,
)
class HelloWorldAgent:
    """
    Agent class that configures how mesh should run the FastMCP server.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Apply dependency injection to decorated functions
    3. Start the FastMCP HTTP server on the configured port
    4. Register all capabilities with the mesh registry
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - Dependency injection between functions
# - HTTP server configuration
# - Service registration with mesh registry
