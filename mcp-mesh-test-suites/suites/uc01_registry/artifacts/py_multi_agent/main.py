#!/usr/bin/env python3
"""
py-multi-agent - MCP Mesh Agent for registry tests.

Multi-file Python agent with multiple tools.
"""

from datetime import datetime
from typing import Any

import mesh
from fastmcp import FastMCP

app = FastMCP("py-multi-agent")


# ===== TOOLS =====


@app.tool()
@mesh.tool(
    capability="greeting",
    description="Greet someone by name",
    tags=["greeting", "python"],
)
async def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}! From py-multi-agent at {datetime.now().isoformat()}"


@app.tool()
@mesh.tool(
    capability="echo",
    description="Echo a message back",
    tags=["utility", "python"],
)
async def echo(message: str) -> str:
    """Echo the input message."""
    return f"Echo: {message}"


@app.tool()
@mesh.tool(
    capability="info",
    description="Get agent info",
    tags=["info", "python"],
)
async def get_info() -> dict[str, Any]:
    """Return agent information."""
    return {
        "name": "py-multi-agent",
        "version": "1.0.0",
        "language": "python",
        "timestamp": datetime.now().isoformat(),
    }


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="py-multi-agent",
    version="1.0.0",
    description="Multi-file Python agent for registry tests",
    http_port=9002,
    enable_http=True,
    auto_run=True,
)
class PyMultiAgent:
    """Agent class for mesh configuration."""

    pass
