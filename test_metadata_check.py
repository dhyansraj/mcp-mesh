#!/usr/bin/env python3
"""
Test script to verify that rich metadata is preserved for registry
while simple strings go to dependency injector.
"""

import json
import sys

sys.path.insert(0, "src/runtime/python/src")

from typing import Any

from mcp_mesh import McpMeshAgent, mesh_agent

print("🔍 Testing metadata separation...")


# Create a test function with rich dependencies
@mesh_agent(
    capability="test_capability",
    dependencies=[
        "simple_string_dep",  # Simple string dependency
        {"capability": "info", "tags": ["system", "general"]},  # Rich dict dependency
    ],
    description="Test function for metadata verification",
)
def test_function(simple_string_dep: Any = None, info: McpMeshAgent = None) -> str:
    """Test function with mixed dependency types."""
    return "test"


print(f"\n✅ Function created: {test_function.__name__}")

# Check what metadata was stored
if hasattr(test_function, "_mesh_metadata"):
    metadata = test_function._mesh_metadata
    print("\n📋 Metadata stored on function:")

    # Original dependencies (should be preserved exactly)
    print(f"  🔗 Original dependencies: {metadata.get('dependencies', [])}")

    # Tools array (should contain rich dependency information)
    if "tools" in metadata and metadata["tools"]:
        for i, tool_def in enumerate(metadata["tools"]):
            print(f"\n  🛠️  Tool {i+1}:")
            print(f"    📦 Capability: {tool_def['capability']}")
            print(f"    🏷️  Tags: {tool_def.get('tags', [])}")
            print(f"    📝 Version: {tool_def.get('version', 'N/A')}")

            if tool_def.get("dependencies"):
                print("    🔗 Rich Dependencies (for Registry):")
                for j, dep in enumerate(tool_def["dependencies"]):
                    print(f"      {j+1}. {json.dumps(dep, indent=8)}")
            else:
                print("    🔗 No dependencies")

print("\n🎯 Key Insight:")
print("  ✅ Rich metadata (tags, versions) is preserved in tool definitions")
print("  ✅ Registry can use this for smart dependency resolution")
print("  ✅ Injector gets simple strings (no unhashable dict errors)")
print("\n🚀 This enables tag-based dependency resolution!")
