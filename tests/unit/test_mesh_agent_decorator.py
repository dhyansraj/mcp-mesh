"""
Tests for the @mesh_agent decorator functionality.
"""

import asyncio

import pytest
from mcp_mesh import mesh_agent


class TestMeshAgentDecorator:
    """Test cases for the mesh_agent decorator functionality."""

    def test_decorator_basic_usage(self):
        """Test that the decorator works with basic parameters."""

        @mesh_agent(capability="file_read")
        def test_function(path: str) -> str:
            """Test function docstring."""
            return f"Read {path}"

        # Verify metadata is attached
        assert hasattr(test_function, "_mesh_metadata")
        metadata = test_function._mesh_metadata
        assert metadata["capability"] == "file_read"
        assert metadata["capabilities"] == ["file_read"]  # Stored as list internally
        assert metadata["description"] == "Test function docstring."

        # Test function execution
        result = test_function("/test/file.txt")
        assert result == "Read /test/file.txt"

    def test_decorator_with_all_parameters(self):
        """Test decorator with all parameters specified."""

        @mesh_agent(
            capability="file_write",
            health_interval=60,
            dependencies=["auth_service", "audit_logger"],
            registry_url="http://test-registry",
            agent_name="test-agent",
            security_context="file_ops",
            timeout=45,
            retry_attempts=5,
            enable_caching=False,
            fallback_mode=False,
            version="2.0.0",
            description="Custom description",
            endpoint="http://test-endpoint",
            tags=["test", "file"],
            performance_profile={"cpu": "low", "memory": "medium"},
            resource_requirements={"min_memory": "512MB"},
            enable_http=True,
            http_host="localhost",
            http_port=8080,
            custom_field="custom_value",
        )
        def test_function():
            return "test"

        metadata = test_function._mesh_metadata
        assert metadata["capability"] == "file_write"
        assert metadata["health_interval"] == 60
        assert metadata["dependencies"] == ["auth_service", "audit_logger"]
        assert metadata["registry_url"] == "http://test-registry"
        assert metadata["agent_name"] == "test-agent"
        assert metadata["security_context"] == "file_ops"
        assert metadata["timeout"] == 45
        assert metadata["retry_attempts"] == 5
        assert metadata["enable_caching"] is False
        assert metadata["fallback_mode"] is False
        assert metadata["version"] == "2.0.0"
        assert metadata["description"] == "Custom description"
        assert metadata["endpoint"] == "http://test-endpoint"
        assert metadata["tags"] == ["test", "file"]
        assert metadata["performance_profile"] == {"cpu": "low", "memory": "medium"}
        assert metadata["resource_requirements"] == {"min_memory": "512MB"}
        assert metadata["enable_http"] is True
        assert metadata["http_host"] == "localhost"
        assert metadata["http_port"] == 8080
        assert metadata["custom_field"] == "custom_value"

    @pytest.mark.asyncio
    async def test_async_function_decoration(self):
        """Test decorator works with async functions."""

        @mesh_agent(capability="async_test")
        async def test_function(value: str) -> str:
            await asyncio.sleep(0.01)  # Simulate async work
            return f"processed: {value}"

        # Verify metadata is attached
        assert hasattr(test_function, "_mesh_metadata")
        assert test_function._mesh_metadata["capability"] == "async_test"

        # Test function execution
        result = await test_function("hello")
        assert result == "processed: hello"

    def test_sync_function_decoration(self):
        """Test decorator works with sync functions."""

        @mesh_agent(capability="sync_test")
        def test_function(value: str) -> str:
            return f"processed: {value}"

        # Verify metadata is attached
        assert hasattr(test_function, "_mesh_metadata")
        assert test_function._mesh_metadata["capability"] == "sync_test"

        # Test function execution
        result = test_function("hello")
        assert result == "processed: hello"

    def test_backward_compatibility_attributes(self):
        """Test that backward compatibility attributes are set."""

        @mesh_agent(capability="test", dependencies=["service1", "service2"])
        def test_function():
            return "test"

        # Check backward compatibility attributes
        assert hasattr(test_function, "_mesh_agent_capabilities")
        assert test_function._mesh_agent_capabilities == ["test"]
        assert hasattr(test_function, "_mesh_agent_dependencies")
        assert test_function._mesh_agent_dependencies == ["service1", "service2"]

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_creation(self):
        """Test that dependency injection wrapper is created when dependencies are specified."""

        # We'll check if the function has the injection-related attributes
        @mesh_agent(capability="test", dependencies=["TestService"])
        def test_function(data: str, TestService=None) -> str:
            if TestService:
                return f"With service: {data}"
            return f"No service: {data}"

        # The function should have dependency metadata
        assert test_function._mesh_agent_dependencies == ["TestService"]

        # Without injection setup, it should work with default
        result = test_function(data="hello")
        assert result == "No service: hello"

    def test_default_values(self):
        """Test that default values are properly set."""

        @mesh_agent(capability="test")
        def test_function():
            """Function doc"""
            return "test"

        metadata = test_function._mesh_metadata

        # Check defaults
        assert metadata["health_interval"] == 30
        assert metadata["dependencies"] == []
        assert metadata["registry_url"] is None
        assert metadata["agent_name"] == "test_function"
        assert metadata["security_context"] is None
        assert metadata["timeout"] == 30
        assert metadata["retry_attempts"] == 3
        assert metadata["enable_caching"] is True
        assert metadata["fallback_mode"] is True
        assert metadata["version"] == "1.0.0"
        assert metadata["description"] == "Function doc"
        assert metadata["endpoint"] is None
        assert metadata["tags"] == []
        assert metadata["performance_profile"] == {}
        assert metadata["resource_requirements"] == {}
        assert metadata["enable_http"] is None
        assert metadata["http_host"] == "0.0.0.0"
        assert metadata["http_port"] == 0

    def test_decorator_preserves_function_attributes(self):
        """Test that decorator preserves function name, docstring, etc."""

        def original_function(x: int, y: int) -> int:
            """Adds two numbers."""
            return x + y

        decorated = mesh_agent(capability="math")(original_function)

        # Check preserved attributes
        assert decorated.__name__ == "original_function"
        assert decorated.__doc__ == "Adds two numbers."

        # Function should still work
        assert decorated(5, 3) == 8

    @pytest.mark.asyncio
    async def test_decorator_with_fastmcp_integration(self):
        """Test that decorator works with FastMCP-style tool decoration."""

        # Simulate FastMCP tool decorator
        def mock_tool_decorator(func):
            func._is_tool = True
            return func

        @mesh_agent(capability="file_read", dependencies=["auth_service"])
        @mock_tool_decorator
        async def read_file(path: str, auth_service: str = None) -> str:
            if auth_service:
                return f"Authenticated read of {path}"
            return f"Read {path}"

        # Verify both decorators work together
        assert hasattr(read_file, "_mesh_metadata")
        assert hasattr(read_file, "_is_tool")
        assert read_file._mesh_metadata["capability"] == "file_read"

        result = await read_file(path="/test/file.txt")
        assert "Read /test/file.txt" in result

    def test_multiple_decorations(self):
        """Test applying decorator to multiple functions."""

        @mesh_agent(capability="read")
        def read_func():
            return "read"

        @mesh_agent(capability="write")
        def write_func():
            return "write"

        # Each should have its own metadata
        assert read_func._mesh_metadata["capability"] == "read"
        assert write_func._mesh_metadata["capability"] == "write"

        # Functions should work independently
        assert read_func() == "read"
        assert write_func() == "write"
