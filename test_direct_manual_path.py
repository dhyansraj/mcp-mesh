#!/usr/bin/env python3
"""
Test the improved registration flow by directly using manual path
"""

import asyncio
import logging
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)


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


async def test_direct_manual_path():
    print("🧪 Testing Direct Manual Registration Path")
    print("=" * 50)

    from mcp_mesh.runtime.processor import MeshToolProcessor

    # Set up mock registry
    mock_registry = MockRegistryClient()
    processor = MeshToolProcessor(mock_registry)

    # Mock agent configuration
    agent_config = {
        "name": "direct-test",
        "http_host": "0.0.0.0",
        "http_port": 0,
        "enable_http": True,
        "version": "1.0.0",
        "namespace": "default",
    }

    # Mock tools
    class MockDecoratedFunction:
        def __init__(self, name, capability):
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

    # Replace method to force manual path
    processor._get_agent_configuration = lambda: agent_config

    # Mock the HTTP wrapper setup to return a fake endpoint
    original_setup = processor._setup_http_wrapper_for_tools

    async def mock_http_setup(agent_id, tools, agent_config):
        print(f"🌐 Setting up HTTP wrapper for {agent_id}")
        # Simulate HTTP wrapper startup
        fake_endpoint = "http://127.0.0.1:8889"
        print(f"🚀 HTTP wrapper started for {agent_id}: {fake_endpoint}")
        return fake_endpoint

    processor._setup_http_wrapper_for_tools = mock_http_setup

    print("🔍 Expected to see:")
    print("   • HTTP setup BEFORE registration")
    print("   • Registration with REAL endpoint (not port 0)")
    print("")

    # This should now show the improved flow
    await processor.process_tools(tools)

    print("\n✅ Test completed!")


if __name__ == "__main__":
    asyncio.run(test_direct_manual_path())
