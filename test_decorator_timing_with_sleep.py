#!/usr/bin/env python3
"""
Test decorator processing timing - with manual sleep to keep process alive
"""

import logging
import os
import sys
import time

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

print("🧪 Testing decorator processing WITH manual sleep...")

import mesh


@mesh.agent(name="timing-test-with-sleep", auto_run=True, auto_run_interval=10)
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
print("🔄 Adding manual sleep to keep process alive...")

# Manual sleep to give background processor time
time.sleep(15)

print("🔚 Script ending after sleep...")
