#!/usr/bin/env python3
"""
Test script to understand the timing of decorator registration and MeshToolProcessor processing.
"""

import asyncio
import logging

# Set up logging to see the flow
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)

print("=== STEP 1: Import mesh ===")
import mesh

print("=== STEP 2: Check DecoratorRegistry state ===")
from mcp_mesh import DecoratorRegistry

print(f"Mesh agents: {list(DecoratorRegistry.get_mesh_agents().keys())}")
print(f"Mesh tools: {list(DecoratorRegistry.get_mesh_tools().keys())}")

print("=== STEP 3: Define @mesh.agent decorator ===")


@mesh.agent(name="test-agent", auto_run=False)
class TestAgent:
    pass


print("=== STEP 4: Check DecoratorRegistry after @mesh.agent ===")
print(f"Mesh agents: {list(DecoratorRegistry.get_mesh_agents().keys())}")
print(f"Mesh tools: {list(DecoratorRegistry.get_mesh_tools().keys())}")

print("=== STEP 5: Define @mesh.tool decorator ===")


@mesh.tool(capability="greeting")
def say_hello():
    return "Hello!"


print("=== STEP 6: Check DecoratorRegistry after @mesh.tool ===")
print(f"Mesh agents: {list(DecoratorRegistry.get_mesh_agents().keys())}")
print(f"Mesh tools: {list(DecoratorRegistry.get_mesh_tools().keys())}")

print("=== STEP 7: Check if MeshToolProcessor would find decorators ===")
# Simulate what MeshToolProcessor._get_agent_configuration() does
mesh_agents = DecoratorRegistry.get_mesh_agents()
if mesh_agents:
    for func_name, decorated_func in mesh_agents.items():
        metadata = decorated_func.metadata
        print(f"Found @mesh.agent config: {metadata}")
else:
    print("No @mesh.agent decorators found by processor")

mesh_tools = DecoratorRegistry.get_mesh_tools()
if mesh_tools:
    for func_name, decorated_func in mesh_tools.items():
        metadata = decorated_func.metadata
        print(f"Found @mesh.tool: {func_name} with metadata: {metadata}")
else:
    print("No @mesh.tool decorators found by processor")

print("=== STEP 8: Import and check runtime processor ===")
from mcp_mesh.runtime.processor import MeshToolProcessor


# Create a mock registry client
class MockRegistryClient:
    def __init__(self):
        pass

    async def post(self, endpoint, json=None):
        print(f"MockRegistryClient.post({endpoint}, {json})")

        class MockResponse:
            status = 201

            async def json(self):
                return {"status": "success", "dependencies_resolved": {}}

        return MockResponse()


mock_client = MockRegistryClient()
processor = MeshToolProcessor(mock_client)

print("=== STEP 9: Test processor._get_agent_configuration() ===")
agent_config = processor._get_agent_configuration()
print(f"Agent config found by processor: {agent_config}")

print("=== STEP 10: Test processor.process_tools() ===")


async def test_processing():
    tools = DecoratorRegistry.get_mesh_tools()
    print(f"Tools to process: {list(tools.keys())}")

    results = await processor.process_tools(tools)
    print(f"Processing results: {results}")


# Run the async test
asyncio.run(test_processing())

print("=== TIMING ANALYSIS COMPLETE ===")
