#!/usr/bin/env python3
"""
Test the improved registration flow using manual path
"""

import asyncio
import logging
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)


# Force manual registration by making generated client unavailable
class MockRegistryClient:
    def __init__(self):
        self.logger = logging.getLogger("MockRegistry")

    async def register_multi_tool_agent(self, agent_id, metadata):
        # Extract key endpoint info from the registration
        http_host = metadata.get("http_host", "not set")
        http_port = metadata.get("http_port", "not set")
        endpoint = metadata.get("endpoint", "not set")

        self.logger.info("🎯 REGISTRATION PAYLOAD:")
        self.logger.info(f"   Agent ID: {agent_id}")
        self.logger.info(f"   HTTP Host: {http_host}")
        self.logger.info(f"   HTTP Port: {http_port}")
        self.logger.info(f"   Full Endpoint: {endpoint}")
        self.logger.info(f"   Tools: {len(metadata.get('tools', []))}")

        return {"status": "success"}


async def test_manual_registration_flow():
    print("🧪 Testing Manual Registration Flow (Shows Real Endpoint)")
    print("=" * 60)

    from mcp_mesh.runtime.processor import MeshToolProcessor

    # Set up mock registry that doesn't have .post method (forces manual path)
    mock_registry = MockRegistryClient()
    processor = MeshToolProcessor(mock_registry)

    # Mock some tools with agent config
    class MockDecoratedFunction:
        def __init__(self, name, capability):
            # Create a real function that can be used with FastMCP
            def mock_func():
                return f"Response from {name}"

            mock_func.__name__ = name

            self.function = mock_func
            self.metadata = {
                "capability": capability,
                "description": f"Test {name}",
                "version": "1.0.0",
                "tags": ["test"],
                "dependencies": [],
            }

    tools = {"test_function": MockDecoratedFunction("test_function", "test_capability")}

    # Mock agent config to enable HTTP
    mock_agent_config = {
        "name": "endpoint-test",
        "http_host": "0.0.0.0",
        "http_port": 0,  # Auto-assign
        "enable_http": True,
    }

    # Mock the _get_agent_configuration method
    processor._get_agent_configuration = lambda: mock_agent_config

    print("🔍 Expected flow:")
    print("   1. 🌐 Setting up HTTP wrapper FIRST")
    print("   2. 🚀 HTTP wrapper started with real port")
    print("   3. 🔧 Updated registration with real HTTP endpoint")
    print("   4. 🎯 REGISTRATION PAYLOAD showing real endpoint")
    print("")

    # Process tools - this should now show the improved flow
    await processor.process_tools(tools)

    print("\n✅ Test completed!")


if __name__ == "__main__":
    asyncio.run(test_manual_registration_flow())
