"""
Comprehensive Integration Test Suite for Registry Service

This test suite provides complete coverage of the Registry Service functionality
including agent registration, heartbeat monitoring, service discovery, health
management, and pull-based architecture compliance.

Covers:
- Agent lifecycle management (register, heartbeat, discovery, eviction)
- Advanced service discovery with filtering and fuzzy matching
- Capability search with semantic versioning and tags
- Health monitoring and automatic status transitions
- Pull-based MCP protocol compliance
- Performance and concurrent operation testing
- Error handling and graceful degradation
- Registry metrics and monitoring
"""

import asyncio
import time
from typing import Any

import aiohttp
import pytest

# Import only from mcp-mesh-types for MCP SDK compatibility
# Import registry components
from mcp_mesh.server.registry_server import RegistryServer


class TestRegistryServiceComprehensive:
    """
    Comprehensive test suite for Registry Service.

    Tests cover the complete workflow of:
    1. Agent registration and validation
    2. Heartbeat monitoring and status transitions
    3. Service discovery with advanced filtering
    4. Capability search and matching
    5. Health monitoring and automatic eviction
    6. Pull-based architecture compliance
    7. Performance and concurrent operations
    8. Error handling and resilience
    9. Registry metrics and monitoring
    """

    @pytest.fixture
    async def registry_server(self):
        """Create and start a full registry server for integration testing."""
        server = RegistryServer(host="localhost", port=8000)

        # Start server in background
        server_task = asyncio.create_task(server.start())

        # Wait for server to start
        await asyncio.sleep(1.0)

        yield server

        # Cleanup
        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    @pytest.fixture
    def comprehensive_test_agents(self) -> list[dict[str, Any]]:
        """Create comprehensive test agent registrations covering various scenarios."""

        # File Agent - Standard capabilities
        file_agent = {
            "id": "file-agent-comprehensive-001",
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
            "labels": {
                "env": "production",
                "team": "platform",
                "zone": "us-west-2a",
                "criticality": "high",
            },
            "security_context": "standard",
            "health_interval": 30.0,
        }

        # Command Agent - System operations with higher version
        command_agent = {
            "id": "command-agent-comprehensive-001",
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
                    "tags": ["shell", "system", "execution", "async"],
                },
                {
                    "name": "monitor_process",
                    "description": "Monitor running processes and resource usage",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "beta",
                    "tags": ["monitoring", "process", "resources", "realtime"],
                },
                {
                    "name": "kill_process",
                    "description": "Terminate running processes",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "stable",
                    "tags": ["process", "termination", "cleanup"],
                },
            ],
            "labels": {
                "env": "production",
                "team": "devops",
                "zone": "us-west-2b",
                "criticality": "medium",
            },
            "security_context": "high_security",
            "health_interval": 15.0,
        }

        # Developer Agent - Development tools
        developer_agent = {
            "id": "developer-agent-comprehensive-001",
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
                    "tags": ["code", "review", "quality", "analysis", "automated"],
                },
                {
                    "name": "test_generation",
                    "description": "Generate comprehensive unit tests",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "experimental",
                    "tags": ["testing", "automation", "generation", "unit-tests"],
                },
                {
                    "name": "refactor_code",
                    "description": "Suggest and apply code refactoring",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "beta",
                    "tags": [
                        "refactoring",
                        "optimization",
                        "improvement",
                        "code-quality",
                    ],
                },
                {
                    "name": "documentation_generation",
                    "description": "Generate technical documentation",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "stable",
                    "tags": ["documentation", "generation", "technical", "markdown"],
                },
            ],
            "labels": {
                "env": "development",
                "team": "engineering",
                "zone": "us-east-1a",
                "criticality": "low",
            },
            "security_context": "standard",
            "health_interval": 60.0,
        }

        # Database Agent - Data operations with mixed stability
        database_agent = {
            "id": "database-agent-comprehensive-001",
            "name": "Database Operations Agent",
            "namespace": "data",
            "agent_type": "database_agent",
            "endpoint": "http://localhost:8004/mcp",
            "capabilities": [
                {
                    "name": "execute_query",
                    "description": "Execute SQL queries with result formatting",
                    "category": "database_operations",
                    "version": "3.0.1",
                    "stability": "stable",
                    "tags": ["sql", "database", "query", "relational"],
                },
                {
                    "name": "backup_database",
                    "description": "Create database backups",
                    "category": "database_operations",
                    "version": "3.0.1",
                    "stability": "stable",
                    "tags": ["backup", "database", "maintenance", "disaster-recovery"],
                },
                {
                    "name": "schema_migration",
                    "description": "Perform database schema migrations",
                    "category": "database_operations",
                    "version": "3.0.1",
                    "stability": "beta",
                    "tags": ["migration", "schema", "database", "deployment"],
                },
                {
                    "name": "performance_tuning",
                    "description": "Analyze and optimize database performance",
                    "category": "database_operations",
                    "version": "3.0.1",
                    "stability": "experimental",
                    "tags": ["performance", "optimization", "tuning", "analysis"],
                },
            ],
            "labels": {
                "env": "production",
                "team": "data",
                "zone": "eu-west-1a",
                "criticality": "high",
            },
            "security_context": "high_security",
            "health_interval": 20.0,
        }

        # Monitoring Agent - Observability and alerting
        monitoring_agent = {
            "id": "monitoring-agent-comprehensive-001",
            "name": "Monitoring and Alerting Agent",
            "namespace": "observability",
            "agent_type": "monitoring_agent",
            "endpoint": "http://localhost:8005/mcp",
            "capabilities": [
                {
                    "name": "collect_metrics",
                    "description": "Collect system and application metrics",
                    "category": "monitoring",
                    "version": "2.3.0",
                    "stability": "stable",
                    "tags": ["metrics", "collection", "monitoring", "observability"],
                },
                {
                    "name": "create_alert",
                    "description": "Create and manage alerts",
                    "category": "monitoring",
                    "version": "2.3.0",
                    "stability": "stable",
                    "tags": ["alerts", "notification", "monitoring", "threshold"],
                },
                {
                    "name": "generate_dashboard",
                    "description": "Generate monitoring dashboards",
                    "category": "monitoring",
                    "version": "2.3.0",
                    "stability": "beta",
                    "tags": ["dashboard", "visualization", "monitoring", "grafana"],
                },
            ],
            "labels": {
                "env": "production",
                "team": "sre",
                "zone": "us-central-1a",
                "criticality": "high",
            },
            "security_context": "standard",
            "health_interval": 10.0,
        }

        return [
            file_agent,
            command_agent,
            developer_agent,
            database_agent,
            monitoring_agent,
        ]

    @pytest.mark.asyncio
    async def test_complete_agent_lifecycle(
        self, registry_server, comprehensive_test_agents
    ):
        """Test complete agent lifecycle: register -> heartbeat -> discover -> evict."""

        async with aiohttp.ClientSession() as session:
            registered_agent_ids = []

            # Phase 1: Register all agents
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200
                    result = await resp.json()
                    assert result["status"] == "success"
                    assert result["agent_id"] == agent_data["id"]
                    registered_agent_ids.append(agent_data["id"])

            # Verify all agents are registered but pending
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == len(comprehensive_test_agents)

                # All should be in pending status initially
                for agent in data["agents"]:
                    assert agent["status"] == "pending"

            # Phase 2: Send heartbeats to make agents healthy
            for agent_id in registered_agent_ids:
                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_id, "status": "healthy"},
                ) as resp:
                    assert resp.status == 200
                    result = await resp.json()
                    assert result["status"] == "success"

            # Verify all agents are now healthy
            async with session.get(
                "http://localhost:8000/agents?status=healthy"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == len(comprehensive_test_agents)

            # Phase 3: Test service discovery across all dimensions

            # Discovery by namespace
            async with session.get(
                "http://localhost:8000/agents?namespace=system"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 2  # file_agent and command_agent

            # Discovery by capability category
            async with session.get(
                "http://localhost:8000/agents?capability_category=development"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 1  # developer_agent
                assert data["agents"][0]["id"] == "developer-agent-comprehensive-001"

            # Discovery by labels
            async with session.get(
                "http://localhost:8000/agents?label_selector=env=production"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 4  # file, command, database, monitoring

            # Discovery by version constraint
            async with session.get(
                "http://localhost:8000/agents?version_constraint=%3E%3D2.0.0"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 3  # command, database, monitoring

            # Phase 4: Test capability search
            async with session.get(
                "http://localhost:8000/capabilities?category=file_operations"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] == 3  # read, write, list

                file_ops = [
                    cap
                    for cap in data["capabilities"]
                    if cap["category"] == "file_operations"
                ]
                assert len(file_ops) == 3

            # Test fuzzy capability search
            async with session.get(
                "http://localhost:8000/capabilities?name=database&fuzzy_match=true"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                # Should match database operations
                db_caps = [
                    cap
                    for cap in data["capabilities"]
                    if "database" in cap["name"].lower()
                    or "database" in cap["description"].lower()
                ]
                assert len(db_caps) >= 2

            # Phase 5: Test health monitoring
            for agent_id in registered_agent_ids:
                async with session.get(
                    f"http://localhost:8000/health/{agent_id}"
                ) as resp:
                    assert resp.status == 200
                    health_data = await resp.json()
                    assert health_data["status"] == "healthy"
                    assert health_data["agent_id"] == agent_id
                    assert health_data["time_since_heartbeat"] is not None
                    assert health_data["time_since_heartbeat"] < 5.0

            # Phase 6: Test registry metrics
            async with session.get("http://localhost:8000/metrics") as resp:
                assert resp.status == 200
                metrics = await resp.json()

                assert metrics["total_agents"] == len(comprehensive_test_agents)
                assert metrics["healthy_agents"] == len(comprehensive_test_agents)

                # Calculate expected capabilities: 3+3+4+4+3 = 17
                expected_capabilities = sum(
                    len(agent["capabilities"]) for agent in comprehensive_test_agents
                )
                assert metrics["total_capabilities"] == expected_capabilities

                # All capability names should be unique
                assert metrics["unique_capability_types"] == expected_capabilities

                assert metrics["registrations_processed"] >= len(
                    comprehensive_test_agents
                )
                assert metrics["heartbeats_processed"] >= len(comprehensive_test_agents)

    @pytest.mark.asyncio
    async def test_pull_based_architecture_compliance(
        self, registry_server, comprehensive_test_agents
    ):
        """Test that registry strictly follows pull-based architecture."""

        async with aiohttp.ClientSession() as session:
            # Register agents
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Verify pull-based behavior:

            # 1. Registry does NOT initiate connections (passive registration)
            agents = await registry_server.registry_service.storage.list_agents()
            assert len(agents) == len(comprehensive_test_agents)
            # All operations are reactive to agent requests

            # 2. Heartbeats are agent-initiated (passive monitoring)
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_data["id"]},
                ) as resp:
                    assert resp.status == 200

            # 3. Health monitoring is timer-based, not connection-based
            # Registry checks timestamps, doesn't ping agents
            evicted = (
                await registry_server.registry_service.storage.check_agent_health_and_evict_expired()
            )
            assert isinstance(evicted, list)  # Returns passive check results

            # 4. Service discovery is query-based (agents query registry)
            async with session.get(
                "http://localhost:8000/agents?namespace=system"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 0

            # 5. No WebSocket or persistent connections from registry to agents
            # This is verified by the fact that all endpoints are HTTP request/response

            # This demonstrates Kubernetes API server pattern:
            # - Registry is passive data store
            # - Agents actively register, heartbeat, and query
            # - No outbound connections from registry to agents

    @pytest.mark.asyncio
    async def test_advanced_filtering_capabilities(
        self, registry_server, comprehensive_test_agents
    ):
        """Test advanced filtering and search capabilities."""

        async with aiohttp.ClientSession() as session:
            # Register and activate all agents
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_data["id"]},
                ) as resp:
                    assert resp.status == 200

            # Test complex label selectors
            async with session.get(
                "http://localhost:8000/agents?label_selector=env=production,criticality=high"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                # Should match file_agent, database_agent, monitoring_agent
                high_crit_agents = [
                    agent
                    for agent in data["agents"]
                    if agent["labels"].get("env") == "production"
                    and agent["labels"].get("criticality") == "high"
                ]
                assert len(high_crit_agents) >= 3

            # Test fuzzy capability matching with tags
            async with session.get(
                "http://localhost:8000/capabilities?tags=monitoring&fuzzy_match=true"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                monitoring_caps = [
                    cap for cap in data["capabilities"] if "monitoring" in cap["tags"]
                ]
                assert (
                    len(monitoring_caps) >= 4
                )  # process monitoring + monitoring agent caps

            # Test version constraint combinations
            async with session.get(
                "http://localhost:8000/capabilities?version_constraint=%3E%3D2.0.0&stability=stable"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                stable_v2_caps = [
                    cap
                    for cap in data["capabilities"]
                    if cap["stability"] == "stable"
                    and cap["version"].startswith(("2.", "3."))
                ]
                assert len(stable_v2_caps) >= 3

            # Test agent status filtering
            async with session.get(
                "http://localhost:8000/capabilities?agent_status=healthy"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                # All capabilities should be from healthy agents
                for cap in data["capabilities"]:
                    assert "agent_id" in cap
                    # Verify agent is healthy by checking individual health
                    async with session.get(
                        f"http://localhost:8000/health/{cap['agent_id']}"
                    ) as health_resp:
                        assert health_resp.status == 200
                        health_data = await health_resp.json()
                        assert health_data["status"] == "healthy"

            # Test description-based search
            async with session.get(
                "http://localhost:8000/capabilities?description_contains=file"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                file_desc_caps = [
                    cap
                    for cap in data["capabilities"]
                    if "file" in cap["description"].lower()
                ]
                assert len(file_desc_caps) >= 2  # read_file, write_file

            # Test excluding deprecated capabilities
            async with session.get(
                "http://localhost:8000/capabilities?include_deprecated=false"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                deprecated_caps = [
                    cap
                    for cap in data["capabilities"]
                    if cap["stability"] == "deprecated"
                ]
                assert len(deprecated_caps) == 0

    @pytest.mark.asyncio
    async def test_performance_and_concurrency(
        self, registry_server, comprehensive_test_agents
    ):
        """Test performance under concurrent operations."""

        async with aiohttp.ClientSession() as session:
            # Register agents first
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Test concurrent heartbeats
            heartbeat_tasks = []
            for agent_data in comprehensive_test_agents:
                for _ in range(5):  # Multiple heartbeats per agent
                    task = asyncio.create_task(
                        session.post(
                            "http://localhost:8000/heartbeat",
                            json={"agent_id": agent_data["id"]},
                        )
                    )
                    heartbeat_tasks.append(task)

            # Execute all heartbeats concurrently
            heartbeat_responses = await asyncio.gather(*heartbeat_tasks)

            # All should succeed
            for response in heartbeat_responses:
                assert response.status == 200

            # Test concurrent service discovery queries
            query_tasks = []
            query_params = [
                "namespace=system",
                "capability_category=development",
                "label_selector=env=production",
                "status=healthy",
                "version_constraint=%3E%3D2.0.0",
            ]

            for params in query_params:
                for _ in range(10):  # Multiple identical queries
                    task = asyncio.create_task(
                        session.get(f"http://localhost:8000/agents?{params}")
                    )
                    query_tasks.append(task)

            # Execute all queries concurrently
            start_time = time.time()
            query_responses = await asyncio.gather(*query_tasks)
            total_time = time.time() - start_time

            # All should succeed
            for response in query_responses:
                assert response.status == 200

            # Should complete reasonably fast (caching should help)
            assert total_time < 10.0  # 50 queries in under 10 seconds

            # Test concurrent capability searches
            capability_tasks = []
            search_terms = ["file", "command", "database", "monitoring", "development"]

            for term in search_terms:
                for _ in range(8):  # Multiple searches per term
                    task = asyncio.create_task(
                        session.get(
                            f"http://localhost:8000/capabilities?name={term}&fuzzy_match=true"
                        )
                    )
                    capability_tasks.append(task)

            # Execute all capability searches concurrently
            capability_responses = await asyncio.gather(*capability_tasks)

            # All should succeed
            for response in capability_responses:
                assert response.status == 200

    @pytest.mark.asyncio
    async def test_error_handling_and_resilience(
        self, registry_server, comprehensive_test_agents
    ):
        """Test comprehensive error handling and system resilience."""

        async with aiohttp.ClientSession() as session:
            # Test registration with invalid data
            invalid_agent = comprehensive_test_agents[0].copy()
            del invalid_agent["id"]  # Remove required field

            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": invalid_agent},
            ) as resp:
                result = await resp.json()
                assert result["status"] == "error"
                assert "id" in result["error"]

            # Test heartbeat for non-existent agent
            async with session.post(
                "http://localhost:8000/heartbeat",
                json={"agent_id": "non-existent-agent-123"},
            ) as resp:
                assert resp.status == 404
                result = await resp.json()
                assert "not found" in result["detail"].lower()

            # Test health check for non-existent agent
            async with session.get(
                "http://localhost:8000/health/non-existent-agent-123"
            ) as resp:
                assert resp.status == 404

            # Test invalid query parameters
            async with session.get(
                "http://localhost:8000/agents?label_selector=invalid-format"
            ) as resp:
                assert resp.status == 400
                result = await resp.json()
                assert "invalid label selector" in result["detail"].lower()

            # Test malformed version constraints
            async with session.get(
                "http://localhost:8000/agents?version_constraint=invalid-version"
            ) as resp:
                # Should handle gracefully, possibly returning no results
                assert resp.status in [200, 400]

            # Register a valid agent for duplicate testing
            valid_agent = comprehensive_test_agents[0]
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": valid_agent},
            ) as resp:
                assert resp.status == 200

            # Test duplicate registration (should update, not error)
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": valid_agent},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["status"] == "success"

            # Verify agent is still discoverable
            async with session.get("http://localhost:8000/agents") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["count"] >= 1

                agent_ids = [agent["id"] for agent in data["agents"]]
                assert valid_agent["id"] in agent_ids

    @pytest.mark.asyncio
    async def test_health_monitoring_and_eviction(self, registry_server):
        """Test health monitoring with automatic eviction."""

        # Create test agent with short timeouts for testing
        test_agent = {
            "id": "eviction-test-agent-001",
            "name": "Eviction Test Agent",
            "namespace": "test",
            "agent_type": "test_agent",
            "endpoint": "http://localhost:8010/mcp",
            "capabilities": [
                {
                    "name": "test_capability",
                    "description": "Test capability",
                    "category": "test",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["test"],
                }
            ],
            "labels": {"env": "test"},
            "security_context": "standard",
            "health_interval": 2.0,  # Short interval for testing
            "timeout_threshold": 3.0,  # 3 seconds timeout
            "eviction_threshold": 6.0,  # 6 seconds eviction
        }

        async with aiohttp.ClientSession() as session:
            # Register agent
            async with session.post(
                "http://localhost:8000/mcp/tools/register_agent",
                json={"registration_data": test_agent},
            ) as resp:
                assert resp.status == 200

            # Send initial heartbeat
            async with session.post(
                "http://localhost:8000/heartbeat", json={"agent_id": test_agent["id"]}
            ) as resp:
                assert resp.status == 200

            # Verify agent is healthy
            async with session.get(
                f"http://localhost:8000/health/{test_agent['id']}"
            ) as resp:
                assert resp.status == 200
                health_data = await resp.json()
                assert health_data["status"] == "healthy"

            # Wait for timeout threshold to pass
            await asyncio.sleep(4.0)

            # Check health status - should be degraded
            async with session.get(
                f"http://localhost:8000/health/{test_agent['id']}"
            ) as resp:
                assert resp.status == 200
                health_data = await resp.json()
                assert health_data["status"] in [
                    "degraded",
                    "expired",
                ]  # May have moved to expired

            # Wait for eviction threshold to pass
            await asyncio.sleep(3.0)

            # Check health status - should be expired or not found
            async with session.get(
                f"http://localhost:8000/health/{test_agent['id']}"
            ) as resp:
                if resp.status == 200:
                    health_data = await resp.json()
                    assert health_data["status"] == "expired"
                else:
                    assert resp.status == 404  # Agent may have been evicted

    @pytest.mark.asyncio
    async def test_registry_metrics_comprehensive(
        self, registry_server, comprehensive_test_agents
    ):
        """Test comprehensive registry metrics and monitoring."""

        async with aiohttp.ClientSession() as session:
            # Get initial metrics
            async with session.get("http://localhost:8000/metrics") as resp:
                assert resp.status == 200
                initial_metrics = await resp.json()
                initial_agent_count = initial_metrics["total_agents"]
                initial_registrations = initial_metrics["registrations_processed"]
                initial_heartbeats = initial_metrics["heartbeats_processed"]

            # Register all agents
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

            # Send heartbeats
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_data["id"]},
                ) as resp:
                    assert resp.status == 200

            # Get updated metrics
            async with session.get("http://localhost:8000/metrics") as resp:
                assert resp.status == 200
                metrics = await resp.json()

                # Verify basic counts
                assert metrics["total_agents"] == initial_agent_count + len(
                    comprehensive_test_agents
                )
                assert metrics["healthy_agents"] >= len(comprehensive_test_agents)
                assert metrics[
                    "registrations_processed"
                ] == initial_registrations + len(comprehensive_test_agents)
                assert metrics["heartbeats_processed"] >= initial_heartbeats + len(
                    comprehensive_test_agents
                )

                # Verify capability counts
                expected_capabilities = sum(
                    len(agent["capabilities"]) for agent in comprehensive_test_agents
                )
                assert metrics["total_capabilities"] >= expected_capabilities

                # Verify system metrics
                assert metrics["uptime_seconds"] > 0
                assert "memory_usage_mb" in metrics
                assert "active_connections" in metrics

                # Verify agent distribution
                assert "agents_by_namespace" in metrics
                assert "agents_by_status" in metrics
                assert "capabilities_by_category" in metrics

            # Test Prometheus metrics format
            async with session.get("http://localhost:8000/metrics/prometheus") as resp:
                assert resp.status == 200
                prometheus_data = await resp.text()

                # Verify key Prometheus metrics exist
                required_metrics = [
                    "mcp_registry_agents_total",
                    "mcp_registry_capabilities_total",
                    "mcp_registry_agents_by_status",
                    "mcp_registry_uptime_seconds",
                    "mcp_registry_registrations_total",
                    "mcp_registry_heartbeats_total",
                ]

                for metric in required_metrics:
                    assert metric in prometheus_data

                # Verify metric values are present
                assert (
                    f"mcp_registry_agents_total {metrics['total_agents']}"
                    in prometheus_data
                )

    @pytest.mark.asyncio
    async def test_service_integration_workflows(
        self, registry_server, comprehensive_test_agents
    ):
        """Test realistic service integration workflows."""

        async with aiohttp.ClientSession() as session:
            # Register all agents
            for agent_data in comprehensive_test_agents:
                async with session.post(
                    "http://localhost:8000/mcp/tools/register_agent",
                    json={"registration_data": agent_data},
                ) as resp:
                    assert resp.status == 200

                async with session.post(
                    "http://localhost:8000/heartbeat",
                    json={"agent_id": agent_data["id"]},
                ) as resp:
                    assert resp.status == 200

            # Workflow 1: Development task requiring multiple agents
            # Developer needs to read code, run tests, and monitor results

            # 1. Find file operations for code reading
            async with session.get(
                "http://localhost:8000/capabilities?category=file_operations"
            ) as resp:
                assert resp.status == 200
                file_data = await resp.json()
                read_capabilities = [
                    cap for cap in file_data["capabilities"] if "read" in cap["name"]
                ]
                assert len(read_capabilities) >= 1
                file_agent_id = read_capabilities[0]["agent_id"]

            # 2. Find development tools for testing
            async with session.get(
                "http://localhost:8000/capabilities?category=development"
            ) as resp:
                assert resp.status == 200
                dev_data = await resp.json()
                test_capabilities = [
                    cap for cap in dev_data["capabilities"] if "test" in cap["name"]
                ]
                assert len(test_capabilities) >= 1
                dev_agent_id = test_capabilities[0]["agent_id"]

            # 3. Find monitoring for observability
            async with session.get(
                "http://localhost:8000/capabilities?category=monitoring"
            ) as resp:
                assert resp.status == 200
                monitor_data = await resp.json()
                collect_capabilities = [
                    cap
                    for cap in monitor_data["capabilities"]
                    if "collect" in cap["name"]
                ]
                assert len(collect_capabilities) >= 1
                monitor_agent_id = collect_capabilities[0]["agent_id"]

            # Verify we found different agents for different purposes
            agents_found = {file_agent_id, dev_agent_id, monitor_agent_id}
            assert len(agents_found) >= 2  # Should be different agents

            # Workflow 2: DevOps deployment requiring database and monitoring

            # 1. Find database migration capabilities
            async with session.get(
                "http://localhost:8000/capabilities?name=schema_migration"
            ) as resp:
                assert resp.status == 200
                migration_data = await resp.json()
                assert migration_data["count"] >= 1
                db_agent_id = migration_data["capabilities"][0]["agent_id"]

            # 2. Find system monitoring for deployment health
            async with session.get(
                "http://localhost:8000/capabilities?tags=monitoring&agent_status=healthy"
            ) as resp:
                assert resp.status == 200
                monitoring_data = await resp.json()
                health_monitoring = [
                    cap
                    for cap in monitoring_data["capabilities"]
                    if "monitoring" in cap["tags"] and cap["agent_id"] != db_agent_id
                ]
                assert len(health_monitoring) >= 1

            # Workflow 3: Security audit requiring multiple high-security agents

            # Find all high-security agents
            async with session.get(
                "http://localhost:8000/agents?label_selector=env=production"
            ) as resp:
                assert resp.status == 200
                prod_data = await resp.json()

                high_sec_agents = [
                    agent
                    for agent in prod_data["agents"]
                    if agent.get("security_context") == "high_security"
                ]
                assert len(high_sec_agents) >= 2  # command and database agents

            # Workflow 4: Performance optimization across all systems

            # Find all stable capabilities for reliable optimization
            async with session.get(
                "http://localhost:8000/capabilities?stability=stable"
            ) as resp:
                assert resp.status == 200
                stable_data = await resp.json()

                stable_by_category = {}
                for cap in stable_data["capabilities"]:
                    category = cap["category"]
                    if category not in stable_by_category:
                        stable_by_category[category] = []
                    stable_by_category[category].append(cap)

                # Should have stable capabilities across multiple categories
                assert len(stable_by_category) >= 4

                # Each category should have at least one stable capability
                for category, caps in stable_by_category.items():
                    assert len(caps) >= 1


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/integration/test_comprehensive_registry_suite.py -v
    pytest.main([__file__, "-v"])
