#!/usr/bin/env python3
"""
calculator-agent - Simple MCP Mesh tool provider for the RFC #1100 experiment.

Provides a basic calculator tool (add) that the LLM consumer can discover and
call inside its agentic loop. Keeping a single deterministic tool keeps the
experiment focused: does Gemini-3 response_json_schema + tools loop?
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


@mesh.agent(
    name="calculator-agent",
    version="1.0.0",
    description="Simple calculator tool provider",
    http_port=9030,
    enable_http=True,
    auto_run=True,
)
class CalculatorAgentConfig:
    """Calculator tool provider agent."""

    pass
