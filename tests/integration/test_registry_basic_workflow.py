"""
Basic Registry Workflow Integration Test

Tests the core registry functionality:
- Agent registration via MCP
- Heartbeat updates via REST
- Service discovery via REST
- Pull-based behavior verification
"""

import asyncio

import aiohttp
import pytest
from mcp_mesh_runtime.server.models import AgentCapability, AgentRegistration
from mcp_mesh_runtime.server.registry_server import RegistryServer


class TestRegistryBasicWorkflow:
    """Test basic registry operations via both MCP and REST APIs."""

    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        """Setup registry server for each test."""
        self.server = RegistryServer(host="localhost", port=8001)

        # Start server in background
        self.server_task = asyncio.create_task(self.server.start())

        # Wait for server to be ready
        await asyncio.sleep(2)

        yield

        # Cleanup
        await self.server.stop()
        self.server_task.cancel()
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass

    async def test_complete_registry_workflow(self):
        """Test complete workflow: register agent -> heartbeat -> discovery."""

        # Step 1: Register an agent via MCP protocol
        agent_data = AgentRegistration(
            name="test-file-agent",
            namespace="test",
            endpoint="http://localhost:9001",
            capabilities=[
                AgentCapability(
                    name="file_read",
                    description="Read files from filesystem",
                    version="1.0.0",
                    category="file_operations",
                    tags=["filesystem", "read"],
                ),
                AgentCapability(
                    name="file_write",
                    description="Write files to filesystem",
                    version="1.0.0",
                    category="file_operations",
                    tags=["filesystem", "write"],
                ),
            ],
            agent_type="file-agent",
            labels={"environment": "test", "role": "file-handler"},
        )

        # Register via MCP (simulating the agent registration)
        async with aiohttp.ClientSession() as session:
            # Use REST endpoint to register (simulating MCP registration)
            register_url = "http://localhost:8001/agents"
            async with session.post(
                register_url, json=agent_data.model_dump()
            ) as response:
                # Note: This would normally be done via MCP protocol
                # but we're using REST for simplicity in this integration test
                pass

        # Wait a moment for registration to complete
        await asyncio.sleep(1)

        # Step 2: Send heartbeat via REST API (pull-based behavior)
        heartbeat_url = "http://localhost:8001/heartbeat"
        heartbeat_data = {
            "agent_id": agent_data.id,
            "status": "healthy",
            "metadata": {"load": "low", "memory_usage": "50%"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(heartbeat_url, json=heartbeat_data) as response:
                assert response.status == 200
                result = await response.json()
                assert result["status"] == "success"
                assert "timestamp" in result

        # Step 3: Discover agents via REST API (pull-based)
        discovery_url = "http://localhost:8001/agents"

        async with aiohttp.ClientSession() as session:
            # Test basic discovery
            async with session.get(discovery_url) as response:
                assert response.status == 200
                result = await response.json()

                assert "agents" in result
                assert "count" in result
                assert "timestamp" in result
                assert result["count"] >= 1

                # Find our registered agent
                found_agent = None
                for agent in result["agents"]:
                    if agent["name"] == "test-file-agent":
                        found_agent = agent
                        break

                assert found_agent is not None
                assert found_agent["namespace"] == "test"
                assert found_agent["status"] == "healthy"
                assert len(found_agent["capabilities"]) == 2

        # Step 4: Test capability discovery (pull-based)
        capabilities_url = "http://localhost:8001/capabilities"

        async with aiohttp.ClientSession() as session:
            # Test capability search by category
            params = {"category": "file_operations"}
            async with session.get(capabilities_url, params=params) as response:
                assert response.status == 200
                result = await response.json()

                assert "capabilities" in result
                assert result["count"] >= 2

                # Verify our capabilities are present
                cap_names = [cap["name"] for cap in result["capabilities"]]
                assert "file_read" in cap_names
                assert "file_write" in cap_names

        # Step 5: Test filtered discovery (pull-based querying)
        async with aiohttp.ClientSession() as session:
            # Test label selector
            params = {"label_selector": "environment=test,role=file-handler"}
            async with session.get(discovery_url, params=params) as response:
                assert response.status == 200
                result = await response.json()
                assert result["count"] >= 1

            # Test capability filtering
            params = {"capability": "file_read"}
            async with session.get(discovery_url, params=params) as response:
                assert response.status == 200
                result = await response.json()
                assert result["count"] >= 1

            # Test namespace filtering
            params = {"namespace": "test"}
            async with session.get(discovery_url, params=params) as response:
                assert response.status == 200
                result = await response.json()
                assert result["count"] >= 1

    async def test_pull_based_behavior_verification(self):
        """Verify that the registry follows pull-based patterns."""

        # Register a test agent
        agent_data = AgentRegistration(
            name="pull-test-agent",
            namespace="default",
            endpoint="http://localhost:9002",
            capabilities=[
                AgentCapability(name="test_capability", description="Test capability")
            ],
        )

        async with aiohttp.ClientSession() as session:
            # Step 1: Verify agents must actively send heartbeats (pull-based)
            register_url = "http://localhost:8001/agents"

            # Register agent
            await session.post(register_url, json=agent_data.model_dump())
            await asyncio.sleep(1)

            # Step 2: Verify initial registration state
            discovery_url = "http://localhost:8001/agents"
            async with session.get(discovery_url) as response:
                result = await response.json()
                agent = next(
                    (a for a in result["agents"] if a["name"] == "pull-test-agent"),
                    None,
                )
                assert agent is not None
                # Agent should start in pending/healthy state
                assert agent["status"] in ["pending", "healthy"]

            # Step 3: Send heartbeat to maintain health (pull-based client responsibility)
            heartbeat_url = "http://localhost:8001/heartbeat"
            heartbeat_data = {"agent_id": agent_data.id, "status": "healthy"}

            async with session.post(heartbeat_url, json=heartbeat_data) as response:
                assert response.status == 200

            # Step 4: Verify health endpoint (pull-based monitoring)
            health_url = f"http://localhost:8001/health/{agent_data.id}"
            async with session.get(health_url) as response:
                assert response.status == 200
                health_status = await response.json()
                assert health_status["agent_id"] == agent_data.id
                assert health_status["status"] == "healthy"
                assert "last_heartbeat" in health_status

            # Step 5: Verify metrics endpoint (pull-based observability)
            metrics_url = "http://localhost:8001/metrics"
            async with session.get(metrics_url) as response:
                assert response.status == 200
                metrics = await response.json()
                assert "total_agents" in metrics
                assert "healthy_agents" in metrics
                assert metrics["total_agents"] >= 1

    async def test_registry_health_check(self):
        """Test registry service health check."""

        async with aiohttp.ClientSession() as session:
            # Test main health endpoint
            health_url = "http://localhost:8001/health"
            async with session.get(health_url) as response:
                assert response.status == 200
                result = await response.json()
                assert result["status"] == "healthy"
                assert result["service"] == "mcp-mesh-registry"

            # Test root endpoint with service info
            root_url = "http://localhost:8001/"
            async with session.get(root_url) as response:
                assert response.status == 200
                result = await response.json()
                assert result["service"] == "MCP Mesh Registry Service"
                assert "endpoints" in result
                assert "features" in result
                assert (
                    result["architecture"]
                    == "Kubernetes API Server pattern (PASSIVE pull-based)"
                )
