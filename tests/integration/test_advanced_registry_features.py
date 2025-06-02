"""Integration tests for advanced registry features."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp_mesh_types import (
    AgentInfo,
    AgentSelectionResult,
    AgentVersionInfo,
    CapabilityMetadata,
    CapabilityQuery,
    DeploymentInfo,
    DeploymentResult,
    LifecycleStatus,
    RegistryConfig,
    SecurityConfig,
    SelectionCriteria,
    SelectionWeights,
    SemanticVersion,
    ServerConfig,
    ServiceDiscoveryConfig,
)

# Mock implementation for testing advanced features
# from mcp_mesh.shared.registry_client import RegistryClient
# from mcp_mesh.shared.service_discovery import ServiceDiscoveryManager
# from mcp_mesh.shared.agent_selection import AgentSelectionManager
# from mcp_mesh.shared.lifecycle_manager import LifecycleManager
# from mcp_mesh.shared.versioning import VersioningManager
# from mcp_mesh.shared.capability_matching import CapabilityMatcher


class MockRegistryClient:
    def __init__(self):
        pass

    async def get_agents(self):
        return []


class MockServiceDiscoveryManager:
    def __init__(self, client, config):
        self.client = client
        self.config = config

    async def discover_agents(self, query, include_unhealthy=True):
        return []


class MockAgentSelectionManager:
    def __init__(self, weights):
        self.weights = weights
        self.algorithm = "weighted"

    async def select_agents(self, agents, criteria):

        return AgentSelectionResult(
            success=True,
            selected_agents=agents[:1] if agents else [],
            selection_metadata={"algorithm": self.algorithm},
        )


class MockLifecycleManager:
    def __init__(self):
        pass

    async def drain_agent(self, agent_info, timeout=30):
        from mcp_mesh_types import DrainResult

        return DrainResult(
            success=True, agent_id=agent_info.agent_id, status="draining"
        )

    def start_health_monitoring(self, agent_info, interval=60):
        return None

    async def stop_health_monitoring(self, agent_id):
        pass

    def get_health_history(self, agent_id):
        return []


class MockVersioningManager:
    def __init__(self):
        pass

    def is_compatible(self, v1, v2):
        return v1.major == v2.major

    def sort_versions(self, versions):
        return sorted(versions, key=lambda v: (v.major, v.minor, v.patch))

    async def deploy_canary(self, current, new, traffic_percent=10):

        return DeploymentResult(
            success=True,
            deployment_type="canary",
            traffic_split={
                f"v{current.version.major}.{current.version.minor}.{current.version.patch}": 100
                - traffic_percent,
                f"v{new.version.major}.{new.version.minor}.{new.version.patch}": traffic_percent,
            },
        )

    async def rollback_agent(self, agent_info, target_version):
        from mcp_mesh_types import RollbackInfo

        return RollbackInfo(
            success=True,
            previous_version=agent_info.version,
            rolled_back_to=target_version,
            rollback_reason="manual_rollback",
        )


class MockCapabilityMatcher:
    def __init__(self):
        pass

    def calculate_match_score(self, agent_capabilities, query):
        from mcp_mesh_types import CompatibilityScore

        # Simple mock scoring
        query_caps = query.capabilities if hasattr(query, "capabilities") else []
        agent_cap_names = [cap.name for cap in agent_capabilities]

        if any(cap in agent_cap_names for cap in query_caps):
            score = 0.8
        else:
            score = 0.2

        return CompatibilityScore(
            overall_score=score,
            capability_score=score,
            performance_score=0.8,
            security_score=0.9,
            availability_score=0.85,
        )


class TestAdvancedServiceDiscovery:
    """Test advanced service discovery features."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        return MockRegistryClient()

    @pytest.fixture
    def service_discovery_manager(self, mock_registry_client):
        """Create a service discovery manager with mock client."""
        config = ServiceDiscoveryConfig(
            enable_caching=True,
            cache_ttl=300,
            health_check_enabled=True,
            health_check_interval=60,
        )
        return MockServiceDiscoveryManager(mock_registry_client, config)

    @pytest.mark.asyncio
    async def test_cached_agent_discovery(
        self, service_discovery_manager, mock_registry_client
    ):
        """Test cached agent discovery functionality."""
        # Setup mock response
        agent_info = AgentInfo(
            agent_id="test-agent",
            name="Test Agent",
            version="1.0.0",
            capabilities=[
                CapabilityMetadata(name="file_operations", version="1.0.0"),
            ],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
        )

        mock_registry_client.get_agents = AsyncMock(return_value=[agent_info])

        # First call should hit the registry
        query = CapabilityQuery(capabilities=["file_operations"])
        agents1 = await service_discovery_manager.discover_agents(query)

        assert len(agents1) == 1
        assert agents1[0].agent_id == "test-agent"
        mock_registry_client.get_agents.assert_called_once()

        # Second call should use cache
        mock_registry_client.get_agents.reset_mock()
        agents2 = await service_discovery_manager.discover_agents(query)

        assert len(agents2) == 1
        assert agents2[0].agent_id == "test-agent"
        mock_registry_client.get_agents.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_expiration(
        self, service_discovery_manager, mock_registry_client
    ):
        """Test cache expiration functionality."""
        agent_info = AgentInfo(
            agent_id="test-agent",
            name="Test Agent",
            version="1.0.0",
            capabilities=[
                CapabilityMetadata(name="file_operations", version="1.0.0"),
            ],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
        )

        mock_registry_client.get_agents = AsyncMock(return_value=[agent_info])

        # Configure short cache TTL for testing
        service_discovery_manager.config.cache_ttl = 1  # 1 second

        # First call
        query = CapabilityQuery(capabilities=["file_operations"])
        await service_discovery_manager.discover_agents(query)
        mock_registry_client.get_agents.assert_called_once()

        # Wait for cache expiration
        await asyncio.sleep(1.1)

        # Second call should hit registry again
        mock_registry_client.get_agents.reset_mock()
        await service_discovery_manager.discover_agents(query)
        mock_registry_client.get_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_integration(
        self, service_discovery_manager, mock_registry_client
    ):
        """Test health check integration with discovery."""
        healthy_agent = AgentInfo(
            agent_id="healthy-agent",
            name="Healthy Agent",
            version="1.0.0",
            capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
        )

        unhealthy_agent = AgentInfo(
            agent_id="unhealthy-agent",
            name="Unhealthy Agent",
            version="1.0.0",
            capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
            endpoint="http://localhost:8002",
            status=LifecycleStatus.UNHEALTHY,
        )

        mock_registry_client.get_agents = AsyncMock(
            return_value=[healthy_agent, unhealthy_agent]
        )

        # Discovery should filter out unhealthy agents
        query = CapabilityQuery(capabilities=["test"])
        agents = await service_discovery_manager.discover_agents(
            query, include_unhealthy=False
        )

        assert len(agents) == 1
        assert agents[0].agent_id == "healthy-agent"

        # With include_unhealthy=True, should return both
        agents_all = await service_discovery_manager.discover_agents(
            query, include_unhealthy=True
        )
        assert len(agents_all) == 2


class TestAdvancedAgentSelection:
    """Test advanced agent selection features."""

    @pytest.fixture
    def selection_manager(self):
        """Create an agent selection manager."""
        weights = SelectionWeights(
            capability_match=0.4,
            performance=0.3,
            availability=0.2,
            proximity=0.1,
        )
        return MockAgentSelectionManager(weights)

    @pytest.mark.asyncio
    async def test_weighted_agent_selection(self, selection_manager):
        """Test weighted agent selection algorithm."""
        agents = [
            AgentInfo(
                agent_id="agent-1",
                name="High Performance Agent",
                version="1.0.0",
                capabilities=[
                    CapabilityMetadata(name="file_operations", version="1.0.0"),
                    CapabilityMetadata(name="data_processing", version="1.0.0"),
                ],
                endpoint="http://localhost:8001",
                status=LifecycleStatus.ACTIVE,
                metadata={"performance_score": 0.9, "load": 0.1},
            ),
            AgentInfo(
                agent_id="agent-2",
                name="Lower Performance Agent",
                version="1.0.0",
                capabilities=[
                    CapabilityMetadata(name="file_operations", version="1.0.0"),
                ],
                endpoint="http://localhost:8002",
                status=LifecycleStatus.ACTIVE,
                metadata={"performance_score": 0.6, "load": 0.8},
            ),
        ]

        criteria = SelectionCriteria(
            required_capabilities=["file_operations"],
            preferred_capabilities=["data_processing"],
            max_agents=1,
        )

        result = await selection_manager.select_agents(agents, criteria)

        assert result.success is True
        assert len(result.selected_agents) == 1
        # Should select the high-performance agent with better capabilities
        assert result.selected_agents[0].agent_id == "agent-1"
        assert result.selection_metadata["algorithm"] == "weighted"

    @pytest.mark.asyncio
    async def test_round_robin_selection(self, selection_manager):
        """Test round-robin agent selection."""
        agents = [
            AgentInfo(
                agent_id=f"agent-{i}",
                name=f"Agent {i}",
                version="1.0.0",
                capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
                endpoint=f"http://localhost:800{i}",
                status=LifecycleStatus.ACTIVE,
            )
            for i in range(3)
        ]

        selection_manager.algorithm = "round_robin"
        criteria = SelectionCriteria(required_capabilities=["test"], max_agents=1)

        selected_ids = []
        for _ in range(6):  # Select 6 times to see round-robin behavior
            result = await selection_manager.select_agents(agents, criteria)
            selected_ids.append(result.selected_agents[0].agent_id)

        # Should cycle through agents
        expected_pattern = ["agent-0", "agent-1", "agent-2"] * 2
        assert selected_ids == expected_pattern

    @pytest.mark.asyncio
    async def test_load_balancing_selection(self, selection_manager):
        """Test load-balancing agent selection."""
        agents = [
            AgentInfo(
                agent_id="low-load-agent",
                name="Low Load Agent",
                version="1.0.0",
                capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
                endpoint="http://localhost:8001",
                status=LifecycleStatus.ACTIVE,
                metadata={"current_load": 0.1},
            ),
            AgentInfo(
                agent_id="high-load-agent",
                name="High Load Agent",
                version="1.0.0",
                capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
                endpoint="http://localhost:8002",
                status=LifecycleStatus.ACTIVE,
                metadata={"current_load": 0.9},
            ),
        ]

        selection_manager.algorithm = "load_balanced"
        criteria = SelectionCriteria(required_capabilities=["test"], max_agents=1)

        # Should consistently select the low-load agent
        for _ in range(5):
            result = await selection_manager.select_agents(agents, criteria)
            assert result.selected_agents[0].agent_id == "low-load-agent"


class TestAdvancedLifecycleManagement:
    """Test advanced lifecycle management features."""

    @pytest.fixture
    def lifecycle_manager(self):
        """Create a lifecycle manager."""
        return MockLifecycleManager()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_workflow(self, lifecycle_manager):
        """Test graceful shutdown workflow."""
        agent_info = AgentInfo(
            agent_id="test-agent",
            name="Test Agent",
            version="1.0.0",
            capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
        )

        # Mock the agent's drain endpoint
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"status": "draining"})
            mock_post.return_value.__aenter__.return_value = mock_response

            # Start drain process
            drain_result = await lifecycle_manager.drain_agent(agent_info, timeout=30)

            assert drain_result.success is True
            assert drain_result.agent_id == "test-agent"
            assert drain_result.status == "draining"

    @pytest.mark.asyncio
    async def test_health_monitoring_workflow(self, lifecycle_manager):
        """Test health monitoring workflow."""
        agent_info = AgentInfo(
            agent_id="monitored-agent",
            name="Monitored Agent",
            version="1.0.0",
            capabilities=[CapabilityMetadata(name="test", version="1.0.0")],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
        )

        # Start health monitoring
        monitoring_task = lifecycle_manager.start_health_monitoring(
            agent_info, interval=1
        )

        # Simulate health check responses
        health_responses = [
            {"status": "healthy", "load": 0.2},
            {"status": "healthy", "load": 0.5},
            {"status": "unhealthy", "error": "high load"},
        ]

        with patch("aiohttp.ClientSession.get") as mock_get:
            for i, response_data in enumerate(health_responses):
                mock_response = AsyncMock()
                mock_response.status = (
                    200 if response_data["status"] == "healthy" else 503
                )
                mock_response.json = AsyncMock(return_value=response_data)
                mock_get.return_value.__aenter__.return_value = mock_response

                # Wait for health check
                await asyncio.sleep(1.1)

        # Stop monitoring
        await lifecycle_manager.stop_health_monitoring(agent_info.agent_id)

        # Verify health events were captured
        health_history = lifecycle_manager.get_health_history(agent_info.agent_id)
        assert len(health_history) >= 1


class TestAdvancedVersioning:
    """Test advanced versioning features."""

    @pytest.fixture
    def versioning_manager(self):
        """Create a versioning manager."""
        return MockVersioningManager()

    def test_semantic_version_comparison(self, versioning_manager):
        """Test semantic version comparison logic."""
        versions = [
            SemanticVersion(major=1, minor=0, patch=0),
            SemanticVersion(major=1, minor=1, patch=0),
            SemanticVersion(major=1, minor=0, patch=1),
            SemanticVersion(major=2, minor=0, patch=0),
            SemanticVersion(major=1, minor=1, patch=1),
        ]

        # Test version comparison
        assert versioning_manager.is_compatible(
            versions[0], versions[1]
        )  # 1.0.0 -> 1.1.0 (minor upgrade)
        assert versioning_manager.is_compatible(
            versions[0], versions[2]
        )  # 1.0.0 -> 1.0.1 (patch upgrade)
        assert not versioning_manager.is_compatible(
            versions[0], versions[3]
        )  # 1.0.0 -> 2.0.0 (major upgrade)

        # Test version ordering
        sorted_versions = versioning_manager.sort_versions(versions)
        expected_order = [
            versions[0],
            versions[2],
            versions[1],
            versions[4],
            versions[3],
        ]
        assert sorted_versions == expected_order

    @pytest.mark.asyncio
    async def test_canary_deployment(self, versioning_manager):
        """Test canary deployment workflow."""
        current_version = AgentVersionInfo(
            agent_id="test-agent",
            version=SemanticVersion(major=1, minor=0, patch=0),
            deployment_info=DeploymentInfo(
                environment="production",
                instances=10,
                health_check_url="http://localhost:8001/health",
            ),
        )

        new_version = AgentVersionInfo(
            agent_id="test-agent",
            version=SemanticVersion(major=1, minor=1, patch=0),
            deployment_info=DeploymentInfo(
                environment="production",
                instances=1,  # Canary with 1 instance
                health_check_url="http://localhost:8001/health",
            ),
        )

        # Start canary deployment
        result = await versioning_manager.deploy_canary(
            current_version, new_version, traffic_percent=10
        )

        assert result.success is True
        assert result.deployment_type == "canary"
        assert result.traffic_split["v1.0.0"] == 90
        assert result.traffic_split["v1.1.0"] == 10

    @pytest.mark.asyncio
    async def test_rollback_workflow(self, versioning_manager):
        """Test rollback workflow."""
        current_version = SemanticVersion(major=1, minor=1, patch=0)  # Failed version
        target_version = SemanticVersion(major=1, minor=0, patch=0)  # Rollback target

        agent_info = AgentVersionInfo(
            agent_id="test-agent",
            version=current_version,
            deployment_info=DeploymentInfo(environment="production"),
        )

        # Perform rollback
        rollback_result = await versioning_manager.rollback_agent(
            agent_info, target_version
        )

        assert rollback_result.success is True
        assert rollback_result.previous_version == current_version
        assert rollback_result.rolled_back_to == target_version
        assert rollback_result.rollback_reason == "manual_rollback"


class TestCapabilityMatching:
    """Test advanced capability matching features."""

    @pytest.fixture
    def capability_matcher(self):
        """Create a capability matcher."""
        return MockCapabilityMatcher()

    def test_hierarchical_capability_matching(self, capability_matcher):
        """Test hierarchical capability matching."""
        agent_capabilities = [
            CapabilityMetadata(
                name="file_operations.read",
                version="1.0.0",
                metadata={"supported_formats": ["txt", "json", "yaml"]},
            ),
            CapabilityMetadata(
                name="file_operations.write",
                version="1.0.0",
                metadata={"supported_formats": ["txt", "json"]},
            ),
            CapabilityMetadata(
                name="data_processing.transform",
                version="1.0.0",
            ),
        ]

        # Test exact capability match
        exact_query = CapabilityQuery(capabilities=["file_operations.read"])
        exact_match = capability_matcher.calculate_match_score(
            agent_capabilities, exact_query
        )
        assert exact_match.score >= 0.9

        # Test parent capability match
        parent_query = CapabilityQuery(capabilities=["file_operations"])
        parent_match = capability_matcher.calculate_match_score(
            agent_capabilities, parent_query
        )
        assert parent_match.score >= 0.7  # Should match multiple sub-capabilities

        # Test partial match
        partial_query = CapabilityQuery(
            capabilities=["file_operations.read", "file_operations.delete"]
        )
        partial_match = capability_matcher.calculate_match_score(
            agent_capabilities, partial_query
        )
        assert 0.4 <= partial_match.score <= 0.6  # Should be partial match

    def test_capability_version_compatibility(self, capability_matcher):
        """Test capability version compatibility."""
        agent_capabilities = [
            CapabilityMetadata(name="api", version="2.1.0"),
        ]

        # Compatible version queries
        compatible_queries = [
            CapabilityQuery(
                capabilities=["api"], version_requirements={"api": "^2.0.0"}
            ),
            CapabilityQuery(
                capabilities=["api"], version_requirements={"api": "~2.1.0"}
            ),
            CapabilityQuery(
                capabilities=["api"], version_requirements={"api": ">=2.0.0"}
            ),
        ]

        for query in compatible_queries:
            match = capability_matcher.calculate_match_score(agent_capabilities, query)
            assert match.score >= 0.8, f"Failed for query: {query.version_requirements}"

        # Incompatible version queries
        incompatible_queries = [
            CapabilityQuery(
                capabilities=["api"], version_requirements={"api": "^3.0.0"}
            ),
            CapabilityQuery(
                capabilities=["api"], version_requirements={"api": "~1.0.0"}
            ),
        ]

        for query in incompatible_queries:
            match = capability_matcher.calculate_match_score(agent_capabilities, query)
            assert (
                match.score < 0.5
            ), f"Should fail for query: {query.version_requirements}"


class TestRegistryConfigurationIntegration:
    """Test integration with registry configuration."""

    def test_security_mode_integration(self):
        """Test security mode configuration integration."""
        # API Key security mode
        api_key_config = RegistryConfig(
            security=SecurityConfig(
                mode="api_key",
                api_keys=["test-key-1", "test-key-2"],
            ),
        )

        # Verify configuration is properly structured
        assert api_key_config.security.mode.value == "api_key"
        assert len(api_key_config.security.api_keys) == 2

        # JWT security mode
        jwt_config = RegistryConfig(
            security=SecurityConfig(
                mode="jwt",
                jwt_secret="secret-key",
                jwt_expiration=3600,
            ),
        )

        assert jwt_config.security.mode.value == "jwt"
        assert jwt_config.security.jwt_secret == "secret-key"
        assert jwt_config.security.jwt_expiration == 3600

    def test_performance_configuration_integration(self):
        """Test performance configuration integration."""
        high_performance_config = RegistryConfig(
            server=ServerConfig(
                workers=8,
                max_connections=1000,
                timeout=60,
            ),
            performance=PerformanceConfig(
                max_concurrent_requests=500,
                request_timeout=30,
                cache_enabled=True,
                cache_size=10000,
                background_task_workers=4,
            ),
        )

        # Verify high-performance settings
        assert high_performance_config.server.workers == 8
        assert high_performance_config.server.max_connections == 1000
        assert high_performance_config.performance.max_concurrent_requests == 500
        assert high_performance_config.performance.cache_enabled is True
        assert high_performance_config.performance.background_task_workers == 4

    def test_monitoring_configuration_integration(self):
        """Test monitoring configuration integration."""
        monitoring_config = RegistryConfig(
            monitoring=MonitoringConfig(
                enable_metrics=True,
                metrics_port=9090,
                enable_tracing=True,
                jaeger_endpoint="http://jaeger:14268",
                log_level="DEBUG",
                log_format="json",
                enable_performance_metrics=True,
            ),
        )

        # Verify monitoring settings
        assert monitoring_config.monitoring.enable_metrics is True
        assert monitoring_config.monitoring.metrics_port == 9090
        assert monitoring_config.monitoring.enable_tracing is True
        assert monitoring_config.monitoring.jaeger_endpoint == "http://jaeger:14268"
        assert monitoring_config.monitoring.log_level.value == "DEBUG"


@pytest.mark.asyncio
async def test_end_to_end_advanced_workflow():
    """Test complete end-to-end advanced workflow."""
    # Setup configuration
    config = RegistryConfig(
        discovery=ServiceDiscoveryConfig(
            enable_caching=True,
            cache_ttl=300,
            health_check_enabled=True,
        ),
        security=SecurityConfig(
            mode="api_key",
            api_keys=["test-key"],
        ),
    )

    # Create managers
    registry_client = MockRegistryClient()
    discovery_manager = MockServiceDiscoveryManager(registry_client, config.discovery)

    selection_weights = SelectionWeights(
        capability_match=0.5,
        performance=0.3,
        availability=0.2,
    )
    selection_manager = MockAgentSelectionManager(selection_weights)

    # Setup mock agents
    agents = [
        AgentInfo(
            agent_id="agent-1",
            name="High Performance Agent",
            version="1.0.0",
            capabilities=[
                CapabilityMetadata(name="file_operations", version="1.0.0"),
            ],
            endpoint="http://localhost:8001",
            status=LifecycleStatus.ACTIVE,
            metadata={"performance_score": 0.9},
        ),
        AgentInfo(
            agent_id="agent-2",
            name="Backup Agent",
            version="1.0.0",
            capabilities=[
                CapabilityMetadata(name="file_operations", version="1.0.0"),
            ],
            endpoint="http://localhost:8002",
            status=LifecycleStatus.ACTIVE,
            metadata={"performance_score": 0.6},
        ),
    ]

    registry_client.get_agents = AsyncMock(return_value=agents)

    # 1. Service Discovery
    query = CapabilityQuery(capabilities=["file_operations"])
    discovered_agents = await discovery_manager.discover_agents(query)
    assert len(discovered_agents) == 2

    # 2. Agent Selection
    criteria = SelectionCriteria(
        required_capabilities=["file_operations"],
        max_agents=1,
    )
    selection_result = await selection_manager.select_agents(
        discovered_agents, criteria
    )
    assert selection_result.success is True
    assert len(selection_result.selected_agents) == 1
    # Should select the high-performance agent
    assert selection_result.selected_agents[0].agent_id == "agent-1"

    # 3. Verify the complete workflow completed successfully
    selected_agent = selection_result.selected_agents[0]
    assert selected_agent.status == LifecycleStatus.ACTIVE
    assert any(cap.name == "file_operations" for cap in selected_agent.capabilities)
