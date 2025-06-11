"""Integration tests for HTTP wrapper functionality."""

import asyncio
import json
import socket
from contextlib import closing
from typing import Any

import aiohttp
import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent
from mcp_mesh.runtime.http_wrapper import HttpConfig, HttpMcpWrapper


def get_free_port() -> int:
    """Get a free port by binding to port 0."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@pytest.fixture
async def mcp_server():
    """Create a test MCP server."""
    server = FastMCP(name="test-http-server")

    @server.tool()
    def test_greeting(name: str = "World") -> dict[str, str]:
        """Test greeting function."""
        return {"message": f"Hello, {name}!"}

    @server.tool()
    def test_calculator(operation: str, a: float, b: float) -> dict[str, Any]:
        """Test calculator function."""
        ops = {
            "add": lambda x, y: x + y,
            "subtract": lambda x, y: x - y,
            "multiply": lambda x, y: x * y,
            "divide": lambda x, y: x / y if y != 0 else None,
        }

        if operation not in ops:
            return {"error": f"Unknown operation: {operation}"}

        result = ops[operation](a, b)
        if result is None:
            return {"error": "Division by zero"}

        return {"result": result, "operation": operation}

    return server


@pytest.fixture
async def http_wrapper(mcp_server):
    """Create HTTP wrapper for MCP server."""
    config = HttpConfig(host="127.0.0.1", port=get_free_port(), cors_enabled=True)
    wrapper = HttpMcpWrapper(mcp_server, config)
    await wrapper.setup()
    await wrapper.start()

    yield wrapper

    # Cleanup
    await wrapper.stop()


@pytest.mark.asyncio
async def test_http_wrapper_health_endpoints(http_wrapper):
    """Test that health endpoints are available."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        # Test /health endpoint
        async with session.get(f"{base_url}/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "healthy"
            assert data["agent"] == "test-http-server"

        # Test /ready endpoint
        async with session.get(f"{base_url}/ready") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "ready" in data
            assert data["agent"] == "test-http-server"
            assert data["tools_count"] >= 2

        # Test /livez endpoint
        async with session.get(f"{base_url}/livez") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["alive"] is True
            assert data["agent"] == "test-http-server"


@pytest.mark.asyncio
async def test_http_wrapper_mesh_info(http_wrapper):
    """Test mesh info endpoint."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/mesh/info") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["agent_id"] == "test-http-server"
            assert "stdio" in data["transport"]
            assert "http" in data["transport"]
            assert data["http_endpoint"].startswith("http://")
            assert str(http_wrapper.actual_port) in data["http_endpoint"]


@pytest.mark.asyncio
async def test_http_wrapper_list_tools(http_wrapper):
    """Test listing available tools."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/mesh/tools") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "tools" in data
            assert "test_greeting" in data["tools"]
            assert "test_calculator" in data["tools"]


@pytest.mark.asyncio
async def test_http_wrapper_fallback_mcp_handler(http_wrapper):
    """Test fallback MCP protocol handler."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        # Test tools/list
        payload = {"method": "tools/list"}
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "tools" in data
            assert len(data["tools"]) >= 2

            # Find test_greeting tool
            greeting_tool = next(
                (t for t in data["tools"] if t["name"] == "test_greeting"), None
            )
            assert greeting_tool is not None

        # Test tools/call - greeting
        payload = {
            "method": "tools/call",
            "params": {"name": "test_greeting", "arguments": {"name": "HTTP Test"}},
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "content" in data
            assert data["isError"] is False
            content = json.loads(data["content"][0]["text"])
            assert content["message"] == "Hello, HTTP Test!"

        # Test tools/call - calculator
        payload = {
            "method": "tools/call",
            "params": {
                "name": "test_calculator",
                "arguments": {"operation": "add", "a": 5, "b": 3},
            },
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "content" in data
            assert data["isError"] is False
            content = json.loads(data["content"][0]["text"])
            assert content["result"] == 8
            assert content["operation"] == "add"

        # Test unknown method
        payload = {"method": "unknown/method"}
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert "detail" in data
            assert "Unknown method" in data["detail"]

        # Test unknown tool
        payload = {
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 404
            data = await resp.json()
            assert "detail" in data
            assert "not found" in data["detail"]


@pytest.mark.asyncio
async def test_http_wrapper_cors_headers(http_wrapper):
    """Test CORS headers are properly set."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        # Preflight request
        headers = {
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
        async with session.options(f"{base_url}/mcp", headers=headers) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")


@pytest.mark.asyncio
async def test_http_wrapper_concurrent_requests(http_wrapper):
    """Test handling concurrent requests."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async def make_request(session, name):
        payload = {
            "method": "tools/call",
            "params": {"name": "test_greeting", "arguments": {"name": name}},
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            data = await resp.json()
            content = json.loads(data["content"][0]["text"])
            return content["message"]

    async with aiohttp.ClientSession() as session:
        # Make 10 concurrent requests
        names = [f"User{i}" for i in range(10)]
        tasks = [make_request(session, name) for name in names]
        results = await asyncio.gather(*tasks)

        # Verify all requests were handled correctly
        for i, result in enumerate(results):
            assert result == f"Hello, User{i}!"


@pytest.mark.asyncio
async def test_http_wrapper_error_handling(http_wrapper):
    """Test error handling in HTTP wrapper."""
    base_url = f"http://127.0.0.1:{http_wrapper.actual_port}"

    async with aiohttp.ClientSession() as session:
        # Test division by zero
        payload = {
            "method": "tools/call",
            "params": {
                "name": "test_calculator",
                "arguments": {"operation": "divide", "a": 10, "b": 0},
            },
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["isError"] is False  # Function handles error internally
            content = json.loads(data["content"][0]["text"])
            assert content["error"] == "Division by zero"

        # Test invalid operation
        payload = {
            "method": "tools/call",
            "params": {
                "name": "test_calculator",
                "arguments": {"operation": "invalid", "a": 10, "b": 5},
            },
        }
        async with session.post(f"{base_url}/mcp", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()
            content = json.loads(data["content"][0]["text"])
            assert "Unknown operation" in content["error"]


@pytest.mark.asyncio
async def test_http_wrapper_with_mesh_decorator():
    """Test HTTP wrapper with mesh_agent decorated functions."""
    server = FastMCP(name="mesh-test-server")

    @server.tool()
    @mesh_agent(
        capability="test_capability", enable_http=True, dependencies=["TestDep"]
    )
    def mesh_function(input: str, TestDep: Any = None) -> dict[str, Any]:
        """Function with mesh decorator."""
        return {
            "input": input,
            "has_dependency": TestDep is not None,
            "dependency_type": type(TestDep).__name__ if TestDep else None,
        }

    # Create HTTP wrapper
    config = HttpConfig(port=get_free_port())
    wrapper = HttpMcpWrapper(server, config)
    await wrapper.setup()
    await wrapper.start()

    try:
        base_url = f"http://127.0.0.1:{wrapper.actual_port}"

        async with aiohttp.ClientSession() as session:
            # Get mesh info - should show capabilities and dependencies
            async with session.get(f"{base_url}/mesh/info") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert "test_capability" in data["capabilities"]
                assert "TestDep" in data["dependencies"]

            # Call the function
            payload = {
                "method": "tools/call",
                "params": {"name": "mesh_function", "arguments": {"input": "test"}},
            }
            async with session.post(f"{base_url}/mcp", json=payload) as resp:
                assert resp.status == 200
                data = await resp.json()
                content = json.loads(data["content"][0]["text"])
                assert content["input"] == "test"

    finally:
        await wrapper.stop()


@pytest.mark.asyncio
async def test_http_wrapper_lifecycle():
    """Test HTTP wrapper start/stop lifecycle."""
    server = FastMCP(name="lifecycle-test")
    config = HttpConfig(port=get_free_port())
    wrapper = HttpMcpWrapper(server, config)

    # Setup and start
    await wrapper.setup()
    await wrapper.start()

    # Verify it's running
    assert wrapper.actual_port is not None
    assert wrapper.server is not None

    # Test that port is accessible
    base_url = f"http://127.0.0.1:{wrapper.actual_port}"
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/health") as resp:
            assert resp.status == 200

    # Stop the wrapper
    await wrapper.stop()

    # Verify it's stopped - port should be closed
    await asyncio.sleep(0.5)  # Give it time to fully stop

    # Attempting to connect should fail
    with pytest.raises(aiohttp.ClientError):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=1)
            ) as resp:
                pass
