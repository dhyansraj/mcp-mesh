"""
Simplified integration test for resilient registration.
"""

import asyncio
import subprocess
import time

import pytest
from mcp_mesh import DecoratorRegistry, mesh_agent
from mcp_mesh.runtime.processor import DecoratorProcessor


class TestResilientRegistrationSimple:
    """Simple integration tests for resilient registration."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up before and after tests."""
        # Kill any existing registry
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)
        time.sleep(1)

        # Clear decorator registry
        DecoratorRegistry._mesh_agents.clear()

        yield

        # Cleanup after test
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)
        DecoratorRegistry._mesh_agents.clear()

    @pytest.mark.asyncio
    async def test_standalone_mode_basic(self):
        """Test basic standalone mode - agent works without registry."""

        # Create test agent
        @mesh_agent(
            capability="test_standalone",
            health_interval=5,
            agent_name="standalone_agent",
        )
        def test_function():
            return "Works standalone!"

        # Process without registry
        processor = DecoratorProcessor("http://localhost:8000")
        result = await processor.process_all_decorators()

        # Should succeed in standalone mode
        assert result["total_processed"] == 1
        assert result["total_successful"] == 1

        # Health monitor should be running
        assert len(processor.mesh_agent_processor._health_tasks) == 1

        # Not marked as fully processed (registration failed)
        assert len(processor.mesh_agent_processor._processed_agents) == 0

        # Function still works
        assert test_function() == "Works standalone!"

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_auto_connect_when_registry_starts(self):
        """Test agents connect automatically when registry comes online."""

        # Create test agent with short health interval
        @mesh_agent(
            capability="test_auto_connect",
            health_interval=2,  # Short for faster test
            agent_name="auto_connect_agent",
        )
        def test_function():
            return "Auto connected!"

        # Start without registry
        processor = DecoratorProcessor("http://localhost:8000")
        await processor.process_all_decorators()

        # Verify standalone mode
        assert len(processor.mesh_agent_processor._processed_agents) == 0
        assert len(processor.mesh_agent_processor._health_tasks) == 1

        # Start registry
        registry = subprocess.Popen(
            ["./mcp-mesh-registry"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            # Wait for registry to be ready
            await asyncio.sleep(3)

            # Wait for agent to detect and register (within 2-3 heartbeats)
            max_wait = 8
            start_time = time.time()

            while time.time() - start_time < max_wait:
                if len(processor.mesh_agent_processor._processed_agents) > 0:
                    break
                await asyncio.sleep(0.5)

            # Agent should now be registered
            assert (
                "auto_connect_agent" in processor.mesh_agent_processor._processed_agents
            )

        finally:
            # Cleanup
            await processor.cleanup()
            registry.terminate()
            registry.wait(timeout=5)

    @pytest.mark.asyncio
    async def test_health_monitor_continues_without_registry(self):
        """Test that health monitoring continues even without registry."""
        # Track heartbeat attempts
        heartbeat_count = 0
        original_send_heartbeat = None

        # Create test agent
        @mesh_agent(
            capability="test_health_continues",
            health_interval=1,  # Very short for testing
            agent_name="health_monitor_agent",
        )
        def test_function():
            return "Health monitoring!"

        # Process without registry
        processor = DecoratorProcessor("http://localhost:8000")

        # Patch to count heartbeat attempts
        async def count_heartbeats(*args, **kwargs):
            nonlocal heartbeat_count
            heartbeat_count += 1
            return False  # Simulate failure

        processor.mesh_agent_processor._send_heartbeat = count_heartbeats

        # Start processing
        await processor.process_all_decorators()

        # Wait for multiple heartbeat attempts
        await asyncio.sleep(3.5)

        # Should have attempted multiple heartbeats
        assert heartbeat_count >= 3  # Initial + at least 2 periodic

        # Health task should still be running
        task = processor.mesh_agent_processor._health_tasks.get("health_monitor_agent")
        assert task is not None
        assert not task.done()

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_multiple_agents_resilient(self):
        """Test multiple agents work in standalone and connect together."""

        # Create multiple agents
        @mesh_agent(capability="service_a", health_interval=2, agent_name="service_a")
        def service_a():
            return "Service A"

        @mesh_agent(capability="service_b", health_interval=2, agent_name="service_b")
        def service_b():
            return "Service B"

        @mesh_agent(
            capability="service_c",
            dependencies=["service_a", "service_b"],
            health_interval=2,
            agent_name="service_c",
        )
        def service_c(service_a=None, service_b=None):
            if service_a and service_b:
                return f"C with {service_a()} and {service_b()}"
            return "Service C standalone"

        # Process without registry
        processor = DecoratorProcessor("http://localhost:8000")
        result = await processor.process_all_decorators()

        # All should process successfully in standalone
        assert result["total_processed"] == 3
        assert result["total_successful"] == 3

        # All health monitors running
        assert len(processor.mesh_agent_processor._health_tasks) == 3

        # None registered yet
        assert len(processor.mesh_agent_processor._processed_agents) == 0

        # Functions work in standalone
        assert service_a() == "Service A"
        assert service_b() == "Service B"
        assert service_c() == "Service C standalone"  # No dependencies available

        # Cleanup
        await processor.cleanup()
