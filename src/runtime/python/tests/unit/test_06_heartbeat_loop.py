"""
Unit tests for HeartbeatLoopStep pipeline step.

Tests the simplified heartbeat loop configuration logic after refactoring
to remove duplicated configuration handling and use the config resolver.
"""

from typing import Any, Dict
from unittest.mock import ANY, MagicMock, call, patch

import pytest
# Import the classes under test
from _mcp_mesh.pipeline.mcp_startup.heartbeat_loop import HeartbeatLoopStep
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestHeartbeatLoopStep:
    """Test the HeartbeatLoopStep class initialization and basic properties."""

    def test_initialization(self):
        """Test HeartbeatLoopStep initialization."""
        step = HeartbeatLoopStep()

        assert step.name == "heartbeat-loop"
        assert step.required is False  # Optional - agent can run standalone
        assert (
            step.description
            == "Start background heartbeat loop for registry communication"
        )

    def test_inheritance(self):
        """Test HeartbeatLoopStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = HeartbeatLoopStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = HeartbeatLoopStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)

    def test_get_standalone_mode_method_exists(self):
        """Test _get_standalone_mode method exists and is callable."""
        step = HeartbeatLoopStep()
        assert hasattr(step, "_get_standalone_mode")
        assert callable(step._get_standalone_mode)


class TestHeartbeatLoopStepSuccess:
    """Test successful heartbeat loop configuration scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatLoopStep instance."""
        return HeartbeatLoopStep()

    @pytest.fixture
    def mock_context_with_health_interval(self):
        """Mock context with agent_config containing health_interval."""
        return {
            "agent_config": {
                "health_interval": 45,
                "name": "test-agent",
                "version": "1.0.0",
            },
            "agent_id": "test-agent-abc12345",
        }

    @pytest.fixture
    def mock_context_without_health_interval(self):
        """Mock context with agent_config missing health_interval."""
        return {
            "agent_config": {"name": "test-agent", "version": "1.0.0"},
            "agent_id": "test-agent-abc12345",
        }

    @pytest.fixture
    def mock_context_minimal(self):
        """Mock context with minimal data."""
        return {"agent_config": {}, "agent_id": "test-agent-abc12345"}

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_with_health_interval(
        self, mock_get_config_value, step, mock_context_with_health_interval
    ):
        """Test execute with health_interval in agent_config."""
        # Mock get_config_value to return the health_interval from agent_config (45)
        # The first call gets the health interval, second call gets standalone mode
        mock_get_config_value.side_effect = [45, False]

        result = await step.execute(mock_context_with_health_interval)

        assert result.status == PipelineStatus.SUCCESS
        assert "Heartbeat config prepared (interval: 45s)" in result.message

        # Check heartbeat_config is added to context
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["agent_id"] == "test-agent-abc12345"
        assert heartbeat_config["interval"] == 45
        assert heartbeat_config["standalone_mode"] is False
        assert heartbeat_config["registry_wrapper"] is None

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_without_health_interval_defaults_to_30(
        self, mock_get_config_value, step, mock_context_without_health_interval
    ):
        """Test execute without health_interval defaults to 5 seconds."""
        # Mock get_config_value to return default health interval (5) and standalone mode (False)
        mock_get_config_value.side_effect = [5, False]

        result = await step.execute(mock_context_without_health_interval)

        assert result.status == PipelineStatus.SUCCESS
        assert "Heartbeat config prepared (interval: 5s)" in result.message

        # Check heartbeat_config uses default interval
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["interval"] == 5

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_minimal_context(
        self, mock_get_config_value, step, mock_context_minimal
    ):
        """Test execute with minimal context data."""
        # Mock get_config_value to return default health interval (5) and standalone mode (False)
        mock_get_config_value.side_effect = [5, False]

        result = await step.execute(mock_context_minimal)

        assert result.status == PipelineStatus.SUCCESS
        assert "Heartbeat config prepared (interval: 5s)" in result.message

        # Check heartbeat_config is properly configured
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["agent_id"] == "test-agent-abc12345"
        assert heartbeat_config["interval"] == 5


class TestHeartbeatLoopStepStandalone:
    """Test standalone mode scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatLoopStep instance."""
        return HeartbeatLoopStep()

    @pytest.fixture
    def mock_context(self):
        """Mock context for standalone tests."""
        return {
            "agent_config": {"health_interval": 60, "name": "test-agent"},
            "agent_id": "test-agent-abc12345",
        }

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_standalone_mode(
        self, mock_get_config_value, step, mock_context
    ):
        """Test execute in standalone mode."""
        # Mock standalone mode as True
        mock_get_config_value.return_value = True

        result = await step.execute(mock_context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message
            == "Heartbeat disabled for standalone mode (no registry communication)"
        )

        # Check heartbeat_config is still created but with standalone_mode=True
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["standalone_mode"] is True
        assert heartbeat_config["registry_wrapper"] is None

    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    def test_get_standalone_mode_uses_config_resolver(
        self, mock_get_config_value, step
    ):
        """Test _get_standalone_mode uses config resolver correctly."""
        # Test with True
        mock_get_config_value.return_value = True
        result = step._get_standalone_mode()
        assert result is True

        # Test with False
        mock_get_config_value.return_value = False
        result = step._get_standalone_mode()
        assert result is False

        # Verify config resolver was called with correct parameters
        expected_calls = [
            call("MCP_MESH_STANDALONE", default=False, rule=ANY),
            call("MCP_MESH_STANDALONE", default=False, rule=ANY),
        ]

        # Check that get_config_value was called with MCP_MESH_STANDALONE
        assert mock_get_config_value.call_count == 2
        calls = mock_get_config_value.call_args_list
        assert calls[0][0][0] == "MCP_MESH_STANDALONE"
        assert calls[1][0][0] == "MCP_MESH_STANDALONE"


class TestHeartbeatLoopStepErrors:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatLoopStep instance."""
        return HeartbeatLoopStep()

    @pytest.fixture
    def mock_context_missing_agent_config(self):
        """Mock context missing agent_config."""
        return {"agent_id": "test-agent-abc12345"}

    @pytest.fixture
    def mock_context_missing_agent_id(self):
        """Mock context missing agent_id."""
        return {"agent_config": {"health_interval": 30}}

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_missing_agent_config(
        self, mock_get_config_value, step, mock_context_missing_agent_config
    ):
        """Test execute with missing agent_config."""
        # Mock get_config_value to return default health interval (5) and standalone mode (False)
        mock_get_config_value.side_effect = [5, False]

        result = await step.execute(mock_context_missing_agent_config)

        # Should succeed with default empty config
        assert result.status == PipelineStatus.SUCCESS
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["interval"] == 5  # Default value

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_missing_agent_id(
        self, mock_get_config_value, step, mock_context_missing_agent_id
    ):
        """Test execute with missing agent_id."""
        # Mock standalone mode as False
        mock_get_config_value.return_value = False

        result = await step.execute(mock_context_missing_agent_id)

        # Should succeed with default agent_id
        assert result.status == PipelineStatus.SUCCESS
        heartbeat_config = result.context.get("heartbeat_config")
        assert heartbeat_config is not None
        assert heartbeat_config["agent_id"] == "unknown-agent"  # Default value

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_startup.heartbeat_loop.get_config_value")
    async def test_execute_with_exception(self, mock_get_config_value, step):
        """Test execute with exception during processing."""
        # Mock get_config_value to raise an exception
        mock_get_config_value.side_effect = Exception("Config resolver error")

        context = {"agent_config": {}, "agent_id": "test-agent"}
        result = await step.execute(context)

        # Should handle exception gracefully
        assert result.status == PipelineStatus.FAILED
        assert "Failed to start heartbeat loop" in result.message
        assert "Config resolver error" in result.message
        assert len(result.errors) > 0
