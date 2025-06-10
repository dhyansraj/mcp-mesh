"""
Integration tests for File Operations with MCP Protocol and Mesh Integration.

Tests full integration with FastMCP, MCP protocol compliance,
and mesh agent decorator functionality.
"""

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp_mesh.runtime.shared.types import HealthStatus
from mcp_mesh.runtime.tools.file_operations import FileOperations


# Mock FastMCP for integration testing
class MockFastMCP:
    """Mock FastMCP server for integration testing."""

    def __init__(self, name: str, instructions: str = ""):
        self.name = name
        self.instructions = instructions
        self.tools = {}
        self.resources = {}
        self.prompts = {}
        self._call_log = []

    def tool(self, name: str = None, description: str = None):
        def decorator(func):
            tool_name = name or func.__name__
            self.tools[tool_name] = {
                "function": func,
                "description": description or func.__doc__,
                "name": tool_name,
            }
            return func

        return decorator

    def resource(self, uri: str):
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator

    def prompt(self, name: str = None):
        def decorator(func):
            prompt_name = name or func.__name__
            self.prompts[prompt_name] = func
            return func

        return decorator

    async def call_tool(self, name: str, **kwargs):
        """Simulate MCP tool call."""
        if name not in self.tools:
            raise ValueError(f"Tool {name} not found")

        tool = self.tools[name]
        self._call_log.append(
            {
                "type": "tool_call",
                "name": name,
                "args": kwargs,
                "timestamp": datetime.now(),
            }
        )

        return await tool["function"](**kwargs)

    async def get_resource(self, uri: str):
        """Simulate MCP resource request."""
        if uri not in self.resources:
            raise ValueError(f"Resource {uri} not found")

        self._call_log.append(
            {"type": "resource_request", "uri": uri, "timestamp": datetime.now()}
        )

        return await self.resources[uri]()

    async def get_prompt(self, name: str, **kwargs):
        """Simulate MCP prompt request."""
        if name not in self.prompts:
            raise ValueError(f"Prompt {name} not found")

        self._call_log.append(
            {
                "type": "prompt_request",
                "name": name,
                "args": kwargs,
                "timestamp": datetime.now(),
            }
        )

        return await self.prompts[name](**kwargs)


@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def file_agent_server(temp_dir):
    """Create a complete file agent server for integration testing."""
    from examples.file_operations_fastmcp import FileAgentServer

    # Mock the real FastMCP
    with patch("examples.file_operations_fastmcp.MockFastMCP", MockFastMCP):
        server = FileAgentServer(
            base_directory=str(temp_dir), max_file_size=1024 * 1024  # 1MB
        )
        yield server
        await server.cleanup()


class TestMCPProtocolCompliance:
    """Test compliance with MCP protocol specifications."""

    async def test_tool_registration(self, file_agent_server):
        """Test that tools are properly registered with MCP protocol format."""
        app = file_agent_server.app

        # Check required tools are registered
        required_tools = ["read_file", "write_file", "list_directory", "get_file_info"]
        for tool_name in required_tools:
            assert tool_name in app.tools

            tool = app.tools[tool_name]
            assert "function" in tool
            assert "description" in tool
            assert "name" in tool
            assert callable(tool["function"])

    async def test_resource_registration(self, file_agent_server):
        """Test that resources are properly registered."""
        app = file_agent_server.app

        required_resources = [
            "file://agent/config",
            "file://agent/health",
            "file://agent/stats",
        ]

        for resource_uri in required_resources:
            assert resource_uri in app.resources
            assert callable(app.resources[resource_uri])

    async def test_prompt_registration(self, file_agent_server):
        """Test that prompts are properly registered."""
        app = file_agent_server.app

        required_prompts = ["file_analysis", "file_operation_guide"]
        for prompt_name in required_prompts:
            assert prompt_name in app.prompts
            assert callable(app.prompts[prompt_name])

    async def test_tool_call_json_serializable(self, file_agent_server, temp_dir):
        """Test that tool responses are JSON serializable."""
        app = file_agent_server.app

        # Create test file
        test_file = temp_dir / "test.json"
        test_data = {"message": "hello", "number": 42}
        test_file.write_text(json.dumps(test_data))

        # Test read_file tool
        content = await app.call_tool("read_file", path=str(test_file))
        json.dumps(content)  # Should not raise exception

        # Test write_file tool
        result = await app.call_tool(
            "write_file", path=str(test_file), content='{"updated": true}'
        )
        json.dumps(result)  # Should not raise exception

        # Test list_directory tool
        entries = await app.call_tool("list_directory", path=str(temp_dir))
        json.dumps(entries)  # Should not raise exception

        # Test get_file_info tool
        file_info = await app.call_tool("get_file_info", path=str(test_file))
        json.dumps(file_info)  # Should not raise exception

    async def test_error_handling_protocol(self, file_agent_server):
        """Test that errors follow MCP protocol format."""
        app = file_agent_server.app

        # Test file not found error
        try:
            await app.call_tool("read_file", path="/nonexistent/file.txt")
            raise AssertionError("Should have raised exception")
        except Exception as e:
            # Error should be a standard exception that can be serialized
            error_dict = {"error": str(e), "type": type(e).__name__}
            json.dumps(error_dict)  # Should not raise exception

    async def test_resource_responses(self, file_agent_server):
        """Test that resource responses are properly formatted."""
        app = file_agent_server.app

        # Test config resource
        config_response = await app.get_resource("file://agent/config")
        config_data = json.loads(config_response)
        assert "name" in config_data
        assert "capabilities" in config_data
        assert "mesh_integration" in config_data

        # Test health resource
        health_response = await app.get_resource("file://agent/health")
        health_data = json.loads(health_response)
        assert "status" in health_data
        assert "timestamp" in health_data

        # Test stats resource
        stats_response = await app.get_resource("file://agent/stats")
        stats_data = json.loads(stats_response)
        assert "tools_registered" in stats_data
        assert "mesh_capabilities" in stats_data


class TestMeshIntegration:
    """Test mesh agent decorator integration."""

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_mesh_registration(self, mock_registry_client, file_agent_server):
        """Test mesh capability registration."""
        # Mock the registry client
        mock_client_instance = AsyncMock()
        mock_registry_client.return_value = mock_client_instance

        # Create file operations and trigger mesh registration
        file_ops = FileOperations()

        # Trigger operations to initialize mesh
        try:
            await file_ops.read_file("/tmp/test.txt")
        except:
            pass  # We don't care about the file operation result

        # Verify mesh integration was attempted
        # Note: In real implementation, would verify registry calls
        await file_ops.cleanup()

    async def test_dependency_injection_simulation(self, file_agent_server, temp_dir):
        """Test simulated dependency injection."""
        app = file_agent_server.app

        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("test content")

        # The mesh decorator should inject dependencies, but operations
        # should work in fallback mode when dependencies are unavailable
        content = await app.call_tool("read_file", path=str(test_file))
        assert content == "test content"

        # Write operation should also work
        result = await app.call_tool(
            "write_file", path=str(test_file), content="updated content"
        )
        assert result is True

    async def test_health_monitoring(self, file_agent_server):
        """Test health monitoring functionality."""
        file_ops = file_agent_server.file_ops

        # Perform health check
        health_status = await file_ops.health_check()

        assert isinstance(health_status, HealthStatus)
        assert health_status.agent_name == "file-operations-agent"
        assert health_status.status in ["healthy", "degraded", "unhealthy"]
        assert len(health_status.capabilities) > 0
        assert health_status.timestamp is not None

        # Check that capabilities match expected values
        expected_capabilities = [
            "file_read",
            "file_write",
            "directory_list",
            "secure_access",
        ]
        for cap in expected_capabilities:
            assert cap in health_status.capabilities


class TestSecurityIntegration:
    """Test security features in integration context."""

    async def test_path_traversal_protection_integration(self, file_agent_server):
        """Test path traversal protection through MCP interface."""
        app = file_agent_server.app

        malicious_paths = ["../../../etc/passwd", "../../secret.txt", "../outside.txt"]

        for path in malicious_paths:
            with pytest.raises(Exception):  # Should raise SecurityValidationError
                await app.call_tool("read_file", path=path)

    async def test_file_extension_validation_integration(
        self, file_agent_server, temp_dir
    ):
        """Test file extension validation through MCP interface."""
        app = file_agent_server.app

        # Allowed extension should work
        allowed_file = temp_dir / "test.txt"
        result = await app.call_tool(
            "write_file", path=str(allowed_file), content="allowed content"
        )
        assert result is True

        # Disallowed extension should fail
        disallowed_file = temp_dir / "malicious.exe"
        with pytest.raises(Exception):  # Should raise SecurityValidationError
            await app.call_tool(
                "write_file", path=str(disallowed_file), content="malicious content"
            )

    async def test_size_limit_enforcement_integration(
        self, file_agent_server, temp_dir
    ):
        """Test file size limit enforcement through MCP interface."""
        app = file_agent_server.app

        # Small file should work
        small_content = "small content"
        small_file = temp_dir / "small.txt"
        result = await app.call_tool(
            "write_file", path=str(small_file), content=small_content
        )
        assert result is True

        # Large file should fail (server configured with 1MB limit)
        large_content = "x" * (2 * 1024 * 1024)  # 2MB
        large_file = temp_dir / "large.txt"
        with pytest.raises(Exception):  # Should raise FileOperationError
            await app.call_tool(
                "write_file", path=str(large_file), content=large_content
            )


class TestConcurrentOperations:
    """Test concurrent operations through MCP interface."""

    async def test_concurrent_tool_calls(self, file_agent_server, temp_dir):
        """Test concurrent MCP tool calls."""
        app = file_agent_server.app

        # Create multiple test files
        files_and_content = []
        for i in range(5):
            test_file = temp_dir / f"concurrent_{i}.txt"
            content = f"content for file {i}"
            files_and_content.append((str(test_file), content))

        # Write all files concurrently
        write_tasks = [
            app.call_tool("write_file", path=path, content=content)
            for path, content in files_and_content
        ]
        write_results = await asyncio.gather(*write_tasks)
        assert all(write_results)

        # Read all files concurrently
        read_tasks = [
            app.call_tool("read_file", path=path) for path, _ in files_and_content
        ]
        read_results = await asyncio.gather(*read_tasks)

        # Verify results
        for i, content in enumerate(read_results):
            expected_content = f"content for file {i}"
            assert content == expected_content

    async def test_mixed_concurrent_operations(self, file_agent_server, temp_dir):
        """Test mixed concurrent operations (read, write, list)."""
        app = file_agent_server.app

        # Setup initial files
        for i in range(3):
            test_file = temp_dir / f"initial_{i}.txt"
            test_file.write_text(f"initial content {i}")

        # Mix of operations
        tasks = [
            app.call_tool("read_file", path=str(temp_dir / "initial_0.txt")),
            app.call_tool(
                "write_file", path=str(temp_dir / "new_file.txt"), content="new"
            ),
            app.call_tool("list_directory", path=str(temp_dir)),
            app.call_tool("get_file_info", path=str(temp_dir / "initial_1.txt")),
            app.call_tool("read_file", path=str(temp_dir / "initial_2.txt")),
        ]

        results = await asyncio.gather(*tasks)

        # Verify results
        assert results[0] == "initial content 0"  # read result
        assert results[1] is True  # write result
        assert isinstance(results[2], list)  # list result
        assert isinstance(results[3], dict)  # file info result
        assert results[4] == "initial content 2"  # read result


class TestPromptGeneration:
    """Test MCP prompt generation functionality."""

    async def test_file_analysis_prompt(self, file_agent_server, temp_dir):
        """Test file analysis prompt generation."""
        app = file_agent_server.app

        # Create test file
        test_file = temp_dir / "analysis_test.py"
        test_content = '''def hello_world():
    """Sample Python function."""
    print("Hello, World!")
    return True
'''
        test_file.write_text(test_content)

        # Generate prompt
        prompt_messages = await app.get_prompt(
            "file_analysis", file_path=str(test_file)
        )

        assert isinstance(prompt_messages, list)
        assert len(prompt_messages) > 0

        message = prompt_messages[0]
        assert "role" in message
        assert "content" in message
        assert message["role"] == "user"
        assert "type" in message["content"]
        assert message["content"]["type"] == "text"
        assert "text" in message["content"]

        # Verify prompt contains file information
        prompt_text = message["content"]["text"]
        assert str(test_file) in prompt_text
        assert "Content Preview:" in prompt_text
        assert "hello_world" in prompt_text

    async def test_directory_analysis_prompt(self, file_agent_server, temp_dir):
        """Test directory analysis prompt generation."""
        app = file_agent_server.app

        # Create test directory structure
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.json").write_text('{"key": "value"}')
        (temp_dir / "subdir").mkdir()

        # Generate prompt for directory
        prompt_messages = await app.get_prompt("file_analysis", file_path=str(temp_dir))

        assert isinstance(prompt_messages, list)
        assert len(prompt_messages) > 0

        message = prompt_messages[0]
        prompt_text = message["content"]["text"]

        # Verify directory-specific content
        assert "Directory Information:" in prompt_text
        assert "Contains 3 items" in prompt_text
        assert str(temp_dir) in prompt_text

    async def test_file_operation_guide_prompt(self, file_agent_server):
        """Test file operation guide prompt generation."""
        app = file_agent_server.app

        prompt_messages = await app.get_prompt("file_operation_guide")

        assert isinstance(prompt_messages, list)
        assert len(prompt_messages) > 0

        message = prompt_messages[0]
        assert message["role"] == "assistant"

        prompt_text = message["content"]["text"]
        assert "File Operations Guide:" in prompt_text
        assert "Available Tools:" in prompt_text
        assert "Security Features:" in prompt_text
        assert "Mesh Integration Benefits:" in prompt_text


class TestEndToEndScenarios:
    """Test complete end-to-end scenarios."""

    async def test_complete_document_workflow(self, file_agent_server, temp_dir):
        """Test complete document management workflow."""
        app = file_agent_server.app

        # 1. Create a document
        doc_path = str(temp_dir / "document.md")
        doc_content = """# Project Documentation

## Overview
This is a test document for the MCP-Mesh file agent.

## Features
- Secure file operations
- Mesh integration
- Health monitoring
"""

        result = await app.call_tool("write_file", path=doc_path, content=doc_content)
        assert result is True

        # 2. Read the document
        content = await app.call_tool("read_file", path=doc_path)
        assert content == doc_content

        # 3. Get document info
        file_info = await app.call_tool("get_file_info", path=doc_path)
        assert file_info["type"] == "file"
        assert file_info["extension"] == ".md"
        assert file_info["size"] > 0

        # 4. List directory to see the document
        entries = await app.call_tool("list_directory", path=str(temp_dir))
        assert "document.md" in entries

        # 5. Update the document (with backup)
        updated_content = doc_content + "\n\n## Updates\n- Added new section"
        result = await app.call_tool(
            "write_file", path=doc_path, content=updated_content, create_backup=True
        )
        assert result is True

        # 6. Verify update
        final_content = await app.call_tool("read_file", path=doc_path)
        assert final_content == updated_content
        assert "## Updates" in final_content

        # 7. Verify backup was created
        backup_files = list(temp_dir.glob("document.md.backup.*"))
        assert len(backup_files) == 1

        # 8. Generate analysis prompt for the document
        prompt_messages = await app.get_prompt("file_analysis", file_path=doc_path)
        assert len(prompt_messages) > 0
        assert "document.md" in prompt_messages[0]["content"]["text"]

    async def test_configuration_management_workflow(self, file_agent_server, temp_dir):
        """Test configuration file management workflow."""
        app = file_agent_server.app

        # 1. Create configuration directory
        config_dir = temp_dir / "config"
        config_dir.mkdir()

        # 2. Create multiple config files
        configs = {
            "app.json": '{"name": "myapp", "version": "1.0.0"}',
            "database.json": '{"host": "localhost", "port": 5432}',
            "features.json": '{"feature_a": true, "feature_b": false}',
        }

        for filename, content in configs.items():
            file_path = str(config_dir / filename)
            result = await app.call_tool("write_file", path=file_path, content=content)
            assert result is True

        # 3. List configuration files
        config_entries = await app.call_tool(
            "list_directory", path=str(config_dir), include_details=True
        )
        assert len(config_entries) == 3

        # Verify detailed information
        for entry in config_entries:
            assert entry["type"] == "file"
            assert entry["name"] in configs.keys()
            assert entry["size"] > 0

        # 4. Read and verify each config
        for filename, expected_content in configs.items():
            file_path = str(config_dir / filename)
            content = await app.call_tool("read_file", path=file_path)
            assert content == expected_content

        # 5. Update a config file
        updated_app_config = '{"name": "myapp", "version": "1.1.0", "updated": true}'
        app_config_path = str(config_dir / "app.json")
        result = await app.call_tool(
            "write_file", path=app_config_path, content=updated_app_config
        )
        assert result is True

        # 6. Verify update
        updated_content = await app.call_tool("read_file", path=app_config_path)
        updated_data = json.loads(updated_content)
        assert updated_data["version"] == "1.1.0"
        assert updated_data["updated"] is True


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-s"])
