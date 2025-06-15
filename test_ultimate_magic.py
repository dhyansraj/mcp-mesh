#!/usr/bin/env python3
"""
ULTIMATE MAGIC TEST - Absolutely no manual anything!

This should demonstrate the pure magic experience:
- Just import mesh
- Define @mesh.agent(auto_run=True)
- Define @mesh.tool functions
- Script stays alive automatically!
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🌟 ULTIMATE MAGIC TEST")
print("Just decorators - NO manual calls at all!")
print("=" * 50)

import mesh


@mesh.agent(name="ultimate-magic", auto_run=True, auto_run_interval=5)
class UltimateMagicAgent:
    pass


@mesh.tool(capability="ultimate_greeting")
def ultimate_hello(name: str = "Ultimate User") -> str:
    return f"🌟 Ultimate magic hello, {name}! This is PURE MAGIC!"


@mesh.tool(capability="ultimate_status")
def ultimate_status() -> dict:
    return {
        "service": "ultimate-magic",
        "magic_level": "🌟 ULTIMATE 🌟",
        "manual_calls": 0,
        "auto_run": True,
    }


print("✨ Magic happens here - script should stay alive!")

# Absolutely nothing else - pure magic!
