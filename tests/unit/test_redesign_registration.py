"""
Unit tests for the redesigned registration and dependency injection system.

These tests define the expected behavior BEFORE implementation (TDD).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent
from mcp_mesh.decorators import _get_or_create_agent_id
from mcp_mesh.runtime.registry_client import RegistryClient


class TestAgentIDGeneration:
    """Test the new agent ID generation logic."""

    def test_agent_id_format_with_env_var(self):
        """Test agent ID format when MCP_MESH_AGENT_NAME is set."""
        with patch.dict("os.environ", {"MCP_MESH_AGENT_NAME": "myservice"}):
            # Reset global to test
            import mcp_mesh.decorators

            mcp_mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id()

            # Should be format: myservice-{8chars}
            assert agent_id.startswith("myservice-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_format_without_env_var(self):
        """Test agent ID format when no env var is set."""
        with patch.dict("os.environ", {}, clear=True):
            # Reset global to test
            import mcp_mesh.decorators

            mcp_mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id()

            # Should be format: agent-{8chars}
            assert agent_id.startswith("agent-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_is_shared_across_functions(self):
        """Test that all functions in a process share the same agent ID."""
        # Reset for clean test
        import mcp_mesh.decorators

        mcp_mesh.decorators._SHARED_AGENT_ID = None

        id1 = _get_or_create_agent_id()
        id2 = _get_or_create_agent_id()
        id3 = _get_or_create_agent_id()

        assert id1 == id2 == id3


class TestBatchedRegistration:
    """Test the new batched registration system."""

    @pytest.mark.asyncio
    async def test_single_registration_for_multiple_functions(self):
        """Test that multiple functions result in ONE registration call."""
        mock_registry = AsyncMock(spec=RegistryClient)
        mock_registry.post = AsyncMock(
            return_value=MagicMock(
                status=201, json=AsyncMock(return_value={"status": "success"})
            )
        )

        # Create server with multiple functions
        server = FastMCP("test-batch")

        @server.tool()
        @mesh_agent(capability="greeting")
        def greet(name: str) -> str:
            return f"Hello {name}"

        @server.tool()
        @mesh_agent(capability="farewell")
        def goodbye(name: str) -> str:
            return f"Goodbye {name}"

        # Process all agents
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry

        await processor.process_agents()

        # Should make exactly ONE registration call
        assert mock_registry.post.call_count == 1

        # Check the payload
        call_args = mock_registry.post.call_args
        payload = call_args[1]["json"]

        # Should have tools array
        assert "tools" in payload["metadata"]
        assert len(payload["metadata"]["tools"]) == 2

        # Check tool details
        tools = payload["metadata"]["tools"]
        tool_names = [t["function_name"] for t in tools]
        assert "greet" in tool_names
        assert "goodbye" in tool_names

    @pytest.mark.asyncio
    async def test_registration_payload_structure(self):
        """Test the structure of the batched registration payload."""
        mock_registry = AsyncMock(spec=RegistryClient)
        captured_payload = None

        async def capture_payload(endpoint, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json")
            return MagicMock(
                status=201, json=AsyncMock(return_value={"status": "success"})
            )

        mock_registry.post = AsyncMock(side_effect=capture_payload)

        # Create function with dependencies
        server = FastMCP("test-payload")

        @server.tool()
        @mesh_agent(
            capability="greeting",
            version="1.0.0",
            tags=["demo", "v1"],
            dependencies=[
                {
                    "capability": "date_service",
                    "version": ">=1.0.0",
                    "tags": ["production"],
                }
            ],
        )
        def greet(name: str, date_service=None) -> str:
            return f"Hello {name}"

        # Process
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry

        await processor.process_agents()

        # Verify payload structure
        assert captured_payload is not None
        assert "agent_id" in captured_payload
        assert "metadata" in captured_payload

        metadata = captured_payload["metadata"]
        assert "tools" in metadata

        tool = metadata["tools"][0]
        assert tool["function_name"] == "greet"
        assert tool["capability"] == "greeting"
        assert tool["version"] == "1.0.0"
        assert tool["tags"] == ["demo", "v1"]
        assert len(tool["dependencies"]) == 1
        assert tool["dependencies"][0]["capability"] == "date_service"


class TestDependencyResolution:
    """Test the enhanced dependency resolution system."""

    @pytest.mark.asyncio
    async def test_dependency_resolution_per_tool(self):
        """Test that each tool gets its own dependency resolution."""
        mock_registry = AsyncMock(spec=RegistryClient)

        # Mock registration response with per-tool resolution
        mock_registry.post = AsyncMock(
            return_value=MagicMock(
                status=201,
                json=AsyncMock(
                    return_value={
                        "status": "success",
                        "dependencies_resolved": {
                            "greet": {
                                "date_service": {
                                    "agent_id": "dateservice-123",
                                    "endpoint": "http://date:8080",
                                    "tool_name": "get_date",
                                }
                            },
                            "greet_v2": {
                                "date_service": {
                                    "agent_id": "dateservice-456",  # Different provider!
                                    "endpoint": "http://date-v2:8080",
                                    "tool_name": "get_current_date",
                                }
                            },
                        },
                    }
                ),
            )
        )

        server = FastMCP("test-deps")

        @server.tool()
        @mesh_agent(
            capability="greeting", dependencies=[{"capability": "date_service"}]
        )
        def greet(name: str, date_service=None) -> str:
            return f"Hello {name}"

        @server.tool()
        @mesh_agent(
            capability="greeting_v2",
            dependencies=[{"capability": "date_service", "version": ">=2.0"}],
        )
        def greet_v2(name: str, date_service=None) -> str:
            return f"Greetings {name}"

        # Process and verify each function gets correct dependency
        # This tests that registry can return different providers for same capability
        # based on version constraints


class TestHeartbeatBatching:
    """Test the unified heartbeat system."""

    @pytest.mark.asyncio
    async def test_single_heartbeat_for_multiple_functions(self):
        """Test that one heartbeat covers all functions."""
        mock_registry = AsyncMock(spec=RegistryClient)
        heartbeat_count = 0

        async def count_heartbeats(*args, **kwargs):
            nonlocal heartbeat_count
            heartbeat_count += 1
            return {"status": "success"}

        mock_registry.send_heartbeat_with_response = AsyncMock(
            side_effect=count_heartbeats
        )

        # Create multiple functions
        server = FastMCP("test-heartbeat")

        @server.tool()
        @mesh_agent(capability="func1", health_interval=1)
        def func1() -> str:
            return "1"

        @server.tool()
        @mesh_agent(capability="func2", health_interval=1)
        def func2() -> str:
            return "2"

        @server.tool()
        @mesh_agent(capability="func3", health_interval=1)
        def func3() -> str:
            return "3"

        # Start heartbeat monitoring
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry

        # Should create ONE heartbeat task, not three
        await processor.start_health_monitoring()
        await asyncio.sleep(2.5)  # Wait for 2+ heartbeats

        # Should have ~2 heartbeats, not 6+
        assert heartbeat_count <= 3  # Allow some timing variance


class TestBackwardCompatibility:
    """Test that old single-function agents still work."""

    @pytest.mark.asyncio
    async def test_single_function_agent_works(self):
        """Test backward compatibility with single-function agents."""
        # Old style: one function = one agent
        # Should still work but use new agent ID format

        server = FastMCP("test-compat")

        @server.tool()
        @mesh_agent(capability="greeting")
        def greet(name: str) -> str:
            return f"Hello {name}"

        # Should work without errors
        # Agent ID should still have UUID suffix to prevent collisions


class TestDecoratorOrder:
    """Test that decorator order is preserved correctly."""

    def test_server_tool_must_be_first(self):
        """Test that @server.tool() must come before @mesh_agent()."""
        server = FastMCP("test-order")

        # This should work
        @server.tool()
        @mesh_agent(capability="test")
        def correct_order() -> str:
            return "ok"

        # Verify server.tool cached the original function
        assert hasattr(server, "_tools")
        # The cached function should be our wrapped function

    def test_mesh_agent_wraps_correctly(self):
        """Test that mesh_agent preserves function for server.tool."""
        server = FastMCP("test-wrap")

        @server.tool()
        @mesh_agent(capability="test")
        def my_function(x: int) -> int:
            return x * 2

        # Function should still be callable
        result = my_function(5)
        assert result == 10

        # Function metadata should be preserved
        assert my_function.__name__ == "my_function"
