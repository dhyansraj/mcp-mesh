#!/usr/bin/env python3
"""
Test the improved registration flow with mock registry
"""

import asyncio
import logging
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)


# Mock registry to test the flow
class MockRegistryClient:
    def __init__(self):
        self.logger = logging.getLogger("MockRegistry")

    # Mock for manual registration path
    async def register_multi_tool_agent(self, agent_id, metadata):
        # Extract key endpoint info from the registration
        http_host = metadata.get("http_host", "not set")
        http_port = metadata.get("http_port", "not set")
        endpoint = metadata.get("endpoint", "not set")

        self.logger.info("🎯 REGISTRATION PAYLOAD (Manual):")
        self.logger.info(f"   Agent ID: {agent_id}")
        self.logger.info(f"   HTTP Host: {http_host}")
        self.logger.info(f"   HTTP Port: {http_port}")
        self.logger.info(f"   Full Endpoint: {endpoint}")
        self.logger.info(f"   Tools: {len(metadata.get('tools', []))}")

        return {"status": "success"}

    # Mock for generated client path (this gets called first)
    async def post(self, url, **kwargs):
        self.logger.info("🎯 REGISTRATION PAYLOAD (Generated Client):")
        self.logger.info(f"   URL: {url}")

        data = kwargs.get("json") or kwargs.get("data")
        if data and hasattr(data, "http_host"):
            self.logger.info(f"   HTTP Host: {data.http_host}")
            self.logger.info(f"   HTTP Port: {data.http_port}")
            self.logger.info(f"   Endpoint: {getattr(data, 'endpoint', 'not set')}")
            self.logger.info(
                f"   Tools: {len(data.tools) if hasattr(data, 'tools') else 'unknown'}"
            )
        else:
            self.logger.info(f"   Data type: {type(data)}")
            if hasattr(data, "__dict__"):
                for key, value in data.__dict__.items():
                    if key in ["http_host", "http_port", "endpoint"]:
                        self.logger.info(f"   {key}: {value}")

        # Mock successful response
        class MockResponse:
            def __init__(self):
                self.status_code = 200
                self.json_data = {"status": "success"}

            async def json(self):
                return self.json_data

            def is_success(self):
                return True

        return MockResponse()


async def test_improved_flow():
    print("🧪 Testing Improved Registration Flow")
    print("=" * 50)

    from mcp_mesh.runtime.processor import MeshToolProcessor

    # Set up mock registry
    mock_registry = MockRegistryClient()
    processor = MeshToolProcessor(mock_registry)

    # Mock some tools with agent config
    print("1️⃣ Setting up tools with agent config...")

    class MockDecoratedFunction:
        def __init__(self, name, capability):
            self.function = lambda: f"Response from {name}"
            self.function.__name__ = name
            self.metadata = {
                "capability": capability,
                "description": f"Test {name}",
                "version": "1.0.0",
                "tags": ["test"],
                "dependencies": [],
            }

    tools = {"test_function": MockDecoratedFunction("test_function", "test_capability")}

    # Mock agent config
    mock_agent_config = {
        "name": "improved-test",
        "http_host": "0.0.0.0",
        "http_port": 0,  # Auto-assign
        "enable_http": True,
    }

    # Mock the _get_agent_configuration method
    def mock_get_agent_config():
        return mock_agent_config

    processor._get_agent_configuration = mock_get_agent_config

    print("2️⃣ Processing tools with improved flow...")
    print("🔍 Watch for these key messages:")
    print("   • 🌐 Setting up HTTP wrapper FIRST")
    print("   • 🔧 Updated registration with real HTTP endpoint")
    print("   • 🎯 REGISTRATION PAYLOAD with real endpoint")

    await processor.process_tools(tools)

    print("\n✅ Test completed! Check logs above for the improved flow.")


if __name__ == "__main__":
    asyncio.run(test_improved_flow())
