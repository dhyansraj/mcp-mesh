"""
Test Graceful Handling When Registry is Unavailable

This test suite verifies that the system gracefully handles scenarios where
the registry service is unavailable, including:
- Registry startup delays
- Registry temporary outages
- Registry permanent failures
- Network connectivity issues
- Partial service degradation

Tests ensure that agents and clients can continue operating with reduced
functionality when registry services are unavailable.
"""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

# Import only from mcp-mesh-types for MCP SDK compatibility
# Import registry components for testing
from mcp_mesh_runtime.server.registry_server import RegistryServer


class MockAgent:
    """Mock agent for testing registry unavailability scenarios."""

    def __init__(self, agent_id: str, registry_url: str):
        self.agent_id = agent_id
        self.registry_url = registry_url
        self.is_registered = False
        self.heartbeat_failures = 0
        self.discovery_cache = {}
        self.cache_timestamp = {}
        self.running = False

    async def register(self) -> bool:
        """Attempt to register with registry."""
        registration_data = {
            "id": self.agent_id,
            "name": f"Mock Agent {self.agent_id}",
            "namespace": "test",
            "agent_type": "mock_agent",
            "endpoint": "http://localhost:8010/mcp",
            "capabilities": [
                {
                    "name": "mock_capability",
                    "description": "Mock capability for testing",
                    "category": "testing",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["mock", "testing"],
                }
            ],
            "labels": {"env": "test", "type": "mock"},
            "security_context": "standard",
            "health_interval": 10.0,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.registry_url}/mcp/tools/register_agent",
                    json={"registration_data": registration_data},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self.is_registered = True
                        return True
                    else:
                        return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # Registry unavailable - continue without registration
            self.is_registered = False
            return False

    async def heartbeat(self) -> bool:
        """Send heartbeat to registry."""
        if not self.is_registered:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.registry_url}/heartbeat",
                    json={"agent_id": self.agent_id, "status": "healthy"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self.heartbeat_failures = 0
                        return True
                    else:
                        self.heartbeat_failures += 1
                        return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.heartbeat_failures += 1

            # After multiple failures, assume registry is down
            if self.heartbeat_failures >= 3:
                self.is_registered = False

            return False

    async def discover_agents(self, capability: str) -> list[dict[str, Any]]:
        """Discover agents with caching fallback."""
        cache_key = f"capability:{capability}"

        # Check cache first (30-second TTL)
        if cache_key in self.discovery_cache:
            cached_data, timestamp = self.discovery_cache[cache_key]
            if time.time() - timestamp < 30:
                return cached_data

        # Try registry
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.registry_url}/capabilities",
                    params={"name": capability, "agent_status": "healthy"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        capabilities = data["capabilities"]

                        # Cache the result
                        self.discovery_cache[cache_key] = (capabilities, time.time())
                        return capabilities
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

        # Fallback to stale cache if available
        if cache_key in self.discovery_cache:
            cached_data, _ = self.discovery_cache[cache_key]
            return cached_data

        # No registry and no cache - return empty
        return []

    async def start(self):
        """Start agent with resilient registration."""
        self.running = True

        # Try initial registration with retries
        max_retries = 5
        for attempt in range(max_retries):
            if await self.register():
                break

            if attempt < max_retries - 1:
                # Exponential backoff
                delay = 2**attempt
                await asyncio.sleep(delay)

        # Start heartbeat loop regardless of registration status
        asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """Continuous heartbeat with retry logic."""
        while self.running:
            if not self.is_registered:
                # Try to re-register
                await self.register()
            else:
                # Send heartbeat
                await self.heartbeat()

            await asyncio.sleep(10)  # 10-second heartbeat interval

    async def stop(self):
        """Stop agent."""
        self.running = False


class TestRegistryUnavailableHandling:
    """Test suite for graceful handling of registry unavailability."""

    @pytest.mark.asyncio
    async def test_agent_startup_with_delayed_registry(self):
        """Test agent startup when registry is not immediately available."""
        # Start agent before registry
        agent = MockAgent("delayed-test-agent", "http://localhost:8000")
        await agent.start()

        # Verify agent is running but not registered
        assert agent.running is True
        assert agent.is_registered is False

        # Start registry after a delay
        await asyncio.sleep(2)
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            # Wait for registry to start
            await asyncio.sleep(2)

            # Agent should eventually register
            max_wait = 10
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if agent.is_registered:
                    break
                await asyncio.sleep(0.5)

            assert agent.is_registered is True

        finally:
            await agent.stop()
            await registry_server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_agent_continues_without_registry(self):
        """Test that agent continues operating when registry is permanently unavailable."""
        # Create agent pointing to non-existent registry
        agent = MockAgent("no-registry-agent", "http://localhost:9999")
        await agent.start()

        # Verify agent starts without registry
        assert agent.running is True
        assert agent.is_registered is False

        # Wait for a few heartbeat cycles
        await asyncio.sleep(5)

        # Agent should still be running
        assert agent.running is True
        assert agent.heartbeat_failures > 0

        # Discovery should return empty results gracefully
        results = await agent.discover_agents("any_capability")
        assert results == []

        await agent.stop()

    @pytest.mark.asyncio
    async def test_registry_temporary_outage_recovery(self):
        """Test agent behavior during temporary registry outage."""
        # Start registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            # Wait for registry to start
            await asyncio.sleep(1)

            # Start agent and let it register
            agent = MockAgent("outage-test-agent", "http://localhost:8000")
            await agent.start()

            # Wait for registration
            await asyncio.sleep(2)
            assert agent.is_registered is True

            # Populate discovery cache
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={
                        "registration_data": {
                            "id": "target-agent",
                            "name": "Target Agent",
                            "namespace": "test",
                            "agent_type": "target_agent",
                            "endpoint": "http://localhost:8011/mcp",
                            "capabilities": [
                                {
                                    "name": "target_capability",
                                    "description": "Target capability",
                                    "category": "testing",
                                    "version": "1.0.0",
                                }
                            ],
                            "labels": {"env": "test"},
                            "security_context": "standard",
                            "health_interval": 30.0,
                        }
                    },
                ) as resp:
                    assert resp.status == 200

            # Let agent discover and cache the target
            results = await agent.discover_agents("target_capability")
            assert len(results) >= 1

            # Stop registry (simulate outage)
            await registry_server.stop()
            server_task.cancel()

            # Wait for heartbeat failures
            await asyncio.sleep(12)  # More than 3 heartbeat cycles

            # Agent should detect registry is down
            assert agent.heartbeat_failures >= 3
            assert agent.is_registered is False

            # But discovery should still work from cache
            cached_results = await agent.discover_agents("target_capability")
            assert len(cached_results) >= 1
            assert cached_results[0]["name"] == "target_capability"

            await agent.stop()

        finally:
            if server_task and not server_task.done():
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_network_connectivity_issues(self):
        """Test handling of various network connectivity issues."""
        # Start registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            await asyncio.sleep(1)

            agent = MockAgent("network-test-agent", "http://localhost:8000")
            await agent.start()
            await asyncio.sleep(1)

            # Simulate network timeouts
            with patch("aiohttp.ClientSession.post") as mock_post:
                mock_post.side_effect = asyncio.TimeoutError("Network timeout")

                # Try heartbeat with timeout
                result = await agent.heartbeat()
                assert result is False
                assert agent.heartbeat_failures > 0

            # Simulate connection refused
            with patch("aiohttp.ClientSession.get") as mock_get:
                mock_get.side_effect = aiohttp.ClientConnectionError(
                    "Connection refused"
                )

                # Try discovery with connection error
                results = await agent.discover_agents("any_capability")
                assert results == []  # Should return empty gracefully

            await agent.stop()

        finally:
            await registry_server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_partial_registry_functionality(self):
        """Test behavior when registry has partial functionality."""
        # Start registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            await asyncio.sleep(1)

            agent = MockAgent("partial-test-agent", "http://localhost:8000")

            # Test when registration works but heartbeat fails
            with patch("aiohttp.ClientSession.post") as mock_post:
                # First call (registration) succeeds
                mock_success = AsyncMock()
                mock_success.status = 200
                mock_success.json = AsyncMock(
                    return_value={"status": "success", "agent_id": "partial-test-agent"}
                )

                # Second call (heartbeat) fails
                mock_failure = AsyncMock()
                mock_failure.status = 500

                mock_post.side_effect = [mock_success, mock_failure]

                # Registration should succeed
                result = await agent.register()
                assert result is True
                assert agent.is_registered is True

                # Heartbeat should fail but not crash
                result = await agent.heartbeat()
                assert result is False
                assert agent.heartbeat_failures > 0

            # Test when discovery works but returns errors for some queries
            async with aiohttp.ClientSession() as session:
                # Valid query should work
                async with session.get(
                    "http://localhost:8000/capabilities?name=test"
                ) as resp:
                    assert resp.status == 200

                # Invalid query should fail gracefully
                async with session.get(
                    "http://localhost:8000/capabilities?invalid_param=xyz"
                ) as resp:
                    # Should not crash the registry
                    assert resp.status in [200, 400]  # Either works or fails gracefully

            await agent.stop()

        finally:
            await registry_server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stale_cache_usage(self):
        """Test that agents use stale cache when registry is unavailable."""
        # Start registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            await asyncio.sleep(1)

            # Register target agent in registry
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={
                        "registration_data": {
                            "id": "cache-target-agent",
                            "name": "Cache Target Agent",
                            "namespace": "test",
                            "agent_type": "cache_agent",
                            "endpoint": "http://localhost:8012/mcp",
                            "capabilities": [
                                {
                                    "name": "cached_capability",
                                    "description": "Cached capability",
                                    "category": "caching",
                                    "version": "1.0.0",
                                }
                            ],
                            "labels": {"env": "test"},
                            "security_context": "standard",
                            "health_interval": 30.0,
                        }
                    },
                ) as resp:
                    assert resp.status == 200

            agent = MockAgent("cache-test-agent", "http://localhost:8000")
            await agent.start()

            # Populate cache with fresh data
            fresh_results = await agent.discover_agents("cached_capability")
            assert len(fresh_results) >= 1

            # Stop registry
            await registry_server.stop()
            server_task.cancel()

            # Discovery should still work from cache (within TTL)
            cached_results = await agent.discover_agents("cached_capability")
            assert len(cached_results) >= 1
            assert cached_results == fresh_results

            # Wait for cache to become stale (but still usable)
            await asyncio.sleep(35)  # Beyond normal TTL

            # Should still return stale cache data when registry is unavailable
            stale_results = await agent.discover_agents("cached_capability")
            assert len(stale_results) >= 1
            assert stale_results == fresh_results

            await agent.stop()

        finally:
            if server_task and not server_task.done():
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_multiple_agents_registry_failure(self):
        """Test multiple agents handling registry failure simultaneously."""
        # Start registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            await asyncio.sleep(1)

            # Start multiple agents
            agents = []
            for i in range(5):
                agent = MockAgent(f"multi-agent-{i}", "http://localhost:8000")
                await agent.start()
                agents.append(agent)

            # Wait for all to register
            await asyncio.sleep(3)

            registered_count = sum(1 for agent in agents if agent.is_registered)
            assert registered_count >= 4  # Most should register successfully

            # Stop registry suddenly
            await registry_server.stop()
            server_task.cancel()

            # Wait for heartbeat failures to accumulate
            await asyncio.sleep(15)

            # All agents should detect registry failure
            for agent in agents:
                assert agent.heartbeat_failures >= 2

            # All agents should continue running
            for agent in agents:
                assert agent.running is True

            # Discovery should fail gracefully for all
            for i, agent in enumerate(agents):
                results = await agent.discover_agents(f"capability_{i}")
                assert results == []  # No cache, so empty results

            # Cleanup
            for agent in agents:
                await agent.stop()

        finally:
            if server_task and not server_task.done():
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_registry_restart_recovery(self):
        """Test agent recovery when registry restarts."""
        # Start initial registry
        registry_server = RegistryServer(host="localhost", port=8000)
        server_task = asyncio.create_task(registry_server.start())

        try:
            await asyncio.sleep(1)

            agent = MockAgent("restart-test-agent", "http://localhost:8000")
            await agent.start()

            # Wait for registration
            await asyncio.sleep(2)
            assert agent.is_registered is True

            # Stop registry
            await registry_server.stop()
            server_task.cancel()

            # Wait for agent to detect failure
            await asyncio.sleep(12)
            assert agent.is_registered is False

            # Restart registry (new instance)
            new_registry_server = RegistryServer(host="localhost", port=8000)
            new_server_task = asyncio.create_task(new_registry_server.start())

            await asyncio.sleep(2)

            # Agent should eventually re-register
            max_wait = 15
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if agent.is_registered:
                    break
                await asyncio.sleep(0.5)

            assert agent.is_registered is True

            await agent.stop()
            await new_registry_server.stop()
            new_server_task.cancel()

        finally:
            if server_task and not server_task.done():
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_graceful_degradation_patterns(self):
        """Test various graceful degradation patterns."""

        # Test 1: Circuit breaker pattern
        class CircuitBreakerAgent(MockAgent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.circuit_open = False
                self.failure_count = 0
                self.failure_threshold = 3
                self.last_attempt = 0
                self.circuit_timeout = 30

            async def heartbeat(self):
                # Check circuit breaker
                if self.circuit_open:
                    if time.time() - self.last_attempt > self.circuit_timeout:
                        self.circuit_open = False
                        self.failure_count = 0
                    else:
                        return False

                # Try normal heartbeat
                result = await super().heartbeat()

                if result:
                    self.failure_count = 0
                    self.circuit_open = False
                else:
                    self.failure_count += 1
                    if self.failure_count >= self.failure_threshold:
                        self.circuit_open = True
                        self.last_attempt = time.time()

                return result

        agent = CircuitBreakerAgent("circuit-test-agent", "http://localhost:9999")

        # Simulate failures
        for _ in range(5):
            result = await agent.heartbeat()
            assert result is False

        # Circuit should be open
        assert agent.circuit_open is True

        # Additional calls should be rejected immediately
        start_time = time.time()
        await agent.heartbeat()
        elapsed = time.time() - start_time
        assert elapsed < 0.1  # Should return quickly due to circuit breaker

        # Test 2: Fallback service discovery
        class FallbackAgent(MockAgent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.static_endpoints = {
                    "critical_service": [
                        "http://localhost:8001",
                        "http://localhost:8002",
                    ],
                    "backup_service": ["http://localhost:8003"],
                }

            async def discover_agents(self, capability: str):
                # Try registry first
                results = await super().discover_agents(capability)

                if results:
                    return results

                # Fallback to static configuration
                if capability in self.static_endpoints:
                    return [
                        {
                            "name": capability,
                            "agent_endpoint": endpoint,
                            "agent_id": f"static-{i}",
                            "source": "static",
                        }
                        for i, endpoint in enumerate(self.static_endpoints[capability])
                    ]

                return []

        fallback_agent = FallbackAgent("fallback-test-agent", "http://localhost:9999")

        # Should return static endpoints when registry is unavailable
        results = await fallback_agent.discover_agents("critical_service")
        assert len(results) == 2
        assert all(result["source"] == "static" for result in results)

        # Non-configured service should return empty
        results = await fallback_agent.discover_agents("unknown_service")
        assert results == []


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_registry_unavailable_graceful_handling.py -v
    pytest.main([__file__, "-v"])
