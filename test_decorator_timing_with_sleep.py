#!/usr/bin/env python3
"""
Test script to verify that decorators can be discovered across different scopes and timing.
"""

import asyncio
import logging
import time

# Set up logging to see the flow
logging.basicConfig(level=logging.WARNING)  # Reduce noise

print("=== Testing Decorator Discovery Across Scopes ===")

# Import mesh
import mesh
from mcp_mesh import DecoratorRegistry

# Define decorators at different "times" and scopes
print("1. Define @mesh.agent at module level")


@mesh.agent(name="scope-test-agent", auto_run=False)
class ModuleLevelAgent:
    pass


print("2. Define @mesh.tool at module level")


@mesh.tool(capability="module-greeting")
def module_level_tool():
    return "Hello from module level!"


def define_decorators_in_function():
    """Define decorators inside a function scope"""
    print("3. Define @mesh.tool inside function scope")

    @mesh.tool(capability="function-greeting")
    def function_scoped_tool():
        return "Hello from function scope!"

    return function_scoped_tool


# Call the function to define function-scoped decorator
function_tool = define_decorators_in_function()

# Wait a bit to simulate time passing
print("4. Sleeping for 1 second to simulate time passing...")
time.sleep(1)

print("5. Define another @mesh.tool after delay")


@mesh.tool(capability="delayed-greeting")
def delayed_tool():
    return "Hello from delayed definition!"


# Check what's in the registry
print("\n=== Registry State ===")
print(f"Mesh agents: {list(DecoratorRegistry.get_mesh_agents().keys())}")
print(f"Mesh tools: {list(DecoratorRegistry.get_mesh_tools().keys())}")

# Test processor discovery
print("\n=== Processor Discovery Test ===")
from mcp_mesh.runtime.processor import MeshToolProcessor


class MockRegistryClient:
    def __init__(self):
        pass

    async def post(self, endpoint, json=None):
        print(f"Registry call: {endpoint}")

        class MockResponse:
            status = 201

            async def json(self):
                return {"status": "success", "dependencies_resolved": {}}

        return MockResponse()


processor = MeshToolProcessor(MockRegistryClient())

# Test if processor can find all decorators regardless of scope/timing
print("\n6. Testing processor discovery...")
agent_config = processor._get_agent_configuration()
print(f"Agent config found: {agent_config['name'] if agent_config else 'None'}")

tools = DecoratorRegistry.get_mesh_tools()
print(f"Tools found: {list(tools.keys())}")


# Test the actual processing
async def test_scoped_processing():
    print("\n7. Testing processor.process_tools() with all discovered tools...")
    results = await processor.process_tools(tools)
    print(f"Processing results: {results}")
    return all(results.values())


success = asyncio.run(test_scoped_processing())
print(f"\n=== Result: All tools processed successfully: {success} ===")

# Test if we can discover decorators defined even later
print("\n8. Define one more @mesh.tool after processor creation...")


@mesh.tool(capability="post-processor-greeting")
def post_processor_tool():
    return "Hello from post-processor definition!"


final_tools = DecoratorRegistry.get_mesh_tools()
print(f"Final tools count: {len(final_tools)}")
print(f"All tool names: {list(final_tools.keys())}")

print("\n=== Scope and Discovery Test Complete ===")
