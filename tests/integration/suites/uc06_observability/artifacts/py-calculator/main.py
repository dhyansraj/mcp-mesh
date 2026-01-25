#!/usr/bin/env python3
"""
py-calculator - MCP Mesh Agent

Calculator that compares repeated addition vs multiplication.
Demonstrates dependency injection by using injected add and multiply tools.
"""


import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("PyCalculator Service")


# ===== TOOLS =====


@app.tool()
@mesh.tool(
    capability="calculate",
    description="Multiply two numbers using both repeated addition and direct multiplication",
    tags=["calculator", "math"],
    dependencies=[
        {"capability": "add", "tags": ["+math"]},
        {"capability": "multiply", "tags": ["+math"]},
    ],
)
async def calculate(
    a: int,
    b: int,
    add: mesh.McpMeshTool = None,
    multiply: mesh.McpMeshTool = None,
) -> dict:
    """
    Multiply two numbers using two methods:
    1. Repeated addition: add 'a' to itself 'b' times using injected add tool
    2. Direct multiplication: call injected multiply tool directly

    Args:
        a: First number (will be added repeatedly)
        b: Second number (number of times to add)
        add: Injected add tool from mesh
        multiply: Injected multiply tool from mesh

    Returns:
        Dict with both results for comparison
    """
    results = {
        "a": a,
        "b": b,
        "repeated_addition": None,
        "direct_multiply": None,
        "match": False,
    }

    # Method 1: Repeated addition (a + a + a... b times)
    if add:
        total = 0
        for _ in range(b):
            # Call the injected add tool
            result = await add(a=total, b=a)
            # Extract the numeric result
            if isinstance(result, dict) and "result" in result:
                total = result["result"]
            elif isinstance(result, (int, float)):
                total = result
            else:
                # Try to parse from string
                try:
                    total = float(str(result))
                except (ValueError, TypeError):
                    total = result
        results["repeated_addition"] = total
    else:
        results["repeated_addition"] = "add tool not available"

    # Method 2: Direct multiplication
    if multiply:
        result = await multiply(a=a, b=b)
        # Extract the numeric result
        if isinstance(result, dict) and "result" in result:
            results["direct_multiply"] = result["result"]
        elif isinstance(result, (int, float)):
            results["direct_multiply"] = result
        else:
            # Try to parse from string
            try:
                results["direct_multiply"] = float(str(result))
            except (ValueError, TypeError):
                results["direct_multiply"] = result
    else:
        results["direct_multiply"] = "multiply tool not available"

    # Compare results
    if isinstance(results["repeated_addition"], (int, float)) and isinstance(
        results["direct_multiply"], (int, float)
    ):
        results["match"] = results["repeated_addition"] == results["direct_multiply"]

    return results


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="py-calculator",
    version="1.0.0",
    description="Calculator that compares repeated addition vs multiplication",
    http_port=9022,
    enable_http=True,
    auto_run=True,
)
class PyCalculatorAgent:
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
