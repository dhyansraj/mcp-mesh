#!/usr/bin/env python3
"""
Test the enhanced MockRegistryClient with Go compatibility mode.

This test verifies that:
1. Python can generate requests in the format Go expects
2. MockRegistryClient returns exact Go response formats
3. Python can parse Go responses correctly
4. No live registry needed for testing
"""

import asyncio

# Import the enhanced mock client
import sys

sys.path.append("tests/mocks/python")
from mock_registry_client import create_mock_registry_client


async def test_go_compatible_mock():
    """Test that Go-compatible mock returns exact Go response formats."""
    print("🧪 Testing Go-compatible MockRegistryClient...")

    # Create mock in Go compatibility mode
    mock_client = create_mock_registry_client(go_compatibility_mode=True)

    # Load the test request that matches what Python should generate
    test_request = {
        "agent_id": "agent-hello-world-123",
        "timestamp": "2024-01-20T10:30:45Z",
        "metadata": {
            "name": "hello-world",
            "agent_type": "mcp_agent",
            "namespace": "default",
            "endpoint": "stdio://agent-hello-world-123",
            "version": "1.0.0",
            "decorators": [
                {
                    "function_name": "hello_mesh_simple",
                    "capability": "greeting",
                    "dependencies": [{"capability": "date_service"}],
                    "description": "Simple greeting with date dependency",
                },
                {
                    "function_name": "hello_mesh_typed",
                    "capability": "advanced_greeting",
                    "dependencies": [
                        {"capability": "info", "tags": ["system", "general"]}
                    ],
                    "description": "Advanced greeting with system info",
                },
                {
                    "function_name": "test_dependencies",
                    "capability": "dependency_test",
                    "dependencies": [
                        {"capability": "date_service"},
                        {"capability": "info", "tags": ["system", "disk"]},
                    ],
                    "description": "Test multiple dependencies",
                },
            ],
        },
    }

    print("📝 Testing decorator registration...")

    # Test registration endpoint
    registration_response = await mock_client.post(
        "/agents/register_decorators", test_request
    )

    print(f"✅ Registration response status: {registration_response.status_code}")
    response_data = await registration_response.json()
    print(f"📄 Registration response keys: {list(response_data.keys())}")

    # Verify response has Go format
    assert response_data["status"] == "success"
    assert response_data["agent_id"] == "agent-hello-world-123"
    assert "dependencies_resolved" in response_data
    assert len(response_data["dependencies_resolved"]) == 3

    # Verify per-function dependency resolution
    resolved = response_data["dependencies_resolved"]

    # Check hello_mesh_simple function
    hello_simple = next(
        r for r in resolved if r["function_name"] == "hello_mesh_simple"
    )
    assert hello_simple["capability"] == "greeting"
    assert len(hello_simple["dependencies"]) == 1
    assert hello_simple["dependencies"][0]["capability"] == "date_service"
    assert hello_simple["dependencies"][0]["status"] == "resolved"
    assert "mcp_tool_info" in hello_simple["dependencies"][0]

    # Check hello_mesh_typed function (should resolve system info with tags)
    hello_typed = next(r for r in resolved if r["function_name"] == "hello_mesh_typed")
    assert hello_typed["capability"] == "advanced_greeting"
    assert len(hello_typed["dependencies"]) == 1
    assert hello_typed["dependencies"][0]["capability"] == "info"
    assert (
        hello_typed["dependencies"][0]["mcp_tool_info"]["agent_id"]
        == "system-agent-789"
    )

    # Check test_dependencies function (should have 2 resolved dependencies)
    test_deps = next(r for r in resolved if r["function_name"] == "test_dependencies")
    assert test_deps["capability"] == "dependency_test"
    assert len(test_deps["dependencies"]) == 2

    print("✅ Registration test passed!")

    print("📝 Testing decorator heartbeat...")

    # Test heartbeat endpoint
    heartbeat_response = await mock_client.post("/heartbeat_decorators", test_request)

    print(f"✅ Heartbeat response status: {heartbeat_response.status_code}")

    # Verify heartbeat response has same structure but different message
    heartbeat_data = await heartbeat_response.json()
    assert heartbeat_data["status"] == "success"
    assert heartbeat_data["message"] == "Heartbeat received"
    assert "dependencies_resolved" in heartbeat_data
    assert len(heartbeat_data["dependencies_resolved"]) == 3

    print("✅ Heartbeat test passed!")

    print("📝 Testing request validation...")

    # Test that invalid requests are rejected
    invalid_request = {"invalid": "request"}
    try:
        await mock_client.post("/agents/register_decorators", invalid_request)
        assert False, "Should have failed validation"
    except ValueError as e:
        print(f"✅ Request validation working: {e}")

    print("🎉 All Go-compatible mock tests passed!")
    print("")
    print("📋 Test Summary:")
    print("  ✅ MockRegistryClient returns exact Go response format")
    print("  ✅ Per-function dependency resolution working")
    print("  ✅ Complex dependency matching (tags, capabilities)")
    print("  ✅ Request validation ensures Go compatibility")
    print("  ✅ Both registration and heartbeat endpoints working")
    print("")
    print("🚀 Ready for Python processor testing with no live registry needed!")


if __name__ == "__main__":
    asyncio.run(test_go_compatible_mock())
