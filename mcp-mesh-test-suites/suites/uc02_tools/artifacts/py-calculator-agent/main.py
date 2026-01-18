"""Calculator agent that provides math operations."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-calculator-agent")


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


@mesh.agent(
    name="py-calculator-agent",
    version="1.0.0",
    description="Calculator agent providing math operations",
    http_port=9020,
    auto_run=True,
)
class PyCalculatorAgent:
    pass
