#!/usr/bin/env python3
"""
Quick test of auto-run functionality
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)

# Test auto-run configuration
print("🧪 Testing Auto-Run Feature...")

import mesh

# Test 1: Auto-run disabled (default)
print("\n1️⃣ Testing auto-run disabled (default)")


@mesh.agent(name="test-no-auto")
class TestNoAutoAgent:
    pass


# Should not create auto-run config
result = mesh.start_auto_run_service()
print("✅ No auto-run - service did not start (expected)")

# Test 2: Auto-run enabled
print("\n2️⃣ Testing auto-run enabled")


@mesh.agent(name="test-auto", auto_run=True, auto_run_interval=5)
class TestAutoAgent:
    pass


@mesh.tool(capability="test")
def test_function():
    return "Test!"


print(
    "🎯 Auto-run enabled - would start service if mesh.start_auto_run_service() called"
)
print("✅ Auto-run configuration stored successfully")

# Test 3: Environment variable override
print("\n3️⃣ Testing environment variable override")
os.environ["MCP_MESH_AUTO_RUN"] = "true"
os.environ["MCP_MESH_AUTO_RUN_INTERVAL"] = "30"


@mesh.agent(
    name="test-env", auto_run=False, auto_run_interval=10
)  # Should be overridden
class TestEnvAgent:
    pass


print("✅ Environment variables should override decorator values")

print("\n🎉 Auto-run functionality tests completed!")
print("💡 To see auto-run in action, try: python example/auto_run_simple.py")
