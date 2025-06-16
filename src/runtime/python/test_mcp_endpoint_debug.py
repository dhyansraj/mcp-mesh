#!/usr/bin/env python3

"""
Quick test script to debug MCP endpoint hanging issue.
"""

import asyncio

import httpx

import mesh


@mesh.agent(name="debug-agent", http_port=9999, auto_run=False)
class DebugAgent:
    pass


@mesh.tool(capability="test_capability")
def test_function(message: str) -> str:
    """Test function for debugging."""
    return f"Hello {message}"


async def test_mcp_endpoints():
    """Test the MCP endpoints manually."""

    # Start the auto_run service manually in background
    print("🚀 Starting debug agent...")

    # Import start_auto_run_service
    from mesh.decorators import start_auto_run_service

    # Start the service in a background task
    def run_service():
        try:
            start_auto_run_service()
        except KeyboardInterrupt:
            print("Service stopped")

    import threading

    service_thread = threading.Thread(target=run_service, daemon=True)
    service_thread.start()

    # Wait for server to start
    print("⏳ Waiting for server to start...")
    await asyncio.sleep(3)

    # Test health endpoint
    try:
        print("📋 Testing /health endpoint...")
        health_response = httpx.get("http://127.0.0.1:9999/health", timeout=2.0)
        print(f"Health: {health_response.status_code} - {health_response.json()}")
    except Exception as e:
        print(f"❌ Health endpoint failed: {e}")
        return

    # Test tools/list endpoint
    try:
        print("📋 Testing /mcp tools/list endpoint...")
        list_response = httpx.post(
            "http://127.0.0.1:9999/mcp", json={"method": "tools/list"}, timeout=5.0
        )
        print(f"Tools/list: {list_response.status_code} - {list_response.json()}")
    except Exception as e:
        print(f"❌ Tools/list endpoint failed: {e}")
        return

    # Test tools/call endpoint
    try:
        print("📋 Testing /mcp tools/call endpoint...")
        call_response = httpx.post(
            "http://127.0.0.1:9999/mcp",
            json={
                "method": "tools/call",
                "params": {"name": "test_function", "arguments": {"message": "World"}},
            },
            timeout=5.0,
        )
        print(f"Tools/call: {call_response.status_code} - {call_response.json()}")
    except Exception as e:
        print(f"❌ Tools/call endpoint failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_mcp_endpoints())
