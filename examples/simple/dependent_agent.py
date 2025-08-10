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
@mesh.tool(
    capability="report_service",
    dependencies=[
        {
            "capability": "time_service",
            "tags": ["system", "+time"],  # tag time is optional (plus to have)
        }
    ],
)
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


@app.tool()
@mesh.tool(
    capability="comprehensive_report_service", dependencies=["system_info_service"]
)
def generate_comprehensive_report(
    report_title: str,
    include_system_data: bool = True,
    system_info_service: mesh.McpMeshAgent = None,
) -> dict:
    """Generate a comprehensive report with system information from FastMCP service."""
    # Get enriched system info from FastMCP service (which calls system agent)
    if include_system_data and system_info_service:
        try:
            system_data = system_info_service(include_timestamp=True)
        except Exception as e:
            system_data = {"error": f"Failed to get system data: {e}"}
    else:
        system_data = {"note": "System data not included"}

    # Create comprehensive report
    comprehensive_report = {
        "title": report_title,
        "report_type": "comprehensive",
        "generated_by": "dependent-service",
        "creation_time": "now",  # Will be replaced by actual timestamp when called
        "system_info": system_data,
        "report_sections": {
            "executive_summary": "This report includes system information from multiple services",
            "system_details": system_data.get("system_data", {}),
            "service_chain": [
                "dependent-service (this service)",
                "fastmcp-service (enriches data)",
                "system-agent (provides base system info)",
            ],
        },
        "metadata": {
            "dependency_chain_length": 3,
            "services_involved": [
                "dependent-service",
                "fastmcp-service",
                "system-agent",
            ],
        },
    }

    return comprehensive_report


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
