"""Unit tests for CLI status module."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.status import (
    ServiceStatus,
    StatusAggregator,
    format_status_output,
    format_uptime,
    get_health_color,
    get_status_color,
)


class TestServiceStatus:
    """Test ServiceStatus data class."""

    def test_service_status_creation(self):
        """Test creating ServiceStatus instances."""
        status = ServiceStatus(
            name="test_service",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"port": 8080},
        )

        assert status.name == "test_service"
        assert status.status == "running"
        assert status.health == "healthy"
        assert status.uptime == 300.0
        assert status.metadata == {"port": 8080}

    def test_service_status_to_dict(self):
        """Test ServiceStatus to_dict method."""
        status = ServiceStatus(
            name="test_service",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"port": 8080},
        )

        status_dict = status.to_dict()

        assert status_dict["name"] == "test_service"
        assert status_dict["status"] == "running"
        assert status_dict["health"] == "healthy"
        assert status_dict["uptime"] == 300.0
        assert status_dict["metadata"] == {"port": 8080}

    def test_service_status_from_dict(self):
        """Test ServiceStatus from_dict method."""
        data = {
            "name": "test_service",
            "status": "running",
            "health": "healthy",
            "uptime": 300.0,
            "metadata": {"port": 8080},
        }

        status = ServiceStatus.from_dict(data)

        assert status.name == "test_service"
        assert status.status == "running"
        assert status.health == "healthy"
        assert status.uptime == 300.0
        assert status.metadata == {"port": 8080}

    def test_service_status_defaults(self):
        """Test ServiceStatus with default values."""
        status = ServiceStatus(name="test_service")

        assert status.name == "test_service"
        assert status.status == "unknown"
        assert status.health == "unknown"
        assert status.uptime == 0.0
        assert status.metadata == {}


class TestStatusAggregator:
    """Test StatusAggregator functionality."""

    def test_status_aggregator_creation(self):
        """Test creating StatusAggregator."""
        aggregator = StatusAggregator()
        assert aggregator._registry_manager is None
        assert aggregator._agent_manager is None

    def test_set_managers(self):
        """Test setting managers in aggregator."""
        aggregator = StatusAggregator()

        mock_registry = MagicMock()
        mock_agent = MagicMock()

        aggregator.set_registry_manager(mock_registry)
        aggregator.set_agent_manager(mock_agent)

        assert aggregator._registry_manager == mock_registry
        assert aggregator._agent_manager == mock_agent

    @pytest.mark.asyncio
    async def test_get_registry_status_success(self):
        """Test getting registry status successfully."""
        aggregator = StatusAggregator()

        mock_registry = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.get_uptime.return_value = timedelta(seconds=300)
        mock_process.metadata = {"host": "localhost", "port": 8080}

        mock_registry.process_tracker.get_process.return_value = mock_process
        mock_registry.process_tracker._is_process_running.return_value = True

        aggregator.set_registry_manager(mock_registry)

        status = await aggregator.get_registry_status()

        assert status.name == "registry"
        assert status.status == "running"
        assert status.health == "healthy"
        assert status.uptime == 300.0
        assert status.metadata["pid"] == 12345
        assert status.metadata["host"] == "localhost"
        assert status.metadata["port"] == 8080

    @pytest.mark.asyncio
    async def test_get_registry_status_not_running(self):
        """Test getting registry status when not running."""
        aggregator = StatusAggregator()

        mock_registry = MagicMock()
        mock_registry.process_tracker.get_process.return_value = None

        aggregator.set_registry_manager(mock_registry)

        status = await aggregator.get_registry_status()

        assert status.name == "registry"
        assert status.status == "stopped"
        assert status.health == "unhealthy"
        assert status.uptime == 0.0

    @pytest.mark.asyncio
    async def test_get_registry_status_exception(self):
        """Test getting registry status with exception."""
        aggregator = StatusAggregator()

        mock_registry = MagicMock()
        mock_registry.process_tracker.get_process.side_effect = Exception(
            "Process error"
        )

        aggregator.set_registry_manager(mock_registry)

        status = await aggregator.get_registry_status()

        assert status.name == "registry"
        assert status.status == "error"
        assert status.health == "unhealthy"
        assert "error" in status.metadata

    @pytest.mark.asyncio
    async def test_get_agents_status_success(self):
        """Test getting agents status successfully."""
        aggregator = StatusAggregator()

        mock_agent = MagicMock()

        # Mock agent processes
        mock_process1 = MagicMock()
        mock_process1.pid = 12346
        mock_process1.get_uptime.return_value = timedelta(seconds=200)
        mock_process1.metadata = {"agent_file": "agent1.py"}

        mock_process2 = MagicMock()
        mock_process2.pid = 12347
        mock_process2.get_uptime.return_value = timedelta(seconds=150)
        mock_process2.metadata = {"agent_file": "agent2.py"}

        mock_agent.process_tracker.get_all_processes.return_value = {
            "agent1": mock_process1,
            "agent2": mock_process2,
        }
        mock_agent.process_tracker._is_process_running.return_value = True

        aggregator.set_agent_manager(mock_agent)

        statuses = await aggregator.get_agents_status()

        assert len(statuses) == 2

        agent1_status = next(s for s in statuses if s.name == "agent1")
        assert agent1_status.status == "running"
        assert agent1_status.health == "healthy"
        assert agent1_status.uptime == 200.0
        assert agent1_status.metadata["pid"] == 12346

    @pytest.mark.asyncio
    async def test_get_agents_status_mixed_health(self):
        """Test getting agents status with mixed health."""
        aggregator = StatusAggregator()

        mock_agent = MagicMock()

        # Mock processes with different states
        mock_process1 = MagicMock()
        mock_process1.pid = 12346
        mock_process1.get_uptime.return_value = timedelta(seconds=200)
        mock_process1.metadata = {"agent_file": "agent1.py"}

        mock_process2 = MagicMock()
        mock_process2.pid = 12347
        mock_process2.get_uptime.return_value = timedelta(seconds=150)
        mock_process2.metadata = {"agent_file": "agent2.py"}

        mock_agent.process_tracker.get_all_processes.return_value = {
            "agent1": mock_process1,
            "agent2": mock_process2,
        }

        # agent1 running, agent2 not running
        def mock_is_running(process):
            return process.pid == 12346

        mock_agent.process_tracker._is_process_running.side_effect = mock_is_running

        aggregator.set_agent_manager(mock_agent)

        statuses = await aggregator.get_agents_status()

        agent1_status = next(s for s in statuses if s.name == "agent1")
        agent2_status = next(s for s in statuses if s.name == "agent2")

        assert agent1_status.status == "running"
        assert agent1_status.health == "healthy"

        assert agent2_status.status == "stopped"
        assert agent2_status.health == "unhealthy"

    @pytest.mark.asyncio
    async def test_get_overall_status_all_healthy(self):
        """Test getting overall status when all services are healthy."""
        aggregator = StatusAggregator()

        # Mock registry status
        registry_status = ServiceStatus(
            name="registry", status="running", health="healthy", uptime=300.0
        )

        # Mock agent statuses
        agent_statuses = [
            ServiceStatus(
                name="agent1", status="running", health="healthy", uptime=200.0
            ),
            ServiceStatus(
                name="agent2", status="running", health="healthy", uptime=150.0
            ),
        ]

        with (
            patch.object(
                aggregator, "get_registry_status", return_value=registry_status
            ),
            patch.object(aggregator, "get_agents_status", return_value=agent_statuses),
        ):

            overall_status = await aggregator.get_overall_status()

            assert overall_status["status"] == "healthy"
            assert overall_status["services_count"] == 3
            assert overall_status["healthy_count"] == 3
            assert overall_status["unhealthy_count"] == 0

    @pytest.mark.asyncio
    async def test_get_overall_status_with_unhealthy(self):
        """Test getting overall status with some unhealthy services."""
        aggregator = StatusAggregator()

        # Mock registry status (healthy)
        registry_status = ServiceStatus(
            name="registry", status="running", health="healthy", uptime=300.0
        )

        # Mock agent statuses (one unhealthy)
        agent_statuses = [
            ServiceStatus(
                name="agent1", status="running", health="healthy", uptime=200.0
            ),
            ServiceStatus(
                name="agent2", status="stopped", health="unhealthy", uptime=0.0
            ),
        ]

        with (
            patch.object(
                aggregator, "get_registry_status", return_value=registry_status
            ),
            patch.object(aggregator, "get_agents_status", return_value=agent_statuses),
        ):

            overall_status = await aggregator.get_overall_status()

            assert overall_status["status"] == "degraded"
            assert overall_status["services_count"] == 3
            assert overall_status["healthy_count"] == 2
            assert overall_status["unhealthy_count"] == 1


class TestStatusFormatting:
    """Test status formatting functions."""

    def test_format_uptime_seconds(self):
        """Test formatting uptime in seconds."""
        assert format_uptime(30) == "30.0s"
        assert format_uptime(59.5) == "59.5s"

    def test_format_uptime_minutes(self):
        """Test formatting uptime in minutes."""
        assert format_uptime(60) == "1.0m"
        assert format_uptime(90) == "1.5m"
        assert format_uptime(3599) == "59.98m"

    def test_format_uptime_hours(self):
        """Test formatting uptime in hours."""
        assert format_uptime(3600) == "1.0h"
        assert format_uptime(7200) == "2.0h"
        assert format_uptime(86399) == "23.99h"

    def test_format_uptime_days(self):
        """Test formatting uptime in days."""
        assert format_uptime(86400) == "1.0d"
        assert format_uptime(172800) == "2.0d"
        assert format_uptime(604800) == "7.0d"

    def test_get_status_color(self):
        """Test getting status colors."""
        assert get_status_color("running") == "green"
        assert get_status_color("stopped") == "red"
        assert get_status_color("starting") == "yellow"
        assert get_status_color("error") == "red"
        assert get_status_color("unknown") == "gray"

    def test_get_health_color(self):
        """Test getting health colors."""
        assert get_health_color("healthy") == "green"
        assert get_health_color("unhealthy") == "red"
        assert get_health_color("degraded") == "yellow"
        assert get_health_color("unknown") == "gray"

    def test_format_status_output_basic(self):
        """Test basic status output formatting."""
        registry_status = ServiceStatus(
            name="registry",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"pid": 12345, "port": 8080},
        )

        agent_statuses = [
            ServiceStatus(
                name="agent1",
                status="running",
                health="healthy",
                uptime=200.0,
                metadata={"pid": 12346},
            )
        ]

        overall_status = {
            "status": "healthy",
            "services_count": 2,
            "healthy_count": 2,
            "unhealthy_count": 0,
        }

        output = format_status_output(
            registry_status=registry_status,
            agent_statuses=agent_statuses,
            overall_status=overall_status,
            verbose=False,
            json_output=False,
        )

        assert "MCP Mesh Status" in output
        assert "Overall: healthy" in output
        assert "Registry: running" in output
        assert "agent1: running" in output

    def test_format_status_output_verbose(self):
        """Test verbose status output formatting."""
        registry_status = ServiceStatus(
            name="registry",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"pid": 12345, "port": 8080, "host": "localhost"},
        )

        agent_statuses = [
            ServiceStatus(
                name="agent1",
                status="running",
                health="healthy",
                uptime=200.0,
                metadata={"pid": 12346, "agent_file": "agent1.py"},
            )
        ]

        overall_status = {
            "status": "healthy",
            "services_count": 2,
            "healthy_count": 2,
            "unhealthy_count": 0,
        }

        output = format_status_output(
            registry_status=registry_status,
            agent_statuses=agent_statuses,
            overall_status=overall_status,
            verbose=True,
            json_output=False,
        )

        assert "PID: 12345" in output
        assert "Port: 8080" in output
        assert "Host: localhost" in output
        assert "File: agent1.py" in output

    def test_format_status_output_json(self):
        """Test JSON status output formatting."""
        registry_status = ServiceStatus(
            name="registry",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"pid": 12345},
        )

        agent_statuses = [
            ServiceStatus(
                name="agent1",
                status="running",
                health="healthy",
                uptime=200.0,
                metadata={"pid": 12346},
            )
        ]

        overall_status = {
            "status": "healthy",
            "services_count": 2,
            "healthy_count": 2,
            "unhealthy_count": 0,
        }

        output = format_status_output(
            registry_status=registry_status,
            agent_statuses=agent_statuses,
            overall_status=overall_status,
            verbose=False,
            json_output=True,
        )

        # Should be valid JSON
        data = json.loads(output)

        assert data["overall"]["status"] == "healthy"
        assert data["registry"]["name"] == "registry"
        assert data["registry"]["status"] == "running"
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "agent1"

    def test_format_status_output_empty_agents(self):
        """Test status output with no agents."""
        registry_status = ServiceStatus(
            name="registry", status="running", health="healthy", uptime=300.0
        )

        overall_status = {
            "status": "healthy",
            "services_count": 1,
            "healthy_count": 1,
            "unhealthy_count": 0,
        }

        output = format_status_output(
            registry_status=registry_status,
            agent_statuses=[],
            overall_status=overall_status,
            verbose=False,
            json_output=False,
        )

        assert "No agents running" in output or "Registry: running" in output


class TestStatusIntegration:
    """Test status module integration scenarios."""

    @pytest.mark.asyncio
    async def test_complete_status_collection_workflow(self):
        """Test complete status collection workflow."""
        aggregator = StatusAggregator()

        # Mock managers
        mock_registry = MagicMock()
        mock_agent = MagicMock()

        # Mock registry process
        mock_registry_process = MagicMock()
        mock_registry_process.pid = 12345
        mock_registry_process.get_uptime.return_value = timedelta(seconds=300)
        mock_registry_process.metadata = {"host": "localhost", "port": 8080}

        mock_registry.process_tracker.get_process.return_value = mock_registry_process
        mock_registry.process_tracker._is_process_running.return_value = True

        # Mock agent processes
        mock_agent_process = MagicMock()
        mock_agent_process.pid = 12346
        mock_agent_process.get_uptime.return_value = timedelta(seconds=200)
        mock_agent_process.metadata = {"agent_file": "test_agent.py"}

        mock_agent.process_tracker.get_all_processes.return_value = {
            "test_agent": mock_agent_process
        }
        mock_agent.process_tracker._is_process_running.return_value = True

        aggregator.set_registry_manager(mock_registry)
        aggregator.set_agent_manager(mock_agent)

        # Collect all status information
        registry_status = await aggregator.get_registry_status()
        agent_statuses = await aggregator.get_agents_status()
        overall_status = await aggregator.get_overall_status()

        # Verify results
        assert registry_status.status == "running"
        assert len(agent_statuses) == 1
        assert agent_statuses[0].name == "test_agent"
        assert overall_status["status"] == "healthy"
        assert overall_status["services_count"] == 2

    def test_status_output_formatting_workflow(self):
        """Test complete status output formatting workflow."""
        # Create sample status data
        registry_status = ServiceStatus(
            name="registry",
            status="running",
            health="healthy",
            uptime=300.0,
            metadata={"pid": 12345, "port": 8080},
        )

        agent_statuses = [
            ServiceStatus(
                name="hello_world",
                status="running",
                health="healthy",
                uptime=200.0,
                metadata={"pid": 12346, "agent_file": "hello_world.py"},
            ),
            ServiceStatus(
                name="system_agent",
                status="running",
                health="healthy",
                uptime=150.0,
                metadata={"pid": 12347, "agent_file": "system_agent.py"},
            ),
        ]

        overall_status = {
            "status": "healthy",
            "services_count": 3,
            "healthy_count": 3,
            "unhealthy_count": 0,
        }

        # Test different output formats
        basic_output = format_status_output(
            registry_status,
            agent_statuses,
            overall_status,
            verbose=False,
            json_output=False,
        )

        verbose_output = format_status_output(
            registry_status,
            agent_statuses,
            overall_status,
            verbose=True,
            json_output=False,
        )

        json_output = format_status_output(
            registry_status,
            agent_statuses,
            overall_status,
            verbose=False,
            json_output=True,
        )

        # Verify outputs
        assert "Overall: healthy" in basic_output
        assert "hello_world: running" in basic_output
        assert "system_agent: running" in basic_output

        assert "PID: 12346" in verbose_output
        assert "hello_world.py" in verbose_output

        json_data = json.loads(json_output)
        assert json_data["overall"]["status"] == "healthy"
        assert len(json_data["agents"]) == 2


if __name__ == "__main__":
    pytest.main([__file__])
