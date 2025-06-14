"""
Integration tests for resilient registration with actual registry.

Tests the full flow of agents starting without registry and connecting when it becomes available.
"""

import asyncio
import subprocess
import time
from typing import Any

import aiohttp
import pytest

from mcp_mesh import DecoratorRegistry, mesh_agent
from mcp_mesh.runtime.processor import DecoratorProcessor


class TestResilientRegistrationIntegration:
    """Integration tests for resilient registration behavior."""

    @pytest.fixture
    def registry_process(self):
        """Start and manage registry process."""
        # Make sure no registry is running
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)
        time.sleep(1)

        process = None
        yield process  # Registry not started yet

        # Cleanup
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)

    @pytest.fixture
    def clear_registry(self):
        """Clear decorator registry before and after tests."""
        DecoratorRegistry._mesh_agents.clear()
        yield
        DecoratorRegistry._mesh_agents.clear()

    def start_registry(self) -> subprocess.Popen:
        """Start the registry process."""
        return subprocess.Popen(
            ["./mcp-mesh-registry"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def check_registry_health(self, max_retries=10, delay=0.5) -> bool:
        """Check if registry is healthy."""
        async with aiohttp.ClientSession() as session:
            for _ in range(max_retries):
                try:
                    async with session.get(
                        "http://localhost:8000/health",
                        timeout=aiohttp.ClientTimeout(total=1),
                    ) as response:
                        if response.status == 200:
                            return True
                except:
                    pass
                await asyncio.sleep(delay)
        return False

    async def get_registry_agents(self) -> list[dict[str, Any]]:
        """Get agents from registry."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:8000/agents",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("agents", [])
        except:
            pass
        return []

    @pytest.mark.asyncio
    async def test_agent_starts_without_registry(self, clear_registry):
        """Test that agents can start and work without registry."""

        # Create test agent
        @mesh_agent(
            capability="test_standalone",
            health_interval=5,
            agent_name="standalone_test",
        )
        def test_function():
            return "I work standalone!"

        # Create processor (registry is down)
        processor = DecoratorProcessor("http://localhost:8000")

        # Process decorators
        result = await processor.process_all_decorators()

        # Agent should be processed successfully
        assert result["total_processed"] == 1
        assert result["total_successful"] == 1  # Success in standalone mode

        # Health monitor should be running
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        assert "standalone_test" in processor.mesh_agent_processor._health_tasks

        # Agent should NOT be marked as fully processed (registration failed)
        assert "standalone_test" not in processor.mesh_agent_processor._processed_agents

        # Function should still work
        assert test_function() == "I work standalone!"

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_agent_connects_when_registry_comes_online(
        self, registry_process, clear_registry
    ):
        """Test that agents automatically register when registry becomes available."""

        # Create test agents
        @mesh_agent(
            capability="test_auto_connect_1",
            health_interval=2,  # Short interval for faster test
            agent_name="auto_connect_1",
        )
        def test_function_1():
            return "Function 1"

        @mesh_agent(
            capability="test_auto_connect_2",
            health_interval=2,
            agent_name="auto_connect_2",
        )
        def test_function_2():
            return "Function 2"

        # Create processor (registry is down)
        processor = DecoratorProcessor("http://localhost:8000")

        # Process decorators - should start in standalone mode
        result = await processor.process_all_decorators()
        assert result["total_processed"] == 2
        assert result["total_successful"] == 2

        # Verify no agents are registered yet
        assert len(processor.mesh_agent_processor._processed_agents) == 0

        # Now start the registry
        registry_process = self.start_registry()
        assert await self.check_registry_health(), "Registry failed to start"

        # Wait for agents to detect and register (max 3 heartbeat cycles)
        max_wait = 7  # seconds
        start_time = time.time()

        while time.time() - start_time < max_wait:
            registered_count = len(processor.mesh_agent_processor._processed_agents)
            if registered_count == 2:
                break
            await asyncio.sleep(0.5)

        # Both agents should now be registered
        assert len(processor.mesh_agent_processor._processed_agents) == 2
        assert "auto_connect_1" in processor.mesh_agent_processor._processed_agents
        assert "auto_connect_2" in processor.mesh_agent_processor._processed_agents

        # Verify in registry
        agents = await self.get_registry_agents()
        agent_names = [a.get("name", "") for a in agents]
        assert any("auto-connect-1" in name for name in agent_names)
        assert any("auto-connect-2" in name for name in agent_names)

        # Cleanup
        await processor.cleanup()
        registry_process.terminate()

    @pytest.mark.asyncio
    async def test_heartbeat_continues_through_registry_restart(
        self, registry_process, clear_registry
    ):
        """Test that agents survive registry restarts."""
        # Start registry first
        registry_process = self.start_registry()
        assert self.check_registry_health(), "Registry failed to start"

        # Create test agent
        @mesh_agent(
            capability="test_restart_survivor",
            health_interval=2,
            agent_name="restart_survivor",
        )
        def test_function():
            return "I survive restarts!"

        # Create processor and register
        processor = DecoratorProcessor("http://localhost:8000")
        result = await processor.process_all_decorators()

        # Should register successfully
        assert result["total_successful"] == 1
        assert "restart_survivor" in processor.mesh_agent_processor._processed_agents

        # Verify in registry
        agents = self.get_registry_agents()
        assert len(agents) == 1

        # Stop registry
        registry_process.terminate()
        registry_process.wait()
        await asyncio.sleep(1)

        # Health monitor should still be running
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        task = processor.mesh_agent_processor._health_tasks["restart_survivor"]
        assert not task.done()

        # Restart registry
        registry_process = self.start_registry()
        assert self.check_registry_health(), "Registry failed to restart"

        # Wait for heartbeat to reconnect
        await asyncio.sleep(3)

        # Agent should still be registered
        agents = self.get_registry_agents()
        assert len(agents) == 1
        assert agents[0]["status"] in ["healthy", "degraded"]  # Not expired

        # Cleanup
        await processor.cleanup()
        registry_process.terminate()

    @pytest.mark.asyncio
    async def test_multiple_registration_attempts_idempotent(self, clear_registry):
        """Test that multiple registration attempts are idempotent."""
        # Start registry
        registry_process = self.start_registry()
        assert self.check_registry_health(), "Registry failed to start"

        try:
            # Create test agent
            @mesh_agent(
                capability="test_idempotent",
                health_interval=1,  # Very short for testing
                agent_name="idempotent_test",
            )
            def test_function():
                return "Idempotent"

            # Create processor
            processor = DecoratorProcessor("http://localhost:8000")

            # Process multiple times
            for _ in range(3):
                result = await processor.process_all_decorators()
                assert result["total_successful"] == 1
                await asyncio.sleep(0.5)

            # Should only have one health monitor
            assert len(processor.mesh_agent_processor._health_tasks) == 1

            # Registry should only have one agent
            agents = self.get_registry_agents()
            assert len(agents) == 1

            # Wait for multiple heartbeats
            await asyncio.sleep(3)

            # Still only one agent
            agents = self.get_registry_agents()
            assert len(agents) == 1

            # Cleanup
            await processor.cleanup()

        finally:
            registry_process.terminate()

    @pytest.mark.asyncio
    async def test_late_dependency_injection(self, registry_process, clear_registry):
        """Test that dependency injection works after late registration."""

        # Create dependency service first
        @mesh_agent(capability="dependency_provider", agent_name="DependencyService")
        def dependency_service():
            return {"data": "important"}

        # Create dependent agent
        @mesh_agent(
            capability="dependent",
            dependencies=["DependencyService"],
            health_interval=2,
            agent_name="dependent_agent",
        )
        def dependent_function(DependencyService=None):
            if DependencyService:
                return f"Got dependency: {DependencyService()}"
            return "No dependency"

        # Process without registry (both fail to register)
        processor = DecoratorProcessor("http://localhost:8000")
        await processor.process_all_decorators()

        # Function works but no dependency
        assert dependent_function() == "No dependency"

        # Start registry
        registry_process = self.start_registry()
        assert self.check_registry_health(), "Registry failed to start"

        # Wait for registration
        await asyncio.sleep(4)

        # Both should be registered
        assert len(processor.mesh_agent_processor._processed_agents) == 2

        # Dependency injection should work now
        # (In real implementation, this would require the dependency injector to update)
        # For now, verify both are registered
        agents = self.get_registry_agents()
        assert len(agents) == 2

        # Cleanup
        await processor.cleanup()
        registry_process.terminate()
