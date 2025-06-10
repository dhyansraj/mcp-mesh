#!/usr/bin/env python3
"""
Debug script to check if HTTP wrapper is being initialized
"""

import logging
import os
import time

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Set environment
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8080"
os.environ["MCP_MESH_DEBUG"] = "true"

print("=== Testing HTTP Wrapper Initialization ===\n")

# Import to check what happens
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

print("1. Creating a simple test function with HTTP enabled...")

server = FastMCP(name="test-server")


@server.tool()
@mesh_agent(capability="test", enable_http=True, http_port=9999, health_interval=5)
def test_function():
    """Test function with HTTP enabled."""
    return "Hello from test"


print("2. Decorator applied. Checking for HTTP wrapper initialization...")

# Check if the function has HTTP wrapper attributes
print("\nFunction attributes:")
for attr in dir(test_function):
    if "http" in attr.lower() or "wrapper" in attr.lower():
        print(f"  - {attr}: {getattr(test_function, attr, 'N/A')}")

# Check decorator instance
if hasattr(test_function, "_mesh_decorator_instance"):
    decorator = test_function._mesh_decorator_instance
    print("\nDecorator instance found:")
    print(f"  - enable_http: {decorator.enable_http}")
    print(f"  - http_port: {decorator.http_port}")
    print(f"  - _http_wrapper: {decorator._http_wrapper}")
    print(f"  - _initialized: {decorator._initialized}")

print("\n3. Waiting 5 seconds to see if background initialization happens...")
time.sleep(5)

# Check again
if hasattr(test_function, "_mesh_decorator_instance"):
    decorator = test_function._mesh_decorator_instance
    print("\nAfter waiting:")
    print(f"  - _http_wrapper: {decorator._http_wrapper}")
    print(f"  - _initialized: {decorator._initialized}")

print("\n4. Checking if any HTTP servers are running...")
import subprocess

result = subprocess.run(["netstat", "-tlnp"], capture_output=True, text=True)
if "9999" in result.stdout:
    print("✅ HTTP server found on port 9999!")
else:
    print("❌ No HTTP server on port 9999")

print("\n5. The issue: HTTP wrapper initialization happens in _initialize() method")
print(
    "   but _initialize() is called in a background thread that may not be running properly."
)

# Try to manually trigger initialization
print("\n6. Attempting manual initialization...")
if hasattr(test_function, "_mesh_decorator_instance"):
    decorator = test_function._mesh_decorator_instance
    import asyncio

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(decorator._initialize())
        print("✅ Manual initialization completed")

        # Check HTTP wrapper again
        print(f"  - _http_wrapper: {decorator._http_wrapper}")
        if decorator._http_wrapper:
            print(f"  - HTTP endpoint: {decorator._http_endpoint}")
    except Exception as e:
        print(f"❌ Manual initialization failed: {e}")
        import traceback

        traceback.print_exc()
