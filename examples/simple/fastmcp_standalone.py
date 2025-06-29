#!/usr/bin/env python3
"""
Pure FastMCP Server (no mesh integration)

Test how FastMCP handles internal function calls without mesh dependency injection.
"""

from datetime import datetime

from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Standalone FastMCP Service")


@app.tool()
def get_current_time() -> str:
    """Get the current system time."""
    return datetime.now().isoformat()


@app.tool()
def calculate_with_timestamp(a: float, b: float, operation: str = "add") -> dict:
    """Perform math operation with timestamp - makes MCP call to get_current_time."""
    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "subtract":
        result = a - b
    else:
        result = 0

    # MCP SELF-CALL: Make actual MCP tool call to same server

    import requests

    try:
        response = requests.post(
            "http://localhost:9099/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_current_time", "arguments": {}},
            },
            headers={"Content-Type": "application/json"},
            timeout=5.0,
        )

        if response.status_code == 200:
            data = response.json()
            if "result" in data:
                timestamp = data["result"]["content"][0][
                    "text"
                ]  # Extract from MCP response
            else:
                timestamp = f"MCP_ERROR: {data.get('error', 'Unknown error')}"
        else:
            timestamp = f"HTTP_ERROR: {response.status_code}"

    except Exception as e:
        timestamp = f"EXCEPTION: {str(e)}"

    return {
        "operation": operation,
        "operands": [a, b],
        "result": result,
        "timestamp": timestamp,
        "call_method": "MCP_HTTP_SELF_CALL",
    }


@app.tool()
def process_data(data: str, format_type: str = "json") -> dict:
    """Process and format data."""
    return {
        "input": data,
        "format": format_type,
        "processed_at": datetime.now().isoformat(),
        "length": len(data),
    }


@app.tool()
def complex_operation(x: float, y: float) -> dict:
    """Complex operation that makes multiple MCP self-calls."""
    import requests

    def make_mcp_call(tool_name: str, arguments: dict = None):
        """Helper to make MCP calls to self."""
        try:
            response = requests.post(
                "http://localhost:9099/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                },
                headers={"Content-Type": "application/json"},
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("result", f"Error: {data.get('error')}")
            return f"HTTP_ERROR: {response.status_code}"
        except Exception as e:
            return f"EXCEPTION: {str(e)}"

    # Make multiple MCP self-calls
    calc_result = make_mcp_call(
        "calculate_with_timestamp", {"a": x, "b": y, "operation": "multiply"}
    )

    return {
        "input": {"x": x, "y": y},
        "calculation": calc_result,
        "call_method": "MULTIPLE_MCP_SELF_CALLS",
        "test_purpose": "Compare with mesh self-dependency bypass",
    }


if __name__ == "__main__":
    import uvicorn

    print("🚀 Starting Standalone FastMCP Server on port 9099")
    print("🧪 Testing internal function calls without mesh integration")
    uvicorn.run(app, host="0.0.0.0", port=9099)
