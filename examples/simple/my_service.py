#!/usr/bin/env python3
"""
Test FastMCP discovery with a non-standard filename.

This file is named 'my_service.py' (no 'fastmcp' or 'agent' in the name)
to test that the discovery works regardless of filename.
"""

import mesh
from fastmcp import FastMCP
from mcp_mesh.types import McpMeshAgent

# FastMCP server with a custom variable name
my_server = FastMCP("Custom Service")


@my_server.tool()
@mesh.tool(capability="greeting_service")
def say_hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@my_server.tool()
@mesh.tool(capability="math_service", dependencies=["greeting_service"])
def add_numbers(a: float, b: float, greeter: McpMeshAgent = None) -> dict:
    """Add two numbers with a greeting."""
    greeting = greeter("Calculator") if greeter else "Hello, Calculator!"
    return {
        "greeting": greeting,
        "operation": "addition",
        "operands": [a, b],
        "result": a + b,
    }


@mesh.agent(
    name="custom-service",
    description="Custom service with non-standard naming",
    http_port=8081,
    auto_run=True,
)
class CustomService:
    """Custom service class."""

    pass
