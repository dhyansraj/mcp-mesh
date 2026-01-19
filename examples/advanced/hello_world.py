#!/usr/bin/env python3
"""
MCP Mesh Hello World Example

This example demonstrates the core concepts of MCP Mesh:
1. MCP Mesh tools with automatic dependency injection
2. Hybrid typing support for development flexibility
3. Pure simplicity - just decorators, no manual setup!

Start this agent, then start system_agent.py to see dependency injection in action!
"""

from typing import Any

import mesh
from mcp_mesh import McpMeshTool


@mesh.agent(name="hello-world", http_port=9090)
class HelloWorldAgent:
    """Hello World agent demonstrating MCP Mesh features."""

    pass


# ===== MESH FUNCTION WITH SIMPLE TYPING =====
# Uses Any type for maximum simplicity and flexibility


@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],
    description="Simple greeting with date dependency",
)
def hello_mesh_simple(date_service: Any = None) -> str:
    """
    MCP Mesh greeting with simple typing.

    Uses Any type for maximum flexibility - works with any proxy implementation.
    Great for prototyping and simple use cases.
    """
    if date_service is None:
        return "👋 Hello from MCP Mesh! (Date service not available yet)"

    try:
        # Call the injected function - proxy implements __call__()
        current_date = date_service()
        return f"👋 Hello from MCP Mesh! Today is {current_date}"
    except Exception as e:
        return f"👋 Hello from MCP Mesh! (Error getting date: {e})"


# ===== MESH FUNCTION WITH TYPED INTERFACE =====
# Uses McpMeshTool type for better IDE support and type safety


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
def hello_mesh_typed(info: McpMeshTool | None = None) -> str:
    """
    MCP Mesh greeting with smart tag-based dependency resolution.

    This requests "info" capability with "system" + "general" tags.
    Registry will match SystemAgent_getInfo (not get_disk_info) based on tags!
    """
    if info is None:
        return "👋 Hello from smart MCP Mesh! (info service not available yet)"

    try:
        # This will call the general system info (not disk info) due to smart tag matching!
        system_info = info.invoke()
        uptime = system_info.get("uptime_formatted", "unknown")
        server_name = system_info.get("server_name", "unknown")
        return f"👋 Hello from smart MCP Mesh! Server: {server_name}, Uptime: {uptime}"
    except Exception as e:
        return f"👋 Hello from smart MCP Mesh! (Error getting info: {e})"


# ===== COMPREHENSIVE DASHBOARD =====
# Chains multiple agents together for a complete system report


@mesh.tool(
    capability="system_dashboard",
    dependencies=[
        "system_report",  # From system-agent (which chains to weather-agent)
    ],
    description="Complete system dashboard - demonstrates clean agent chaining",
)
def generate_system_dashboard(
    system_report: McpMeshTool | None = None,
) -> str:
    """
    Generate a comprehensive system dashboard using clean agent chaining.

    This demonstrates elegant MCP Mesh distributed dependency injection:
    hello_world -> system_agent -> weather_agent

    The system agent does the heavy lifting of coordinating multiple services,
    making this function clean and focused.
    """
    dashboard_lines = []
    dashboard_lines.append("=" * 65)
    dashboard_lines.append("🎯 MCP MESH DISTRIBUTED SYSTEM DASHBOARD")
    dashboard_lines.append("=" * 65)
    dashboard_lines.append("")

    if system_report is not None:
        try:
            report = system_report.invoke()

            # Header with greeting
            user_name = "John"  # Could be parameterized
            dashboard_lines.append(f"👋 Hello {user_name}!")
            dashboard_lines.append("")

            # System status overview
            system = report.get("system", {})
            dashboard_lines.append("🖥️  SYSTEM STATUS:")
            dashboard_lines.append("   All systems in your data center look good!")
            dashboard_lines.append(f"   Server: {system.get('server_name', 'Unknown')}")
            dashboard_lines.append(
                f"   Uptime: {system.get('uptime_formatted', 'Unknown')}"
            )
            dashboard_lines.append(
                f"   Current Time: {report.get('timestamp', 'Unknown')}"
            )
            dashboard_lines.append(f"   Version: {system.get('version', 'Unknown')}")
            capabilities = system.get("capabilities_provided", [])
            dashboard_lines.append(
                f"   Active Services: {len(capabilities)} ({', '.join(capabilities[:3])}...)"
            )
            dashboard_lines.append("")

            # Weather report
            weather = report.get("weather", {})
            if "error" not in weather:
                location = weather.get("location", "Unknown")
                dashboard_lines.append(f"🌤️  WEATHER REPORT FOR {location.upper()}:")
                dashboard_lines.append(
                    f"   {report.get('weather_summary', 'No weather data')}"
                )

                # Additional weather details
                feels_like = weather.get("feels_like_f")
                humidity = weather.get("humidity_percent")
                wind = weather.get("wind_speed_mph")
                conditions = weather.get("weather_description", "Unknown")

                if feels_like is not None:
                    dashboard_lines.append(f"   Feels like: {feels_like}°F")
                if humidity is not None:
                    dashboard_lines.append(f"   Humidity: {humidity}%")
                if wind is not None:
                    dashboard_lines.append(f"   Wind: {wind} mph")
                dashboard_lines.append(f"   Conditions: {conditions}")

                location_method = weather.get("location_method", "unknown")
                dashboard_lines.append(f"   Location detection: {location_method}")
            else:
                dashboard_lines.append("🌤️  WEATHER REPORT:")
                dashboard_lines.append(
                    f"   {weather.get('error', 'Weather service unavailable')}"
                )

        except Exception as e:
            dashboard_lines.append(f"❌ Error generating report: {e}")
    else:
        dashboard_lines.append("❌ System report service unavailable")
        dashboard_lines.append("   Cannot generate comprehensive dashboard")

    dashboard_lines.append("")
    dashboard_lines.append("=" * 65)
    dashboard_lines.append("✨ Powered by MCP Mesh Distributed Agent Framework")
    dashboard_lines.append(
        "🔗 Clean Agent Chain: hello-world → system-agent → weather-agent"
    )
    dashboard_lines.append("=" * 65)

    return "\n".join(dashboard_lines)


# ===== DEPENDENCY TEST FUNCTION =====
# Shows multiple dependencies with different typing approaches


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
def test_dependencies(
    date_service: Any = None,
    info: McpMeshTool | None = None,  # This will get the DISK info service!
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
            date = date_service()  # Direct call
            result["date_service"] = f"available: {date}"
        except Exception as e:
            result["date_service"] = f"error: {e}"

    # Test tag-based dependency - should get DISK info service
    if info is not None:
        try:
            disk_info = (
                info.invoke()
            )  # This should return disk/OS info, not general system info
            info_type = disk_info.get("info_type", "unknown")
            result["disk_info_service"] = (
                f"available: {info_type} (smart tag matching worked!)"
            )
        except Exception as e:
            result["disk_info_service"] = f"error: {e}"

    return result


# 🎉 That's it! Pure simplicity with auto_run=True by default!
# No FastMCP server creation, no main function, no manual loops needed!
