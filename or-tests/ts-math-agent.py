#!/usr/bin/env python3
"""
TypeScript Math Agent for Tag-Level OR Testing

This agent provides math_operations with "typescript" tag.
(Implemented in Python for simplicity but tagged as typescript)
Used to test tag-level OR alternatives where consumers can request:
  tags: ["addition", ["python", "typescript"]]
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("TypeScript Math Agent")


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "addition", "typescript"],
    description="Add two numbers (TypeScript implementation)",
)
async def add(a: int, b: int) -> dict:
    """Add two numbers using TypeScript."""
    return {"result": a + b, "implementation": "typescript"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "subtraction", "typescript"],
    description="Subtract two numbers (TypeScript implementation)",
)
async def subtract(a: int, b: int) -> dict:
    """Subtract two numbers using TypeScript."""
    return {"result": a - b, "implementation": "typescript"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "multiplication", "typescript"],
    description="Multiply two numbers (TypeScript implementation)",
)
async def multiply(a: int, b: int) -> dict:
    """Multiply two numbers using TypeScript."""
    return {"result": a * b, "implementation": "typescript"}


@app.tool()
@mesh.tool(
    capability="math_operations",
    tags=["math", "division", "typescript"],
    description="Divide two numbers (TypeScript implementation)",
)
async def divide(a: int, b: int) -> dict:
    """Divide two numbers using TypeScript."""
    if b == 0:
        return {"error": "Division by zero", "implementation": "typescript"}
    return {"result": a / b, "implementation": "typescript"}


@mesh.agent(
    name="ts-math-agent",
    version="1.0.0",
    description="TypeScript math operations for tag-level OR testing",
    http_port=9002,
    enable_http=True,
    auto_run=True,
)
class TsMathAgent:
    pass
