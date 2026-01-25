#!/usr/bin/env python3
"""
calculator-agent - Performs calculations using math-agent.

Demonstrates cross-agent tool calls via dependency injection.
No hardcoded port - mesh auto-assigns an available port.
"""

import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshAgent

app = FastMCP("Calculator Agent")


@app.tool()
@mesh.tool(
    capability="sum_three",
    description="Add three numbers using math-agent's add tool",
    tags=["calculator"],
    dependencies=["add"],  # Depends on math-agent's add capability
)
async def sum_three(
    a: float, b: float, c: float, add_svc: McpMeshAgent = None
) -> float:
    """
    Add three numbers by calling math-agent's add tool twice.

    First: a + b = temp
    Then: temp + c = result
    """
    # First call: a + b
    temp = await add_svc(a=a, b=b)
    # Second call: temp + c
    result = await add_svc(a=temp, b=c)
    return result


@app.tool()
@mesh.tool(
    capability="square",
    description="Calculate square of a number using multiply",
    tags=["calculator"],
    dependencies=["multiply"],  # Depends on math-agent's multiply capability
)
async def square(n: float, multiply_svc: McpMeshAgent = None) -> float:
    """Calculate n squared by calling math-agent's multiply."""
    return await multiply_svc(a=n, b=n)


@app.tool()
@mesh.tool(
    capability="sum_of_squares",
    description="Calculate sum of squares: a^2 + b^2",
    tags=["calculator"],
    dependencies=["add", "multiply"],  # Depends on both
)
async def sum_of_squares(
    a: float,
    b: float,
    add_svc: McpMeshAgent = None,
    multiply_svc: McpMeshAgent = None,
) -> float:
    """
    Calculate a^2 + b^2 using math-agent's tools.

    Demonstrates multiple dependencies in one tool.
    """
    a_squared = await multiply_svc(a=a, b=a)
    b_squared = await multiply_svc(a=b, b=b)
    return await add_svc(a=a_squared, b=b_squared)


@mesh.agent(
    name="calculator-agent",
    version="1.0.0",
    description="Calculator that uses math-agent for operations",
    http_port=0,  # Auto-assign or use MCP_MESH_HTTP_PORT env
    enable_http=True,
    auto_run=True,
)
class CalculatorAgent:
    pass
