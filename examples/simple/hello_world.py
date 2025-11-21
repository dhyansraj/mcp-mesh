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
