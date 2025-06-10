#!/usr/bin/env python3
"""
Check if HTTP wrapper is available and why it might not be starting
"""

import os

os.environ["MCP_MESH_DEBUG"] = "true"

print("=== Checking HTTP Wrapper Availability ===\n")

# Check if HTTP wrapper can be imported
try:
    from mcp_mesh_runtime.server.http_wrapper import HttpMcpWrapper

    print("✅ HttpMcpWrapper can be imported")
    print(f"   Location: {HttpMcpWrapper.__module__}")
except ImportError as e:
    print(f"❌ Cannot import HttpMcpWrapper: {e}")

# Check the decorator module
try:
    import mcp_mesh_runtime.decorators.mesh_agent as ma

    print("\n✅ mesh_agent module loaded")
    print(f"   HTTP_WRAPPER_AVAILABLE: {ma.HTTP_WRAPPER_AVAILABLE}")
    print(f"   HttpMcpWrapper: {ma.HttpMcpWrapper}")
except Exception as e:
    print(f"❌ Error checking mesh_agent module: {e}")

# Check if FastAPI is available (required for HTTP wrapper)
try:
    import fastapi
    import uvicorn

    print("\n✅ Required dependencies available:")
    print(f"   FastAPI version: {fastapi.__version__}")
    print("   Uvicorn available: Yes")
except ImportError as e:
    print(f"\n❌ Missing dependency: {e}")
    print("   The HTTP wrapper requires: pip install fastapi uvicorn")

print("\n=== The Issue ===")
print("The HTTP wrapper initialization happens in a background thread,")
print("but the event loop is closed immediately after initialization.")
print("This causes the HTTP server to start and then stop right away.")
print("\nThe fix would be to keep the event loop running in the background thread.")
