#!/usr/bin/env python3
"""
Hello World example with HTTP transport enabled.

This example demonstrates how to enable HTTP transport for MCP agents,
allowing them to communicate across network boundaries.
"""

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the FastMCP server
server = FastMCP(name="hello-world-http")


@server.tool()
@mesh_agent(
    capability="greeting",
    description="Provides personalized greetings with system date/time",
    dependencies=["SystemAgent"],
    version="2.0.0",
    tags=["greetings", "date-aware"],
    enable_http=True,  # Enable HTTP transport
    http_port=0,  # Auto-assign port (or specify a fixed port)
)
def greet_with_http(
    name: str = "World", style: str = "friendly", SystemAgent: Any = None
) -> dict[str, Any]:
    """
    Generate a personalized greeting with HTTP transport enabled.

    This function can be invoked via HTTP from other agents.
    """
    greeting_styles = {
        "friendly": f"Hello, {name}!",
        "formal": f"Greetings, {name}.",
        "casual": f"Hey there, {name}!",
        "enthusiastic": f"Hi {name}! Great to see you!",
    }

    message = greeting_styles.get(style, f"Hello, {name}!")

    result = {"greeting": message, "style": style, "transport": "http"}

    # Add system date if SystemAgent is available (via HTTP)
    if SystemAgent:
        try:
            # This will make an HTTP call to SystemAgent if it's remote
            date_info = SystemAgent.getDate()
            result["current_date"] = date_info
            result["agent_connection"] = "http"
        except Exception as e:
            logger.error(f"Failed to get date from SystemAgent: {e}")
            result["error"] = str(e)
    else:
        result["warning"] = "SystemAgent not available"

    return result


@server.tool()
@mesh_agent(
    capability="calculator",
    description="Basic arithmetic operations accessible via HTTP",
    version="1.0.0",
    enable_http=True,  # Enable HTTP transport
)
def calculate(operation: str, a: float, b: float) -> dict[str, Any]:
    """
    Perform basic arithmetic operations via HTTP.
    """
    operations = {
        "add": lambda x, y: x + y,
        "subtract": lambda x, y: x - y,
        "multiply": lambda x, y: x * y,
        "divide": lambda x, y: x / y if y != 0 else None,
    }

    if operation not in operations:
        return {
            "error": f"Unknown operation: {operation}",
            "available": list(operations.keys()),
        }

    result = operations[operation](a, b)

    if result is None:
        return {"error": "Division by zero"}

    return {
        "operation": operation,
        "a": a,
        "b": b,
        "result": result,
        "transport": "http",
    }


@server.tool()
@mesh_agent(
    capability="status",
    description="Check HTTP server status",
    version="1.0.0",
    enable_http=True,
)
def get_status() -> dict[str, Any]:
    """
    Get the status of the HTTP-enabled MCP server.
    """
    return {
        "server": server.name,
        "status": "healthy",
        "transport": ["stdio", "http"],
        "capabilities": ["greeting", "calculator", "status"],
        "message": "HTTP transport is enabled for cross-network communication",
    }


if __name__ == "__main__":
    # The mesh runtime will automatically:
    # 1. Start the MCP server on stdio
    # 2. Enable HTTP wrapper on auto-assigned port
    # 3. Register HTTP endpoint with the mesh registry
    # 4. Handle incoming HTTP requests from other agents

    logger.info(f"Starting {server.name} with HTTP transport enabled...")
    logger.info("HTTP endpoint will be automatically assigned and registered")

    # Run the server
    server.run(transport="stdio")
