#!/usr/bin/env python3
"""
Test decorator processing timing - what happens without mesh.start_auto_run_service()?
"""

import logging
import os
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🧪 Testing decorator processing without auto-run...")

import mesh


@mesh.agent(name="timing-test-service", auto_run=True, auto_run_interval=10)
class TimingTestAgent:
    pass


@mesh.tool(capability="test1")
def test_function_1():
    return "Test 1"


@mesh.tool(capability="test2")
def test_function_2():
    return "Test 2"


@mesh.tool(capability="test3")
def test_function_3():
    return "Test 3"


print("✅ All decorators defined")
print("🎯 NOT calling mesh.start_auto_run_service()")
print("📊 Let's see what decorator processing completed...")

# Script will exit here - let's see what logs we get
print("🔚 Script ending normally...")
