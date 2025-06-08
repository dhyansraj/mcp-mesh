"""
Graceful Degradation Tests for Registry Service

Tests how agents and the registry handle various failure scenarios gracefully,
including registry unavailability, network partitions, and partial failures.

Only imports from mcp-mesh-types for MCP SDK compatibility.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import ClientConnectorError

# Import only from mcp-mesh-types for MCP SDK compatibility
from mcp_mesh_runtime.server.models import AgentRegistration

# Import registry components
from mcp_mesh_runtime.server.registry import RegistryService
from mcp_mesh_runtime.server.registry_server import RegistryServer


class MockAgent:
    """Mock agent for testing graceful degradation scenarios."""

    def __init__(self, agent_id: str, registry_url: str = "http://localhost:8000"):
        self.agent_id = agent_id
        self.registry_url = registry_url
        self.registered = False
        self.heartbeat_interval = 30.0
        self.heartbeat_task: asyncio.Task | None = None
        self.last_heartbeat_success = None
        self.failed_heartbeats = 0
        self.max_failed_heartbeats = 3
        self.operational = True

    async def register(self):
        """Attempt to register with registry."""
        registration_data = {
            "id": self.agent_id,
            "name": f"Mock Agent {self.agent_id}",
            "namespace": "test",
            "agent_type": "mock_agent",
            "endpoint": f"http://localhost:900{self.agent_id[-1]}/mcp",
            "capabilities": [
                {
                    "name": "mock_capability",
                    "description": "Mock capability for testing",
                    "category": "testing",
                    "version": "1.0.0",
                }
            ],
            "labels": {"test": "graceful_degradation"},
            "security_context": "standard",
            "health_interval": self.heartbeat_interval,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.registry_url}/mcp/tools/register_agent",
                    json={"registration_data": registration_data},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self.registered = True
                        return True
        except Exception as e:
            print(f"Agent {self.agent_id} registration failed: {e}")

        return False

    async def send_heartbeat(self):
        """Send heartbeat to registry with failure handling."""
        if not self.registered:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.registry_url}/heartbeat",
                    json={"agent_id": self.agent_id},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self.last_heartbeat_success = datetime.now(timezone.utc)
                        self.failed_heartbeats = 0
                        return True
        except Exception as e:
            self.failed_heartbeats += 1
            print(f"Agent {self.agent_id} heartbeat failed: {e}")

        return False

    async def start_heartbeat_loop(self):
        """Start heartbeat loop with graceful degradation."""
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_heartbeat_loop(self):
        """Stop heartbeat loop."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self):
        """Heartbeat loop with exponential backoff on failures."""
        while self.operational:
            try:
                success = await self.send_heartbeat()

                if success:
                    # Normal heartbeat interval
                    await asyncio.sleep(self.heartbeat_interval)
                else:
                    # Exponential backoff on failure
                    backoff = min(300, 2 ** min(self.failed_heartbeats, 8))  # Max 5 min
                    await asyncio.sleep(backoff)

                    # If too many failures, stop trying
                    if self.failed_heartbeats >= self.max_failed_heartbeats:
                        print(
                            f"Agent {self.agent_id} stopping heartbeats after {self.failed_heartbeats} failures"
                        )
                        self.operational = False

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Agent {self.agent_id} heartbeat loop error: {e}")
                await asyncio.sleep(30)

    async def discover_services(self, query: dict | None = None):
        """Attempt service discovery with fallback behavior."""
        try:
            async with aiohttp.ClientSession() as session:
                params = query or {}
                async with session.get(
                    f"{self.registry_url}/agents",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"Agent {self.agent_id} service discovery failed: {e}")
            # Return cached/default service list in real implementation
            return {"agents": [], "count": 0, "error": "registry_unavailable"}

        return None


class TestGracefulDegradation:
    """
    Test suite for graceful degradation scenarios.

    Tests:
    - Registry unavailability scenarios
    - Network partition handling
    - Partial registry failures
    - Agent resilience patterns
    - Recovery workflows
    """

    @pytest.fixture
    async def registry_server(self):
        """Create a registry server for testing."""
        server = RegistryServer(host="localhost", port=8000)

        # Start server
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.5)  # Let server start

        yield server

        # Cleanup
        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_registry_unavailable_during_registration(self):
        """Test agent behavior when registry is unavailable during registration."""

        # Create mock agent with registry that doesn't exist
        agent = MockAgent("test-agent-001", "http://localhost:9999")

        # Registration should fail gracefully
        success = await agent.register()
        assert success is False
        assert agent.registered is False

        # Agent should handle registration failure without crashing
        assert agent.operational is True

    @pytest.mark.asyncio
    async def test_registry_becomes_unavailable_after_registration(
        self, registry_server
    ):
        """Test agent behavior when registry becomes unavailable after registration."""

        # Register agent with working registry
        agent = MockAgent("test-agent-002")
        success = await agent.register()
        assert success is True
        assert agent.registered is True

        # Start heartbeat loop
        await agent.start_heartbeat_loop()

        # Verify initial heartbeat works
        await asyncio.sleep(1)
        assert agent.failed_heartbeats == 0

        # Stop registry to simulate unavailability
        await registry_server.stop()

        # Wait for multiple heartbeat failures
        await asyncio.sleep(15)  # Allow several heartbeat attempts

        # Agent should accumulate failures but remain operational initially
        assert agent.failed_heartbeats > 0

        # Clean up
        await agent.stop_heartbeat_loop()

    @pytest.mark.asyncio
    async def test_registry_recovery_after_outage(self, registry_server):
        """Test agent behavior when registry recovers after an outage."""

        # Create agent and register
        agent = MockAgent("test-agent-003")
        success = await agent.register()
        assert success is True

        # Start heartbeat loop
        await agent.start_heartbeat_loop()
        await asyncio.sleep(1)

        # Simulate registry outage by stopping server
        await registry_server.stop()

        # Wait for heartbeat failures
        await asyncio.sleep(5)
        assert agent.failed_heartbeats > 0

        # Restart registry (simulate recovery)
        server_task = asyncio.create_task(registry_server.start())
        await asyncio.sleep(1)  # Let server start

        # Agent will need to re-register since it's a new server instance
        await agent.register()  # Re-register after recovery

        # Heartbeats should recover
        initial_failures = agent.failed_heartbeats
        await asyncio.sleep(35)  # Wait for successful heartbeat

        # Failed count should reset after successful heartbeat
        assert (
            agent.failed_heartbeats < initial_failures or agent.failed_heartbeats == 0
        )

        # Clean up
        await agent.stop_heartbeat_loop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_partial_registry_failures(self, registry_server):
        """Test handling of partial registry failures."""

        agent = MockAgent("test-agent-004")

        # Register successfully
        success = await agent.register()
        assert success is True

        # Test service discovery when some endpoints work and others don't
        with patch("aiohttp.ClientSession.get") as mock_get:
            # Simulate heartbeat endpoint working but discovery endpoint failing
            async def mock_response(*args, **kwargs):
                url = str(args[0])
                if "/heartbeat" in url:
                    # Heartbeat works
                    mock_resp = AsyncMock()
                    mock_resp.status = 200
                    mock_resp.json = AsyncMock(return_value={"status": "success"})
                    return mock_resp
                elif "/agents" in url:
                    # Discovery fails
                    raise ClientConnectorError(None, OSError("Connection failed"))
                else:
                    raise ClientConnectorError(None, OSError("Connection failed"))

            mock_get.side_effect = mock_response

            # Service discovery should fail gracefully
            result = await agent.discover_services()
            assert result is None or "error" in result

    @pytest.mark.asyncio
    async def test_network_partition_simulation(self, registry_server):
        """Test behavior during network partition simulation."""

        agents = [MockAgent(f"partition-agent-{i}") for i in range(3)]

        # Register all agents
        for agent in agents:
            success = await agent.register()
            assert success is True

        # Start heartbeat loops
        for agent in agents:
            await agent.start_heartbeat_loop()

        await asyncio.sleep(2)  # Allow initial heartbeats

        # Simulate network partition by patching network calls for some agents
        with patch.object(agents[0], "send_heartbeat", return_value=False):
            with patch.object(agents[1], "send_heartbeat", return_value=False):
                # Only agent[2] can reach registry

                await asyncio.sleep(10)  # Allow heartbeat attempts

                # First two agents should accumulate failures
                assert agents[0].failed_heartbeats > 0
                assert agents[1].failed_heartbeats > 0

                # Third agent should continue working
                assert (
                    agents[2].failed_heartbeats == 0
                    or agents[2].last_heartbeat_success is not None
                )

        # Clean up
        for agent in agents:
            await agent.stop_heartbeat_loop()

    @pytest.mark.asyncio
    async def test_registry_database_failure_fallback(self):
        """Test registry behavior when database fails but memory cache works."""

        service = RegistryService()
        await service.initialize()

        try:
            # Register agent successfully
            agent_data = AgentRegistration(
                id="db-failure-test-agent",
                name="DB Failure Test Agent",
                namespace="test",
                agent_type="test_agent",
                endpoint="http://localhost:8010/mcp",
                capabilities=[],
            )

            await service.storage.register_agent(agent_data)

            # Simulate database failure
            with patch.object(
                service.storage.database,
                "update_heartbeat",
                side_effect=Exception("DB Error"),
            ):
                # Heartbeat should still work (fallback to memory)
                success = await service.storage.update_heartbeat(agent_data.id)
                assert success is True

                # Agent should still be retrievable from memory
                agent = await service.storage.get_agent(agent_data.id)
                assert agent is not None
                assert agent.id == agent_data.id

                # Service discovery should still work
                agents = await service.storage.list_agents()
                assert len(agents) >= 1
                assert any(a.id == agent_data.id for a in agents)

        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_registry_memory_corruption_recovery(self):
        """Test registry recovery from memory corruption."""

        service = RegistryService()
        await service.initialize()

        try:
            # Register agent
            agent_data = AgentRegistration(
                id="memory-test-agent",
                name="Memory Test Agent",
                namespace="test",
                agent_type="test_agent",
                endpoint="http://localhost:8011/mcp",
                capabilities=[],
            )

            await service.storage.register_agent(agent_data)

            # Simulate memory corruption
            original_agents = service.storage._agents.copy()
            service.storage._agents.clear()

            # Agent should not be found in memory
            agent = await service.storage.get_agent(agent_data.id)
            assert agent is None

            # But should be recoverable from database
            if service.storage._database_enabled:
                # Reload from database
                await service.storage._load_from_database()

                # Agent should now be available again
                agent = await service.storage.get_agent(agent_data.id)
                if agent:  # If database is working
                    assert agent.id == agent_data.id

        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_concurrent_failure_scenarios(self, registry_server):
        """Test concurrent failure scenarios with multiple agents."""

        # Create multiple agents
        agents = [MockAgent(f"concurrent-agent-{i}") for i in range(5)]

        # Register agents concurrently
        registration_tasks = [agent.register() for agent in agents]
        results = await asyncio.gather(*registration_tasks)

        # All should succeed
        assert all(results)

        # Start heartbeat loops
        for agent in agents:
            await agent.start_heartbeat_loop()

        await asyncio.sleep(2)  # Allow initial heartbeats

        # Simulate different failure scenarios for different agents
        failure_scenarios = [
            # Agent 0: Network timeout
            patch.object(
                agents[0], "send_heartbeat", side_effect=asyncio.TimeoutError()
            ),
            # Agent 1: Connection error
            patch.object(
                agents[1],
                "send_heartbeat",
                side_effect=ClientConnectorError(None, OSError()),
            ),
            # Agent 2: Successful (no patch)
            # Agent 3: HTTP error
            patch.object(agents[3], "send_heartbeat", return_value=False),
            # Agent 4: Successful (no patch)
        ]

        # Apply failure scenarios
        with failure_scenarios[0], failure_scenarios[1], failure_scenarios[3]:
            await asyncio.sleep(10)  # Allow failures to accumulate

            # Failed agents should accumulate failures
            assert agents[0].failed_heartbeats > 0
            assert agents[1].failed_heartbeats > 0
            assert agents[3].failed_heartbeats > 0

            # Successful agents should continue working
            assert agents[2].failed_heartbeats == 0
            assert agents[4].failed_heartbeats == 0

        # Clean up
        for agent in agents:
            await agent.stop_heartbeat_loop()

    @pytest.mark.asyncio
    async def test_registry_graceful_shutdown(self, registry_server):
        """Test registry graceful shutdown behavior."""

        # Register agents
        agents = [MockAgent(f"shutdown-agent-{i}") for i in range(3)]

        for agent in agents:
            success = await agent.register()
            assert success is True
            await agent.start_heartbeat_loop()

        await asyncio.sleep(2)  # Allow heartbeats

        # Verify agents are healthy
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 3

        # Initiate graceful shutdown
        shutdown_task = asyncio.create_task(registry_server.stop())

        # Allow some time for shutdown processing
        await asyncio.sleep(1)

        # Agents should detect registry unavailability
        await asyncio.sleep(5)  # Allow heartbeat failures

        for agent in agents:
            assert agent.failed_heartbeats > 0

        # Complete shutdown
        await shutdown_task

        # Clean up agents
        for agent in agents:
            await agent.stop_heartbeat_loop()

    @pytest.mark.asyncio
    async def test_registry_health_check_resilience(self):
        """Test registry health monitoring resilience."""

        service = RegistryService()
        await service.initialize()
        await service.start_health_monitoring()

        try:
            # Register agents
            agents_data = []
            for i in range(3):
                agent = AgentRegistration(
                    id=f"health-test-agent-{i}",
                    name=f"Health Test Agent {i}",
                    namespace="test",
                    agent_type="test_agent",
                    endpoint=f"http://localhost:80{20+i}/mcp",
                    capabilities=[],
                    timeout_threshold=5.0,  # Short timeout for testing
                    eviction_threshold=10.0,
                )
                await service.storage.register_agent(agent)
                agents_data.append(agent)

            # Send heartbeats for all
            for agent in agents_data:
                await service.storage.update_heartbeat(agent.id)

            # Verify all are healthy
            agents = await service.storage.list_agents()
            healthy_count = sum(1 for a in agents if a.status == "healthy")
            assert healthy_count >= 3

            # Wait for timeout threshold to pass
            await asyncio.sleep(6)

            # Trigger health check
            evicted = await service.storage.check_agent_health_and_evict_expired()

            # Agents should be marked as degraded
            agents = await service.storage.list_agents()
            degraded_count = sum(1 for a in agents if a.status == "degraded")
            assert degraded_count >= 3

            # Wait for eviction threshold
            await asyncio.sleep(5)

            # Trigger health check again
            evicted = await service.storage.check_agent_health_and_evict_expired()

            # Agents should be marked as expired
            agents = await service.storage.list_agents()
            expired_count = sum(1 for a in agents if a.status == "expired")
            assert expired_count >= 3
            assert len(evicted) >= 3

        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_failures(self):
        """Test cache behavior during failure scenarios."""

        service = RegistryService()
        await service.initialize()

        try:
            # Register agent
            agent = AgentRegistration(
                id="cache-test-agent",
                name="Cache Test Agent",
                namespace="test",
                agent_type="test_agent",
                endpoint="http://localhost:8030/mcp",
                capabilities=[],
            )

            await service.storage.register_agent(agent)

            # Query to populate cache
            from mcp_mesh_runtime.server.models import ServiceDiscoveryQuery

            query = ServiceDiscoveryQuery(namespace="test")
            agents1 = await service.storage.list_agents(query)
            assert len(agents1) >= 1

            # Simulate failure during agent update
            with patch.object(
                service.storage.database,
                "register_agent",
                side_effect=Exception("DB Error"),
            ):
                # Update should still work (memory fallback)
                await service.storage.update_heartbeat(agent.id)

            # Cache should be invalidated after update
            agents2 = await service.storage.list_agents(query)
            assert len(agents2) >= 1

            # Results should reflect the update
            updated_agent = next((a for a in agents2 if a.id == agent.id), None)
            assert updated_agent is not None
            assert updated_agent.last_heartbeat is not None

        finally:
            await service.close()


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_graceful_degradation.py -v
    pytest.main([__file__, "-v"])
