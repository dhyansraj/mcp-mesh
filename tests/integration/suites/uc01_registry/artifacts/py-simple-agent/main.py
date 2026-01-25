"""
Simple Python agent for registry tests.
Single-file agent with one tool.
"""

from datetime import datetime

import mesh
from fastmcp import FastMCP

app = FastMCP("py-simple-agent")


@app.tool()
@mesh.tool(
    capability="simple_greeting",
    description="Returns a simple greeting",
    tags=["greeting", "simple", "python"],
)
def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}! From Python agent at {datetime.now().isoformat()}"


@mesh.agent(
    name="py-simple-agent",
    version="1.0.0",
    description="Simple Python agent for testing",
    http_port=9000,
    auto_run=True,
)
class PySimpleAgent:
    pass
