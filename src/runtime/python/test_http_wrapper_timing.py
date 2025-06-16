#!/usr/bin/env python3

"""
Test with HttpMcpWrapper - exactly like processor uses:
1. Create FastMCP server with original functions
2. Wrap with HttpMcpWrapper (like processor does)
3. Start HTTP server
4. Test original functions
5. Update function pointers with DI
6. Test if MCP calls still work through HttpMcpWrapper
"""

import asyncio

from mcp.server.fastmcp import FastMCP

import mesh
from mcp_mesh.runtime.http_wrapper import HttpConfig, HttpMcpWrapper
from mcp_mesh.types import McpMeshAgent


# Mock dependency object
class MockAgent:
    def __init__(self, name: str):
        self.name = name

    def get_info(self) -> str:
        return f"Mock agent: {self.name}"


# Create FastMCP server
server = FastMCP("http-wrapper-test")


@mesh.agent(name="http-wrapper-test", http_port=8129, auto_run=False)
class HttpWrapperTestAgent:
    pass


@mesh.tool(capability="http_wrapper_test")
def test_with_dependency(message: str, agent: McpMeshAgent = None) -> str:
    """Function that expects dependency injection."""
    if agent:
        return f"Message: {message}, Agent: {agent.get_info()}"
    else:
        return f"Message: {message}, **ORIGINAL FUNCTION - NO DI**"


@mesh.tool(capability="http_wrapper_test")
def test_without_dependency(message: str) -> str:
    """Function without dependency injection."""
    return f"Simple message: {message}"


# Global variables
http_wrapper = None
di_applied = False


def setup_original_functions():
    """Setup original functions with FastMCP."""
    global di_applied
    print("📝 Setting up ORIGINAL functions")
    server.tool()(test_with_dependency)
    server.tool()(test_without_dependency)
    di_applied = False
    print("✅ Original functions registered with FastMCP")


async def setup_http_wrapper():
    """Setup HttpMcpWrapper - exactly like processor does."""
    global http_wrapper

    print("🌐 Setting up HttpMcpWrapper...")

    # Create HTTP config
    config = HttpConfig(host="127.0.0.1", port=8129)

    # Create wrapper - this is what processor does
    http_wrapper = HttpMcpWrapper(server, config)

    # Setup wrapper (creates FastAPI app and endpoints)
    await http_wrapper.setup()

    # Start HTTP server
    await http_wrapper.start()

    print(f"✅ HttpMcpWrapper started on {http_wrapper.get_endpoint()}")


def apply_di_manually():
    """Manually apply DI to running server."""
    global di_applied

    if di_applied:
        return "DI already applied"

    print("🔄 Manually applying DI to HttpMcpWrapper...")

    # Create mock agent
    mock_agent = MockAgent("http-wrapper-test-agent")

    # Create DI-enhanced function
    def di_enhanced_function(message: str, agent: McpMeshAgent = None) -> str:
        print(f"🔄 DI wrapper called via HttpMcpWrapper with message='{message}'")
        return f"Message: {message}, Agent: {mock_agent.get_info()}"

    # Update FastMCP tool manager - same as processor does
    if "test_with_dependency" in server._tool_manager._tools:
        tool = server._tool_manager._tools["test_with_dependency"]
        print(f"   Before DI - tool.fn: {tool.fn}")
        tool.fn = di_enhanced_function
        print(f"   After DI - tool.fn: {tool.fn}")
        di_applied = True
        print("✅ DI applied to HttpMcpWrapper!")
        return "DI applied successfully"
    else:
        return "Tool not found"


async def test_sequence():
    """Run the test sequence."""
    print("🚀 Starting HttpMcpWrapper timing test")

    # Step 1: Setup original functions
    setup_original_functions()

    # Step 2: Setup HttpMcpWrapper
    await setup_http_wrapper()

    print("\n" + "=" * 50)
    print("✅ Server ready! Test commands:")
    print("📋 Health check: curl http://127.0.0.1:8129/health")
    print(
        '📋 Test BEFORE DI: curl -X POST http://127.0.0.1:8129/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Before"}}}\''
    )
    print(
        '📋 Apply DI: python -c "import test_http_wrapper_timing; test_http_wrapper_timing.apply_di_manually()"'
    )
    print(
        '📋 Test AFTER DI: curl -X POST http://127.0.0.1:8129/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "After"}}}\''
    )
    print("=" * 50)

    # Wait for manual testing
    print("\n⏳ Waiting 10 seconds for manual testing...")
    await asyncio.sleep(10)

    # Apply DI automatically after 10 seconds
    print("\n🔄 Auto-applying DI after 10 seconds...")
    result = apply_di_manually()
    print(f"DI result: {result}")

    # Keep server running
    print("\n⏳ Server will run for another 30 seconds for testing...")
    await asyncio.sleep(30)

    # Cleanup
    if http_wrapper:
        await http_wrapper.stop()

    print("✅ Test completed!")


if __name__ == "__main__":
    try:
        asyncio.run(test_sequence())
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
        # Try to cleanup
        if http_wrapper:
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(http_wrapper.stop())
            except:
                pass
