"""
Unit tests for FastHeartbeatStep pipeline step.

Tests the fast heartbeat step that performs lightweight HEAD requests
and sets semantic status in context for pipeline decision making.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from _mcp_mesh.pipeline.heartbeat.fast_heartbeat_check import FastHeartbeatStep
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus
from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus


class TestFastHeartbeatStep:
    """Test FastHeartbeatStep implementation."""

    @pytest.fixture
    def fast_heartbeat_step(self):
        """Create FastHeartbeatStep instance for testing."""
        return FastHeartbeatStep()

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Create mock registry wrapper."""
        wrapper = Mock()
        wrapper.check_fast_heartbeat = AsyncMock()
        return wrapper

    @pytest.fixture
    def base_context(self, mock_registry_wrapper):
        """Create base context for testing."""
        return {
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
        }

    @pytest.mark.asyncio
    async def test_step_properties(self, fast_heartbeat_step):
        """Test that step has correct properties."""
        assert fast_heartbeat_step.name == "fast-heartbeat-check"
        assert fast_heartbeat_step.required is True
        assert "Lightweight HEAD request" in fast_heartbeat_step.description

    @pytest.mark.asyncio
    async def test_execute_no_changes_200_ok(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with 200 OK response (no changes)."""
        # Setup
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.NO_CHANGES
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NO_CHANGES
        )
        assert "no changes" in result.message.lower()
        mock_registry_wrapper.check_fast_heartbeat.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_execute_topology_changed_202_accepted(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with 202 Accepted response (topology changed)."""
        # Setup
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert "topology changed" in result.message.lower()
        mock_registry_wrapper.check_fast_heartbeat.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_execute_agent_unknown_410_gone(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with 410 Gone response (agent unknown)."""
        # Setup
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.AGENT_UNKNOWN
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.AGENT_UNKNOWN
        )
        assert "agent re-registration" in result.message.lower()
        mock_registry_wrapper.check_fast_heartbeat.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_execute_registry_error_503_service_unavailable(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with 503 Service Unavailable response (registry error)."""
        # Setup
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.REGISTRY_ERROR
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.REGISTRY_ERROR
        )
        assert "registry error" in result.message.lower()
        mock_registry_wrapper.check_fast_heartbeat.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_execute_network_error_exception(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with network exception (converts to network error)."""
        # Setup - simulate network exception
        mock_registry_wrapper.check_fast_heartbeat.side_effect = ConnectionError(
            "Network failure"
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify - step should succeed but set NETWORK_ERROR status
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NETWORK_ERROR
        )
        assert "network error" in result.message.lower()
        mock_registry_wrapper.check_fast_heartbeat.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_execute_missing_agent_id(
        self, fast_heartbeat_step, mock_registry_wrapper
    ):
        """Test fast heartbeat with missing agent_id in context."""
        # Setup - context without agent_id
        context = {"registry_wrapper": mock_registry_wrapper}

        # Execute
        result = await fast_heartbeat_step.execute(context)

        # Verify - step succeeds but indicates network error for resilience
        assert result.status == PipelineStatus.SUCCESS
        assert "skip for resilience" in result.message.lower()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NETWORK_ERROR
        )
        mock_registry_wrapper.check_fast_heartbeat.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_missing_registry_wrapper(self, fast_heartbeat_step):
        """Test fast heartbeat with missing registry_wrapper in context."""
        # Setup - context without registry_wrapper
        context = {"agent_id": "test-agent-123"}

        # Execute
        result = await fast_heartbeat_step.execute(context)

        # Verify - step succeeds but indicates network error for resilience
        assert result.status == PipelineStatus.SUCCESS
        assert "skip for resilience" in result.message.lower()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NETWORK_ERROR
        )

    @pytest.mark.asyncio
    async def test_execute_empty_context(self, fast_heartbeat_step):
        """Test fast heartbeat with empty context."""
        # Execute
        result = await fast_heartbeat_step.execute({})

        # Verify - step succeeds but indicates network error for resilience
        assert result.status == PipelineStatus.SUCCESS
        assert "skip for resilience" in result.message.lower()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NETWORK_ERROR
        )

    @pytest.mark.asyncio
    async def test_execute_unexpected_exception(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test fast heartbeat with unexpected exception during execution."""
        # Setup - simulate unexpected error
        mock_registry_wrapper.check_fast_heartbeat.side_effect = RuntimeError(
            "Unexpected error"
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify - step should succeed but set NETWORK_ERROR status
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NETWORK_ERROR
        )
        assert "network error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_context_preservation(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test that existing context is preserved and status is added."""
        # Setup
        base_context["existing_key"] = "existing_value"
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.NO_CHANGES
        )

        # Execute
        result = await fast_heartbeat_step.execute(base_context)

        # Verify - existing context preserved, status added
        assert result.is_success()
        assert (
            result.context.get("fast_heartbeat_status")
            == FastHeartbeatStatus.NO_CHANGES
        )
        assert result.context.get("existing_key") == "existing_value"
        assert result.context.get("agent_id") == "test-agent-123"
        assert result.context.get("registry_wrapper") == mock_registry_wrapper

    @pytest.mark.asyncio
    async def test_logging_behavior(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test that appropriate log messages are generated."""
        # Setup
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )

        with patch.object(fast_heartbeat_step, "logger") as mock_logger:
            # Execute
            result = await fast_heartbeat_step.execute(base_context)

            # Verify logging occurred
            assert result.is_success()
            mock_logger.debug.assert_called()
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_error_logging_behavior(
        self, fast_heartbeat_step, base_context, mock_registry_wrapper
    ):
        """Test that error cases log appropriately."""
        # Setup - simulate exception
        mock_registry_wrapper.check_fast_heartbeat.side_effect = ConnectionError(
            "Network failure"
        )

        with patch.object(fast_heartbeat_step, "logger") as mock_logger:
            # Execute
            result = await fast_heartbeat_step.execute(base_context)

            # Verify error logging occurred
            assert result.is_success()  # Step succeeds but logs error
            mock_logger.warning.assert_called()  # Should log warning about network error


class TestFastHeartbeatStepIntegration:
    """Test FastHeartbeatStep integration scenarios."""

    @pytest.fixture
    def fast_heartbeat_step(self):
        """Create FastHeartbeatStep instance for testing."""
        return FastHeartbeatStep()

    @pytest.mark.asyncio
    async def test_multiple_calls_same_context(self, fast_heartbeat_step):
        """Test multiple calls with same context don't interfere."""
        # Setup
        mock_wrapper = Mock()
        mock_wrapper.check_fast_heartbeat = AsyncMock()
        context = {
            "agent_id": "test-agent",
            "registry_wrapper": mock_wrapper,
        }

        # Test different status responses
        statuses = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
            FastHeartbeatStatus.REGISTRY_ERROR,
        ]

        for status in statuses:
            mock_wrapper.check_fast_heartbeat.return_value = status
            result = await fast_heartbeat_step.execute(context)

            assert result.is_success()
            assert result.context.get("fast_heartbeat_status") == status

    @pytest.mark.asyncio
    async def test_different_agent_ids(self, fast_heartbeat_step):
        """Test that different agent IDs are properly passed to registry."""
        # Setup
        mock_wrapper = Mock()
        mock_wrapper.check_fast_heartbeat = AsyncMock(
            return_value=FastHeartbeatStatus.NO_CHANGES
        )

        agent_ids = ["agent-1", "agent-2", "agent-3"]

        for agent_id in agent_ids:
            context = {
                "agent_id": agent_id,
                "registry_wrapper": mock_wrapper,
            }

            result = await fast_heartbeat_step.execute(context)

            assert result.is_success()
            mock_wrapper.check_fast_heartbeat.assert_called_with(agent_id)
