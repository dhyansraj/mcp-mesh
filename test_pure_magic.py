#!/usr/bin/env python3
"""
The Ultimate Magic Test - NO manual calls at all!

Just define decorators and run the script.
The decorator processor should automatically:
1. Register agents and tools
2. Create FastMCP server
3. Start HTTP wrapper
4. Start keep-alive loop automatically
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🪄 PURE MAGIC TEST - NO manual calls!")
print("=" * 50)

import mesh


@mesh.agent(name="pure-magic-service", auto_run=True, auto_run_interval=8)
class PureMagicAgent:
    pass


@mesh.tool(capability="magic_greeting")
def magic_hello(name: str = "Magician") -> str:
    return f"✨ Magic hello, {name}! This service started completely automatically!"


@mesh.tool(capability="magic_math")
def magic_multiply(a: float, b: float) -> float:
    return a * b * 1.01  # Add a little magic


@mesh.tool(capability="magic_status")
def magic_status() -> dict:
    return {
        "service": "pure-magic-service",
        "status": "✨ PURE MAGIC ✨",
        "auto_run": True,
        "magic_level": "MAXIMUM",
    }


print("✅ All decorators defined")
print("🎯 NO mesh.start_auto_run_service() call!")
print("🪄 Let the magic happen automatically...")

# Give background processor a moment to detect auto-run and take over
import time

print("⏳ Giving background processor 3 seconds to detect auto-run...")
time.sleep(3)

# NO manual calls - script should stay alive automatically!
print("🔚 Script logic complete - if auto-run works, this won't exit!")
