#!/usr/bin/env python3
"""
Integration test for MCP Mesh Dependency Injection.
Tests that DI works transparently with MCP protocol.
"""

import asyncio
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


class MockRegistryHandler(BaseHTTPRequestHandler):
    """Mock registry that always returns SystemAgent as available."""

    def do_POST(self):
        """Handle POST requests from mesh runtime."""
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length).decode("utf-8")  # Read body but don't store

        if self.path == "/agents/register_with_metadata":
            response = {
                "id": "test-server",
                "status": "registered",
                "message": "Agent registered successfully",
            }
            self._send_json_response(response)

        elif self.path == "/heartbeat":
            # Always return SystemAgent as available
            response = {
                "status": "healthy",
                "dependencies_resolved": {
                    "SystemAgent": {
                        "agent_id": "mock-system-agent",
                        "endpoint": "http://localhost:8888/SystemAgent",
                        "status": "healthy",
                    }
                },
            }
            self._send_json_response(response)
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == "/health":
            self._send_json_response({"status": "healthy", "service": "mock-registry"})
        else:
            self.send_error(404)

    def _send_json_response(self, data):
        response_body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format, *args):
        pass  # Suppress logs


def get_free_port():
    """Get a free port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


@pytest.fixture
async def mock_registry():
    """Start mock registry on a free port."""
    port = get_free_port()
    server = HTTPServer(("localhost", port), MockRegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Set environment variable
    os.environ["REGISTRY_URL"] = f"http://localhost:{port}"

    yield f"http://localhost:{port}"

    # Cleanup
    server.shutdown()
    del os.environ["REGISTRY_URL"]


def create_test_server_correct_order() -> FastMCP:
    """Create MCP server with CORRECT decorator order."""
    server = FastMCP(name="test-di-server-correct")

    @server.tool()  # server.tool FIRST
    @mesh_agent(  # mesh_agent SECOND
        capability="data_processor",
        dependencies=["SystemAgent"],
        health_interval=5,
    )
    def process_data_correct_order(data: str, SystemAgent: Any = None) -> dict:
        """Function with correct decorator order."""
        result = {
            "input_data": data,
            "dependency_status": "not_injected",
            "error": None,
        }

        if SystemAgent is not None:
            result["dependency_status"] = "injected"
            result["proxy_type"] = type(SystemAgent).__name__

            try:
                # Try to use the dependency
                date = SystemAgent.getDate()
                result["system_info"] = f"Date: {date}"
            except RuntimeError as e:
                result["error"] = str(e)
                result["error_type"] = "expected_stdio_limitation"

        return result

    return server


def create_test_server_wrong_order() -> FastMCP:
    """Create MCP server with WRONG decorator order."""
    server = FastMCP(name="test-di-server-wrong")

    @mesh_agent(  # mesh_agent FIRST (WRONG!)
        capability="data_processor",
        dependencies=["SystemAgent"],
        health_interval=5,
    )
    @server.tool()  # server.tool SECOND
    def process_data_wrong_order(data: str, SystemAgent: Any = None) -> dict:
        """Function with wrong decorator order."""
        result = {
            "input_data": data,
            "dependency_status": "not_injected",
            "error": None,
        }

        if SystemAgent is not None:
            result["dependency_status"] = "injected"
            result["proxy_type"] = type(SystemAgent).__name__

        return result

    return server


@pytest.mark.asyncio
async def test_dependency_injection_correct_order(mock_registry):
    """Test that DI works with correct decorator order."""
    # Create server with correct order
    server = create_test_server_correct_order()

    # Wait for DI to happen
    await asyncio.sleep(8)

    # Get the function from server
    assert hasattr(server, "_tool_manager")
    tools = server._tool_manager._tools
    assert "process_data_correct_order" in tools

    func = tools["process_data_correct_order"].fn

    # Check injection happened
    assert hasattr(func, "_injected_deps")
    assert "SystemAgent" in func._injected_deps
    assert func._injected_deps["SystemAgent"] is not None

    # Call function as MCP would (only with required params)
    result = func(data="test-input")

    # Verify DI worked
    assert result["dependency_status"] == "injected"
    assert result["proxy_type"] == "DynamicServiceProxy"
    assert result.get("error_type") == "expected_stdio_limitation"
    assert "stdio transport doesn't support HTTP calls" in result.get("error", "")


@pytest.mark.asyncio
async def test_dependency_injection_wrong_order(mock_registry):
    """Test that DI fails with wrong decorator order."""
    # Create server with wrong order
    server = create_test_server_wrong_order()

    # Wait for potential DI
    await asyncio.sleep(8)

    # Get the function from server
    assert hasattr(server, "_tool_manager")
    tools = server._tool_manager._tools
    assert "process_data_wrong_order" in tools

    func = tools["process_data_wrong_order"].fn

    # Check injection did NOT happen (FastMCP unwrapped it)
    assert not hasattr(func, "_injected_deps")

    # Call function - DI won't work
    result = func(data="test-input")

    # Verify DI did NOT work
    assert result["dependency_status"] == "not_injected"


@pytest.mark.asyncio
async def test_mcp_client_transparency(mock_registry):
    """Test that MCP clients don't need to know about dependencies."""
    server = create_test_server_correct_order()

    # Wait for DI
    await asyncio.sleep(8)

    # Simulate MCP client behavior
    tools = server._tool_manager._tools
    func = tools["process_data_correct_order"].fn

    # MCP client only passes business parameters
    # No SystemAgent parameter passed!
    result = func(data="client-data-123")

    # But function still has SystemAgent available
    assert result["dependency_status"] == "injected"
    assert result["input_data"] == "client-data-123"

    # This proves DI is transparent to MCP protocol


@pytest.mark.asyncio
async def test_registry_unavailable():
    """Test graceful degradation when registry is unavailable."""
    # Clear any existing injections first
    from mcp_mesh.runtime.dependency_injector import get_global_injector

    injector = get_global_injector()
    await injector.unregister_dependency("SystemAgent")

    # Set invalid registry URL
    os.environ["REGISTRY_URL"] = "http://localhost:99999"

    try:
        # Create a fresh server function
        server = FastMCP(name="test-no-registry")

        @server.tool()
        @mesh_agent(
            capability="test_no_registry",
            dependencies=["SystemAgent"],
            health_interval=5,
        )
        def process_without_registry(data: str, SystemAgent: Any = None) -> dict:
            """Function to test without registry."""
            return {
                "input_data": data,
                "dependency_status": (
                    "injected" if SystemAgent is not None else "not_injected"
                ),
            }

        # Wait a bit
        await asyncio.sleep(3)

        # Get function
        tools = server._tool_manager._tools
        func = tools["process_without_registry"].fn

        # Call function - should work without DI
        result = func(data="test-without-registry")

        # Should gracefully handle missing dependency
        assert result["dependency_status"] == "not_injected"
        assert result["input_data"] == "test-without-registry"

    finally:
        if "REGISTRY_URL" in os.environ:
            del os.environ["REGISTRY_URL"]


def test_decorator_order_detection():
    """Test that we can detect decorator order issues."""
    server1 = create_test_server_correct_order()
    server2 = create_test_server_wrong_order()

    # Get functions
    func1 = server1._tool_manager._tools["process_data_correct_order"].fn
    func2 = server2._tool_manager._tools["process_data_wrong_order"].fn

    # Correct order should have injection attributes
    assert hasattr(func1, "_mesh_agent_dependencies")
    assert hasattr(func1, "_injected_deps")

    # Wrong order loses these attributes (FastMCP unwraps)
    assert not hasattr(func2, "_injected_deps")
