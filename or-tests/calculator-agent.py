#!/usr/bin/env python3
"""
Calculator Agent with Tag-Level OR Dependencies

This agent demonstrates tag-level OR syntax for dependencies:
  tags: ["addition", ["python", "typescript"]]

This means: require "addition" tag AND (prefer "python" OR fallback to "typescript")

Test scenarios:
1. Both py-math-agent and ts-math-agent running -> uses python (first alternative)
2. Only ts-math-agent running -> uses typescript (fallback)
3. Neither running -> dependencies unresolved
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Calculator Agent")


@app.tool()
@mesh.tool(
    capability="calculator",
    tags=["math", "calculator"],
    description="Calculate using available math implementations",
    dependencies=[
        # Each dependency uses tag-level OR with preference:
        # operation AND (python OR +typescript) = prefer typescript if available
        {
            "capability": "math_operations",
            "tags": ["addition", ["python", "+typescript"]],  # +typescript = preferred
        },
        {
            "capability": "math_operations",
            "tags": ["subtraction", ["python", "+typescript"]],
        },
        {
            "capability": "math_operations",
            "tags": ["multiplication", ["python", "+typescript"]],
        },
        {
            "capability": "math_operations",
            "tags": ["division", ["python", "+typescript"]],
        },
    ],
)
async def calculate(
    a: int,
    b: int,
    operator: str = "+",
    add: mesh.McpMeshTool = None,
    subtract: mesh.McpMeshTool = None,
    multiply: mesh.McpMeshTool = None,
    divide: mesh.McpMeshTool = None,
) -> dict:
    """
    Perform calculation using injected math operations.

    The math operations are resolved based on tag-level OR:
    - Prefers "python" tagged implementations
    - Falls back to "typescript" if python unavailable
    """
    ops = {
        "+": ("add", add),
        "-": ("subtract", subtract),
        "*": ("multiply", multiply),
        "/": ("divide", divide),
    }

    if operator not in ops:
        return {"error": f"Unknown operator: {operator}"}

    op_name, op_func = ops[operator]

    if op_func is None:
        return {"error": f"No provider available for {op_name}"}

    result = await op_func(a=a, b=b)

    return {
        "expression": f"{a} {operator} {b}",
        "result": result.get("result"),
        "implementation": result.get("implementation", "unknown"),
        "operator": op_name,
    }


@mesh.agent(
    name="calculator-agent",
    version="1.0.0",
    description="Calculator using tag-level OR dependencies",
    http_port=9003,
    enable_http=True,
    auto_run=True,
)
class CalculatorAgent:
    pass
