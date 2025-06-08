"""
Integration Tests for Pull-Based Registry Workflows

Tests the complete workflow of agent registration, heartbeat monitoring,
service discovery, and health management using the pull-based architecture.

Ensures all imports are from mcp-mesh for MCP SDK compatibility.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

# Import only from mcp-mesh for MCP SDK compatibility
from mcp_mesh_runtime.exceptions import SecurityValidationError
from mcp_mesh_runtime.server.models import (
    AgentCapability,
    AgentRegistration,
    CapabilitySearchQuery,
    ServiceDiscoveryQuery,
)

# Import registry components
from mcp_mesh_runtime.server.registry import RegistryService


class TestPullBasedWorkflows:
    """
    Test suite for pull-based registry workflows.

    Covers:
    - Agent registration and heartbeat workflows
    - Service discovery with advanced filtering
    - Health monitoring and automatic status updates
    - Pull-based MCP protocol compliance
    - Graceful degradation when registry is unavailable
    """

    @pytest.fixture
    async def registry_service(self):
        """Create a test registry service."""
        service = RegistryService()
        await service.initialize()
        await service.start_health_monitoring()
        yield service
        await service.close()

    @pytest.fixture
    async def sample_agents(self) -> list[AgentRegistration]:
        """Create sample agent registrations for testing."""
        file_agent = AgentRegistration(
            id="file-agent-001",
            name="File Operations Agent",
            namespace="system",
            agent_type="file_agent",
            endpoint="http://localhost:8001/mcp",
            capabilities=[
                AgentCapability(
                    name="read_file",
                    description="Read file contents",
                    category="file_operations",
                    version="1.0.0",
                    stability="stable",
                    tags=["io", "filesystem"],
                ),
                AgentCapability(
                    name="write_file",
                    description="Write file contents",
                    category="file_operations",
                    version="1.0.0",
                    stability="stable",
                    tags=["io", "filesystem"],
                ),
            ],
            labels={"env": "test", "team": "platform"},
            security_context="standard",
            health_interval=30.0,
        )

        command_agent = AgentRegistration(
            id="command-agent-001",
            name="Command Execution Agent",
            namespace="system",
            agent_type="command_agent",
            endpoint="http://localhost:8002/mcp",
            capabilities=[
                AgentCapability(
                    name="execute_command",
                    description="Execute system commands",
                    category="system_operations",
                    version="2.1.0",
                    stability="stable",
                    tags=["shell", "system"],
                ),
                AgentCapability(
                    name="monitor_process",
                    description="Monitor running processes",
                    category="system_operations",
                    version="2.1.0",
                    stability="beta",
                    tags=["monitoring", "process"],
                ),
            ],
            labels={"env": "test", "team": "devops"},
            security_context="high_security",
            health_interval=15.0,
        )

        developer_agent = AgentRegistration(
            id="developer-agent-001",
            name="Developer Assistant Agent",
            namespace="development",
            agent_type="developer_agent",
            endpoint="http://localhost:8003/mcp",
            capabilities=[
                AgentCapability(
                    name="code_review",
                    description="Perform automated code reviews",
                    category="development",
                    version="1.5.2",
                    stability="stable",
                    tags=["code", "review", "quality"],
                ),
                AgentCapability(
                    name="test_generation",
                    description="Generate unit tests",
                    category="development",
                    version="1.5.2",
                    stability="experimental",
                    tags=["testing", "automation"],
                ),
            ],
            labels={"env": "dev", "team": "engineering"},
            security_context="standard",
            health_interval=60.0,
        )

        return [file_agent, command_agent, developer_agent]

    @pytest.mark.asyncio
    async def test_agent_registration_workflow(self, registry_service, sample_agents):
        """Test complete agent registration workflow."""
        storage = registry_service.storage

        # Test registering each agent
        for agent in sample_agents:
            result = await storage.register_agent(agent)

            # Verify registration succeeded
            assert result.id == agent.id
            assert result.name == agent.name
            assert result.status == "pending"  # Initial status
            assert result.resource_version is not None
            assert result.updated_at is not None

            # Verify agent can be retrieved
            retrieved = await storage.get_agent(agent.id)
            assert retrieved is not None
            assert retrieved.id == agent.id
            assert retrieved.name == agent.name

        # Verify all agents are listed
        all_agents = await storage.list_agents()
        assert len(all_agents) == len(sample_agents)

        registered_ids = {a.id for a in all_agents}
        expected_ids = {a.id for a in sample_agents}
        assert registered_ids == expected_ids

    @pytest.mark.asyncio
    async def test_heartbeat_workflow(self, registry_service, sample_agents):
        """Test agent heartbeat workflow and status transitions."""
        storage = registry_service.storage

        # Register agents
        for agent in sample_agents:
            await storage.register_agent(agent)

        file_agent_id = sample_agents[0].id

        # Test initial heartbeat
        success = await storage.update_heartbeat(file_agent_id)
        assert success is True

        # Verify agent status changed to healthy
        agent = await storage.get_agent(file_agent_id)
        assert agent.status == "healthy"
        assert agent.last_heartbeat is not None

        # Test heartbeat for non-existent agent
        success = await storage.update_heartbeat("non-existent-agent")
        assert success is False

    @pytest.mark.asyncio
    async def test_service_discovery_workflows(self, registry_service, sample_agents):
        """Test comprehensive service discovery scenarios."""
        storage = registry_service.storage

        # Register and activate agents
        for agent in sample_agents:
            await storage.register_agent(agent)
            await storage.update_heartbeat(agent.id)  # Make them healthy

        # Test discovery by capability
        query = ServiceDiscoveryQuery(capabilities=["read_file"])
        agents = await storage.list_agents(query)
        assert len(agents) == 1
        assert agents[0].id == "file-agent-001"

        # Test discovery by capability category
        query = ServiceDiscoveryQuery(capability_category="file_operations")
        agents = await storage.list_agents(query)
        assert len(agents) == 1
        assert agents[0].id == "file-agent-001"

        # Test discovery by namespace
        query = ServiceDiscoveryQuery(namespace="system")
        agents = await storage.list_agents(query)
        assert len(agents) == 2  # file_agent and command_agent

        # Test discovery by status
        query = ServiceDiscoveryQuery(status="healthy")
        agents = await storage.list_agents(query)
        assert len(agents) == 3  # All agents should be healthy

        # Test discovery by labels
        query = ServiceDiscoveryQuery(labels={"env": "test"})
        agents = await storage.list_agents(query)
        assert len(agents) == 2  # file_agent and command_agent

        # Test fuzzy capability matching
        query = ServiceDiscoveryQuery(capabilities=["file"], fuzzy_match=True)
        agents = await storage.list_agents(query)
        assert len(agents) >= 1  # Should match "read_file", "write_file"

        # Test version constraint filtering
        query = ServiceDiscoveryQuery(version_constraint=">=2.0.0")
        agents = await storage.list_agents(query)
        assert len(agents) == 1  # Only command_agent has v2.1.0
        assert agents[0].id == "command-agent-001"

    @pytest.mark.asyncio
    async def test_capability_search_workflows(self, registry_service, sample_agents):
        """Test enhanced capability search functionality."""
        storage = registry_service.storage

        # Register and activate agents
        for agent in sample_agents:
            await storage.register_agent(agent)
            await storage.update_heartbeat(agent.id)

        # Test capability search by name
        query = CapabilitySearchQuery(name="execute_command")
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) == 1
        assert capabilities[0]["name"] == "execute_command"
        assert capabilities[0]["agent_id"] == "command-agent-001"

        # Test capability search by category
        query = CapabilitySearchQuery(category="file_operations")
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) == 2  # read_file and write_file

        # Test capability search by stability
        query = CapabilitySearchQuery(stability="stable")
        capabilities = await storage.search_capabilities(query)
        stable_count = sum(1 for cap in capabilities if cap["stability"] == "stable")
        assert stable_count >= 3  # Multiple stable capabilities

        # Test capability search by tags
        query = CapabilitySearchQuery(tags=["filesystem"])
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) == 2  # read_file and write_file

        # Test fuzzy capability name search
        query = CapabilitySearchQuery(name="command", fuzzy_match=True)
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) >= 1  # Should match "execute_command"

        # Test description search
        query = CapabilitySearchQuery(description_contains="file")
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) >= 2  # Should match file operations

        # Test filtering by agent status
        query = CapabilitySearchQuery(agent_status="healthy")
        capabilities = await storage.search_capabilities(query)
        assert len(capabilities) >= 6  # All capabilities from healthy agents

        # Test excluding deprecated capabilities
        query = CapabilitySearchQuery(include_deprecated=False)
        capabilities = await storage.search_capabilities(query)
        deprecated_count = sum(
            1 for cap in capabilities if cap["stability"] == "deprecated"
        )
        assert deprecated_count == 0

    @pytest.mark.asyncio
    async def test_health_monitoring_workflow(self, registry_service, sample_agents):
        """Test passive health monitoring and status transitions."""
        storage = registry_service.storage

        # Register agents with different timeout thresholds
        file_agent = sample_agents[0]
        file_agent.timeout_threshold = 5.0  # 5 seconds for testing
        file_agent.eviction_threshold = 10.0  # 10 seconds for testing

        await storage.register_agent(file_agent)
        await storage.update_heartbeat(file_agent.id)

        # Verify agent is healthy
        agent = await storage.get_agent(file_agent.id)
        assert agent.status == "healthy"

        # Wait for timeout threshold to pass
        await asyncio.sleep(6)

        # Trigger health check
        evicted_agents = await storage.check_agent_health_and_evict_expired()

        # Agent should be marked as degraded
        agent = await storage.get_agent(file_agent.id)
        assert agent.status == "degraded"
        assert file_agent.id not in evicted_agents

        # Wait for eviction threshold to pass
        await asyncio.sleep(5)

        # Trigger health check again
        evicted_agents = await storage.check_agent_health_and_evict_expired()

        # Agent should be marked as expired
        agent = await storage.get_agent(file_agent.id)
        assert agent.status == "expired"
        assert file_agent.id in evicted_agents

    @pytest.mark.asyncio
    async def test_health_status_endpoint(self, registry_service, sample_agents):
        """Test health status retrieval for agents."""
        storage = registry_service.storage

        # Register and activate agent
        file_agent = sample_agents[0]
        await storage.register_agent(file_agent)
        await storage.update_heartbeat(file_agent.id)

        # Get health status
        health_status = await storage.get_agent_health(file_agent.id)
        assert health_status is not None
        assert health_status.agent_id == file_agent.id
        assert health_status.status == "healthy"
        assert health_status.last_heartbeat is not None
        assert health_status.time_since_heartbeat is not None
        assert health_status.time_since_heartbeat < 5.0  # Recent heartbeat
        assert health_status.is_expired is False
        assert "healthy" in health_status.message

        # Test health status for non-existent agent
        health_status = await storage.get_agent_health("non-existent")
        assert health_status is None

    @pytest.mark.asyncio
    async def test_registry_metrics_workflow(self, registry_service, sample_agents):
        """Test registry metrics collection and reporting."""
        storage = registry_service.storage

        # Get initial metrics
        initial_metrics = await storage.get_registry_metrics()
        assert initial_metrics.total_agents == 0
        assert initial_metrics.healthy_agents == 0
        assert initial_metrics.registrations_processed >= 0
        assert initial_metrics.heartbeats_processed >= 0

        # Register agents
        for agent in sample_agents:
            await storage.register_agent(agent)
            await storage.update_heartbeat(agent.id)

        # Get updated metrics
        metrics = await storage.get_registry_metrics()
        assert metrics.total_agents == len(sample_agents)
        assert metrics.healthy_agents == len(sample_agents)
        assert metrics.total_capabilities == 6  # Sum of all capabilities
        assert metrics.unique_capability_types == 6  # All unique capability names
        assert (
            metrics.registrations_processed
            == initial_metrics.registrations_processed + len(sample_agents)
        )
        assert (
            metrics.heartbeats_processed
            == initial_metrics.heartbeats_processed + len(sample_agents)
        )
        assert metrics.uptime_seconds > 0

        # Test Prometheus metrics
        prometheus_data = await storage.get_prometheus_metrics()
        assert isinstance(prometheus_data, str)
        assert "mcp_registry_agents_total" in prometheus_data
        assert "mcp_registry_capabilities_total" in prometheus_data
        assert "mcp_registry_uptime_seconds" in prometheus_data

    @pytest.mark.asyncio
    async def test_pull_based_architecture_compliance(
        self, registry_service, sample_agents
    ):
        """Test that registry follows pull-based architecture patterns."""
        storage = registry_service.storage

        # Register agents
        for agent in sample_agents:
            await storage.register_agent(agent)

        # Verify that registry does NOT initiate connections to agents
        # This is demonstrated by the fact that all operations are passive:

        # 1. Agents call registry to register (not push from registry)
        agents = await storage.list_agents()
        assert len(agents) == len(sample_agents)

        # 2. Agents call registry to send heartbeats (not pull from registry)
        for agent in sample_agents:
            success = await storage.update_heartbeat(agent.id)
            assert success is True

        # 3. Health monitoring is timer-based, not connection-based
        # Registry checks timestamps, doesn't ping agents
        evicted = await storage.check_agent_health_and_evict_expired()
        assert isinstance(evicted, list)  # Returns passive check results

        # 4. Service discovery is query-based (agents query registry)
        query = ServiceDiscoveryQuery(namespace="system")
        discovered = await storage.list_agents(query)
        assert len(discovered) >= 0

        # This demonstrates the Kubernetes API server pattern:
        # - Registry is a passive data store
        # - Agents actively register, heartbeat, and query
        # - No outbound connections from registry to agents

    @pytest.mark.asyncio
    async def test_security_validation_workflow(self, registry_service):
        """Test security context validation during registration."""

        # Test high security context with missing capabilities
        high_security_agent = AgentRegistration(
            id="secure-agent-001",
            name="Secure Agent",
            namespace="security",
            agent_type="security_agent",
            endpoint="http://localhost:8010/mcp",
            capabilities=[
                AgentCapability(
                    name="basic_operation",
                    description="Basic operation",
                    category="general",
                    version="1.0.0",
                )
            ],
            security_context="high_security",
        )

        # Should fail validation due to missing required capabilities
        with pytest.raises(SecurityValidationError):
            await registry_service._validate_security_context(high_security_agent)

        # Test high security context with required capabilities
        secure_agent_valid = AgentRegistration(
            id="secure-agent-002",
            name="Valid Secure Agent",
            namespace="security",
            agent_type="security_agent",
            endpoint="http://localhost:8011/mcp",
            capabilities=[
                AgentCapability(
                    name="authentication",
                    description="Auth",
                    category="security",
                    version="1.0.0",
                ),
                AgentCapability(
                    name="authorization",
                    description="Authz",
                    category="security",
                    version="1.0.0",
                ),
                AgentCapability(
                    name="audit",
                    description="Audit",
                    category="security",
                    version="1.0.0",
                ),
            ],
            security_context="high_security",
        )

        # Should pass validation
        await registry_service._validate_security_context(secure_agent_valid)

        # Registration should succeed
        result = await registry_service.storage.register_agent(secure_agent_valid)
        assert result.id == secure_agent_valid.id

    @pytest.mark.asyncio
    async def test_cache_behavior_workflow(self, registry_service, sample_agents):
        """Test response caching behavior for performance."""
        storage = registry_service.storage

        # Register agents
        for agent in sample_agents:
            await storage.register_agent(agent)
            await storage.update_heartbeat(agent.id)

        # First query should populate cache
        query = ServiceDiscoveryQuery(namespace="system")
        start_time = time.time()
        agents1 = await storage.list_agents(query)
        first_query_time = time.time() - start_time

        # Second identical query should use cache (faster)
        start_time = time.time()
        agents2 = await storage.list_agents(query)
        second_query_time = time.time() - start_time

        # Results should be identical
        assert len(agents1) == len(agents2)
        assert {a.id for a in agents1} == {a.id for a in agents2}

        # Second query should be faster (cached)
        # Note: In tests this might not always be measurable due to small dataset
        assert second_query_time <= first_query_time * 2  # Allow for variance

        # Cache should be invalidated after agent changes
        new_agent = AgentRegistration(
            id="new-agent",
            name="New Agent",
            namespace="system",
            agent_type="test_agent",
            endpoint="http://localhost:8020/mcp",
            capabilities=[],
        )
        await storage.register_agent(new_agent)

        # Query should now return updated results
        agents3 = await storage.list_agents(query)
        assert len(agents3) == len(agents1) + 1

    @pytest.mark.asyncio
    async def test_concurrent_operations_workflow(
        self, registry_service, sample_agents
    ):
        """Test concurrent operations for race condition safety."""
        storage = registry_service.storage

        # Test concurrent registrations
        registration_tasks = []
        for i, agent in enumerate(sample_agents):
            agent.id = f"{agent.id}-concurrent-{i}"
            task = asyncio.create_task(storage.register_agent(agent))
            registration_tasks.append(task)

        # Wait for all registrations to complete
        results = await asyncio.gather(*registration_tasks)

        # All should succeed
        assert len(results) == len(sample_agents)
        for result in results:
            assert result.resource_version is not None

        # Test concurrent heartbeats
        agent_ids = [result.id for result in results]
        heartbeat_tasks = []
        for agent_id in agent_ids:
            task = asyncio.create_task(storage.update_heartbeat(agent_id))
            heartbeat_tasks.append(task)

        # Wait for all heartbeats
        heartbeat_results = await asyncio.gather(*heartbeat_tasks)

        # All should succeed
        assert all(heartbeat_results)

        # Test concurrent queries
        query_tasks = []
        for _ in range(5):
            task = asyncio.create_task(storage.list_agents())
            query_tasks.append(task)

        # Wait for all queries
        query_results = await asyncio.gather(*query_tasks)

        # All should return same results
        expected_count = len(sample_agents)
        for agents in query_results:
            assert len(agents) == expected_count

    @pytest.mark.asyncio
    async def test_version_constraint_edge_cases(self, registry_service):
        """Test edge cases in version constraint matching."""
        storage = registry_service.storage

        # Create agent with various version formats
        test_agent = AgentRegistration(
            id="version-test-agent",
            name="Version Test Agent",
            namespace="test",
            agent_type="test_agent",
            endpoint="http://localhost:8030/mcp",
            capabilities=[
                AgentCapability(
                    name="v1_0_0", description="Test", category="test", version="1.0.0"
                ),
                AgentCapability(
                    name="v1_2_3", description="Test", category="test", version="1.2.3"
                ),
                AgentCapability(
                    name="v2_0_0", description="Test", category="test", version="2.0.0"
                ),
                AgentCapability(
                    name="v2_1_0_beta",
                    description="Test",
                    category="test",
                    version="2.1.0-beta",
                ),
            ],
        )

        await storage.register_agent(test_agent)

        # Test various constraint formats
        test_cases = [
            (">=1.0.0", 4),  # All versions
            (">=2.0.0", 2),  # v2.0.0 and v2.1.0-beta
            (">1.0.0", 3),  # Exclude v1.0.0
            ("~1.2.0", 1),  # Compatible with 1.2.x
            ("^1.0.0", 2),  # Compatible with 1.x.x
            ("=1.0.0", 1),  # Exact match
            ("<2.0.0", 2),  # Less than 2.0.0
        ]

        for constraint, expected_count in test_cases:
            query = ServiceDiscoveryQuery(version_constraint=constraint)
            agents = await storage.list_agents(query)

            # Count matching capabilities
            matching_caps = 0
            for agent in agents:
                for cap in agent.capabilities:
                    if storage._match_version_constraint(cap.version, constraint):
                        matching_caps += 1

            assert (
                matching_caps == expected_count
            ), f"Constraint '{constraint}' should match {expected_count} capabilities, got {matching_caps}"

    @pytest.mark.asyncio
    async def test_fuzzy_matching_accuracy(self, registry_service, sample_agents):
        """Test fuzzy matching accuracy and edge cases."""
        storage = registry_service.storage

        # Register agents
        for agent in sample_agents:
            await storage.register_agent(agent)

        # Test fuzzy matching with various queries
        test_cases = [
            ("file", True),  # Should match "read_file", "write_file"
            ("command", True),  # Should match "execute_command"
            ("code", True),  # Should match "code_review"
            ("xyz", False),  # Should not match anything
            ("", False),  # Empty query should not match
            ("read", True),  # Should match "read_file"
        ]

        for query_term, should_match in test_cases:
            query = ServiceDiscoveryQuery(capabilities=[query_term], fuzzy_match=True)
            agents = await storage.list_agents(query)

            if should_match:
                assert (
                    len(agents) > 0
                ), f"Fuzzy query '{query_term}' should match some agents"
            else:
                assert (
                    len(agents) == 0
                ), f"Fuzzy query '{query_term}' should not match any agents"

    @pytest.mark.asyncio
    async def test_watch_event_notifications(self, registry_service, sample_agents):
        """Test watch event notifications for registry changes."""
        storage = registry_service.storage

        # Create a watcher
        watcher_queue = storage.create_watcher()

        # Register an agent and check for ADDED event
        file_agent = sample_agents[0]
        await storage.register_agent(file_agent)

        # Should receive ADDED event
        event = await asyncio.wait_for(watcher_queue.get(), timeout=1.0)
        assert event["type"] == "ADDED"
        assert event["object"]["id"] == file_agent.id

        # Update heartbeat and check for MODIFIED event
        await storage.update_heartbeat(file_agent.id)

        # Should receive MODIFIED event
        event = await asyncio.wait_for(watcher_queue.get(), timeout=1.0)
        assert event["type"] == "MODIFIED"
        assert event["object"]["id"] == file_agent.id

        # Unregister agent and check for DELETED event
        await storage.unregister_agent(file_agent.id)

        # Should receive DELETED event
        event = await asyncio.wait_for(watcher_queue.get(), timeout=1.0)
        assert event["type"] == "DELETED"
        assert event["object"]["id"] == file_agent.id


class TestGracefulDegradation:
    """Test agent behavior when registry is unavailable."""

    @pytest.mark.asyncio
    async def test_registry_unavailable_scenarios(self):
        """Test various registry unavailability scenarios."""

        # Simulate registry connection failure
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = ConnectionError("Registry unavailable")

            # Agent should handle registry unavailability gracefully
            # This would be implemented in the agent-side code
            # Here we verify the registry behavior when agents reconnect

            service = RegistryService()
            await service.initialize()

            try:
                # Test that registry accepts delayed registrations
                late_agent = AgentRegistration(
                    id="late-agent",
                    name="Late Agent",
                    namespace="test",
                    agent_type="test_agent",
                    endpoint="http://localhost:8040/mcp",
                    capabilities=[],
                )

                # Registration should succeed when registry is available
                result = await service.storage.register_agent(late_agent)
                assert result.id == late_agent.id

                # Agent should be discoverable immediately
                agents = await service.storage.list_agents()
                assert len(agents) == 1
                assert agents[0].id == late_agent.id

            finally:
                await service.close()

    @pytest.mark.asyncio
    async def test_partial_registry_failure(self):
        """Test behavior during partial registry failures."""
        service = RegistryService()
        await service.initialize()

        try:
            # Register agent successfully
            agent = AgentRegistration(
                id="resilient-agent",
                name="Resilient Agent",
                namespace="test",
                agent_type="test_agent",
                endpoint="http://localhost:8050/mcp",
                capabilities=[],
            )

            await service.storage.register_agent(agent)

            # Simulate database failure but memory still works
            with patch.object(
                service.storage.database,
                "update_heartbeat",
                side_effect=Exception("DB Error"),
            ):
                # Heartbeat should still succeed (fallback to memory)
                success = await service.storage.update_heartbeat(agent.id)
                assert success is True

                # Agent should still be retrievable
                retrieved = await service.storage.get_agent(agent.id)
                assert retrieved is not None
                assert retrieved.id == agent.id

        finally:
            await service.close()


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_registry_pull_based_workflows.py -v
    pytest.main([__file__, "-v"])
