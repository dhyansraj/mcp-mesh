#!/usr/bin/env python3
"""
py-math-agent - MCP Mesh Agent

A MCP Mesh agent generated using meshctl scaffold.
"""


import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("PyMathAgent Service")


# ===== TOOLS =====


@app.tool()
@mesh.tool(
    capability="add",
    description="Add two numbers together",
    tags=["math"],
)
async def add(a: float, b: float) -> float:
    """
    Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of a and b
    """
    return a + b


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="py-math-agent",
    version="1.0.0",
    description="MCP Mesh agent for py-math-agent",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class PyMathAgentAgent:
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
