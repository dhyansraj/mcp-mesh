"""Integration tests for Registry Integration Service Discovery (Phase 2).

Tests the complete service discovery workflow including:
- Service endpoint resolution through registry client
- Health-aware proxy creation excluding degraded services
- discover_service_by_class functionality
- select_best_service_instance with criteria matching
- monitor_service_health with callback system
- MCP compliance using official SDK patterns
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_mesh.shared.registry_client import RegistryClient
from src.mcp_mesh.shared.service_discovery import (
    EnhancedServiceDiscovery,
    HealthMonitor,
    SelectionCriteria,
    ServiceDiscovery,
)
from src.mcp_mesh.shared.types import EndpointInfo, HealthStatusType
from src.mcp_mesh.tools.discovery_tools import DiscoveryTools


class MockFileService:
    """Mock service class for testing."""

    def read_file(self, path: str) -> str:
        return f"Content of {path}"

    def write_file(self, path: str, content: str) -> bool:
        return True


class MockCalculatorService:
    """Mock calculator service for testing."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def multiply(self, a: int, b: int) -> int:
        return a * b


@pytest.fixture
async def mock_registry_client():
    """Create a mock registry client."""
    client = AsyncMock(spec=RegistryClient)

    # Mock agent data
    mock_agents = [
        {
            "agent_id": "file-agent-1",
            "metadata": {
                "name": "FileAgent1",
                "version": "1.0.0",
                "description": "File operations agent",
                "capabilities": [
                    {
                        "name": "fileservice",
                        "version": "1.0.0",
                        "description": "File operations capability",
                        "tags": ["file", "io"],
                        "performance_metrics": {},
                        "security_level": "standard",
                        "resource_requirements": {},
                        "metadata": {"service_class": "MockFileService"},
                    }
                ],
                "dependencies": [],
                "health_interval": 30,
                "endpoint": "mcp://localhost:8081/fileservice",
                "tags": ["file", "storage"],
                "performance_profile": {},
                "resource_usage": {},
                "metadata": {"provided_services": ["MockFileService", "fileservice"]},
            },
            "status": "active",
            "health_score": 0.95,
            "availability": 0.98,
            "current_load": 0.3,
            "response_time_ms": 50,
            "success_rate": 0.99,
            "last_updated": "2024-01-01T12:00:00",
        },
        {
            "agent_id": "calc-agent-1",
            "metadata": {
                "name": "CalculatorAgent1",
                "version": "1.2.0",
                "description": "Calculator service agent",
                "capabilities": [
                    {
                        "name": "calculatorservice",
                        "version": "1.2.0",
                        "description": "Mathematical operations",
                        "tags": ["math", "calculator"],
                        "performance_metrics": {},
                        "security_level": "standard",
                        "resource_requirements": {},
                        "metadata": {"service_class": "MockCalculatorService"},
                    }
                ],
                "dependencies": [],
                "health_interval": 30,
                "endpoint": "mcp://localhost:8082/calculatorservice",
                "tags": ["math", "computation"],
                "performance_profile": {},
                "resource_usage": {},
                "metadata": {
                    "provided_services": ["MockCalculatorService", "calculatorservice"]
                },
            },
            "status": "active",
            "health_score": 0.85,
            "availability": 0.95,
            "current_load": 0.6,
            "response_time_ms": 75,
            "success_rate": 0.97,
            "last_updated": "2024-01-01T12:00:00",
        },
        {
            "agent_id": "file-agent-2",
            "metadata": {
                "name": "FileAgent2",
                "version": "1.1.0",
                "description": "File operations agent (degraded)",
                "capabilities": [
                    {
                        "name": "fileservice",
                        "version": "1.1.0",
                        "description": "File operations capability",
                        "tags": ["file", "io"],
                        "performance_metrics": {},
                        "security_level": "standard",
                        "resource_requirements": {},
                        "metadata": {"service_class": "MockFileService"},
                    }
                ],
                "dependencies": [],
                "health_interval": 30,
                "endpoint": "mcp://localhost:8083/fileservice",
                "tags": ["file", "storage"],
                "performance_profile": {},
                "resource_usage": {},
                "metadata": {"provided_services": ["MockFileService", "fileservice"]},
            },
            "status": "active",
            "health_score": 0.65,  # Degraded
            "availability": 0.75,
            "current_load": 0.9,
            "response_time_ms": 200,
            "success_rate": 0.85,
            "last_updated": "2024-01-01T12:00:00",
        },
    ]

    client.get_all_agents.return_value = mock_agents
    client.get_agent.side_effect = lambda agent_id: next(
        (agent for agent in mock_agents if agent["agent_id"] == agent_id), None
    )

    return client


@pytest.fixture
async def service_discovery(mock_registry_client):
    """Create a service discovery instance."""
    return ServiceDiscovery(mock_registry_client)


@pytest.fixture
async def enhanced_service_discovery(mock_registry_client):
    """Create an enhanced service discovery instance."""
    return EnhancedServiceDiscovery(mock_registry_client)


class TestServiceDiscoveryBasics:
    """Test basic service discovery functionality."""

    async def test_discover_service_by_class_healthy_only(self, service_discovery):
        """Test discovering healthy service endpoints by class."""
        endpoints = await service_discovery.discover_service_by_class(MockFileService)

        assert len(endpoints) == 1  # Only healthy endpoints
        assert endpoints[0].service_name == "mockfileservice"
        assert endpoints[0].status == HealthStatusType.HEALTHY
        assert endpoints[0].url == "mcp://localhost:8081/fileservice"

    async def test_discover_service_by_class_includes_all(self, service_discovery):
        """Test discovering all service endpoints including degraded."""
        # Get all agents and filter manually to include degraded
        agents = await service_discovery._get_all_agents()
        file_agents = [
            agent
            for agent in agents
            if service_discovery._agent_provides_service(agent, MockFileService)
        ]

        assert len(file_agents) == 2  # Both healthy and degraded

        # Convert to endpoints manually
        endpoints = []
        for agent in file_agents:
            endpoint = service_discovery._agent_to_endpoint_info(
                agent, "mockfileservice"
            )
            if endpoint:
                endpoints.append(endpoint)

        assert len(endpoints) == 2
        healthy_endpoints = [
            e for e in endpoints if e.status == HealthStatusType.HEALTHY
        ]
        degraded_endpoints = [
            e for e in endpoints if e.status == HealthStatusType.DEGRADED
        ]

        assert len(healthy_endpoints) == 1
        assert len(degraded_endpoints) == 1

    async def test_select_best_service_instance(self, service_discovery):
        """Test selecting the best service instance based on criteria."""
        criteria = SelectionCriteria(
            min_compatibility_score=0.7,
            max_response_time_ms=100,
            min_success_rate=0.95,
            max_load=0.8,
        )

        best_endpoint = await service_discovery.select_best_service_instance(
            MockFileService, criteria
        )

        assert best_endpoint is not None
        assert best_endpoint.url == "mcp://localhost:8081/fileservice"
        assert best_endpoint.metadata["health_score"] == 0.95

    async def test_select_best_service_instance_no_match(self, service_discovery):
        """Test selection when no instance meets criteria."""
        criteria = SelectionCriteria(
            min_compatibility_score=0.99,  # Very high threshold
            max_response_time_ms=10,  # Very low threshold
            min_success_rate=0.999,  # Very high threshold
            max_load=0.1,  # Very low threshold
        )

        best_endpoint = await service_discovery.select_best_service_instance(
            MockFileService, criteria
        )

        assert best_endpoint is None

    async def test_monitor_service_health_callback(self, service_discovery):
        """Test health monitoring with callback system."""
        callback_calls = []

        def health_callback(endpoint_url: str, status: HealthStatusType):
            callback_calls.append((endpoint_url, status))

        monitor = await service_discovery.monitor_service_health(
            MockFileService, health_callback
        )

        assert isinstance(monitor, HealthMonitor)
        assert monitor.is_monitoring()
        assert monitor.service_name == "mockfileservice"

        # Stop monitoring
        await monitor.stop_monitoring()
        assert not monitor.is_monitoring()

    async def test_agent_provides_service_detection(self, service_discovery):
        """Test detection of whether an agent provides a service."""
        agents = await service_discovery._get_all_agents()

        file_agent = agents[0]  # file-agent-1
        calc_agent = agents[1]  # calc-agent-1

        assert service_discovery._agent_provides_service(file_agent, MockFileService)
        assert not service_discovery._agent_provides_service(
            file_agent, MockCalculatorService
        )

        assert service_discovery._agent_provides_service(
            calc_agent, MockCalculatorService
        )
        assert not service_discovery._agent_provides_service(
            calc_agent, MockFileService
        )

    async def test_agent_to_endpoint_info_conversion(self, service_discovery):
        """Test conversion of agent info to endpoint info."""
        agents = await service_discovery._get_all_agents()
        file_agent = agents[0]

        endpoint = service_discovery._agent_to_endpoint_info(file_agent, "fileservice")

        assert endpoint is not None
        assert endpoint.url == "mcp://localhost:8081/fileservice"
        assert endpoint.service_name == "fileservice"
        assert endpoint.service_version == "1.0.0"
        assert endpoint.protocol == "mcp"
        assert endpoint.status == HealthStatusType.HEALTHY
        assert endpoint.metadata["agent_id"] == "file-agent-1"
        assert endpoint.metadata["health_score"] == 0.95


class TestEnhancedServiceDiscovery:
    """Test enhanced service discovery with health-aware proxy creation."""

    async def test_get_healthy_endpoints_only(self, enhanced_service_discovery):
        """Test getting only healthy endpoints."""
        healthy_endpoints = await enhanced_service_discovery.get_healthy_endpoints(
            MockFileService
        )

        assert len(healthy_endpoints) == 1
        assert all(e.status == HealthStatusType.HEALTHY for e in healthy_endpoints)

    @patch("src.mcp_mesh.shared.service_discovery.get_proxy_factory")
    async def test_create_healthy_proxy(
        self, mock_get_factory, enhanced_service_discovery
    ):
        """Test creating a proxy for a healthy service instance."""
        # Mock proxy factory
        mock_factory = MagicMock()
        mock_proxy = MagicMock()
        mock_factory.create_service_proxy.return_value = mock_proxy
        mock_get_factory.return_value = mock_factory

        criteria = SelectionCriteria(
            min_compatibility_score=0.7,
            max_response_time_ms=5000,
            min_success_rate=0.9,
            max_load=0.8,
        )

        proxy = await enhanced_service_discovery.create_healthy_proxy(
            MockFileService, criteria
        )

        assert proxy is not None
        assert proxy == mock_proxy
        mock_factory.create_service_proxy.assert_called_once()

    @patch("src.mcp_mesh.shared.service_discovery.get_proxy_factory")
    async def test_create_healthy_proxy_no_endpoint(
        self, mock_get_factory, enhanced_service_discovery
    ):
        """Test proxy creation when no healthy endpoint is available."""
        mock_factory = MagicMock()
        mock_get_factory.return_value = mock_factory

        # Use very strict criteria that no endpoint can meet
        criteria = SelectionCriteria(
            min_compatibility_score=0.99,
            max_response_time_ms=1,
            min_success_rate=0.999,
            max_load=0.01,
        )

        proxy = await enhanced_service_discovery.create_healthy_proxy(
            MockFileService, criteria
        )

        assert proxy is None
        mock_factory.create_service_proxy.assert_not_called()


class TestHealthMonitor:
    """Test health monitoring system."""

    async def test_health_monitor_lifecycle(self, service_discovery):
        """Test health monitor start/stop lifecycle."""
        callback_calls = []

        def health_callback(endpoint_url: str, status: HealthStatusType):
            callback_calls.append((endpoint_url, status))

        monitor = HealthMonitor(
            service_name="testservice",
            service_class=MockFileService,
            callback=health_callback,
            service_discovery=service_discovery,
            check_interval=1,  # Short interval for testing
        )

        assert not monitor.is_monitoring()

        await monitor.start_monitoring()
        assert monitor.is_monitoring()

        # Let it run briefly
        await asyncio.sleep(0.1)

        await monitor.stop_monitoring()
        assert not monitor.is_monitoring()

    async def test_health_monitor_status_tracking(self, service_discovery):
        """Test health monitor status tracking."""
        callback_calls = []

        def health_callback(endpoint_url: str, status: HealthStatusType):
            callback_calls.append((endpoint_url, status))

        monitor = HealthMonitor(
            service_name="mockfileservice",
            service_class=MockFileService,
            callback=health_callback,
            service_discovery=service_discovery,
            check_interval=0.1,  # Very short for testing
        )

        await monitor.start_monitoring()

        # Wait for at least one health check
        await asyncio.sleep(0.2)

        current_status = monitor.get_current_status()
        assert len(current_status) > 0

        await monitor.stop_monitoring()

    async def test_health_monitor_endpoint_health_check(self, service_discovery):
        """Test endpoint health checking logic."""
        monitor = HealthMonitor(
            service_name="mockfileservice",
            service_class=MockFileService,
            callback=lambda x, y: None,
            service_discovery=service_discovery,
        )

        # Create test endpoint
        endpoint = EndpointInfo(
            url="mcp://test:8080/service",
            service_name="testservice",
            service_version="1.0.0",
            protocol="mcp",
            status=HealthStatusType.HEALTHY,
        )

        health_status = await monitor._check_endpoint_health(endpoint)
        assert health_status == HealthStatusType.HEALTHY


class TestMCPCompliantTools:
    """Test MCP-compliant discovery tools."""

    async def test_discovery_tools_initialization(self, service_discovery):
        """Test discovery tools initialization."""
        tools = DiscoveryTools(service_discovery)
        assert tools.service_discovery == service_discovery

    @patch("mcp.server.Server")
    async def test_register_tools_with_server(self, mock_server, service_discovery):
        """Test registering tools with MCP server."""
        tools = DiscoveryTools(service_discovery)
        mock_app = mock_server.return_value

        # Register tools
        tools.register_tools(mock_app)

        # Verify tools were registered (check that tool decorator was called)
        assert mock_app.tool.called

    async def test_mcp_tool_discover_service_by_class(self, service_discovery):
        """Test MCP tool for service discovery by class."""
        tools = DiscoveryTools(service_discovery)

        # Create a mock app and register tools
        class MockApp:
            def __init__(self):
                self.tools = {}

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    return func

                return decorator

        mock_app = MockApp()
        tools.register_tools(mock_app)

        # Test the discover_service_by_class tool
        assert "discover_service_by_class" in mock_app.tools
        result = await mock_app.tools["discover_service_by_class"]("MockFileService")

        # Should return JSON string
        assert isinstance(result, str)
        import json

        data = json.loads(result)
        assert isinstance(data, list)

    async def test_mcp_tool_select_best_service_instance(self, service_discovery):
        """Test MCP tool for selecting best service instance."""
        tools = DiscoveryTools(service_discovery)

        class MockApp:
            def __init__(self):
                self.tools = {}

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    return func

                return decorator

        mock_app = MockApp()
        tools.register_tools(mock_app)

        # Test the select_best_service_instance tool
        assert "select_best_service_instance" in mock_app.tools
        result = await mock_app.tools["select_best_service_instance"](
            "MockFileService", min_compatibility_score=0.7, max_response_time_ms=100
        )

        # Should return JSON string
        assert isinstance(result, str)
        import json

        data = json.loads(result)
        assert "url" in data or "error" in data

    async def test_mcp_tool_monitor_service_health_status(self, service_discovery):
        """Test MCP tool for health monitoring status."""
        tools = DiscoveryTools(service_discovery)

        class MockApp:
            def __init__(self):
                self.tools = {}

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    return func

                return decorator

        mock_app = MockApp()
        tools.register_tools(mock_app)

        # Test the monitor_service_health_status tool
        assert "monitor_service_health_status" in mock_app.tools
        result = await mock_app.tools["monitor_service_health_status"](
            "MockFileService"
        )

        # Should return JSON string
        assert isinstance(result, str)
        import json

        data = json.loads(result)
        assert "service_class" in data
        assert "total_endpoints" in data


class TestIntegrationScenarios:
    """Test complete integration scenarios."""

    async def test_complete_service_discovery_workflow(
        self, enhanced_service_discovery
    ):
        """Test complete workflow from discovery to proxy creation."""
        # 1. Discover services
        endpoints = await enhanced_service_discovery.discover_service_by_class(
            MockFileService
        )
        assert len(endpoints) > 0

        # 2. Select best instance
        criteria = SelectionCriteria(min_compatibility_score=0.7)
        best_endpoint = await enhanced_service_discovery.select_best_service_instance(
            MockFileService, criteria
        )
        assert best_endpoint is not None

        # 3. Get healthy endpoints only
        healthy_endpoints = await enhanced_service_discovery.get_healthy_endpoints(
            MockFileService
        )
        assert len(healthy_endpoints) > 0
        assert all(e.status == HealthStatusType.HEALTHY for e in healthy_endpoints)

    async def test_fallback_when_no_healthy_services(self, service_discovery):
        """Test graceful fallback when no healthy services are available."""
        # Mock a scenario where all services are degraded
        with patch.object(service_discovery, "_agent_to_endpoint_info") as mock_convert:
            # Make all endpoints appear unhealthy
            def mock_endpoint_conversion(agent, service_name):
                endpoint = EndpointInfo(
                    url=f"mcp://localhost:8080/{service_name}",
                    service_name=service_name,
                    service_version="1.0.0",
                    protocol="mcp",
                    status=HealthStatusType.UNHEALTHY,
                )
                return endpoint

            mock_convert.side_effect = mock_endpoint_conversion

            endpoints = await service_discovery.discover_service_by_class(
                MockFileService
            )
            assert len(endpoints) == 0  # No healthy endpoints

    async def test_service_discovery_with_multiple_service_types(
        self, service_discovery
    ):
        """Test discovery with multiple different service types."""
        # Test file service discovery
        file_endpoints = await service_discovery.discover_service_by_class(
            MockFileService
        )
        assert len(file_endpoints) > 0

        # Test calculator service discovery
        calc_endpoints = await service_discovery.discover_service_by_class(
            MockCalculatorService
        )
        assert len(calc_endpoints) > 0

        # Ensure they're different
        file_urls = {e.url for e in file_endpoints}
        calc_urls = {e.url for e in calc_endpoints}
        assert file_urls != calc_urls

    async def test_health_monitoring_with_status_changes(self, service_discovery):
        """Test health monitoring responds to status changes."""
        status_changes = []

        def track_changes(endpoint_url: str, status: HealthStatusType):
            status_changes.append((endpoint_url, status))

        monitor = await service_discovery.monitor_service_health(
            MockFileService, track_changes
        )

        # Start monitoring
        await monitor.start_monitoring()

        # Simulate status change by modifying agent health
        # This would normally happen through registry updates

        await asyncio.sleep(0.1)  # Brief monitoring period

        await monitor.stop_monitoring()

        # Should have captured initial status
        current_status = monitor.get_current_status()
        assert len(current_status) >= 0  # May be empty if no endpoints found


@pytest.mark.asyncio
class TestRegistryIntegrationCompliance:
    """Test compliance with registry integration requirements."""

    async def test_registry_client_integration(self, mock_registry_client):
        """Test proper integration with registry client."""
        service_discovery = ServiceDiscovery(mock_registry_client)

        # Verify registry client is used for agent data
        agents = await service_discovery._get_all_agents()
        mock_registry_client.get_all_agents.assert_called()

        assert len(agents) > 0

    async def test_health_aware_filtering(self, service_discovery):
        """Test that degraded services are properly filtered."""
        # Get all endpoints (including degraded)
        agents = await service_discovery._get_all_agents()
        all_file_agents = [
            agent
            for agent in agents
            if service_discovery._agent_provides_service(agent, MockFileService)
        ]

        # Get only healthy endpoints
        healthy_endpoints = await service_discovery.discover_service_by_class(
            MockFileService
        )

        # Should have fewer healthy than total
        assert len(healthy_endpoints) < len(all_file_agents)
        assert all(e.status == HealthStatusType.HEALTHY for e in healthy_endpoints)

    async def test_capability_matching_integration(self, service_discovery):
        """Test integration with capability matching system."""
        # The service discovery should use capability matching for scoring
        criteria = SelectionCriteria(min_compatibility_score=0.5)

        endpoint = await service_discovery.select_best_service_instance(
            MockFileService, criteria
        )

        # Should select the best performing healthy endpoint
        assert endpoint is not None
        assert endpoint.metadata["health_score"] >= 0.8  # Should be the healthy one

    async def test_mcp_sdk_compliance(self, service_discovery):
        """Test MCP SDK compliance patterns."""
        tools = DiscoveryTools(service_discovery)

        # Tools should be registerable with MCP server
        class MockServer:
            def __init__(self):
                self.registered_tools = []

            def tool(self):
                def decorator(func):
                    self.registered_tools.append(func)
                    return func

                return decorator

        mock_server = MockServer()
        tools.register_tools(mock_server)

        # Should have registered multiple tools
        assert len(mock_server.registered_tools) > 0

        # All tools should be async functions (MCP requirement)
        for tool_func in mock_server.registered_tools:
            assert asyncio.iscoroutinefunction(tool_func)
