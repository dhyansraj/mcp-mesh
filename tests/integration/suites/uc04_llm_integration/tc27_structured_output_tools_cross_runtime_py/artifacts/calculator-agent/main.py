#!/usr/bin/env python3
"""
calculator-agent - Simple MCP Mesh tool provider for testing.

Provides basic calculator tools (add, multiply) that LLM agents can discover and use.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("CalculatorAgent")


class CalcInput(BaseModel):
    """Input for calculator operations."""

    a: float = Field(..., description="First number")
    b: float = Field(..., description="Second number")


@app.tool()
@mesh.tool(
    capability="calculator",
    description="Add two numbers",
    version="1.0.0",
    tags=["calculator", "math"],
)
def calc_add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@app.tool()
@mesh.tool(
    capability="calculator",
    description="Multiply two numbers",
    version="1.0.0",
    tags=["calculator", "math"],
)
def calc_multiply(a: float, b: float) -> float:
    """Multiply two numbers together."""
    return a * b


@mesh.agent(
    name="calculator-agent",
    version="1.0.0",
    description="Simple calculator tool provider",
    http_port=9048,
    enable_http=True,
    auto_run=True,
)
class CalculatorAgentConfig:
    """Calculator tool provider agent."""

    pass
