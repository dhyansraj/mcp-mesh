#!/usr/bin/env python3
"""
Test script for simplified MCP Mesh pipeline.

This script tests the basic decorator → registry → heartbeat flow
without the complex features like FastMCP, HTTP wrappers, etc.
"""

import asyncio
import os
import sys

# Enable MCP Mesh runtime
os.environ["MCP_MESH_ENABLED"] = "true"

# Import the decorators to test
import mesh
from _mcp_mesh.pipeline.startup_orchestrator import process_decorators_once


# Test decorators
@mesh.tool(capability="test_capability")
def test_function():
    """Test function for pipeline verification."""
    return "Hello from test function!"


@mesh.tool(capability="dependent_capability", dependencies=["test_capability"])
def dependent_function(test_service=None):
    """Test function with dependencies."""
    if test_service:
        return f"Dependent function called test_service: {test_service}"
    return "Dependent function called without test_service"


async def main():
    """Test the MCP Mesh pipeline."""
    print("🧪 Testing MCP Mesh pipeline...")

    try:
        # Execute the pipeline once
        result = await process_decorators_once()

        # Print results
        print("\n📊 Pipeline Result:")
        print(f"   Status: {result['status']}")
        print(f"   Message: {result['message']}")
        print(f"   Errors: {len(result['errors'])}")

        if result["errors"]:
            print("   Error details:")
            for error in result["errors"]:
                print(f"     - {error}")

        print("\n📋 Context Summary:")
        context = result.get("context", {})
        pipeline_context = context.get("pipeline_context", {})

        # Print key metrics
        print(f"   Agents: {pipeline_context.get('agent_count', 0)}")
        print(f"   Tools: {pipeline_context.get('tool_count', 0)}")
        print(f"   Agent ID: {pipeline_context.get('agent_id', 'unknown')}")
        print(
            f"   Pipeline Steps: {context.get('executed_steps', 0)}/{context.get('total_steps', 0)}"
        )

        # Print tools found
        tools_list = pipeline_context.get("tools_list", [])
        if tools_list:
            print("\n🔧 Tools Discovered:")
            for tool in tools_list:
                deps = tool.get("dependencies", [])
                dep_count = len(deps)
                print(
                    f"   - {tool['function_name']} (capability: {tool['capability']}, deps: {dep_count})"
                )

        # Print dependencies resolved
        deps_resolved = pipeline_context.get("dependencies_resolved", {})
        if deps_resolved and isinstance(deps_resolved, dict):
            print("\n🔗 Dependencies Resolved:")
            for dep_name, dep_info in deps_resolved.items():
                if isinstance(dep_info, dict):
                    status = dep_info.get("status", "unknown")
                    agent = dep_info.get("agent_id", "unknown")
                    print(f"   - {dep_name}: {status} (agent: {agent})")
                else:
                    print(f"   - {dep_name}: {dep_info}")

        print("\n✅ Pipeline test completed!")

        return result["status"] == "success"

    except Exception as e:
        print(f"\n💥 Pipeline test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
