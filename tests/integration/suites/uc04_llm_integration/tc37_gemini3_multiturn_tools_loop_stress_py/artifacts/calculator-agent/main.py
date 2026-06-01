#!/usr/bin/env python3
"""
calculator-agent - MCP Mesh tool provider for the RFC #1100 loop-stress TC.

Exposes TWO distinct deterministic tools (add, multiply) so the LLM consumer's
agentic loop is forced through MULTIPLE sequential tool-call rounds when given a
prompt with a data dependency ("first add, then multiply the result"). This
stresses the Gemini-3 server-enforced response_json_schema + tools path (now
default-on per RFC #1100) against the documented infinite-tool-loop risk: a
loop-safe path terminates in a small number of iterations; a runaway path keeps
calling tools until max_iterations.
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
    description="Calculator tool provider with add + multiply",
    http_port=9030,
    enable_http=True,
    auto_run=True,
)
class CalculatorAgentConfig:
    """Calculator tool provider agent (two distinct tools)."""

    pass
