#!/usr/bin/env python3

"""
Test async DI timing - exactly like processor behavior:
1. Start MCP server with original functions
2. Server runs and serves requests
3. Wait 5 seconds (simulating registry call)
4. Update function pointers with DI-enhanced versions
5. Test if MCP calls work after async update
"""

import asyncio
import inspect
import threading

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

import mesh
from mcp_mesh.types import McpMeshAgent


# Mock dependency object
class MockAgent:
    def __init__(self, name: str):
        self.name = name

    def get_info(self) -> str:
        return f"Mock agent: {self.name}"


# Create FastMCP server
server = FastMCP("async-di-test")


@mesh.agent(name="async-di-test", http_port=8127, auto_run=False)
class AsyncDITestAgent:
    pass


@mesh.tool(capability="async_di_test")
def test_with_dependency(message: str, agent: McpMeshAgent = None) -> str:
    """Function that expects dependency injection."""
    if agent:
        return f"Message: {message}, Agent: {agent.get_info()}"
    else:
        return f"Message: {message}, No agent injected (ORIGINAL FUNCTION)"


@mesh.tool(capability="async_di_test")
def test_without_dependency(message: str) -> str:
    """Function without dependency injection."""
    return f"Simple message: {message}"


def initial_setup():
    """Initial setup - register original functions with FastMCP."""
    print("📝 Step 1: Register ORIGINAL functions with FastMCP")
    server.tool()(test_with_dependency)
    server.tool()(test_without_dependency)
    print("✅ Original functions registered")


async def simulate_registry_call_and_di():
    """Simulate registry call delay and then perform DI update."""
    print("🔄 Step 2: Simulating registry call...")
    print("   MCP server is running with ORIGINAL functions")

    # Wait 5 seconds - simulating registry call
    await asyncio.sleep(5)

    print("📡 Step 3: Registry responded! Processing DI...")

    # Analyze function for DI needs
    sig = inspect.signature(test_with_dependency)
    needs_injection = any(
        param.annotation == McpMeshAgent for param in sig.parameters.values()
    )
    print(f"   test_with_dependency needs injection: {needs_injection}")

    if needs_injection:
        # Create mock agent
        mock_agent = MockAgent("async-test-agent")

        # Create DI-enhanced function
        def di_enhanced_function(message: str, agent: McpMeshAgent = None) -> str:
            print(f"🔄 DI wrapper called (ASYNC UPDATE) with message='{message}'")
            return test_with_dependency(message, mock_agent)

        print("📝 Step 4: Updating FastMCP tool manager with DI-enhanced function")
        # Update the tool manager - this is the critical operation
        if "test_with_dependency" in server._tool_manager._tools:
            tool = server._tool_manager._tools["test_with_dependency"]
            print(f"   Before update - tool.fn: {tool.fn}")
            tool.fn = di_enhanced_function
            print(f"   After update - tool.fn: {tool.fn}")
            print("✅ FastMCP function pointer updated asynchronously!")
        else:
            print("❌ Tool not found in FastMCP tool manager")


# Initial setup
initial_setup()

# Create FastAPI app
app = FastAPI(title="Async DI Timing Test")


# Add fallback MCP endpoints
@app.post("/mcp")
async def mcp_handler(request: dict):
    method = request.get("method")
    params = request.get("params", {})

    if method == "tools/list":
        tools = []
        for name, tool in server._tool_manager._tools.items():
            tools.append(
                {
                    "name": name,
                    "description": getattr(tool, "description", ""),
                }
            )
        return {"tools": tools}

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in server._tool_manager._tools:
            return {"error": f"Tool '{tool_name}' not found"}

        tool = server._tool_manager._tools[tool_name]
        try:
            print(f"🚀 Calling tool '{tool_name}' with current function: {tool.fn}")
            result = tool.fn(**arguments)
            print(f"✅ Tool result: {result}")
            return {
                "content": [{"type": "text", "text": str(result)}],
                "isError": False,
            }
        except Exception as e:
            print(f"❌ Tool error: {e}")
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

    return {"error": f"Unknown method: {method}"}


@app.get("/health")
async def health():
    return {"status": "healthy", "tools": len(server._tool_manager._tools)}


# Background task to simulate async DI processing
async def background_di_processor():
    """Background task that simulates the processor's async DI behavior."""
    await simulate_registry_call_and_di()


if __name__ == "__main__":
    print("🚀 Starting async DI timing test server on http://127.0.0.1:8127")
    print("⏳ Server will start with ORIGINAL functions")
    print("⏳ After 5 seconds, DI will update function pointers")
    print()
    print(
        '📋 Test BEFORE DI (should show original): curl -X POST http://127.0.0.1:8127/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print(
        '📋 Test AFTER DI (should show mock): curl -X POST http://127.0.0.1:8127/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print("🛑 Press Ctrl+C to stop")

    # Start the background DI processor in a separate thread
    def run_background_task():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(background_di_processor())
        loop.close()

    di_thread = threading.Thread(target=run_background_task, daemon=True)
    di_thread.start()

    uvicorn.run(app, host="127.0.0.1", port=8127, log_level="info")
