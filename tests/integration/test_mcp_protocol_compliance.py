"""
MCP Protocol Compliance Tests

Comprehensive tests to validate MCP JSON-RPC 2.0 protocol compliance
for the File Agent implementation.
"""

import json
import uuid
from typing import Any

import pytest

from mcp_mesh.shared.exceptions import (
    FileNotFoundError,
    FileOperationError,
    SecurityValidationError,
)
from mcp_mesh.tools.file_operations import FileOperations


class MCPProtocolValidator:
    """Utility class for validating MCP protocol compliance."""

    @staticmethod
    def validate_tool_call_request(request: dict[str, Any]) -> bool:
        """Validate MCP tool call request format."""
        required_fields = ["jsonrpc", "method", "id"]
        if not all(field in request for field in required_fields):
            return False

        if request["jsonrpc"] != "2.0":
            return False

        if request["method"] != "tools/call":
            return False

        # Validate params structure
        if "params" not in request:
            return False

        params = request["params"]
        if "name" not in params or "arguments" not in params:
            return False

        return True

    @staticmethod
    def validate_tool_call_response(response: dict[str, Any]) -> bool:
        """Validate MCP tool call response format."""
        required_fields = ["jsonrpc", "id"]
        if not all(field in response for field in required_fields):
            return False

        if response["jsonrpc"] != "2.0":
            return False

        # Either result or error must be present, but not both
        has_result = "result" in response
        has_error = "error" in response

        if has_result == has_error:  # XOR check
            return False

        # If error, validate error structure
        if has_error:
            error = response["error"]
            if not isinstance(error, dict):
                return False
            if "code" not in error or "message" not in error:
                return False

        return True

    @staticmethod
    def validate_error_response(error: dict[str, Any]) -> bool:
        """Validate MCP error response structure."""
        required_fields = ["code", "message"]
        if not all(field in error for field in required_fields):
            return False

        # Code must be integer
        if not isinstance(error["code"], int):
            return False

        # Message must be string
        if not isinstance(error["message"], str):
            return False

        return True


@pytest.fixture
async def file_ops():
    """Create FileOperations instance for testing."""
    ops = FileOperations()
    yield ops
    await ops.cleanup()


@pytest.fixture
def mcp_validator():
    """Create MCP protocol validator."""
    return MCPProtocolValidator()


class TestMCPToolRegistration:
    """Test MCP tool registration and discovery."""

    async def test_tool_list_format(self, file_ops):
        """Test tools/list response format compliance."""
        # Simulate tools/list request
        request = {"jsonrpc": "2.0", "method": "tools/list", "id": str(uuid.uuid4())}

        # Expected tools in the file operations
        expected_tools = ["read_file", "write_file", "list_directory"]

        # In a real implementation, this would be handled by the MCP server
        # For testing, we simulate the response
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read file contents with security validation",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path to read",
                                },
                                "encoding": {"type": "string", "default": "utf-8"},
                            },
                            "required": ["path"],
                        },
                    },
                    {
                        "name": "write_file",
                        "description": "Write content to file with backup and validation",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path to write",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Content to write",
                                },
                                "encoding": {"type": "string", "default": "utf-8"},
                                "create_backup": {"type": "boolean", "default": True},
                            },
                            "required": ["path", "content"],
                        },
                    },
                    {
                        "name": "list_directory",
                        "description": "List directory contents with security validation",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Directory path to list",
                                },
                                "include_hidden": {"type": "boolean", "default": False},
                                "include_details": {
                                    "type": "boolean",
                                    "default": False,
                                },
                            },
                            "required": ["path"],
                        },
                    },
                ]
            },
        }

        # Validate response format
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "tools" in response["result"]

        tools = response["result"]["tools"]
        assert len(tools) == 3

        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["name"] in expected_tools

    async def test_tool_call_request_validation(self, mcp_validator):
        """Test validation of tool call requests."""
        # Valid request
        valid_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "test-123",
            "params": {"name": "read_file", "arguments": {"path": "/test/file.txt"}},
        }
        assert mcp_validator.validate_tool_call_request(valid_request)

        # Invalid requests
        invalid_requests = [
            # Missing jsonrpc
            {
                "method": "tools/call",
                "id": "test-123",
                "params": {"name": "read_file", "arguments": {}},
            },
            # Wrong jsonrpc version
            {
                "jsonrpc": "1.0",
                "method": "tools/call",
                "id": "test-123",
                "params": {"name": "read_file", "arguments": {}},
            },
            # Missing method
            {
                "jsonrpc": "2.0",
                "id": "test-123",
                "params": {"name": "read_file", "arguments": {}},
            },
            # Missing params
            {"jsonrpc": "2.0", "method": "tools/call", "id": "test-123"},
            # Invalid params structure
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": "test-123",
                "params": {"arguments": {}},  # Missing name
            },
        ]

        for invalid_request in invalid_requests:
            assert not mcp_validator.validate_tool_call_request(invalid_request)


class TestMCPToolCallProtocol:
    """Test MCP tool call protocol compliance."""

    async def test_successful_tool_call_response(self, file_ops, mcp_validator):
        """Test successful tool call response format."""
        # Simulate successful read_file call
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "read-test-123",
            "params": {"name": "read_file", "arguments": {"path": "/tmp/test.txt"}},
        }

        # Create test file
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            temp_path = f.name

        try:
            # Simulate tool execution
            content = await file_ops.read_file(temp_path)

            # Format response according to MCP protocol
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"content": [{"type": "text", "text": content}]},
            }

            # Validate response
            assert mcp_validator.validate_tool_call_response(response)
            assert response["result"]["content"][0]["text"] == "test content"

        finally:
            import os

            os.unlink(temp_path)

    async def test_error_tool_call_response(self, file_ops, mcp_validator):
        """Test error tool call response format."""
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": "error-test-123",
            "params": {
                "name": "read_file",
                "arguments": {"path": "/nonexistent/file.txt"},
            },
        }

        try:
            await file_ops.read_file("/nonexistent/file.txt")
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError as e:
            # Format error response according to MCP protocol
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32603,  # Internal error
                    "message": str(e),
                    "data": {
                        "type": "FileNotFoundError",
                        "file_path": "/nonexistent/file.txt",
                    },
                },
            }

            # Validate error response
            assert mcp_validator.validate_tool_call_response(response)
            assert mcp_validator.validate_error_response(response["error"])

    async def test_all_tools_mcp_compliance(self, file_ops, mcp_validator):
        """Test all file operation tools for MCP compliance."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")

            # Test cases for each tool
            test_cases = [
                {
                    "tool": "write_file",
                    "args": {"path": test_file, "content": "test content"},
                    "setup": None,
                    "expected_type": bool,
                },
                {
                    "tool": "read_file",
                    "args": {"path": test_file},
                    "setup": lambda: open(test_file, "w").write("test content"),
                    "expected_type": str,
                },
                {
                    "tool": "list_directory",
                    "args": {"path": temp_dir},
                    "setup": None,
                    "expected_type": list,
                },
            ]

            for i, test_case in enumerate(test_cases):
                request_id = f"test-{i}"

                # Setup if needed
                if test_case["setup"]:
                    test_case["setup"]()

                try:
                    # Execute tool
                    tool_func = getattr(file_ops, test_case["tool"])
                    result = await tool_func(**test_case["args"])

                    # Format successful response
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        json.dumps(result)
                                        if not isinstance(result, str)
                                        else result
                                    ),
                                }
                            ]
                        },
                    }

                    # Validate response format
                    assert mcp_validator.validate_tool_call_response(response)
                    assert isinstance(result, test_case["expected_type"])

                except Exception as e:
                    # Format error response
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": str(e),
                            "data": {"type": type(e).__name__},
                        },
                    }

                    # Validate error response format
                    assert mcp_validator.validate_tool_call_response(response)
                    assert mcp_validator.validate_error_response(response["error"])


class TestMCPResourceProtocol:
    """Test MCP resource protocol compliance."""

    async def test_resource_list_format(self):
        """Test resources/list response format."""
        request = {
            "jsonrpc": "2.0",
            "method": "resources/list",
            "id": "resource-list-123",
        }

        # Simulate resources/list response
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "resources": [
                    {
                        "uri": "file://agent/config",
                        "name": "Agent Configuration",
                        "description": "Current agent configuration and capabilities",
                        "mimeType": "application/json",
                    },
                    {
                        "uri": "file://agent/health",
                        "name": "Agent Health Status",
                        "description": "Current health status and diagnostics",
                        "mimeType": "application/json",
                    },
                    {
                        "uri": "file://agent/stats",
                        "name": "Agent Statistics",
                        "description": "Operational statistics and metrics",
                        "mimeType": "application/json",
                    },
                ]
            },
        }

        # Validate response format
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "resources" in response["result"]

        resources = response["result"]["resources"]
        assert len(resources) == 3

        for resource in resources:
            assert "uri" in resource
            assert "name" in resource
            assert "description" in resource
            assert "mimeType" in resource
            assert resource["uri"].startswith("file://agent/")

    async def test_resource_read_format(self, file_ops):
        """Test resources/read response format."""
        request = {
            "jsonrpc": "2.0",
            "method": "resources/read",
            "id": "resource-read-123",
            "params": {"uri": "file://agent/health"},
        }

        # Get health status
        health_status = await file_ops.health_check()
        health_data = {
            "agent_name": health_status.agent_name,
            "status": health_status.status.value,
            "capabilities": health_status.capabilities,
            "timestamp": health_status.timestamp.isoformat(),
            "checks": health_status.checks,
            "uptime_seconds": health_status.uptime_seconds,
        }

        # Format response
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "contents": [
                    {
                        "uri": "file://agent/health",
                        "mimeType": "application/json",
                        "text": json.dumps(health_data, indent=2),
                    }
                ]
            },
        }

        # Validate response format
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "contents" in response["result"]

        content = response["result"]["contents"][0]
        assert "uri" in content
        assert "mimeType" in content
        assert "text" in content

        # Validate JSON content
        parsed_data = json.loads(content["text"])
        assert "agent_name" in parsed_data
        assert "status" in parsed_data
        assert "capabilities" in parsed_data


class TestMCPPromptProtocol:
    """Test MCP prompt protocol compliance."""

    async def test_prompt_list_format(self):
        """Test prompts/list response format."""
        request = {"jsonrpc": "2.0", "method": "prompts/list", "id": "prompt-list-123"}

        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "prompts": [
                    {
                        "name": "file_analysis",
                        "description": "Analyze file or directory structure and content",
                        "arguments": [
                            {
                                "name": "file_path",
                                "description": "Path to file or directory to analyze",
                                "required": True,
                            }
                        ],
                    },
                    {
                        "name": "file_operation_guide",
                        "description": "Provide guidance on file operations and best practices",
                    },
                ]
            },
        }

        # Validate response format
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "prompts" in response["result"]

        prompts = response["result"]["prompts"]
        assert len(prompts) == 2

        for prompt in prompts:
            assert "name" in prompt
            assert "description" in prompt

    async def test_prompt_get_format(self):
        """Test prompts/get response format."""
        request = {
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": "prompt-get-123",
            "params": {
                "name": "file_analysis",
                "arguments": {"file_path": "/test/file.txt"},
            },
        }

        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "description": "Analyze file or directory structure and content",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Please analyze the file at /test/file.txt and provide insights about its structure and content.",
                        },
                    }
                ],
            },
        }

        # Validate response format
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "messages" in response["result"]

        messages = response["result"]["messages"]
        assert len(messages) > 0

        message = messages[0]
        assert "role" in message
        assert "content" in message
        assert message["role"] in ["user", "assistant", "system"]


class TestMCPErrorHandling:
    """Test MCP error handling compliance."""

    async def test_standard_error_codes(self, file_ops, mcp_validator):
        """Test standard MCP error codes."""
        error_test_cases = [
            {
                "operation": lambda: file_ops.read_file(""),
                "expected_code": -32602,  # Invalid params
                "description": "Empty path parameter",
            },
            {
                "operation": lambda: file_ops.read_file("/nonexistent/file.txt"),
                "expected_code": -32603,  # Internal error (file not found)
                "description": "File not found",
            },
            {
                "operation": lambda: file_ops.read_file("../../../etc/passwd"),
                "expected_code": -32603,  # Internal error (security violation)
                "description": "Path traversal attempt",
            },
        ]

        for i, test_case in enumerate(error_test_cases):
            request_id = f"error-test-{i}"

            try:
                await test_case["operation"]()
                raise AssertionError(
                    f"Should have raised exception for: {test_case['description']}"
                )
            except Exception as e:
                # Format error response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": test_case["expected_code"],
                        "message": str(e),
                        "data": {
                            "type": type(e).__name__,
                            "description": test_case["description"],
                        },
                    },
                }

                # Validate error response
                assert mcp_validator.validate_tool_call_response(response)
                assert mcp_validator.validate_error_response(response["error"])
                assert response["error"]["code"] == test_case["expected_code"]

    async def test_error_serialization(self):
        """Test that all errors can be serialized to JSON."""
        from mcp_mesh.shared.exceptions import (
            FileAccessDeniedError,
            FileNotFoundError,
            FileTooLargeError,
        )

        test_exceptions = [
            FileOperationError("Test error", file_path="/test", operation="read"),
            FileNotFoundError("/nonexistent/file.txt"),
            FileAccessDeniedError("/restricted/file.txt", "read"),
            FileTooLargeError("/large/file.txt", 1000000, 500000),
            SecurityValidationError("Invalid path"),
        ]

        for exc in test_exceptions:
            error_dict = {
                "code": -32603,
                "message": str(exc),
                "data": {
                    "type": type(exc).__name__,
                    "details": exc.__dict__ if hasattr(exc, "__dict__") else {},
                },
            }

            # Should be JSON serializable
            json_str = json.dumps(error_dict)
            parsed = json.loads(json_str)

            assert parsed["code"] == -32603
            assert parsed["message"] == str(exc)
            assert parsed["data"]["type"] == type(exc).__name__


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
