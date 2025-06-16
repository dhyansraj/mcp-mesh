#!/usr/bin/env python3

"""
Simple test to check MCP endpoint without dependencies
"""

import mesh


@mesh.agent(name="simple-test", http_port=8124, auto_run=True)
class SimpleTestAgent:
    pass


@mesh.tool(capability="simple_test")
def simple_function(message: str = "World") -> str:
    """Simple function without dependencies."""
    return f"Hello {message}!"


print("🚀 Simple test agent started on http://127.0.0.1:8124")
print(
    "📋 Test with: curl -X POST http://127.0.0.1:8124/mcp -H 'Content-Type: application/json' -d '{\"method\": \"tools/list\"}'"
)
print("🛑 Press Ctrl+C to stop")
