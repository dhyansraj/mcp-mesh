#!/usr/bin/env python3
"""
Simple Auto-Run Example

This demonstrates the ultimate "magical" experience:
- NO manual FastMCP server creation
- NO manual while True loop
- Just call mesh.start_auto_run_service() at the end!

Run: python example/auto_run_simple.py
"""

import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Import mesh
import mesh


# Define agent with auto-run enabled
@mesh.agent(
    name="simple-auto-service",
    auto_run=True,
    auto_run_interval=10,  # Heartbeat every 10 seconds
)
class SimpleAutoAgent:
    pass


# Define tools
@mesh.tool(capability="greeting")
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}! This service started automatically!"


@mesh.tool(capability="math")
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


@mesh.tool(capability="status")
def get_status() -> dict:
    """Get service status."""
    return {
        "service": "simple-auto-service",
        "status": "running",
        "auto_run": True,
        "tools": ["greeting", "math", "status"],
    }


# 🎉 This is all you need! No while True loop required!
mesh.start_auto_run_service()
