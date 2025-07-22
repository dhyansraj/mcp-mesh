#!/usr/bin/env python3
"""
FastMCP Agent with Mesh Integration Example

This demonstrates the ideal developer experience:
- Keep familiar FastMCP decorators (@app.tool, @app.prompt, @app.resource)
- Add minimal mesh decorators (@mesh.tool, @mesh.agent) for DI and orchestration
- No main method or server management needed - mesh handles it automatically
"""

import json
from datetime import datetime

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("FastMCP Service")


# PROMPTS with mesh integration
@app.prompt()
@mesh.tool(capability="prompt_service", dependencies=["time_service"])
def analysis_prompt(
    topic: str, depth: str = "basic", time_service: mesh.McpMeshAgent = None
) -> str:
    """Generate analysis prompt with current time."""
    timestamp = time_service() if time_service else "unknown"

    return f"""Please analyze the following topic in detail:

Topic: {topic}
Analysis Depth: {depth}
Generated At: {timestamp}

Provide:
1. Overview and context
2. Key points and insights
3. Conclusions and recommendations

Focus on delivering {depth} level analysis.
"""


# TOOLS with mesh integration
@app.tool()
@mesh.tool(capability="time_service", tags=["system", "time"])
def get_current_time() -> str:
    """Get the current system time."""
    return datetime.now().isoformat()


@app.tool()
@mesh.tool(capability="math_service", dependencies=["time_service"])
def calculate_with_timestamp(
    a: float, b: float, operation: str = "add", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Perform math operation with timestamp from time service."""
    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "subtract":
        result = a - b
    else:
        result = 0

    timestamp = time_service() if time_service else "unknown"

    return {
        "operation": operation,
        "operands": [a, b],
        "result": result,
        "timestamp": timestamp,
    }


@app.tool()
@mesh.tool(capability="data_service", tags=["data", "json"])
def process_data(data: str, format_type: str = "json") -> dict:
    """Process and format data."""
    return {
        "input": data,
        "format": format_type,
        "processed_at": datetime.now().isoformat(),
        "length": len(data),
    }


@app.prompt()
@mesh.tool(capability="template_service")
def report_template(title: str, sections: list | None = None) -> str:
    """Generate report template."""
    sections = sections or ["Introduction", "Analysis", "Conclusion"]

    template = f"""# {title}

Generated: {datetime.now().isoformat()}

"""

    for i, section in enumerate(sections, 1):
        template += f"## {i}. {section}\n\n[Content for {section.lower()}]\n\n"

    return template


# RESOURCES with mesh integration
@app.resource("config://service")
@mesh.tool(capability="config_service")
async def service_config() -> str:
    """Service configuration data."""
    config = {
        "service_name": "FastMCP Service",
        "version": "1.0.0",
        "capabilities": [
            "time_service",
            "math_service",
            "data_service",
            "prompt_service",
            "template_service",
            "config_service",
        ],
        "transport": "http",
        "mesh_enabled": True,
        "created_at": datetime.now().isoformat(),
    }
    return json.dumps(config, indent=2)


@app.resource("status://health/{status_type}")
@mesh.tool(capability="status_service", dependencies=["time_service"])
async def health_status(
    status_type: str, time_service: mesh.McpMeshAgent = None
) -> str:
    """Health status information."""
    timestamp = time_service() if time_service else "unknown"

    status = {
        "status": "healthy",
        "status_type": status_type,
        "uptime": "running",
        "last_check": timestamp,
        "services": {
            "fastmcp": "active",
            "mesh": "integrated",
            "dependencies": "resolved",
        },
    }
    return json.dumps(status, indent=2)


# AGENT configuration - this tells mesh how to run the FastMCP server
@mesh.agent(
    name="fastmcp-service",
    version="1.0.0",
    description="FastMCP service with mesh integration",
    http_port=9092,
    enable_http=True,
    auto_run=True,
)
class FastMCPService:
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
