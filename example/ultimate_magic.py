#!/usr/bin/env python3
"""
🌟 ULTIMATE MAGIC EXAMPLE 🌟

This demonstrates the ultimate "magical" experience:
- Just import mesh
- Define @mesh.agent(auto_run=True)
- Define @mesh.tool functions
- NO manual calls needed!
- Script automatically stays alive!

Run: python example/ultimate_magic.py
"""

import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🌟 ULTIMATE MAGIC - NO MANUAL CALLS NEEDED!")
print("=" * 60)
print("✨ Just decorators - script will stay alive automatically!")

import mesh


@mesh.agent(
    name="ultimate-magic-service",
    version="1.0.0",
    description="Ultimate magic auto-run service",
    auto_run=True,
    auto_run_interval=8,
)
class UltimateMagicAgent:
    """Ultimate magic agent - no manual lifecycle management needed."""

    pass


@mesh.tool(capability="ultimate_greeting")
def ultimate_hello(name: str = "Magic User") -> str:
    """Ultimate magical greeting."""
    return f"🌟 Ultimate magic hello, {name}! This service started COMPLETELY automatically!"


@mesh.tool(capability="ultimate_math")
def ultimate_calculate(operation: str, a: float, b: float) -> dict:
    """Ultimate magical calculator."""
    operations = {
        "add": a + b,
        "multiply": a * b,
        "power": a**b,
        "magic": a * b + 42,  # Add some magic!
    }

    return {
        "operation": operation,
        "result": operations.get(operation, "Unknown operation"),
        "magic_level": "🌟 ULTIMATE 🌟",
        "auto_run": True,
    }


@mesh.tool(capability="ultimate_status")
def ultimate_status() -> dict:
    """Get ultimate service status."""
    return {
        "service": "ultimate-magic-service",
        "status": "🌟 RUNNING WITH ULTIMATE MAGIC 🌟",
        "manual_calls_required": 0,
        "auto_run_enabled": True,
        "magic_level": "MAXIMUM",
        "features": [
            "✨ Automatic service startup",
            "🚀 Auto-created FastMCP server",
            "🌐 Auto-configured HTTP endpoints",
            "💓 Automatic keep-alive heartbeats",
            "🛑 Graceful shutdown handling",
        ],
    }


print("✅ All decorators defined")
print("🪄 NO mesh.start_auto_run_service() call needed!")
print("🎯 NO while True loop needed!")
print("✨ Script will automatically stay alive via atexit magic!")

# 🎉 ABSOLUTELY NO MANUAL CALLS NEEDED!
# The script will automatically stay alive thanks to the atexit handler!
