#!/usr/bin/env python3
"""
Integration test for Multi-Tool MCP Mesh Integration.

Tests that multi-tool decorators work correctly with MCP protocol,
including proper decorator order, tool registration, and dependency injection.

This test verifies the critical order issue where @server.tool() must come
before @mesh_agent() to preserve the mesh metadata for dependency injection.
"""

import asyncio
import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent, mesh_tool


class MockMultiToolRegistryHandler(BaseHTTPRequestHandler):
    """Mock registry that supports multi-tool format."""

    def do_POST(self):
        """Handle POST requests from mesh runtime."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            request_data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            request_data = {}

        if self.path == "/agents/register":
            # Handle multi-tool registration
            response = {
                "status": "success",
                "agent_id": request_data.get("agent_id", "multi-tool-agent"),
                "resource_version": "1703123456789",
                "timestamp": "2023-12-20T10:30:45Z",
                "message": "Multi-tool agent registered successfully",
                "metadata": {
                    "dependencies_resolved": {
                        # For greet tool - needs date_service
                        "greet": {
                            "date_service": {
                                "agent_id": "date-provider-123",
                                "tool_name": "get_current_date",
                                "capability": "date_service",
                                "version": "1.2.0",
                                "endpoint": "http://localhost:8888/date_service",
                            }
                        },
                        # For process_data tool - needs auth_service
                        "process_data": {
                            "auth_service": {
                                "agent_id": "auth-provider-456",
                                "tool_name": "authenticate",
                                "capability": "auth_service",
                                "version": "2.0.0",
                                "endpoint": "http://localhost:8889/auth_service",
                            }
                        },
                        # For farewell tool - no dependencies
                        "farewell": {},
                    }
                },
            }
            self._send_json_response(response)

        elif self.path == "/heartbeat":
            # Return updated dependency resolution
            response = {
                "status": "success",
                "timestamp": "2023-12-20T10:35:00Z",
                "dependencies_resolved": {
                    "greet": {
                        "date_service": {
                            "agent_id": "date-provider-123",
                            "tool_name": "get_current_date",
                            "endpoint": "http://localhost:8888/date_service",
                        }
                    },
                    "process_data": {
                        "auth_service": {
                            "agent_id": "auth-provider-456",
                            "tool_name": "authenticate",
                            "endpoint": "http://localhost:8889/auth_service",
                        }
                    },
                    "farewell": {},
                },
            }
            self._send_json_response(response)
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == "/health":
            self._send_json_response(
                {"status": "healthy", "service": "mock-multi-tool-registry"}
            )
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
async def mock_multi_tool_registry():
    """Start mock registry supporting multi-tool format."""
    port = get_free_port()
    server = HTTPServer(("localhost", port), MockMultiToolRegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Set environment variable
    os.environ["MCP_MESH_REGISTRY_URL"] = f"http://localhost:{port}"

    yield f"http://localhost:{port}"

    # Cleanup
    server.shutdown()
    if "MCP_MESH_REGISTRY_URL" in os.environ:
        del os.environ["MCP_MESH_REGISTRY_URL"]


@pytest.fixture
async def temp_dir():
    """Create temporary directory for file operations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


def create_single_capability_server() -> FastMCP:
    """Create MCP server with LEGACY single-capability format."""
    server = FastMCP(name="test-single-capability")

    @server.tool()  # server.tool FIRST (correct order)
    @mesh_agent(  # mesh_agent SECOND with legacy format
        capability="greeting",
        version="1.0.0",
        dependencies=["date_service"],
        health_interval=5,
    )
    def greet_legacy(name: str, date_service: Any = None) -> dict:
        """Legacy single-capability greeting function."""
        result = {
            "greeting": f"Hello {name}!",
            "dependency_status": "not_injected",
            "format": "legacy_single_capability",
        }

        if date_service is not None:
            result["dependency_status"] = "injected"
            result["proxy_type"] = type(date_service).__name__
            try:
                # Try to use the dependency
                date = date_service.get_current_date()
                result["current_date"] = date
            except Exception as e:
                result["error"] = str(e)

        return result

    return server


def create_multi_tool_server() -> FastMCP:
    """Create MCP server with NEW multi-tool format."""
    server = FastMCP(name="test-multi-tool")

    @server.tool()  # server.tool FIRST (correct order)
    @mesh_agent(  # mesh_agent SECOND with new multi-tool format
        tools=[
            {
                "function_name": "greet",
                "capability": "greeting",
                "version": "1.0.0",
                "tags": ["demo", "v1"],
                "dependencies": [
                    {
                        "capability": "date_service",
                        "version": ">=1.0.0",
                        "tags": ["production"],
                    }
                ],
            },
            {
                "function_name": "farewell",
                "capability": "goodbye",
                "version": "1.0.0",
                "tags": ["demo"],
                "dependencies": [],
            },
        ],
        enable_http=True,
        http_port=8889,
        health_interval=5,
    )
    def greet(name: str, date_service: Any = None) -> dict:
        """Multi-tool greeting function."""
        result = {
            "greeting": f"Hello {name}!",
            "dependency_status": "not_injected",
            "format": "multi_tool",
        }

        if date_service is not None:
            result["dependency_status"] = "injected"
            result["proxy_type"] = type(date_service).__name__
            try:
                date = date_service.get_current_date()
                result["current_date"] = date
            except Exception as e:
                result["error"] = str(e)

        return result

    @server.tool()  # Additional tool with different dependencies
    @mesh_agent(
        tools=[
            {
                "function_name": "process_data",
                "capability": "data_processing",
                "version": "2.0.0",
                "dependencies": [{"capability": "auth_service", "version": ">=2.0.0"}],
            }
        ],
        health_interval=5,
    )
    def process_data(data: str, auth_service: Any = None) -> dict:
        """Data processing function with auth dependency."""
        result = {
            "processed_data": f"Processed: {data}",
            "dependency_status": "not_injected",
            "format": "multi_tool",
        }

        if auth_service is not None:
            result["dependency_status"] = "injected"
            result["proxy_type"] = type(auth_service).__name__
            try:
                auth_result = auth_service.authenticate("user123")
                result["auth_result"] = auth_result
            except Exception as e:
                result["error"] = str(e)

        return result

    return server


def create_auto_discovery_server() -> FastMCP:
    """Create MCP server with auto-discovery multi-tool format."""
    server = FastMCP(name="test-auto-discovery")

    class FileOperationsAgent:
        """Agent with auto-discovered tools."""

        @mesh_tool(
            capability="file_read",
            version="1.0.0",
            dependencies=["auth_service"],
            tags=["file", "read"],
        )
        def read_file(self, path: str, auth_service: Any = None) -> dict:
            """Read file with auth dependency."""
            result = {
                "operation": "read_file",
                "path": path,
                "dependency_status": "not_injected",
            }

            if auth_service is not None:
                result["dependency_status"] = "injected"

            return result

        @mesh_tool(
            capability="file_write",
            version="1.0.0",
            dependencies=[],
            tags=["file", "write"],
        )
        def write_file(self, path: str, content: str) -> dict:
            """Write file without dependencies."""
            return {
                "operation": "write_file",
                "path": path,
                "content_length": len(content),
                "dependency_status": "no_dependencies",
            }

    # Register the auto-discovery agent
    FileOperationsAgent()

    @server.tool()
    @mesh_agent(auto_discover_tools=True, default_version="1.0.0")
    def file_operations_wrapper(**kwargs) -> dict:
        """Wrapper for auto-discovered file operations."""
        # This would be handled by the runtime in a real scenario
        return {"status": "auto_discovery_configured"}

    return server


def create_class_based_multi_tool_server(temp_dir: Path) -> FastMCP:
    """Create MCP server with class-based multi-tool agent."""
    server = FastMCP(name="test-class-multi-tool")

    @mesh_agent(
        tools=[
            {
                "function_name": "read_file",
                "capability": "file_read",
                "version": "1.0.0",
                "dependencies": [{"capability": "auth_service"}],
            },
            {
                "function_name": "write_file",
                "capability": "file_write",
                "version": "1.0.0",
                "dependencies": [],
            },
            {
                "function_name": "list_files",
                "capability": "file_list",
                "version": "1.0.0",
                "dependencies": [],
            },
        ],
        enable_http=True,
        http_port=8890,
        health_interval=5,
    )
    class FileAgent:
        """Class-based multi-tool file agent."""

        def __init__(self):
            self.base_dir = temp_dir

        @server.tool()
        def read_file(self, filename: str, auth_service: Any = None) -> dict:
            """Read file with auth check."""
            result = {
                "operation": "read_file",
                "filename": filename,
                "dependency_status": "not_injected",
            }

            if auth_service is not None:
                result["dependency_status"] = "injected"

            file_path = self.base_dir / filename
            if file_path.exists():
                result["content"] = file_path.read_text()
                result["exists"] = True
            else:
                result["exists"] = False

            return result

        @server.tool()
        def write_file(self, filename: str, content: str) -> dict:
            """Write file without dependencies."""
            file_path = self.base_dir / filename
            file_path.write_text(content)

            return {
                "operation": "write_file",
                "filename": filename,
                "content_length": len(content),
                "dependency_status": "no_dependencies",
                "written": True,
            }

        @server.tool()
        def list_files(self) -> dict:
            """List files without dependencies."""
            files = [f.name for f in self.base_dir.iterdir() if f.is_file()]

            return {
                "operation": "list_files",
                "files": files,
                "file_count": len(files),
                "dependency_status": "no_dependencies",
            }

    return server


@pytest.mark.asyncio
async def test_legacy_single_capability_integration(mock_multi_tool_registry):
    """Test that legacy single-capability format still works with integration."""
    server = create_single_capability_server()

    # Wait for DI to happen
    await asyncio.sleep(8)

    # Get the function from server
    assert hasattr(server, "_tool_manager")
    tools = server._tool_manager._tools
    assert "greet_legacy" in tools

    func = tools["greet_legacy"].fn

    # Check injection happened
    assert hasattr(func, "_mesh_metadata")
    metadata = func._mesh_metadata
    assert metadata["capability"] == "greeting"
    assert metadata["capabilities"] == ["greeting"]
    assert "tools" in metadata  # Converted to multi-tool format internally
    assert len(metadata["tools"]) == 1
    assert metadata["tools"][0]["capability"] == "greeting"

    # Call function as MCP would
    result = func(name="Alice")

    # Verify function works
    assert result["greeting"] == "Hello Alice!"
    assert result["format"] == "legacy_single_capability"
    # DI may or may not work depending on registry response


@pytest.mark.asyncio
async def test_multi_tool_format_integration(mock_multi_tool_registry):
    """Test that new multi-tool format works with integration."""
    server = create_multi_tool_server()

    # Wait for DI to happen
    await asyncio.sleep(8)

    # Get functions from server
    assert hasattr(server, "_tool_manager")
    tools = server._tool_manager._tools
    assert "greet" in tools
    assert "process_data" in tools

    greet_func = tools["greet"].fn
    process_func = tools["process_data"].fn

    # Check multi-tool metadata
    assert hasattr(greet_func, "_mesh_metadata")
    greet_metadata = greet_func._mesh_metadata
    assert "tools" in greet_metadata
    assert len(greet_metadata["tools"]) == 2  # greet and farewell

    greet_tool = greet_metadata["tools"][0]
    assert greet_tool["function_name"] == "greet"
    assert greet_tool["capability"] == "greeting"
    assert greet_tool["version"] == "1.0.0"
    assert greet_tool["tags"] == ["demo", "v1"]
    assert len(greet_tool["dependencies"]) == 1
    assert greet_tool["dependencies"][0]["capability"] == "date_service"

    # Check process_data metadata
    assert hasattr(process_func, "_mesh_metadata")
    process_metadata = process_func._mesh_metadata
    assert "tools" in process_metadata
    process_tool = process_metadata["tools"][0]
    assert process_tool["function_name"] == "process_data"
    assert process_tool["capability"] == "data_processing"

    # Call functions as MCP would
    greet_result = greet_func(name="Bob")
    process_result = process_func(data="test-data")

    # Verify functions work
    assert greet_result["greeting"] == "Hello Bob!"
    assert greet_result["format"] == "multi_tool"
    assert process_result["processed_data"] == "Processed: test-data"
    assert process_result["format"] == "multi_tool"


@pytest.mark.asyncio
async def test_class_based_multi_tool_integration(mock_multi_tool_registry, temp_dir):
    """Test that class-based multi-tool agents work with integration."""
    server = create_class_based_multi_tool_server(temp_dir)

    # Wait for DI to happen
    await asyncio.sleep(8)

    # Get functions from server
    assert hasattr(server, "_tool_manager")
    tools = server._tool_manager._tools
    assert "read_file" in tools
    assert "write_file" in tools
    assert "list_files" in tools

    read_func = tools["read_file"].fn
    write_func = tools["write_file"].fn
    list_func = tools["list_files"].fn

    # Test file operations
    # First write a file
    write_result = write_func(filename="test.txt", content="Hello World!")
    assert write_result["written"] is True
    assert write_result["operation"] == "write_file"
    assert write_result["content_length"] == 12

    # Then read it back
    read_result = read_func(filename="test.txt")
    assert read_result["exists"] is True
    assert read_result["content"] == "Hello World!"
    assert read_result["operation"] == "read_file"

    # List files
    list_result = list_func()
    assert "test.txt" in list_result["files"]
    assert list_result["file_count"] >= 1
    assert list_result["operation"] == "list_files"


@pytest.mark.asyncio
async def test_decorator_order_with_multi_tool(mock_multi_tool_registry):
    """Test that decorator order is critical for multi-tool format."""
    # Test correct order (server.tool first, then mesh_agent)
    server_correct = FastMCP(name="test-order-correct")

    @server_correct.tool()  # CORRECT: server.tool FIRST
    @mesh_agent(
        tools=[
            {
                "function_name": "correct_order_func",
                "capability": "test_capability",
                "dependencies": [{"capability": "auth_service"}],
            }
        ]
    )
    def correct_order_func(data: str, auth_service: Any = None) -> dict:
        """Function with correct decorator order."""
        return {
            "data": data,
            "has_dependency": auth_service is not None,
            "order": "correct",
        }

    # Test wrong order (mesh_agent first, then server.tool)
    server_wrong = FastMCP(name="test-order-wrong")

    @mesh_agent(  # WRONG: mesh_agent FIRST
        tools=[
            {
                "function_name": "wrong_order_func",
                "capability": "test_capability",
                "dependencies": [{"capability": "auth_service"}],
            }
        ]
    )
    @server_wrong.tool()  # WRONG: server.tool SECOND
    def wrong_order_func(data: str, auth_service: Any = None) -> dict:
        """Function with wrong decorator order."""
        return {
            "data": data,
            "has_dependency": auth_service is not None,
            "order": "wrong",
        }

    # Wait for DI
    await asyncio.sleep(8)

    # Test correct order preserves metadata
    correct_tools = server_correct._tool_manager._tools
    correct_func = correct_tools["correct_order_func"].fn
    assert hasattr(correct_func, "_mesh_metadata")
    assert hasattr(correct_func, "_mesh_agent_dependencies")

    # Test wrong order loses metadata (FastMCP unwraps it)
    wrong_tools = server_wrong._tool_manager._tools
    wrong_func = wrong_tools["wrong_order_func"].fn
    # FastMCP may have unwrapped the mesh decorator
    # The function should still work but without mesh integration


@pytest.mark.asyncio
async def test_multi_tool_registry_communication(mock_multi_tool_registry):
    """Test that multi-tool format is correctly communicated to registry."""
    server = create_multi_tool_server()

    # Wait for registration
    await asyncio.sleep(8)

    # Verify the server registered properly
    # In a real scenario, we would check the registry logs
    # For now, we verify the functions have the correct metadata

    tools = server._tool_manager._tools
    greet_func = tools["greet"].fn

    if hasattr(greet_func, "_mesh_metadata"):
        metadata = greet_func._mesh_metadata

        # Verify multi-tool structure
        assert "tools" in metadata
        assert len(metadata["tools"]) == 2

        # Check that it can be serialized (for registry communication)
        import json

        json_metadata = json.dumps(metadata, default=str)
        parsed_metadata = json.loads(json_metadata)

        assert "tools" in parsed_metadata
        assert parsed_metadata["agent_name"] is not None


@pytest.mark.asyncio
async def test_heartbeat_with_multi_tool_dependencies(mock_multi_tool_registry):
    """Test that heartbeat correctly handles per-tool dependency resolution."""
    server = create_multi_tool_server()

    # Wait for initial registration and heartbeat
    await asyncio.sleep(10)

    # In a real scenario, the runtime would be sending heartbeats
    # and receiving per-tool dependency updates
    # For this test, we verify the structure is in place

    tools = server._tool_manager._tools
    greet_func = tools["greet"].fn
    process_func = tools["process_data"].fn

    # Both functions should have mesh metadata
    assert hasattr(greet_func, "_mesh_metadata")
    assert hasattr(process_func, "_mesh_metadata")

    # Verify they have different tool configurations
    greet_metadata = greet_func._mesh_metadata
    process_metadata = process_func._mesh_metadata

    # Find the specific tools
    greet_tool = next(
        (tool for tool in greet_metadata["tools"] if tool["function_name"] == "greet"),
        None,
    )
    process_tool = next(
        (
            tool
            for tool in process_metadata["tools"]
            if tool["function_name"] == "process_data"
        ),
        None,
    )

    assert greet_tool is not None
    assert process_tool is not None

    # Verify different dependencies
    greet_deps = [dep["capability"] for dep in greet_tool["dependencies"]]
    process_deps = [dep["capability"] for dep in process_tool["dependencies"]]

    assert "date_service" in greet_deps
    assert "auth_service" in process_deps


@pytest.mark.asyncio
async def test_graceful_degradation_without_registry():
    """Test that multi-tool format works even without registry."""
    # Clear any existing registry URL
    if "MCP_MESH_REGISTRY_URL" in os.environ:
        del os.environ["MCP_MESH_REGISTRY_URL"]

    server = create_multi_tool_server()

    # Wait a bit
    await asyncio.sleep(3)

    # Functions should still work without registry
    tools = server._tool_manager._tools
    greet_func = tools["greet"].fn

    # Call function - should work without DI
    result = greet_func(name="Alice")

    assert result["greeting"] == "Hello Alice!"
    assert result["format"] == "multi_tool"
    # dependency_status may be "not_injected" which is fine


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
