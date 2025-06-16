#!/usr/bin/env python3

"""
Real processor flow test - let the processor handle everything:
1. Use real @mesh.tool decorators
2. Let processor create FastMCP + HTTP server
3. Let processor do registration calls
4. Let processor do DI
5. Test if MCP endpoints work through the real flow
"""

import time

import mesh
from mcp_mesh.types import McpMeshAgent


@mesh.agent(name="real-processor-test", http_port=8130, auto_run=False)
class RealProcessorTestAgent:
    pass


@mesh.tool(capability="real_processor_test")
def test_with_dependency(message: str, agent: McpMeshAgent = None) -> str:
    """Function that expects dependency injection."""
    if agent:
        return f"Message: {message}, Agent type: {type(agent).__name__}"
    else:
        return f"Message: {message}, **NO DEPENDENCY INJECTED**"


@mesh.tool(capability="real_processor_test")
def test_without_dependency(message: str) -> str:
    """Function without dependency injection."""
    return f"Simple message: {message}"


if __name__ == "__main__":
    print("🚀 Starting REAL processor flow test on http://127.0.0.1:8130")
    print("📋 This uses the actual MeshDecoratorProcessor")
    print("📋 The processor will:")
    print("   1. Process @mesh.tool decorators")
    print("   2. Create FastMCP server automatically")
    print("   3. Create HttpMcpWrapper automatically")
    print("   4. Make registration calls to registry")
    print("   5. Set up dependency injection")
    print("   6. Start HTTP server")
    print()
    print("📋 Test commands:")
    print("   curl http://127.0.0.1:8130/health")
    print(
        "   curl -X POST http://127.0.0.1:8130/mcp -H 'Content-Type: application/json' -d '{\"method\": \"tools/list\"}'"
    )
    print(
        '   curl -X POST http://127.0.0.1:8130/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_without_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print(
        '   curl -X POST http://127.0.0.1:8130/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print()
    print("⏳ Waiting for processor to start server...")

    # Keep the script alive so processor can work
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
