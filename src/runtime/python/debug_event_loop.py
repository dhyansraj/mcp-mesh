#!/usr/bin/env python3

"""
Debug event loop issues with HTTP server startup.
"""

import asyncio

import httpx

import mesh


@mesh.agent(name="debug-agent", http_port=9998, auto_run=False)
class DebugAgent:
    pass


@mesh.tool(capability="test_capability")
def test_function(message: str) -> str:
    """Test function for debugging."""
    return f"Hello {message}"


async def main():
    """Test the MCP endpoints manually with proper event loop management."""

    print("🚀 Starting debug agent with proper event loop...")

    # Get the current event loop
    loop = asyncio.get_event_loop()
    print(f"📍 Current event loop: {loop}")

    # Import the processor directly and test
    from mcp_mesh import DecoratorRegistry
    from mcp_mesh.engine.generated_registry_client import (
        GeneratedRegistryClient as RegistryClient,
    )
    from mcp_mesh.engine.processor import MeshDecoratorProcessor

    # Create registry client
    registry_client = RegistryClient("http://localhost:8000")

    # Create processor
    processor = MeshDecoratorProcessor(registry_client)

    # Get tools
    mesh_tools = DecoratorRegistry.get_mesh_tools()
    print(f"📝 Found {len(mesh_tools)} tools: {list(mesh_tools.keys())}")

    # Process tools (this should start HTTP server)
    print("🔄 Processing tools...")
    results = await processor.process_tools(mesh_tools)
    print(f"📊 Processing results: {results}")

    # Wait a bit for server to start
    print("⏳ Waiting for server to start...")
    await asyncio.sleep(3)

    # Check if server is listening
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        result = sock.connect_ex(("127.0.0.1", 9998))
        if result == 0:
            print("✅ Port 9998 is open and listening")
        else:
            print(f"❌ Port 9998 is not listening (result: {result})")
    finally:
        sock.close()

    # Test health endpoint
    try:
        print("📋 Testing /health endpoint...")
        health_response = httpx.get("http://127.0.0.1:9998/health", timeout=2.0)
        print(f"Health: {health_response.status_code} - {health_response.json()}")
    except Exception as e:
        print(f"❌ Health endpoint failed: {e}")
        return

    # Test tools/list endpoint
    try:
        print("📋 Testing /mcp tools/list endpoint...")
        list_response = httpx.post(
            "http://127.0.0.1:9998/mcp", json={"method": "tools/list"}, timeout=5.0
        )
        print(f"Tools/list: {list_response.status_code} - {list_response.json()}")
    except Exception as e:
        print(f"❌ Tools/list endpoint failed: {e}")
        return

    print("✅ All tests completed successfully!")

    # Keep event loop alive for a bit
    print("⏳ Keeping event loop alive...")
    await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
