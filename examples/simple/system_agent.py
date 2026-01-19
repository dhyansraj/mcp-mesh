#!/usr/bin/env python3
"""
MCP Mesh System Agent Example with FastMCP Integration

This agent provides system information capabilities that other agents can depend on.
Demonstrates the hybrid FastMCP + MCP Mesh architecture:

- FastMCP decorators (@app.tool) for familiar MCP development
- MCP Mesh decorators (@mesh.tool) for dependency injection and orchestration
- Tools: Function names (MCP function names)
- Capabilities: What others can depend on
- Pure simplicity: Just dual decorators, no manual setup!

Function names can be different from capability names for maximum flexibility.
"""

from datetime import datetime
from typing import Any

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("System Agent Service")


# Store start time for uptime calculations
start_time = datetime.now()

# ===== DATE SERVICE =====
# Tool: "get_current_time" | Capability: "date_service"


@app.tool()
@mesh.tool(
    capability="date_service",  # Capability name (what others depend on)
    description="Get current system date and time",
    version="1.0.0",
    tags=["system", "time", "clock"],
)
def get_current_time() -> str:  # Function name can be anything!
    """
    Get the current system date and time.

    This function provides the "date_service" capability.
    Function name 'get_current_time' can be anything - capability name matters!

    Returns:
        Formatted date and time string
    """
    now = datetime.now()
    return now.strftime("%B %d, %Y at %I:%M %p")


# ===== GENERAL SYSTEM INFO SERVICE =====
# Tool: "fetch_system_overview" | Capability: "info"


@app.tool()
@mesh.tool(
    capability="info",  # Generic capability name for smart matching
    description="Get comprehensive system information",
    version="1.0.0",
    tags=["system", "general", "monitoring"],  # Tags for smart resolution
)
def fetch_system_overview() -> dict[str, Any]:  # Clear: function name ≠ capability
    """
    Get comprehensive system information.

    This function provides the "info" capability with "system" + "general" tags.
    Smart matching: hello_world dependency "info" with "system" tag will match this.

    Returns:
        Dictionary containing system information
    """

    uptime = datetime.now() - start_time

    return {
        "server_name": "system-agent",
        "current_time": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "uptime_seconds": uptime.total_seconds(),
        "uptime_formatted": f"{uptime.total_seconds():.1f} seconds",
        "version": "1.0.0",
        "capabilities_provided": [
            "date_service",  # From get_current_time() function
            "info",  # From fetch_system_overview() function - generic capability with smart tag matching
        ],
        "agent_type": "system_service",
    }


# ===== UPTIME SERVICE (Different function name vs capability) =====
# Tool: "get_uptime" | Capability: "uptime_info"


@app.tool()
@mesh.tool(
    capability="uptime_info",  # Capability name (what others depend on)
    description="Get system uptime information",
    version="1.0.0",
    tags=["system", "uptime"],
)
def check_how_long_running() -> str:  # Function name can be descriptive and different!
    """
    Get system uptime information.

    This demonstrates function_name != capability:
    - MCP calls: "check_how_long_running"
    - Capability provided: "uptime_info"
    - Dependencies declare: "uptime_info"

    Returns:
        Human-readable uptime string
    """
    uptime = datetime.now() - start_time
    return f"System running for {uptime.total_seconds():.1f} seconds"


# ===== SECOND INFO SERVICE (Different Tags) =====
# Same capability "info" but different tags - shows tag-based filtering


@app.tool()
@mesh.tool(
    capability="info",  # Same capability name!
    description="Get disk and OS information",
    version="1.0.0",
    tags=[
        "system",
        "disk",
        "os",
    ],  # Different tags - won't match "general" requests
)
def analyze_storage_and_os() -> dict[str, Any]:  # Completely different function name!
    """
    Get disk and OS information.

    This also provides "info" capability but with "disk" + "os" tags.
    Smart matching: requests for "info" with "general" tags won't match this.
    Only requests specifically wanting "disk" or "os" info will get this.
    """
    return {
        "info_type": "disk_and_os",
        "disk_usage": "simulated_75_percent",
        "os_version": "simulated_linux_6.x",
        "filesystem": "ext4",
        "mount_points": ["/", "/home", "/var"],
        "tags": ["disk", "os", "system"],
        "note": "This provides 'info' capability but with different tags than general system info",
    }


# ===== STATUS SERVICE WITH DEPENDENCY =====


@app.tool()
@mesh.tool(
    capability="health_check",
    dependencies=["date_service"],  # Depends on capability name, not function name!
    description="Get system status with current time",
    version="1.0.0",
)
def perform_health_diagnostic(
    date_service: mesh.McpMeshTool | None = None,
) -> dict[str, Any]:
    """
    Get system status including current time.

    This tool both provides AND consumes capabilities:
    - Provides: "health_check" (via perform_health_diagnostic function)
    - Consumes: "date_service" (from get_current_time function)

    Demonstrates how agents can be both providers and consumers.
    """
    uptime = datetime.now() - start_time

    status = {
        "status": "healthy",
        "uptime_seconds": uptime.total_seconds(),
        "memory_usage": "simulated_normal",
        "cpu_usage": "simulated_low",
        "service_name": "system-agent",
    }

    # Use injected date service if available
    if date_service is not None:
        try:
            current_time = date_service()
            status["timestamp"] = current_time
            status["time_service"] = "available"
        except Exception as e:
            status["timestamp"] = "error"
            status["time_service"] = f"error: {e}"
    else:
        status["timestamp"] = "date_service_unavailable"
        status["time_service"] = "not_injected"

    return status


# AGENT configuration - this tells mesh how to run the FastMCP server
@mesh.agent(
    name="system-agent",
    version="1.0.0",
    description="System Agent service with FastMCP and mesh integration",
    http_port=9091,
    enable_http=True,
    auto_run=True,
)
class SystemAgent:
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
