"""
Unit tests for resilient registration behavior.

Tests that agents continue with health monitoring even when initial registration fails.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp_mesh import DecoratorRegistry
from mcp_mesh.runtime.processor import DecoratorProcessor, MeshAgentProcessor
from mcp_mesh.runtime.registry_client import RegistryClient


class TestResilientRegistration:
    """Test resilient registration behavior when registry is unavailable."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        client = AsyncMock(spec=RegistryClient)
        client.url = "http://localhost:8000"
        return client

    @pytest.fixture
    def processor(self, mock_registry_client):
        """Create a processor with mocked registry client."""
        processor = DecoratorProcessor("http://localhost:8000")
        processor.registry_client = mock_registry_client
        processor.mesh_agent_processor = MeshAgentProcessor(mock_registry_client)
        processor.mesh_agent_processor.registry_client = mock_registry_client
        return processor

    @pytest.mark.asyncio
    async def test_health_monitor_starts_when_registration_fails(self, processor):
        """Test that health monitoring starts even if initial registration fails."""
        # Setup: Mock registry to fail registration
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )
        )

        # Create a test function with metadata
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 30,
            "dependencies": [],
            "agent_name": "test_agent",
        }

        # Process the agent
        result = await processor.mesh_agent_processor.process_single_agent(
            "test_agent", MagicMock(function=test_func, metadata=metadata)
        )

        # Verify health monitor was started despite registration failure
        assert result is True  # Should return True for standalone mode
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        assert "test_agent" in processor.mesh_agent_processor._health_tasks
        assert (
            "test_agent" not in processor.mesh_agent_processor._processed_agents
        )  # Not marked as processed

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_registration_retry_on_heartbeat(self, processor):
        """Test that failed registrations are retried during heartbeat."""
        # Setup: Initially fail, then succeed
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call fails
                return MagicMock(
                    status=500,
                    json=AsyncMock(return_value={"error": "Connection failed"}),
                )
            else:
                # Subsequent calls succeed
                return MagicMock(
                    status=201, json=AsyncMock(return_value={"status": "success"})
                )

        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            side_effect=mock_post
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            side_effect=[False, True, True]  # First heartbeat fails, then succeeds
        )

        # Create test agent
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 0.1,  # Very short for testing
            "dependencies": [],
            "agent_name": "test_agent",
        }

        # Process agent (should fail registration but start health monitor)
        result = await processor.mesh_agent_processor.process_single_agent(
            "test_agent", MagicMock(function=test_func, metadata=metadata)
        )

        assert result is True
        assert "test_agent" not in processor.mesh_agent_processor._processed_agents

        # Wait for health monitor to retry
        await asyncio.sleep(0.3)

        # Verify retry happened and succeeded
        assert call_count >= 2  # Initial attempt + retry
        assert "test_agent" in processor.mesh_agent_processor._processed_agents

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_health_monitor_continues_after_registration(self, processor):
        """Test that health monitoring continues after successful registration."""
        # Setup: Successful registration
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=201, json=AsyncMock(return_value={"status": "success"})
            )
        )

        heartbeat_count = 0

        async def count_heartbeats(*args, **kwargs):
            nonlocal heartbeat_count
            heartbeat_count += 1
            return True

        processor.mesh_agent_processor.registry_client.send_heartbeat = count_heartbeats

        # Create test agent
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 0.1,  # Very short for testing
            "dependencies": [],
            "agent_name": "test_agent",
        }

        # Process agent
        result = await processor.mesh_agent_processor.process_single_agent(
            "test_agent", MagicMock(function=test_func, metadata=metadata)
        )

        assert result is True
        assert "test_agent" in processor.mesh_agent_processor._processed_agents

        # Wait for multiple heartbeats
        await asyncio.sleep(0.35)

        # Should have sent multiple heartbeats
        assert heartbeat_count >= 3  # Initial + at least 2 periodic

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_multiple_agents_resilient_registration(self, processor):
        """Test multiple agents can work in standalone mode."""
        # Setup: Registry always fails
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            return_value=False
        )

        # Create multiple test agents
        agents = []
        for i in range(3):
            test_func = MagicMock(__name__=f"test_agent_{i}")
            metadata = {
                "capability": f"test_{i}",
                "capabilities": [f"test_{i}"],
                "health_interval": 30,
                "dependencies": [],
                "agent_name": f"test_agent_{i}",
            }
            agents.append(
                (f"test_agent_{i}", MagicMock(function=test_func, metadata=metadata))
            )

        # Process all agents
        results = {}
        for name, agent in agents:
            results[name] = await processor.mesh_agent_processor.process_single_agent(
                name, agent
            )

        # All should succeed in standalone mode
        assert all(results.values())
        assert len(processor.mesh_agent_processor._health_tasks) == 3
        assert (
            len(processor.mesh_agent_processor._processed_agents) == 0
        )  # None registered

        # Cleanup
        for task in processor.mesh_agent_processor._health_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_dependency_injection_after_late_registration(self, processor):
        """Test that dependency injection is set up after late registration."""
        # Mock the internal registration method
        call_count = 0

        async def mock_register(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # First attempt fails
            else:
                return {"status": "success"}  # Second attempt succeeds

        processor.mesh_agent_processor._register_with_mesh_registry = AsyncMock(
            side_effect=mock_register
        )

        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            side_effect=[False, True]
        )

        # Mock the dependency injection setup
        processor.mesh_agent_processor._setup_dependency_injection = AsyncMock()

        # Create test agent with dependencies
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 0.1,
            "dependencies": ["ServiceA", "ServiceB"],
            "agent_name": "test_agent",
        }

        decorated_func = MagicMock(function=test_func, metadata=metadata)

        # Mock DecoratorRegistry to return our function
        with patch.object(
            DecoratorRegistry,
            "get_mesh_agents",
            return_value={"test_agent": decorated_func},
        ):
            # Process agent
            await processor.mesh_agent_processor.process_single_agent(
                "test_agent", decorated_func
            )

            # Initially, dependency injection should not be called (registration failed)
            processor.mesh_agent_processor._setup_dependency_injection.assert_not_called()

            # Wait for retry and dependency injection setup
            await asyncio.sleep(0.3)

            # After successful retry, dependency injection should be set up
            processor.mesh_agent_processor._setup_dependency_injection.assert_called_once_with(
                decorated_func
            )

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
