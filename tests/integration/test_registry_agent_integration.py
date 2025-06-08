"""
Registry Service Integration Tests with Existing Agents

Tests integration between the Registry Service and existing MCP agents
(File Agent, Command Agent, Developer Agent) to verify end-to-end workflows.

Only imports from mcp-mesh-types for MCP SDK compatibility.
"""

import asyncio
from typing import Any

import aiohttp
import pytest

# Import only from mcp-mesh-types for MCP SDK compatibility
# Import registry and agent components
from mcp_mesh_runtime.server.registry_server import RegistryServer


class TestRegistryAgentIntegration:
    """
    Integration tests between Registry Service and existing agents.

    Tests:
    - File Agent registration and discovery
    - Command Agent registration and discovery
    - Developer Agent registration and discovery
    - Cross-agent service discovery workflows
    - Health monitoring across agent types
    - Resource sharing and capability matching
    """

    @pytest.fixture
    async def registry_server(self):
        """Create and start a full registry server."""
        server = RegistryServer(host="localhost", port=8000)

        # Start server in background
        server_task = asyncio.create_task(server.start())

        # Wait a moment for server to start
        await asyncio.sleep(0.5)

        yield server

        # Cleanup
        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    @pytest.fixture
    def file_agent_registration(self) -> dict[str, Any]:
        """File Agent registration data."""
        return {
            "id": "file-agent-integration-001",
            "name": "File Operations Agent",
            "namespace": "system",
            "agent_type": "file_agent",
            "endpoint": "http://localhost:8001/mcp",
            "capabilities": [
                {
                    "name": "read_file",
                    "description": "Read file contents from filesystem",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "read"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to file",
                            }
                        },
                        "required": ["file_path"],
                    },
                },
                {
                    "name": "write_file",
                    "description": "Write content to filesystem",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "write"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["file_path", "content"],
                    },
                },
                {
                    "name": "list_directory",
                    "description": "List directory contents",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "directory"],
                },
            ],
            "labels": {"env": "production", "team": "platform", "zone": "us-west-2a"},
            "security_context": "standard",
            "health_interval": 30.0,
        }

    @pytest.fixture
    def command_agent_registration(self) -> dict[str, Any]:
        """Command Agent registration data."""
        return {
            "id": "command-agent-integration-001",
            "name": "Command Execution Agent",
            "namespace": "system",
            "agent_type": "command_agent",
            "endpoint": "http://localhost:8002/mcp",
            "capabilities": [
                {
                    "name": "execute_command",
                    "description": "Execute system commands with output capture",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "stable",
                    "tags": ["shell", "system", "execution"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "timeout": {"type": "number", "default": 30},
                        },
                        "required": ["command"],
                    },
                },
                {
                    "name": "monitor_process",
                    "description": "Monitor running processes and resource usage",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "beta",
                    "tags": ["monitoring", "process", "resources"],
                },
                {
                    "name": "kill_process",
                    "description": "Terminate running processes",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "stable",
                    "tags": ["process", "termination"],
                },
            ],
            "labels": {"env": "production", "team": "devops", "zone": "us-west-2b"},
            "security_context": "high_security",
            "health_interval": 15.0,
        }

    @pytest.fixture
    def developer_agent_registration(self) -> dict[str, Any]:
        """Developer Agent registration data."""
        return {
            "id": "developer-agent-integration-001",
            "name": "Developer Assistant Agent",
            "namespace": "development",
            "agent_type": "developer_agent",
            "endpoint": "http://localhost:8003/mcp",
            "capabilities": [
                {
                    "name": "code_review",
                    "description": "Perform automated code reviews with quality analysis",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "stable",
                    "tags": ["code", "review", "quality", "analysis"],
                },
                {
                    "name": "test_generation",
                    "description": "Generate comprehensive unit tests",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "experimental",
                    "tags": ["testing", "automation", "generation"],
                },
                {
                    "name": "refactor_code",
                    "description": "Suggest and apply code refactoring",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "beta",
                    "tags": ["refactoring", "optimization", "improvement"],
                },
                {
                    "name": "documentation_generation",
                    "description": "Generate technical documentation",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "stable",
                    "tags": ["documentation", "generation", "technical"],
                },
            ],
            "labels": {
                "env": "development",
                "team": "engineering",
                "zone": "us-east-1a",
            },
            "security_context": "standard",
            "health_interval": 60.0,
        }

    @pytest.mark.asyncio
    async def test_individual_agent_registration_workflows(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test registration workflow for each agent type."""

        async with aiohttp.ClientSession() as session:
            # Test File Agent registration
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": file_agent_registration},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["status"] == "success"
                assert result["agent_id"] == file_agent_registration["id"]

            # Test Command Agent registration
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": command_agent_registration},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["status"] == "success"
                assert result["agent_id"] == command_agent_registration["id"]

            # Test Developer Agent registration
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": developer_agent_registration},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["status"] == "success"
                assert result["agent_id"] == developer_agent_registration["id"]

            # Verify all agents are discoverable
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 3

                agent_ids = {agent["id"] for agent in data["agents"]}
                expected_ids = {
                    file_agent_registration["id"],
                    command_agent_registration["id"],
                    developer_agent_registration["id"],
                }
                assert agent_ids == expected_ids

    @pytest.mark.asyncio
    async def test_cross_agent_service_discovery(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test service discovery across different agent types."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Test discovery by capability category
            async with session.get(
                "http://localhost:8000/agents?capability_category=file_operations"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 1
                assert data["agents"][0]["id"] == file_agent_registration["id"]

            # Test discovery by namespace
            async with session.get(
                "http://localhost:8000/agents?namespace=system"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 2  # File and Command agents

                agent_ids = {agent["id"] for agent in data["agents"]}
                expected_ids = {
                    file_agent_registration["id"],
                    command_agent_registration["id"],
                }
                assert agent_ids == expected_ids

            # Test discovery by labels
            async with session.get(
                "http://localhost:8000/agents?label_selector=env=production"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 2  # File and Command agents

            # Test fuzzy capability matching
            async with session.get(
                "http://localhost:8000/agents?capability=file&fuzzy_match=true"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 1  # Should match file operations

    @pytest.mark.asyncio
    async def test_capability_search_across_agents(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test comprehensive capability search across all agent types."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Test capability search by stability
            async with session.get(
                "http://localhost:8000/capabilities?stability=stable"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                stable_capabilities = [
                    cap for cap in data["capabilities"] if cap["stability"] == "stable"
                ]
                assert len(stable_capabilities) >= 6  # Multiple stable capabilities

            # Test capability search by tags
            async with session.get(
                "http://localhost:8000/capabilities?tags=filesystem"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                filesystem_caps = [
                    cap for cap in data["capabilities"] if "filesystem" in cap["tags"]
                ]
                assert len(filesystem_caps) == 3  # File operations capabilities

            # Test capability search by category
            async with session.get(
                "http://localhost:8000/capabilities?category=development"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                dev_capabilities = [
                    cap
                    for cap in data["capabilities"]
                    if cap["category"] == "development"
                ]
                assert len(dev_capabilities) == 4  # Developer agent capabilities

            # Test fuzzy capability name search
            async with session.get(
                "http://localhost:8000/capabilities?name=command&fuzzy_match=true"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                # Should match "execute_command"
                command_caps = [
                    cap
                    for cap in data["capabilities"]
                    if "command" in cap["name"].lower()
                ]
                assert len(command_caps) >= 1

    @pytest.mark.asyncio
    async def test_agent_heartbeat_workflows(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test heartbeat workflows for different agent types."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            agent_ids = []
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200
                    result = await resp.json()
                    agent_ids.append(result["agent_id"])

            # Send heartbeats for all agents
            for agent_id in agent_ids:
                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_id, "status": "healthy"},
                ) as resp:
                    assert resp.status == 200
                    result = await resp.json()
                    assert result["status"] == "success"

            # Verify all agents are healthy
            for agent_id in agent_ids:
                async with session.get(
                    f"http://localhost:8000/health/{agent_id}"
                ) as resp:
                    assert resp.status == 200
                    health_data = await resp.json()
                    assert health_data["status"] == "healthy"
                    assert health_data["agent_id"] == agent_id
                    assert health_data["time_since_heartbeat"] is not None
                    assert health_data["time_since_heartbeat"] < 5.0  # Recent heartbeat

    @pytest.mark.asyncio
    async def test_version_constraint_filtering(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test version constraint filtering across different agent versions."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Test version constraint: >= 2.0.0 (should match Command Agent v2.1.0)
            async with session.get(
                "http://localhost:8000/agents?version_constraint=%3E%3D2.0.0"  # URL encoded >=2.0.0
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 1
                assert data["agents"][0]["id"] == command_agent_registration["id"]

            # Test version constraint: >= 1.0.0 (should match all agents)
            async with session.get(
                "http://localhost:8000/agents?version_constraint=%3E%3D1.0.0"  # URL encoded >=1.0.0
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 3

            # Test version constraint: ~1.5.0 (should match Developer Agent v1.5.2)
            async with session.get(
                "http://localhost:8000/agents?version_constraint=~1.5.0"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 1
                assert data["agents"][0]["id"] == developer_agent_registration["id"]

    @pytest.mark.asyncio
    async def test_health_monitoring_with_different_intervals(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test health monitoring with different heartbeat intervals."""

        async with aiohttp.ClientSession() as session:
            # Register all agents with different health intervals
            # File: 30s, Command: 15s, Developer: 60s
            agent_ids = []
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200
                    result = await resp.json()
                    agent_ids.append(result["agent_id"])

            # Send initial heartbeats
            for agent_id in agent_ids:
                async with session.post(
                    "http://localhost:8000/heartbeat", json={"agent_id": agent_id}
                ) as resp:
                    assert resp.status == 200

            # Verify all agents are healthy initially
            async with session.get(
                "http://localhost:8000/agents?status=healthy"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 3

            # Test that agents have different timeout thresholds
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()

                agents_by_id = {agent["id"]: agent for agent in data["agents"]}

                # Command agent should have shortest timeout (15s interval)
                command_agent = agents_by_id[command_agent_registration["id"]]
                file_agent = agents_by_id[file_agent_registration["id"]]
                developer_agent = agents_by_id[developer_agent_registration["id"]]

                # Verify timeout thresholds are set appropriately
                assert (
                    command_agent["timeout_threshold"]
                    <= file_agent["timeout_threshold"]
                )
                assert (
                    file_agent["timeout_threshold"]
                    <= developer_agent["timeout_threshold"]
                )

    @pytest.mark.asyncio
    async def test_resource_sharing_workflows(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test workflows that involve multiple agents working together."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Scenario: Developer wants to review code in a file
            # 1. Discover file operations capabilities
            async with session.get(
                "http://localhost:8000/capabilities?category=file_operations"
            ) as resp:
                assert resp.status == 200
                file_data = await resp.json()
                assert file_data["count"] == 3  # read, write, list

                # Should find read_file capability
                read_file_caps = [
                    cap
                    for cap in file_data["capabilities"]
                    if cap["name"] == "read_file"
                ]
                assert len(read_file_caps) == 1
                file_agent_id = read_file_caps[0]["agent_id"]
                assert file_agent_id == file_agent_registration["id"]

            # 2. Discover code review capabilities
            async with session.get(
                "http://localhost:8000/capabilities?name=code_review"
            ) as resp:
                assert resp.status == 200
                review_data = await resp.json()
                assert review_data["count"] == 1

                review_cap = review_data["capabilities"][0]
                developer_agent_id = review_cap["agent_id"]
                assert developer_agent_id == developer_agent_registration["id"]

            # Scenario: System monitoring and process management
            # 1. Discover process monitoring
            async with session.get(
                "http://localhost:8000/capabilities?name=monitor_process"
            ) as resp:
                assert resp.status == 200
                monitor_data = await resp.json()
                assert monitor_data["count"] == 1

                monitor_cap = monitor_data["capabilities"][0]
                command_agent_id = monitor_cap["agent_id"]
                assert command_agent_id == command_agent_registration["id"]

            # 2. Discover command execution for remediation
            async with session.get(
                "http://localhost:8000/capabilities?name=execute_command"
            ) as resp:
                assert resp.status == 200
                exec_data = await resp.json()
                assert exec_data["count"] == 1

                exec_cap = exec_data["capabilities"][0]
                assert exec_cap["agent_id"] == command_agent_registration["id"]

    @pytest.mark.asyncio
    async def test_registry_metrics_with_multiple_agents(
        self,
        registry_server,
        file_agent_registration,
        command_agent_registration,
        developer_agent_registration,
    ):
        """Test registry metrics with multiple registered agents."""

        async with aiohttp.ClientSession() as session:
            # Get initial metrics
            async with session.get("http://localhost:8000/metrics") as resp:
                assert resp.status == 200
                initial_metrics = await resp.json()
                initial_agent_count = initial_metrics["total_agents"]
                initial_capability_count = initial_metrics["total_capabilities"]

            # Register all agents
            for agent_data in [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Send heartbeats to make all agents healthy
            agent_registrations = [
                file_agent_registration,
                command_agent_registration,
                developer_agent_registration,
            ]
            for agent_data in agent_registrations:
                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_data["id"]},
                ) as resp:
                    assert resp.status == 200

            # Get updated metrics
            async with session.get("http://localhost:8000/metrics") as resp:
                assert resp.status == 200
                metrics = await resp.json()

                # Verify metrics reflect all agents
                assert metrics["total_agents"] == initial_agent_count + 3
                assert metrics["healthy_agents"] >= 3

                # Calculate expected capabilities: 3 + 3 + 4 = 10
                expected_capabilities = sum(
                    len(agent["capabilities"]) for agent in agent_registrations
                )
                assert (
                    metrics["total_capabilities"]
                    == initial_capability_count + expected_capabilities
                )

                # Should have at least 10 unique capability types
                assert metrics["unique_capability_types"] >= 10

                # Verify uptime is tracking
                assert metrics["uptime_seconds"] > 0

            # Test Prometheus metrics format
            async with session.get("http://localhost:8000/metrics/prometheus") as resp:
                assert resp.status == 200
                prometheus_data = await resp.text()

                # Verify key Prometheus metrics are present
                assert "mcp_registry_agents_total" in prometheus_data
                assert "mcp_registry_capabilities_total" in prometheus_data
                assert "mcp_registry_agents_by_status" in prometheus_data
                assert (
                    f"mcp_registry_agents_total {metrics['total_agents']}"
                    in prometheus_data
                )

    @pytest.mark.asyncio
    async def test_error_handling_and_resilience(
        self, registry_server, file_agent_registration
    ):
        """Test error handling and resilience with agent operations."""

        async with aiohttp.ClientSession() as session:
            # Test registration with invalid data
            invalid_registration = file_agent_registration.copy()
            del invalid_registration["id"]  # Remove required field

            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": invalid_registration},
            ) as resp:
                result = await resp.json()
                assert result["status"] == "error"

            # Test heartbeat for non-existent agent
            async with session.post(
                "http://localhost:8000/heartbeat",
                json={"agent_id": "non-existent-agent"},
            ) as resp:
                assert resp.status == 404

            # Test health check for non-existent agent
            async with session.get(
                "http://localhost:8000/health/non-existent-agent"
            ) as resp:
                assert resp.status == 404

            # Register valid agent
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": file_agent_registration},
            ) as resp:
                assert resp.status == 200

            # Test duplicate registration (should update, not error)
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": file_agent_registration},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["status"] == "success"

            # Verify agent is still discoverable
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 1


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_registry_agent_integration.py -v
    pytest.main([__file__, "-v"])
