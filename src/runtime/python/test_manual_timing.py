#!/usr/bin/env python3

"""
Manual timing test - start server, test original, manually trigger DI, test again
"""


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
server = FastMCP("manual-timing-test")


@mesh.agent(name="manual-timing-test", http_port=8128, auto_run=False)
class ManualTimingTestAgent:
    pass


@mesh.tool(capability="manual_timing")
def test_with_dependency(message: str, agent: McpMeshAgent = None) -> str:
    """Function that expects dependency injection."""
    if agent:
        return f"Message: {message}, Agent: {agent.get_info()}"
    else:
        return f"Message: {message}, **ORIGINAL FUNCTION - NO DI**"


# Global flag to track DI state
di_applied = False


def setup_original_functions():
    """Setup original functions."""
    global di_applied
    print("📝 Setting up ORIGINAL functions")
    server.tool()(test_with_dependency)
    di_applied = False
    print("✅ Original function registered")


def apply_di_manually():
    """Manually apply DI - can be called via endpoint."""
    global di_applied

    if di_applied:
        return "DI already applied"

    print("🔄 Manually applying DI...")

    # Create mock agent
    mock_agent = MockAgent("manual-test-agent")

    # Create DI-enhanced function
    def di_enhanced_function(message: str, agent: McpMeshAgent = None) -> str:
        print(f"🔄 DI wrapper called with message='{message}'")
        return f"Message: {message}, Agent: {mock_agent.get_info()}"  # Direct return, not calling original

    # Update FastMCP tool manager
    if "test_with_dependency" in server._tool_manager._tools:
        tool = server._tool_manager._tools["test_with_dependency"]
        print(f"   Before: {tool.fn}")
        tool.fn = di_enhanced_function
        print(f"   After: {tool.fn}")
        di_applied = True
        print("✅ DI applied manually!")
        return "DI applied successfully"
    else:
        return "Tool not found"


# Setup original functions
setup_original_functions()

# Create FastAPI app
app = FastAPI(title="Manual Timing Test")


# Manual DI trigger endpoint
@app.post("/apply-di")
async def trigger_di():
    result = apply_di_manually()
    return {"status": result, "di_applied": di_applied}


@app.get("/di-status")
async def di_status():
    return {"di_applied": di_applied}


# MCP endpoints
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
            print(f"🚀 Calling tool '{tool_name}' (DI applied: {di_applied})")
            result = tool.fn(**arguments)
            print(f"✅ Result: {result}")
            return {
                "content": [{"type": "text", "text": str(result)}],
                "isError": False,
            }
        except Exception as e:
            print(f"❌ Error: {e}")
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

    return {"error": f"Unknown method: {method}"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "tools": len(server._tool_manager._tools),
        "di_applied": di_applied,
    }


if __name__ == "__main__":
    print("🚀 Starting manual timing test server on http://127.0.0.1:8128")
    print("⏳ Server starts with ORIGINAL functions")
    print()
    print("📋 Check DI status: curl http://127.0.0.1:8128/di-status")
    print(
        '📋 Test BEFORE DI: curl -X POST http://127.0.0.1:8128/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "Before"}}}\''
    )
    print("📋 Apply DI manually: curl -X POST http://127.0.0.1:8128/apply-di")
    print(
        '📋 Test AFTER DI: curl -X POST http://127.0.0.1:8128/mcp -H \'Content-Type: application/json\' -d \'{"method": "tools/call", "params": {"name": "test_with_dependency", "arguments": {"message": "After"}}}\''
    )
    print("🛑 Press Ctrl+C to stop")

    uvicorn.run(app, host="127.0.0.1", port=8128, log_level="info")
