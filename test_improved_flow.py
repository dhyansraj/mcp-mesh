#!/usr/bin/env python3
"""
Test the improved registration flow
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🧪 Testing Improved Registration Flow")
print("=" * 50)

import mesh


@mesh.agent(name="improved-test")
class ImprovedTestAgent:
    pass


@mesh.tool(capability="test_capability")
def test_function() -> str:
    return "Test response"


print("✅ Decorators defined")
print("🔍 Look for these log messages:")
print("   1. 🌐 Setting up HTTP wrapper FIRST")
print("   2. 🔧 Updated registration with real HTTP endpoint")
print("   3. 📝 Registering with real endpoint info")

# Let it auto-run
print("⏳ Auto-run should show the improved flow...")
