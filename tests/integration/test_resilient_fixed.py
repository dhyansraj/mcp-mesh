"""
Fixed integration tests for resilient registration.
"""

import asyncio
import os
import subprocess
import time

import pytest
from mcp_mesh import DecoratorRegistry, mesh_agent
from mcp_mesh.runtime.processor import DecoratorProcessor


class TestResilientRegistrationFixed:
    """Fixed integration tests with proper timing and cleanup."""

    @pytest.fixture(autouse=True)
    async def cleanup(self):
        """Clean up before and after tests."""
        # Kill any existing registry
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)
        await asyncio.sleep(1)

        # Clear decorator registry
        DecoratorRegistry._mesh_agents.clear()

        yield

        # Cleanup after test
        subprocess.run(["pkill", "-f", "mcp-mesh-registry"], stderr=subprocess.DEVNULL)
        DecoratorRegistry._mesh_agents.clear()

    async def wait_for_registry_health(self, timeout=10):
        """Wait for registry to be healthy."""
        import aiohttp

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "http://localhost:8000/health",
                        timeout=aiohttp.ClientTimeout(total=1),
                    ) as resp:
                        if resp.status == 200:
                            return True
            except:
                pass
            await asyncio.sleep(0.5)
        return False

    @pytest.mark.asyncio
    async def test_auto_connect_when_registry_starts_fixed(self):
        """Test agents connect automatically when registry becomes available - FIXED."""

        # Create test agent with short health interval
        @mesh_agent(
            capability="test_auto_connect",
            health_interval=2,  # Short for faster test
            agent_name="auto_connect_agent",
        )
        def test_function():
            return "Auto connected!"

        # Start without registry - process decorators
        processor = DecoratorProcessor("http://localhost:8000")
        result = await processor.process_all_decorators()

        # Should succeed in standalone mode
        assert result["total_successful"] == 1
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        assert (
            len(processor.mesh_agent_processor._processed_agents) == 0
        )  # Not registered

        # Start registry
        registry = subprocess.Popen(
            ["./mcp-mesh-registry"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "GIN_MODE": "release"},  # Reduce noise
        )

        try:
            # Wait for registry to be healthy
            registry_ready = await self.wait_for_registry_health()
            assert registry_ready, "Registry failed to become healthy"

            # Monitor registration status
            # The health monitor runs every 2 seconds, so wait up to 3 cycles
            for attempt in range(6):  # 6 * 2 = 12 seconds max
                await asyncio.sleep(2)

                if (
                    "auto_connect_agent"
                    in processor.mesh_agent_processor._processed_agents
                ):
                    break

                # Check if health task is still running
                task = processor.mesh_agent_processor._health_tasks.get(
                    "auto_connect_agent"
                )
                assert (
                    task and not task.done()
                ), f"Health task died on attempt {attempt}"

            # Verify registration succeeded
            assert (
                "auto_connect_agent" in processor.mesh_agent_processor._processed_agents
            ), "Agent failed to register after registry came online"

            # Function should still work
            assert test_function() == "Auto connected!"

        finally:
            # Proper cleanup
            await processor.cleanup()
            registry.terminate()
            registry.wait(timeout=5)

    @pytest.mark.asyncio
    async def test_health_monitor_continues_without_registry_fixed(self):
        """Test that health monitoring continues even without registry - FIXED."""
        heartbeat_attempts = []

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

        # Track heartbeat attempts with original method
        original_send_heartbeat = processor.mesh_agent_processor._send_heartbeat

        async def track_heartbeats(agent_name, metadata):
            heartbeat_attempts.append(time.time())
            return await original_send_heartbeat(agent_name, metadata)

        processor.mesh_agent_processor._send_heartbeat = track_heartbeats

        # Start processing
        result = await processor.process_all_decorators()
        assert result["total_successful"] == 1

        # Clear initial heartbeat from list
        heartbeat_attempts.clear()

        # Wait for multiple heartbeat cycles
        await asyncio.sleep(3.5)

        # Should have multiple heartbeat attempts (at least 3)
        assert (
            len(heartbeat_attempts) >= 3
        ), f"Only {len(heartbeat_attempts)} heartbeats detected"

        # Verify heartbeats are periodic (roughly 1 second apart)
        if len(heartbeat_attempts) >= 2:
            intervals = [
                heartbeat_attempts[i + 1] - heartbeat_attempts[i]
                for i in range(len(heartbeat_attempts) - 1)
            ]
            avg_interval = sum(intervals) / len(intervals)
            assert (
                0.8 <= avg_interval <= 1.5
            ), f"Heartbeat interval {avg_interval} not close to 1s"

        # Health task should still be running
        task = processor.mesh_agent_processor._health_tasks.get("health_monitor_agent")
        assert task is not None
        assert not task.done(), "Health monitor task stopped unexpectedly"

        # Function should work
        assert test_function() == "Health monitoring!"

        # Cleanup
        await processor.cleanup()

    @pytest.mark.asyncio
    async def test_resilient_through_registry_failure(self):
        """Test agents survive registry going down and coming back up."""

        @mesh_agent(
            capability="survivor", health_interval=2, agent_name="survivor_agent"
        )
        def survivor():
            return "I survive!"

        # Start WITH registry first
        registry = subprocess.Popen(
            ["./mcp-mesh-registry"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            # Wait for registry
            assert await self.wait_for_registry_health(), "Registry failed to start"

            # Process agent - should register successfully
            processor = DecoratorProcessor("http://localhost:8000")
            result = await processor.process_all_decorators()

            # Wait for registration
            await asyncio.sleep(2)
            assert "survivor_agent" in processor.mesh_agent_processor._processed_agents

            # Kill registry
            registry.terminate()
            registry.wait(timeout=5)
            await asyncio.sleep(1)

            # Heartbeats should continue failing but task stays alive
            await asyncio.sleep(3)

            # Health task should still be running
            task = processor.mesh_agent_processor._health_tasks.get("survivor_agent")
            assert task and not task.done()

            # Function still works
            assert survivor() == "I survive!"

            # Restart registry
            registry = subprocess.Popen(
                ["./mcp-mesh-registry"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for reconnection
            assert await self.wait_for_registry_health()
            await asyncio.sleep(4)  # Wait for heartbeat cycle

            # Should still be registered (heartbeats resumed)
            # Note: Agent stays in _processed_agents even during downtime
            assert "survivor_agent" in processor.mesh_agent_processor._processed_agents

            # Cleanup
            await processor.cleanup()

        finally:
            if registry.poll() is None:
                registry.terminate()
                registry.wait(timeout=5)
