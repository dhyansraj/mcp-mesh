#!/usr/bin/env python3
"""
MCP Mesh System Agent Example

This agent provides system information capabilities that other agents can depend on.
Demonstrates the tools vs capabilities architecture:

- Tools: Function names (MCP function names)
- Capabilities: What others can depend on
- Pure simplicity: Just decorators, no manual setup!

Function names can be different from capability names for maximum flexibility.
"""

from datetime import datetime
from typing import Any

import mesh
from mcp_mesh import McpMeshTool


@mesh.agent(name="system-agent", http_port=9091)
class SystemAgent:
    """System information agent providing date and info capabilities."""

    pass


# Store start time for uptime calculations
start_time = datetime.now()

# ===== DATE SERVICE =====
# Tool: "get_current_time" | Capability: "date_service"


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


@mesh.tool(
    capability="health_check",
    dependencies=["date_service"],  # Depends on capability name, not function name!
    description="Get system status with current time",
    version="1.0.0",
)
def perform_health_diagnostic(
    date_service: McpMeshTool | None = None,
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
            current_time = date_service.invoke()
            status["timestamp"] = current_time
            status["time_service"] = "available"
        except Exception as e:
            status["timestamp"] = "error"
            status["time_service"] = f"error: {e}"
    else:
        status["timestamp"] = "date_service_unavailable"
        status["time_service"] = "not_injected"

    return status


# ===== COMPREHENSIVE SYSTEM REPORT WITH WEATHER =====


@mesh.tool(
    capability="system_report",
    dependencies=[
        "weather_service",  # From weather-agent
    ],
    description="Comprehensive system report including weather data",
    version="1.0.0",
)
def generate_comprehensive_report(
    weather_service: McpMeshTool | None = None,
) -> dict[str, Any]:
    """
    Generate a comprehensive system report with weather information.

    This demonstrates multi-agent chaining:
    hello_world -> system_agent -> weather_agent

    The system agent acts as a middleman, collecting both system info
    and weather data to provide a complete environmental report.
    """
    uptime = datetime.now() - start_time

    report = {
        "report_type": "comprehensive_system_environment",
        "generated_at": datetime.now().isoformat(),
        "system": {
            "server_name": "system-agent",
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": f"{uptime.total_seconds():.1f} seconds",
            "version": "1.0.0",
            "agent_type": "system_service",
            "capabilities_provided": [
                "date_service",
                "info",
                "uptime_info",
                "health_check",
                "system_report",
            ],
        },
        "timestamp": None,
        "weather": None,
    }

    # Get current time locally (no dependency injection needed)
    current_time = get_current_time()
    report["timestamp"] = current_time
    report["system"]["current_time"] = current_time

    # Get weather information from weather agent
    if weather_service is not None:
        try:
            weather_data = weather_service.invoke()
            report["weather"] = weather_data
            # Add formatted summary
            location = weather_data.get("location", "Unknown")
            temp = weather_data.get("temperature_f", "N/A")
            conditions = weather_data.get("weather_description", "Unknown")
            report["weather_summary"] = f"{temp}°F in {location} - {conditions}"
        except Exception as e:
            report["weather"] = {"error": f"Weather service error: {e}"}
            report["weather_summary"] = "Weather data unavailable"
    else:
        report["weather"] = {"error": "Weather service not available"}
        report["weather_summary"] = "Weather service not injected"

    return report


# 🎉 That's it! Pure simplicity with auto_run=True by default!
# No FastMCP server creation, no main function, no manual loops needed!
