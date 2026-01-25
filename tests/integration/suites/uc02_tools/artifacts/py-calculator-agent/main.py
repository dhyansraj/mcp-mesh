"""Calculator agent that provides math operations.

This agent demonstrates:
1. Simple local tools (calc_add, calc_multiply)
2. Multi-dependency injection with the calculate() function that depends on
   4 tools from py-math-agent: add, subtract, multiply, divide
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-calculator-agent")


# ===== LOCAL TOOLS (for backward compatibility) =====


@app.tool()
@mesh.tool(
    capability="calculator",
    description="Add two numbers",
    tags=["math", "calculator"],
)
def calc_add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@app.tool()
@mesh.tool(
    capability="calculator",
    description="Multiply two numbers",
    tags=["math", "calculator"],
)
def calc_multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


# ===== MULTI-DEPENDENCY TOOL =====


@app.tool()
@mesh.tool(
    capability="calculator",
    description="Calculate result using operator (+, -, *, /)",
    tags=["math", "calculator", "multi-dep"],
    dependencies=[
        {"capability": "math_operations", "tags": ["addition"]},
        {"capability": "math_operations", "tags": ["subtraction"]},
        {"capability": "math_operations", "tags": ["multiplication"]},
        {"capability": "math_operations", "tags": ["division"]},
    ],
)
async def calculate(
    a: int,
    b: int,
    operator: str,
    add: mesh.McpMeshTool = None,
    subtract: mesh.McpMeshTool = None,
    multiply: mesh.McpMeshTool = None,
    divide: mesh.McpMeshTool = None,
) -> dict:
    """
    Perform calculation using the specified operator.

    Depends on 4 tools from py-math-agent:
    - add (for +)
    - subtract (for -)
    - multiply (for *)
    - divide (for /)

    Args:
        a: First operand
        b: Second operand
        operator: One of +, -, *, /

    Returns:
        Dict with operation details and result
    """
    result = {
        "a": a,
        "b": b,
        "operator": operator,
        "result": None,
        "source": None,
        "error": None,
    }

    try:
        if operator == "+":
            if add:
                result["result"] = await add(a=a, b=b)
                result["source"] = "py-math-agent"
            else:
                result["result"] = a + b
                result["source"] = "local"

        elif operator == "-":
            if subtract:
                result["result"] = await subtract(a=a, b=b)
                result["source"] = "py-math-agent"
            else:
                result["result"] = a - b
                result["source"] = "local"

        elif operator == "*":
            if multiply:
                result["result"] = await multiply(a=a, b=b)
                result["source"] = "py-math-agent"
            else:
                result["result"] = a * b
                result["source"] = "local"

        elif operator == "/":
            if b == 0:
                result["error"] = "Cannot divide by zero"
            elif divide:
                result["result"] = await divide(a=a, b=b)
                result["source"] = "py-math-agent"
            else:
                result["result"] = a / b
                result["source"] = "local"

        else:
            result["error"] = f"Unknown operator: {operator}. Use +, -, *, /"

    except Exception as e:
        result["error"] = str(e)

    return result


@mesh.agent(
    name="py-calculator-agent",
    version="1.0.0",
    description="Calculator agent with local tools and multi-dependency calculate()",
    http_port=9020,
    auto_run=True,
)
class PyCalculatorAgent:
    pass
