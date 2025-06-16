#!/usr/bin/env python3

"""
Minimal test - just FastMCP + FastAPI without DI/registration
"""


import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

import mesh

# Create FastMCP server
server = FastMCP("minimal-test")


@mesh.agent(name="minimal-test", http_port=8125, auto_run=False)
class MinimalAgent:
    pass


@mesh.tool(capability="minimal")
def hello_world(message: str = "World") -> str:
    """Simple hello world function."""
    return f"Hello {message}!"


# Register tool with FastMCP directly
server.tool()(hello_world)

# Create FastAPI app
app = FastAPI(title="Minimal MCP Test")

# Mount MCP endpoints
try:
    from mcp.server.fastapi import create_app

    mcp_app = create_app(server)
    app.mount("/mcp", mcp_app)
    print("✅ Using official MCP FastAPI integration")
except ImportError:
    print("❌ Official MCP FastAPI not available - using fallback")

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
                result = tool.fn(**arguments)
                return {
                    "content": [{"type": "text", "text": str(result)}],
                    "isError": False,
                }
            except Exception as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}

        return {"error": f"Unknown method: {method}"}


@app.get("/health")
async def health():
    return {"status": "healthy", "tools": len(server._tool_manager._tools)}


if __name__ == "__main__":
    print("🚀 Starting minimal server on http://127.0.0.1:8125")
    print("📋 Test with: curl http://127.0.0.1:8125/health")
    print(
        "📋 Test with: curl -X POST http://127.0.0.1:8125/mcp -H 'Content-Type: application/json' -d '{\"method\": \"tools/list\"}'"
    )
    print("🛑 Press Ctrl+C to stop")

    uvicorn.run(app, host="127.0.0.1", port=8125, log_level="info")
