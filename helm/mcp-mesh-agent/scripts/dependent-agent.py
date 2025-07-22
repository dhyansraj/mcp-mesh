#!/usr/bin/env python3
"""
Dependent Agent Example

This demonstrates an agent that depends on capabilities from other agents:
- Uses @mesh.tool with dependencies to require time_service capability
- Shows how dependency injection automatically resolves and injects services
- Minimal FastMCP setup with just two functions that depend on external services
"""


import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Dependent Service")


@app.tool()
@mesh.tool(capability="report_service", dependencies=["time_service"])
def generate_report(
    title: str, content: str = "Sample content", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Generate a timestamped report using the time service."""
    # Get timestamp from the injected time service
    timestamp = time_service() if time_service else "unknown"

    report = {
        "title": title,
        "content": content,
        "generated_at": timestamp,
        "agent": "dependent-service",
        "status": "completed",
    }

    return report


@app.tool()
@mesh.tool(capability="analysis_service", dependencies=["time_service"])
def analyze_data(
    data: list, analysis_type: str = "basic", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Analyze data with timestamp from time service."""
    # Get timestamp from the injected time service
    timestamp = time_service() if time_service else "unknown"

    # Simple analysis
    if not data:
        result = {"error": "No data provided", "count": 0, "average": None}
    else:
        # Try to analyze as numbers, fallback to general analysis
        try:
            numbers = [float(x) for x in data]
            result = {
                "count": len(numbers),
                "sum": sum(numbers),
                "average": sum(numbers) / len(numbers),
                "min": min(numbers),
                "max": max(numbers),
            }
        except (ValueError, TypeError):
            # Fallback for non-numeric data
            result = {
                "count": len(data),
                "data_types": list(set(type(x).__name__ for x in data)),
                "sample": data[:3] if len(data) > 3 else data,
            }

    analysis = {
        "analysis_type": analysis_type,
        "result": result,
        "analyzed_at": timestamp,
        "agent": "dependent-service",
    }

    return analysis


# AGENT configuration - depends on time_service from the FastMCP agent
@mesh.agent(
    name="dependent-service",
    version="1.0.0",
    description="Dependent service that uses time_service capability",
    http_host="dependent-agent",
    http_port=9093,
    enable_http=True,
    auto_run=True,
)
class DependentService:
    """
    Agent that demonstrates dependency injection.

    This agent:
    1. Provides report_service and analysis_service capabilities
    2. Depends on time_service capability (from fastmcp-agent)
    3. Uses dependency injection to get timestamps from the time service
    4. Shows how mesh automatically resolves and injects dependencies
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - Dependency resolution and injection
# - Service discovery and connection
# - HTTP server configuration
# - Service registration with mesh registry