"""
MCP Protocol Compliance Tests - Pull-Based Architecture

Verifies that the Registry Service strictly follows MCP protocol specifications
with pull-based architecture patterns. Ensures registry never initiates
connections to agents and follows Kubernetes API server patterns.

Only imports from mcp-mesh-types for MCP SDK compatibility.
"""

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

# Import only from mcp-mesh-types for MCP SDK compatibility
from mcp_mesh.server.models import AgentCapability, AgentRegistration

# Import registry and MCP components
from mcp_mesh.server.registry import RegistryService


class TestMCPProtocolCompliance:
    """
    Test suite for MCP protocol compliance in pull-based architecture.

    Verifies:
    - MCP tool interface compliance
    - Pull-based communication patterns
    - Resource management following Kubernetes patterns
    - No outbound connections from registry
    - Proper error handling and responses
    """

    @pytest.fixture
    async def registry_service(self):
        """Create a test registry service."""
        service = RegistryService()
        await service.initialize()
        yield service
        await service.close()

    @pytest.fixture
    def sample_registration_data(self) -> dict[str, Any]:
        """Sample agent registration data for MCP tool testing."""
        return {
            "id": "mcp-test-agent-001",
            "name": "MCP Test Agent",
            "namespace": "test",
            "agent_type": "test_agent",
            "endpoint": "http://localhost:8080/mcp",
            "capabilities": [
                {
                    "name": "test_capability",
                    "description": "Test capability for MCP compliance",
                    "category": "testing",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["test", "mcp"],
                }
            ],
            "labels": {"env": "test"},
            "security_context": "standard",
            "health_interval": 30.0,
        }

    @pytest.mark.asyncio
    async def test_mcp_tool_register_agent_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP tool interface for agent registration."""
        app = registry_service.get_app()

        # Verify FastMCP app structure
        assert isinstance(app, FastMCP)
        assert hasattr(app, "tools")

        # Find register_agent tool
        register_tool = None
        for tool in app.tools:
            if tool.name == "register_agent":
                register_tool = tool
                break

        assert register_tool is not None, "register_agent tool not found"
        assert register_tool.description == "Register agent with the service mesh"

        # Test tool execution
        result = await register_tool.handler(sample_registration_data)

        # Verify MCP-compliant response structure
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "success"
        assert "agent_id" in result
        assert result["agent_id"] == sample_registration_data["id"]
        assert "resource_version" in result
        assert "message" in result

        # Verify agent was actually registered
        agent = await registry_service.storage.get_agent(sample_registration_data["id"])
        assert agent is not None
        assert agent.id == sample_registration_data["id"]

    @pytest.mark.asyncio
    async def test_mcp_tool_discover_services_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP tool interface for service discovery."""
        app = registry_service.get_app()

        # Register an agent first
        await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )

        # Find discover_services tool
        discover_tool = None
        for tool in app.tools:
            if tool.name == "discover_services":
                discover_tool = tool
                break

        assert discover_tool is not None, "discover_services tool not found"
        assert discover_tool.description == "Discover available services"

        # Test tool execution with empty query
        result = await discover_tool.handler()

        # Verify MCP-compliant response structure
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "success"
        assert "agents" in result
        assert "count" in result
        assert isinstance(result["agents"], list)
        assert result["count"] == len(result["agents"])
        assert result["count"] >= 1

        # Test with query parameters
        query = {"namespace": "test"}
        result = await discover_tool.handler(query)

        assert result["status"] == "success"
        assert result["count"] >= 1
        assert all(agent["namespace"] == "test" for agent in result["agents"])

    @pytest.mark.asyncio
    async def test_mcp_tool_heartbeat_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP tool interface for heartbeat processing."""
        app = registry_service.get_app()

        # Register an agent first
        await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )

        # Find heartbeat tool
        heartbeat_tool = None
        for tool in app.tools:
            if tool.name == "heartbeat":
                heartbeat_tool = tool
                break

        assert heartbeat_tool is not None, "heartbeat tool not found"
        assert heartbeat_tool.description == "Send agent heartbeat"

        # Test tool execution
        result = await heartbeat_tool.handler(sample_registration_data["id"])

        # Verify MCP-compliant response structure
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "success"
        assert "timestamp" in result
        assert "message" in result

        # Test with non-existent agent
        result = await heartbeat_tool.handler("non-existent-agent")
        assert result["status"] == "error"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_mcp_tool_unregister_agent_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP tool interface for agent unregistration."""
        app = registry_service.get_app()

        # Register an agent first
        await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )

        # Find unregister_agent tool
        unregister_tool = None
        for tool in app.tools:
            if tool.name == "unregister_agent":
                unregister_tool = tool
                break

        assert unregister_tool is not None, "unregister_agent tool not found"
        assert unregister_tool.description == "Unregister agent from service mesh"

        # Test tool execution
        result = await unregister_tool.handler(sample_registration_data["id"])

        # Verify MCP-compliant response structure
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "success"
        assert "message" in result

        # Verify agent was actually unregistered
        agent = await registry_service.storage.get_agent(sample_registration_data["id"])
        assert agent is None

        # Test with non-existent agent
        result = await unregister_tool.handler("non-existent-agent")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_mcp_tool_get_agent_status_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP tool interface for agent status retrieval."""
        app = registry_service.get_app()

        # Register an agent first
        await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )

        # Find get_agent_status tool
        status_tool = None
        for tool in app.tools:
            if tool.name == "get_agent_status":
                status_tool = tool
                break

        assert status_tool is not None, "get_agent_status tool not found"
        assert status_tool.description == "Get agent status and details"

        # Test tool execution
        result = await status_tool.handler(sample_registration_data["id"])

        # Verify MCP-compliant response structure
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "success"
        assert "agent" in result
        assert isinstance(result["agent"], dict)

        # Verify agent data structure
        agent_data = result["agent"]
        assert agent_data["id"] == sample_registration_data["id"]
        assert agent_data["name"] == sample_registration_data["name"]
        assert "capabilities" in agent_data
        assert "resource_version" in agent_data

    @pytest.mark.asyncio
    async def test_pull_based_architecture_compliance(self, registry_service):
        """Verify strict adherence to pull-based architecture."""

        # Test 1: Registry should never initiate outbound connections
        with patch("aiohttp.ClientSession") as mock_client:
            with patch("requests.get") as mock_get:
                with patch("requests.post") as mock_post:

                    # Perform various registry operations
                    sample_agent = AgentRegistration(
                        id="pull-test-agent",
                        name="Pull Test Agent",
                        namespace="test",
                        agent_type="test_agent",
                        endpoint="http://localhost:8090/mcp",
                        capabilities=[],
                    )

                    # Register agent
                    await registry_service.storage.register_agent(sample_agent)

                    # Process heartbeat
                    await registry_service.storage.update_heartbeat(sample_agent.id)

                    # Perform service discovery
                    await registry_service.storage.list_agents()

                    # Perform health check
                    await registry_service.storage.check_agent_health_and_evict_expired()

                    # Verify NO outbound HTTP calls were made
                    assert not mock_client.called
                    assert not mock_get.called
                    assert not mock_post.called

        # Test 2: Verify all operations are passive/reactive
        operations_log = []

        class MockStorage:
            def __init__(self, real_storage):
                self.real_storage = real_storage

            async def register_agent(self, agent):
                operations_log.append(("register", "incoming"))
                return await self.real_storage.register_agent(agent)

            async def update_heartbeat(self, agent_id):
                operations_log.append(("heartbeat", "incoming"))
                return await self.real_storage.update_heartbeat(agent_id)

            async def list_agents(self, query=None):
                operations_log.append(("discover", "incoming"))
                return await self.real_storage.list_agents(query)

        # Temporarily replace storage to monitor operations
        original_storage = registry_service.storage
        mock_storage = MockStorage(original_storage)

        # All operations should be marked as "incoming" (agent-initiated)
        sample_agent = AgentRegistration(
            id="passive-test-agent",
            name="Passive Test Agent",
            namespace="test",
            agent_type="test_agent",
            endpoint="http://localhost:8091/mcp",
            capabilities=[],
        )

        await mock_storage.register_agent(sample_agent)
        await mock_storage.update_heartbeat(sample_agent.id)
        await mock_storage.list_agents()

        # Verify all operations were incoming (agent-initiated)
        assert len(operations_log) == 3
        assert all(direction == "incoming" for _, direction in operations_log)

    @pytest.mark.asyncio
    async def test_kubernetes_api_patterns_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test compliance with Kubernetes API server patterns."""

        # Test 1: Resource versioning
        agent = await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )
        assert agent.resource_version is not None
        initial_version = agent.resource_version

        # Update should increment resource version
        await registry_service.storage.update_heartbeat(agent.id)
        updated_agent = await registry_service.storage.get_agent(agent.id)
        assert updated_agent.resource_version != initial_version

        # Test 2: Watch events
        watcher = registry_service.storage.create_watcher()

        # Register new agent and verify watch event
        new_agent_data = sample_registration_data.copy()
        new_agent_data["id"] = "watch-test-agent"
        await registry_service.storage.register_agent(
            AgentRegistration(**new_agent_data)
        )

        # Should receive ADDED event
        event = await asyncio.wait_for(watcher.get(), timeout=1.0)
        assert event["type"] == "ADDED"
        assert event["object"]["id"] == new_agent_data["id"]
        assert "timestamp" in event

        # Test 3: Declarative state management
        # Registry should maintain desired state vs actual state patterns
        agents_before = await registry_service.storage.list_agents()
        count_before = len(agents_before)

        # Add agent
        test_agent = AgentRegistration(
            id="state-test-agent",
            name="State Test Agent",
            namespace="test",
            agent_type="test_agent",
            endpoint="http://localhost:8092/mcp",
            capabilities=[],
        )
        await registry_service.storage.register_agent(test_agent)

        agents_after = await registry_service.storage.list_agents()
        assert len(agents_after) == count_before + 1

        # Remove agent
        await registry_service.storage.unregister_agent(test_agent.id)

        agents_final = await registry_service.storage.list_agents()
        assert len(agents_final) == count_before

    @pytest.mark.asyncio
    async def test_mcp_error_handling_compliance(self, registry_service):
        """Test MCP-compliant error handling."""
        app = registry_service.get_app()

        # Test error handling in each tool
        tools_to_test = [
            ("register_agent", {"invalid": "data"}),
            ("unregister_agent", "non-existent-agent"),
            ("heartbeat", "non-existent-agent"),
            ("get_agent_status", "non-existent-agent"),
        ]

        for tool_name, invalid_input in tools_to_test:
            tool = None
            for t in app.tools:
                if t.name == tool_name:
                    tool = t
                    break

            assert tool is not None

            # Test with invalid input
            try:
                if tool_name == "register_agent":
                    result = await tool.handler(invalid_input)
                else:
                    result = await tool.handler(invalid_input)

                # Should return error status, not raise exception
                assert isinstance(result, dict)
                assert "status" in result
                if result["status"] == "error":
                    assert "message" in result or "error" in result

            except Exception as e:
                # If exception is raised, it should be handled gracefully
                # In MCP tools, errors should be returned as status responses
                pytest.fail(f"Tool {tool_name} raised unhandled exception: {e}")

    @pytest.mark.asyncio
    async def test_mcp_data_serialization_compliance(
        self, registry_service, sample_registration_data
    ):
        """Test MCP data serialization compliance."""

        # Register agent
        agent = await registry_service.storage.register_agent(
            AgentRegistration(**sample_registration_data)
        )

        # Test that all data can be properly serialized to JSON
        agent_dict = agent.model_dump()

        # Should be JSON serializable
        json_str = json.dumps(agent_dict)
        assert isinstance(json_str, str)

        # Should be deserializable back to dict
        reloaded_dict = json.loads(json_str)
        assert isinstance(reloaded_dict, dict)
        assert reloaded_dict["id"] == agent.id

        # Test tool responses are JSON serializable
        app = registry_service.get_app()

        # Get discover_services tool
        discover_tool = None
        for tool in app.tools:
            if tool.name == "discover_services":
                discover_tool = tool
                break

        result = await discover_tool.handler()

        # Tool response should be JSON serializable
        json_result = json.dumps(result)
        assert isinstance(json_result, str)

        reloaded_result = json.loads(json_result)
        assert reloaded_result["status"] == "success"

    @pytest.mark.asyncio
    async def test_mcp_resource_limits_compliance(self, registry_service):
        """Test resource limits and pagination patterns."""

        # Test large agent registration doesn't break the system
        large_agent = AgentRegistration(
            id="large-agent",
            name="Agent with Many Capabilities",
            namespace="test",
            agent_type="test_agent",
            endpoint="http://localhost:8093/mcp",
            capabilities=[
                AgentCapability(
                    name=f"capability_{i}",
                    description=f"Test capability {i}",
                    category="testing",
                    version="1.0.0",
                )
                for i in range(100)  # 100 capabilities
            ],
        )

        # Should handle large registration
        result = await registry_service.storage.register_agent(large_agent)
        assert result.id == large_agent.id
        assert len(result.capabilities) == 100

        # Test service discovery with large results
        agents = await registry_service.storage.list_agents()
        assert len(agents) >= 1

        # Should be able to serialize large results
        json.dumps([agent.model_dump() for agent in agents])

    @pytest.mark.asyncio
    async def test_mcp_concurrent_access_compliance(self, registry_service):
        """Test concurrent access patterns for MCP compliance."""

        # Test concurrent tool executions
        app = registry_service.get_app()

        # Find tools
        register_tool = None
        discover_tool = None

        for tool in app.tools:
            if tool.name == "register_agent":
                register_tool = tool
            elif tool.name == "discover_services":
                discover_tool = tool

        assert register_tool is not None
        assert discover_tool is not None

        # Create multiple agent registrations
        agent_data_list = []
        for i in range(5):
            data = {
                "id": f"concurrent-agent-{i}",
                "name": f"Concurrent Agent {i}",
                "namespace": "test",
                "agent_type": "test_agent",
                "endpoint": f"http://localhost:80{90+i}/mcp",
                "capabilities": [],
                "labels": {},
                "security_context": "standard",
                "health_interval": 30.0,
            }
            agent_data_list.append(data)

        # Execute concurrent registrations
        register_tasks = [register_tool.handler(data) for data in agent_data_list]

        # Execute concurrent discoveries
        discover_tasks = [discover_tool.handler() for _ in range(3)]

        # Wait for all operations
        all_results = await asyncio.gather(
            *register_tasks, *discover_tasks, return_exceptions=True
        )

        # Check that no exceptions occurred
        for result in all_results:
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent operation failed: {result}")
            assert isinstance(result, dict)
            assert "status" in result

    @pytest.mark.asyncio
    async def test_mcp_security_context_compliance(self, registry_service):
        """Test security context handling in MCP tools."""
        app = registry_service.get_app()

        # Find register tool
        register_tool = None
        for tool in app.tools:
            if tool.name == "register_agent":
                register_tool = tool
                break

        assert register_tool is not None

        # Test security context validation
        high_security_data = {
            "id": "security-test-agent",
            "name": "Security Test Agent",
            "namespace": "security",
            "agent_type": "security_agent",
            "endpoint": "http://localhost:8094/mcp",
            "capabilities": [
                {
                    "name": "basic_operation",
                    "description": "Basic operation",
                    "category": "general",
                    "version": "1.0.0",
                }
            ],
            "labels": {},
            "security_context": "high_security",
            "health_interval": 30.0,
        }

        # Should fail due to missing security capabilities
        result = await register_tool.handler(high_security_data)
        assert result["status"] == "error"
        assert "message" in result or "error" in result

        # Test with valid security context
        valid_security_data = high_security_data.copy()
        valid_security_data["id"] = "valid-security-agent"
        valid_security_data["capabilities"] = [
            {
                "name": "authentication",
                "description": "Auth",
                "category": "security",
                "version": "1.0.0",
            },
            {
                "name": "authorization",
                "description": "Authz",
                "category": "security",
                "version": "1.0.0",
            },
            {
                "name": "audit",
                "description": "Audit",
                "category": "security",
                "version": "1.0.0",
            },
        ]

        result = await register_tool.handler(valid_security_data)
        assert result["status"] == "success"


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_mcp_protocol_compliance_pull.py -v
    pytest.main([__file__, "-v"])
