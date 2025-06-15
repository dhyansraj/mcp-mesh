#!/usr/bin/env python3
"""
Test HTTP endpoint update functionality
"""

import asyncio
import logging
import sys

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.DEBUG)


# Mock registry - just log what would be sent
class MockRegistryClient:
    def __init__(self):
        self.logger = logging.getLogger("MockRegistry")

    async def register_multi_tool_agent(self, agent_id, metadata):
        self.logger.info(f"📝 INITIAL REGISTRATION - Agent: {agent_id}")
        self.logger.info(f"   HTTP Host: {metadata.get('http_host', 'not set')}")
        self.logger.info(f"   HTTP Port: {metadata.get('http_port', 'not set')}")
        return {"status": "success"}

    async def update_agent_endpoint(self, endpoint_data):
        self.logger.info(f"🔄 ENDPOINT UPDATE - Agent: {endpoint_data['agent_id']}")
        self.logger.info(f"   HTTP Host: {endpoint_data['http_host']}")
        self.logger.info(f"   HTTP Port: {endpoint_data['http_port']}")
        self.logger.info(f"   Full Endpoint: {endpoint_data['endpoint']}")
        return {"status": "success"}


async def test_endpoint_update_flow():
    """Test the full endpoint update flow"""

    print("🧪 Testing HTTP Endpoint Update Flow")
    print("=" * 50)

    # Import the processor
    from mcp_mesh.runtime.processor import MeshToolProcessor

    # Set up mock registry
    mock_registry = MockRegistryClient()
    processor = MeshToolProcessor(mock_registry)

    # Mock some tools
    print("1️⃣ Setting up mock tools...")

    # Mock decorated function
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

    tools = {
        "test_tool_1": MockDecoratedFunction("test_tool_1", "test1"),
        "test_tool_2": MockDecoratedFunction("test_tool_2", "test2"),
    }

    print("2️⃣ Processing tools (this will register with http_port=0)...")
    await processor.process_tools(tools)

    print("\n3️⃣ Simulating HTTP wrapper startup...")
    # Simulate what happens when HTTP wrapper starts
    agent_id = "test-agent-12345"
    http_endpoint = "http://127.0.0.1:8889"

    print(f"4️⃣ Updating registration with endpoint: {http_endpoint}")
    await processor._update_agent_registration_with_http_endpoint(
        agent_id, http_endpoint
    )

    print("\n✅ Test completed! Check logs above to see:")
    print("   • Initial registration with http_port=0")
    print("   • Endpoint update with actual host/port/endpoint")


if __name__ == "__main__":
    asyncio.run(test_endpoint_update_flow())
