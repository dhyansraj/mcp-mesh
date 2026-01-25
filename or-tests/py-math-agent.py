#!/usr/bin/env python3
"""
Python Math Agent for Tag-Level OR Testing

This agent provides math_operations with "python" tag.
Used to test tag-level OR alternatives where consumers can request:
  tags: ["addition", ["python", "typescript"]]
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Python Math Agent")


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "addition", "python"],
    description="Add two numbers (Python implementation)",
)
async def add(a: int, b: int) -> dict:
    """Add two numbers using Python."""
    return {"result": a + b, "implementation": "python"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "subtraction", "python"],
    description="Subtract two numbers (Python implementation)",
)
async def subtract(a: int, b: int) -> dict:
    """Subtract two numbers using Python."""
    return {"result": a - b, "implementation": "python"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "multiplication", "python"],
    description="Multiply two numbers (Python implementation)",
)
async def multiply(a: int, b: int) -> dict:
    """Multiply two numbers using Python."""
    return {"result": a * b, "implementation": "python"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "division", "python"],
    description="Divide two numbers (Python implementation)",
)
async def divide(a: int, b: int) -> dict:
    """Divide two numbers using Python."""
    if b == 0:
        return {"error": "Division by zero", "implementation": "python"}
    return {"result": a / b, "implementation": "python"}


@mesh.agent(
    name="py-math-agent",
    version="1.0.0",
    description="Python math operations for tag-level OR testing",
    http_port=9001,
    enable_http=True,
    auto_run=True,
)
class PyMathAgent:
    pass
