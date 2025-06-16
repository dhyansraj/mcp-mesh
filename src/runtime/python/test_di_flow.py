#!/usr/bin/env python3

"""
Test dependency injection flow:
1. Process decorators and cache function pointers
2. Create FastMCP and FastAPI
3. Inject mock object into function parameter
4. Test if MCP calls still work
"""

import inspect

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
server = FastMCP("di-test")


@mesh.agent(name="di-test", http_port=8126, auto_run=False)
class DITestAgent:
    pass


@mesh.tool(capability="di_test")
def test_with_dependency(message: str, agent: McpMeshAgent = None) -> str:
    """Function that expects dependency injection."""
    if agent:
        return f"Message: {message}, Agent: {agent.get_info()}"
    else:
        return f"Message: {message}, No agent injected"


@mesh.tool(capability="di_test")
def test_without_dependency(message: str) -> str:
    """Function without dependency injection."""
    return f"Simple message: {message}"


def process_and_inject():
    """Process decorators, cache functions, then inject dependencies."""

    print("📝 Step 1: Cache original function pointers")
    original_with_dep = test_with_dependency
    original_without_dep = test_without_dependency

    print("📝 Step 2: Register functions with FastMCP")
    server.tool()(original_with_dep)
    server.tool()(original_without_dep)

    print("📝 Step 3: Analyze function signatures for DI")
    sig = inspect.signature(original_with_dep)
    needs_injection = any(
        param.annotation == McpMeshAgent for param in sig.parameters.values()
    )
    print(f"   test_with_dependency needs injection: {needs_injection}")

    print("📝 Step 4: Create DI-enhanced function")
    if needs_injection:
        # Create mock agent
        mock_agent = MockAgent("test-agent")

        # Create wrapper that injects the mock
        def di_enhanced_function(message: str, agent: McpMeshAgent = None) -> str:
            print(
                f"🔄 DI wrapper called with message='{message}', injecting mock agent"
            )
            return original_with_dep(message, mock_agent)

        print("📝 Step 5: Update FastMCP tool manager with DI-enhanced function")
        # Update the tool manager to use DI-enhanced function
        if "test_with_dependency" in server._tool_manager._tools:
            tool = server._tool_manager._tools["test_with_dependency"]
            print(f"   Original tool.fn: {tool.fn}")
            tool.fn = di_enhanced_function
            print(f"   Updated tool.fn: {tool.fn}")

    print("✅ DI processing complete")


# Process decorators and setup DI
process_and_inject()

# Create FastAPI app
app = FastAPI(title="DI Test")


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
            print(f"🚀 Calling tool '{tool_name}' with function: {tool.fn}")
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


if __name__ == "__main__":
    print("🚀 Starting DI test server on http://127.0.0.1:8126")
    print("📋 Test with: curl http://127.0.0.1:8126/health")
    print(
        "📋 Test tools/list: curl -X POST http://127.0.0.1:8126/mcp -H 'Content-Type: application/json' -d '{\"method\": \"tools/list\"}'"
    )
    print(
        '📋 Test without DI: curl -X POST http://127.0.0.1:8126/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_without_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print(
        '📋 Test with DI: curl -X POST http://127.0.0.1:8126/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Hello"}}}\''
    )
    print("🛑 Press Ctrl+C to stop")

    uvicorn.run(app, host="127.0.0.1", port=8126, log_level="info")
