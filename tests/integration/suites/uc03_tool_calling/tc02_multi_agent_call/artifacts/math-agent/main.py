#!/usr/bin/env python3
"""
math-agent - Provides basic arithmetic operations.

No hardcoded port - mesh auto-assigns an available port.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Math Agent")


@app.tool()
@mesh.tool(
    capability="add",
    description="Add two numbers together",
    tags=["math", "arithmetic"],
)
async def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


@app.tool()
@mesh.tool(
    capability="multiply",
    description="Multiply two numbers",
    tags=["math", "arithmetic"],
)
async def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the product."""
    return a * b


@mesh.agent(
    name="math-agent",
    version="1.0.0",
    description="Provides basic arithmetic operations",
    http_port=0,  # Auto-assign or use MCP_MESH_HTTP_PORT env
    enable_http=True,
    auto_run=True,
)
class MathAgent:
    pass
