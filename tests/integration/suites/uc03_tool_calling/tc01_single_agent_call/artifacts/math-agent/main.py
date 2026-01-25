#!/usr/bin/env python3
"""
math-agent - A simple math agent for testing tool calls.

Provides basic arithmetic operations as MCP tools.
"""

import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("Math Agent")


# ===== TOOLS =====


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
    capability="subtract",
    description="Subtract second number from first",
    tags=["math", "arithmetic"],
)
async def subtract(a: float, b: float) -> float:
    """Subtract b from a and return the difference."""
    return a - b


@app.tool()
@mesh.tool(
    capability="multiply",
    description="Multiply two numbers",
    tags=["math", "arithmetic"],
)
async def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the product."""
    return a * b


@app.tool()
@mesh.tool(
    capability="divide",
    description="Divide first number by second",
    tags=["math", "arithmetic"],
)
async def divide(a: float, b: float) -> float:
    """Divide a by b and return the quotient."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="math-agent",
    version="1.0.0",
    description="Simple math agent providing arithmetic operations",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class MathAgent:
    """Math agent that provides basic arithmetic tools."""

    pass
