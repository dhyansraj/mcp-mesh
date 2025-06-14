"""
Core integration tests for resilient registration - simplified and focused.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_mesh import DecoratorRegistry, mesh_agent
from mcp_mesh.runtime.processor import DecoratorProcessor


class TestResilientCore:
    """Core tests for resilient registration behavior."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up decorator registry."""
        DecoratorRegistry._mesh_agents.clear()
        yield
        DecoratorRegistry._mesh_agents.clear()

    @pytest.mark.asyncio
    async def test_standalone_mode_works(self):
        """Test that agents work in standalone mode when registry is unavailable."""

        # Create test agent
        @mesh_agent(
            capability="test_standalone",
            health_interval=5,
            agent_name="standalone_agent",
        )
        def test_function():
            return "Works standalone!"

        # Create processor with failing registry
        processor = DecoratorProcessor("http://localhost:8000")

        # Mock registry to always fail
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "Connection failed"})
        mock_response.text = AsyncMock(return_value="Connection failed")

        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=mock_response
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            return_value=False
        )

        # Process decorators
        result = await processor.process_all_decorators()

        # Should succeed in standalone mode
        assert result["total_processed"] == 1
        assert result["total_successful"] == 1

        # Health monitor should be running
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        # The function name is 'test_function', not 'standalone_agent'
        task = processor.mesh_agent_processor._health_tasks["test_function"]
        assert not task.done()

        # Not fully registered (registration failed)
        assert "test_function" not in processor.mesh_agent_processor._processed_agents

        # Function still works
        assert test_function() == "Works standalone!"

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_heartbeat_continues_without_registry(self):
        """Test that heartbeat monitoring continues even when registry is down."""
        heartbeat_count = 0

        # Create test agent with very short interval
        @mesh_agent(
            capability="test_heartbeat",
            health_interval=0.5,  # 500ms for faster testing
            agent_name="heartbeat_agent",
        )
        def test_function():
            return "Heartbeat test"

        # Create processor
        processor = DecoratorProcessor("http://localhost:8000")

        # Mock registry to fail but count heartbeat attempts
        async def count_heartbeats(*args, **kwargs):
            nonlocal heartbeat_count
            heartbeat_count += 1
            return False  # Always fail

        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            side_effect=count_heartbeats
        )

        # Process and wait
        await processor.process_all_decorators()

        # Wait for multiple heartbeat cycles
        await asyncio.sleep(2.5)  # Should get ~5 heartbeats (initial + 4 periodic)

        # Verify multiple heartbeat attempts
        assert (
            heartbeat_count >= 4
        ), f"Expected at least 4 heartbeats, got {heartbeat_count}"

        # Health task should still be running
        task = processor.mesh_agent_processor._health_tasks.get("test_function")
        assert task and not task.done()

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_late_registration_works(self):
        """Test that agents register when registry becomes available."""

        # Create agent
        @mesh_agent(
            capability="late_register",
            health_interval=1,
            agent_name="late_agent",
            dependencies=["TestService"],
        )
        def test_function(TestService=None):
            if TestService:
                return "Connected with dependency!"
            return "No dependency yet"

        # Create processor
        processor = DecoratorProcessor("http://localhost:8000")

        # Start with failing registry
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            if call_count <= 2:  # First 2 calls fail
                mock_resp.status = 500
                mock_resp.json = AsyncMock(return_value={"error": "Connection failed"})
                mock_resp.text = AsyncMock(return_value="Connection failed")
            else:  # Then succeed
                mock_resp.status = 201
                mock_resp.json = AsyncMock(return_value={"status": "success"})
            return mock_resp

        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            side_effect=mock_post
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            side_effect=[False, False, True, True]  # Fail first 2, then succeed
        )

        # Process - should work in standalone
        result = await processor.process_all_decorators()
        assert result["total_successful"] == 1
        assert "test_function" not in processor.mesh_agent_processor._processed_agents

        # Wait for retry cycles
        await asyncio.sleep(3)

        # Should now be registered (keyed by function name)
        assert "test_function" in processor.mesh_agent_processor._processed_agents

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_multiple_agents_resilient(self):
        """Test multiple agents working in standalone mode."""
        # Create multiple agents with unique function names
        agents_created = []

        @mesh_agent(capability="service_0", health_interval=2, agent_name="agent_0")
        def service_0():
            return "Service 0"

        @mesh_agent(capability="service_1", health_interval=2, agent_name="agent_1")
        def service_1():
            return "Service 1"

        @mesh_agent(capability="service_2", health_interval=2, agent_name="agent_2")
        def service_2():
            return "Service 2"

        agents_created = ["service_0", "service_1", "service_2"]

        # Process with failing registry
        processor = DecoratorProcessor("http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "Connection failed"})
        mock_response.text = AsyncMock(return_value="Connection failed")

        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=mock_response
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            return_value=False
        )

        result = await processor.process_all_decorators()

        # All should succeed in standalone
        assert result["total_processed"] == 3
        assert result["total_successful"] == 3

        # All health monitors running
        assert len(processor.mesh_agent_processor._health_tasks) == 3

        # None registered
        assert len(processor.mesh_agent_processor._processed_agents) == 0

        # Cleanup
        await processor.cleanup()
