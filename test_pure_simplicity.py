#!/usr/bin/env python3
"""
🌟 PURE SIMPLICITY TEST 🌟

The absolute simplest possible MCP service:
- Import mesh
- Define @mesh.agent (auto_run=True by default now!)
- Define @mesh.tool
- Done! Script stays alive automatically!
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🌟 PURE SIMPLICITY - auto_run=True by default!")
print("=" * 50)

import mesh


@mesh.agent(name="simple-service")  # No auto_run=True needed!
class SimpleAgent:
    pass


@mesh.tool(capability="greeting")
def hello() -> str:
    return "Hello from the simplest possible MCP service!"


print("✅ That's it! Script will stay alive automatically!")

# NO manual calls - auto_run=True by default!
