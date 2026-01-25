"""Math agent with multiple tools for testing tool calls."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-math-agent")


@app.tool()
@mesh.tool(
    capability="math_operations",
    description="Add two numbers",
    tags=["math", "addition"],
)
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@app.tool()
@mesh.tool(
    capability="math_operations",
    description="Subtract two numbers",
    tags=["math", "subtraction"],
)
def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


@app.tool()
@mesh.tool(
    capability="math_operations",
    description="Multiply two numbers",
    tags=["math", "multiplication"],
)
def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


@app.tool()
@mesh.tool(
    capability="math_operations",
    description="Divide two numbers",
    tags=["math", "division"],
)
def divide(a: int, b: int) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


@mesh.agent(
    name="py-math-agent",
    version="1.0.0",
    description="Math agent with add, subtract, multiply, divide tools",
    http_port=9010,
    auto_run=True,
)
class PyMathAgent:
    pass
