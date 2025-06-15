#!/usr/bin/env python3
"""
🌟 PURE SIMPLICITY EXAMPLE 🌟

The absolute simplest possible MCP service:
- Import mesh
- Define @mesh.agent (auto_run=True by default!)
- Define @mesh.tool
- Done! Script stays alive automatically!

Run: python example/pure_simplicity.py
"""

import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🌟 PURE SIMPLICITY - The Simplest MCP Service!")
print("=" * 60)

import mesh


@mesh.agent(name="simple-service")  # auto_run=True by default now!
class SimpleAgent:
    pass


@mesh.tool(capability="greeting")
def hello(name: str = "World") -> str:
    """Simple greeting function."""
    return f"Hello, {name}! From the simplest MCP service ever!"


@mesh.tool(capability="math")
def add(a: float, b: float) -> float:
    """Simple addition."""
    return a + b


print("✅ That's it! Just 2 decorators and 2 functions!")
print("🪄 Script will automatically stay alive!")
print("🚀 No auto_run=True needed - it's the default!")

# 🎉 ABSOLUTELY NOTHING ELSE NEEDED!
# auto_run=True by default = ultimate simplicity!
