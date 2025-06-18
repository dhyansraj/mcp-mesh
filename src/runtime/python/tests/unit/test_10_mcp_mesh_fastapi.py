"""
Test FastAPI integration for @mesh.tool decorated functions.

Verifies that decorated functions are actually exposed as HTTP endpoints
and can be called via HTTP requests.
"""

import pytest
from fastapi.testclient import TestClient

from mcp_mesh.runtime.http_wrapper import HttpConfig, HttpMcpWrapper


class TestFastAPIIntegration:
    """Test that @mesh.tool functions are exposed as FastAPI endpoints."""

    @pytest.mark.asyncio
    async def test_http_wrapper_creates_fastapi_app(self):
        """Test that HttpMcpWrapper creates a functional FastAPI app."""
        from mcp.server.fastmcp import FastMCP

        # Create a simple FastMCP server with a tool
        server = FastMCP("test-server")

        @server.tool()
        def simple_greet(name: str = "World") -> str:
            """Simple greeting function."""
            return f"Hello {name}!"

        # Create HTTP wrapper
        config = HttpConfig(host="0.0.0.0", port=0)
        wrapper = HttpMcpWrapper(server, config)

        # Setup the wrapper (this creates the FastAPI app)
        await wrapper.setup()

        # Test the FastAPI app directly
        with TestClient(wrapper.app) as client:
            # Test health endpoint
            health_response = client.get("/health")
            assert health_response.status_code == 200
            health_data = health_response.json()
            assert health_data["status"] == "healthy"
            assert health_data["agent"] == "test-server"

            # Test mesh info endpoint
            info_response = client.get("/mesh/info")
            assert info_response.status_code == 200
            info_data = info_response.json()
            assert "tools" in info_data
            assert len(info_data["tools"]) == 1
            assert info_data["tools"][0]["name"] == "simple_greet"

            # Test ready endpoint
            ready_response = client.get("/ready")
            assert ready_response.status_code == 200
            ready_data = ready_response.json()
            assert "ready" in ready_data
            assert "tools_count" in ready_data
            assert ready_data["tools_count"] >= 1  # Should have our simple_greet tool

            # Test tools listing endpoint
            tools_response = client.get("/mesh/tools")
            assert tools_response.status_code == 200
            tools_data = tools_response.json()
            assert "tools" in tools_data

            # tools_data["tools"] is a dictionary of tool_name -> tool_info
            tools_dict = tools_data["tools"]
            assert isinstance(tools_dict, dict)
            assert "simple_greet" in tools_dict

            # Test MCP protocol endpoint - list tools
            mcp_list_response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            assert mcp_list_response.status_code == 200
            mcp_list_data = mcp_list_response.json()

            # Handle both standard MCP protocol format and fallback format
            if "result" in mcp_list_data:
                # Standard MCP protocol format
                mcp_tools = mcp_list_data["result"]["tools"]
            else:
                # Fallback format (direct tools list)
                mcp_tools = mcp_list_data["tools"]

            mcp_tool_names = [tool["name"] for tool in mcp_tools]
            assert "simple_greet" in mcp_tool_names

            # Test calling our decorated function via MCP protocol over HTTP
            mcp_call_response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "simple_greet", "arguments": {"name": "Alice"}},
                },
            )
            assert mcp_call_response.status_code == 200
            mcp_call_data = mcp_call_response.json()

            # Handle both standard MCP protocol format and fallback format
            if "result" in mcp_call_data:
                # Standard MCP protocol format
                result_content = mcp_call_data["result"]["content"]
            else:
                # Fallback format (direct content)
                result_content = mcp_call_data["content"]

            # Verify function was called and returned expected result
            assert len(result_content) > 0
            assert "Hello Alice!" in result_content[0]["text"]

            # Verify no errors occurred
            if "isError" in mcp_call_data:
                assert mcp_call_data["isError"] is False

    @pytest.mark.asyncio
    async def test_multiple_tools_single_fastapi_server(self):
        """Test that multiple functions can be served by a single FastAPI server."""
        from mcp.server.fastmcp import FastMCP

        # Create a FastMCP server with multiple tools
        server = FastMCP("multi-tool-server")

        @server.tool()
        def greet(name: str = "World") -> str:
            return f"Hello {name}!"

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        @server.tool()
        def get_timestamp() -> str:
            return "2023-12-25T10:30:00Z"

        # Create HTTP wrapper for the server with multiple tools
        config = HttpConfig(host="0.0.0.0", port=0)
        wrapper = HttpMcpWrapper(server, config)
        await wrapper.setup()

        # Test the single FastAPI app serves all tools
        with TestClient(wrapper.app) as client:
            # Test that all tools are listed
            list_response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            assert list_response.status_code == 200
            tools_data = list_response.json()

            # Handle fallback format
            if "result" in tools_data:
                tools = tools_data["result"]["tools"]
            else:
                tools = tools_data["tools"]

            tool_names = {tool["name"] for tool in tools}

            # All our functions should be available on the same server
            assert "greet" in tool_names
            assert "add" in tool_names
            assert "get_timestamp" in tool_names

            # Test calling each function via the same HTTP endpoint
            test_cases = [
                ("greet", {"name": "Bob"}, "Hello Bob!"),
                ("add", {"a": 5, "b": 3}, "8"),
                ("get_timestamp", {}, "2023-12-25T10:30:00Z"),
            ]

            for tool_name, args, expected in test_cases:
                call_response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": args},
                    },
                )
                assert call_response.status_code == 200
                call_data = call_response.json()

                # Handle fallback format
                if "result" in call_data:
                    result_text = call_data["result"]["content"][0]["text"]
                else:
                    result_text = call_data["content"][0]["text"]

                assert expected in result_text

    @pytest.mark.asyncio
    async def test_health_endpoints_availability(self):
        """Test that all expected health endpoints are available."""
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("health-test-server")

        @server.tool()
        def test_function() -> str:
            return "test"

        # Create real HttpMcpWrapper to test actual endpoints
        config = HttpConfig(host="0.0.0.0", port=0)
        wrapper = HttpMcpWrapper(server, config)
        await wrapper.setup()

        # Test all health endpoints
        with TestClient(wrapper.app) as client:
            # Test /health
            health_response = client.get("/health")
            assert health_response.status_code == 200
            health_data = health_response.json()
            assert health_data["status"] == "healthy"
            assert "agent" in health_data

            # Test /ready
            ready_response = client.get("/ready")
            assert ready_response.status_code == 200
            ready_data = ready_response.json()
            assert "ready" in ready_data
            assert "tools_count" in ready_data

            # Test /livez (Kubernetes liveness)
            livez_response = client.get("/livez")
            assert livez_response.status_code == 200
            livez_data = livez_response.json()
            assert livez_data["alive"] is True

            # Test /mesh/info
            info_response = client.get("/mesh/info")
            assert info_response.status_code == 200
            info_data = info_response.json()
            assert "agent_id" in info_data
            assert "capabilities" in info_data
            assert "transport" in info_data

            # Test /mesh/tools
            tools_response = client.get("/mesh/tools")
            assert tools_response.status_code == 200
            tools_data = tools_response.json()
            assert "tools" in tools_data

            # Test /metrics (Prometheus)
            metrics_response = client.get("/metrics")
            assert metrics_response.status_code == 200
            # Metrics should be in text format
            assert "text/plain" in metrics_response.headers.get("content-type", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
