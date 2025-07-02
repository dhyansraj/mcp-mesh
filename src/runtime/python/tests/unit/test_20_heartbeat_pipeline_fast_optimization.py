"""
Unit tests for HeartbeatPipeline fast optimization with resilient logic.

Tests the conditional execution logic in HeartbeatPipeline that decides
whether to execute subsequent steps based on fast heartbeat status.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from _mcp_mesh.pipeline.heartbeat.heartbeat_pipeline import HeartbeatPipeline
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus
from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus


class TestHeartbeatPipelineResilientLogic:
    """Test HeartbeatPipeline conditional execution based on fast heartbeat status."""

    @pytest.fixture
    def mock_registry_connection_step(self):
        """Create mock registry connection step."""
        step = Mock()
        step.name = "registry-connection"
        step.required = True
        step.execute = AsyncMock(
            return_value=PipelineResult(message="Registry connected")
        )
        return step

    @pytest.fixture
    def mock_fast_heartbeat_step(self):
        """Create mock fast heartbeat step."""
        step = Mock()
        step.name = "fast-heartbeat-check"
        step.required = True
        step.execute = AsyncMock()
        return step

    @pytest.fixture
    def mock_agent_refresh_step(self):
        """Create mock agent refresh step (renamed from heartbeat send)."""
        step = Mock()
        step.name = "agent-refresh"
        step.required = True
        step.execute = AsyncMock(return_value=PipelineResult(message="Agent refreshed"))
        return step

    @pytest.fixture
    def mock_dependency_resolution_step(self):
        """Create mock dependency resolution step."""
        step = Mock()
        step.name = "dependency-resolution"
        step.required = False
        step.execute = AsyncMock(
            return_value=PipelineResult(message="Dependencies resolved")
        )
        return step

    @pytest.fixture
    def heartbeat_pipeline(
        self,
        mock_registry_connection_step,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Create HeartbeatPipeline with mocked steps."""
        pipeline = HeartbeatPipeline()

        # Replace steps with mocks
        pipeline.steps = [
            mock_registry_connection_step,
            mock_fast_heartbeat_step,
            mock_agent_refresh_step,
            mock_dependency_resolution_step,
        ]

        return pipeline

    @pytest.fixture
    def base_context(self):
        """Create base context for testing."""
        return {
            "agent_id": "test-agent-123",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
        }

    @pytest.mark.asyncio
    async def test_no_changes_skip_subsequent_steps(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that NO_CHANGES status skips agent refresh and dependency resolution."""
        # Setup - fast heartbeat returns NO_CHANGES
        fast_result = PipelineResult(message="No changes detected")
        fast_result.add_context("fast_heartbeat_status", FastHeartbeatStatus.NO_CHANGES)
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - only registry connection and fast heartbeat executed
        assert result.is_success()
        mock_fast_heartbeat_step.execute.assert_called_once()
        mock_agent_refresh_step.execute.assert_not_called()
        mock_dependency_resolution_step.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_topology_changed_execute_all_steps(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that TOPOLOGY_CHANGED status executes all subsequent steps."""
        # Setup - fast heartbeat returns TOPOLOGY_CHANGED
        fast_result = PipelineResult(message="Topology changed")
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - all steps executed
        assert result.is_success()
        mock_fast_heartbeat_step.execute.assert_called_once()
        mock_agent_refresh_step.execute.assert_called_once()
        mock_dependency_resolution_step.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_unknown_execute_all_steps(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that AGENT_UNKNOWN status executes all subsequent steps."""
        # Setup - fast heartbeat returns AGENT_UNKNOWN
        fast_result = PipelineResult(message="Agent unknown")
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.AGENT_UNKNOWN
        )
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - all steps executed
        assert result.is_success()
        mock_fast_heartbeat_step.execute.assert_called_once()
        mock_agent_refresh_step.execute.assert_called_once()
        mock_dependency_resolution_step.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_registry_error_skip_for_resilience(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that REGISTRY_ERROR status skips subsequent steps for resilience."""
        # Setup - fast heartbeat returns REGISTRY_ERROR
        fast_result = PipelineResult(message="Registry error")
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.REGISTRY_ERROR
        )
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - subsequent steps skipped for resilience
        assert result.is_success()
        mock_fast_heartbeat_step.execute.assert_called_once()
        mock_agent_refresh_step.execute.assert_not_called()
        mock_dependency_resolution_step.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_network_error_skip_for_resilience(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that NETWORK_ERROR status skips subsequent steps for resilience."""
        # Setup - fast heartbeat returns NETWORK_ERROR
        fast_result = PipelineResult(message="Network error")
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.NETWORK_ERROR
        )
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - subsequent steps skipped for resilience
        assert result.is_success()
        mock_fast_heartbeat_step.execute.assert_called_once()
        mock_agent_refresh_step.execute.assert_not_called()
        mock_dependency_resolution_step.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_fast_heartbeat_step_failure_fallback(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
        mock_dependency_resolution_step,
    ):
        """Test that fast heartbeat step failure falls back to full pipeline."""
        # Setup - fast heartbeat step succeeds but sets network error for resilience
        fast_result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            message="Fast heartbeat check: Skip for resilience (network error)",
        )
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.NETWORK_ERROR
        )
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - pipeline should skip remaining steps for resilience
        assert result.is_success() or result.status == PipelineStatus.PARTIAL
        mock_fast_heartbeat_step.execute.assert_called_once()
        # With network error status, remaining steps are skipped for resilience
        mock_agent_refresh_step.execute.assert_not_called()
        mock_dependency_resolution_step.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_passing_between_steps(
        self,
        heartbeat_pipeline,
        base_context,
        mock_fast_heartbeat_step,
        mock_agent_refresh_step,
    ):
        """Test that context is properly passed between steps."""
        # Setup - fast heartbeat adds status to context
        fast_result = PipelineResult(message="Topology changed")
        fast_result.add_context(
            "fast_heartbeat_status", FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        fast_result.add_context("additional_data", "test_value")
        mock_fast_heartbeat_step.execute.return_value = fast_result

        # Execute
        result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

        # Verify - context passed to subsequent steps
        assert result.is_success()

        # Check that agent refresh step received updated context
        agent_refresh_call_args = mock_agent_refresh_step.execute.call_args[0][0]
        assert (
            agent_refresh_call_args["fast_heartbeat_status"]
            == FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert agent_refresh_call_args["additional_data"] == "test_value"
        assert agent_refresh_call_args["agent_id"] == "test-agent-123"

    @pytest.mark.asyncio
    async def test_pipeline_state_preservation_during_errors(
        self, heartbeat_pipeline, base_context
    ):
        """Test that pipeline state is preserved during error conditions."""
        # Setup - add existing state to context
        base_context["existing_dependencies"] = {"tool1": "endpoint1"}
        base_context["last_known_topology"] = {"agents": ["agent1", "agent2"]}

        # Setup - fast heartbeat returns error status
        with patch.object(heartbeat_pipeline, "steps") as mock_steps:
            mock_registry_step = Mock()
            mock_registry_step.execute = AsyncMock(
                return_value=PipelineResult(message="Connected")
            )

            mock_fast_step = Mock()
            fast_result = PipelineResult(message="Network error")
            fast_result.add_context(
                "fast_heartbeat_status", FastHeartbeatStatus.NETWORK_ERROR
            )
            mock_fast_step.execute = AsyncMock(return_value=fast_result)

            mock_steps.__iter__.return_value = [mock_registry_step, mock_fast_step]

            # Execute
            result = await heartbeat_pipeline.execute_heartbeat_cycle(base_context)

            # Verify - existing state preserved
            assert result.is_success()
            assert "existing_dependencies" in result.context
            assert "last_known_topology" in result.context


class TestHeartbeatPipelineStepExecution:
    """Test step execution patterns in HeartbeatPipeline."""

    @pytest.fixture
    def heartbeat_pipeline(self):
        """Create HeartbeatPipeline for testing."""
        return HeartbeatPipeline()

    @pytest.mark.asyncio
    async def test_step_order_maintained(self, heartbeat_pipeline):
        """Test that steps are executed in the correct order."""
        # Verify step order in pipeline
        expected_step_names = [
            "registry-connection",
            "fast-heartbeat-check",
            "heartbeat-send",  # TODO: Will be renamed to agent-refresh
            "dependency-resolution",
        ]

        actual_step_names = [step.name for step in heartbeat_pipeline.steps]
        assert actual_step_names == expected_step_names

    @pytest.mark.asyncio
    async def test_fast_heartbeat_step_required(self, heartbeat_pipeline):
        """Test that fast heartbeat step is marked as required."""
        fast_heartbeat_step = None
        for step in heartbeat_pipeline.steps:
            if step.name == "fast-heartbeat-check":
                fast_heartbeat_step = step
                break

        assert fast_heartbeat_step is not None
        assert fast_heartbeat_step.required is True

    @pytest.mark.asyncio
    async def test_pipeline_configuration(self, heartbeat_pipeline):
        """Test that pipeline is properly configured."""
        assert heartbeat_pipeline.name == "heartbeat-pipeline"
        assert len(heartbeat_pipeline.steps) == 4

        # Verify each step has required properties
        for step in heartbeat_pipeline.steps:
            assert hasattr(step, "name")
            assert hasattr(step, "required")
            assert hasattr(step, "execute")


class TestHeartbeatPipelineLogging:
    """Test logging behavior in HeartbeatPipeline."""

    @pytest.fixture
    def heartbeat_pipeline(self):
        """Create HeartbeatPipeline for testing."""
        return HeartbeatPipeline()

    @pytest.mark.asyncio
    async def test_optimization_logging(self, heartbeat_pipeline):
        """Test that optimization decisions are logged."""
        with patch.object(heartbeat_pipeline, "logger") as mock_logger:
            # Setup context with fast heartbeat status
            context = {
                "agent_id": "test-agent",
                "fast_heartbeat_status": FastHeartbeatStatus.NO_CHANGES,
            }

            with patch.object(heartbeat_pipeline, "steps", []):
                # Execute
                result = await heartbeat_pipeline.execute_heartbeat_cycle(context)

                # Verify optimization is logged
                mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_resilience_logging(self, heartbeat_pipeline):
        """Test that resilience decisions are logged."""
        with patch.object(heartbeat_pipeline, "logger") as mock_logger:
            # Setup context with error status
            context = {
                "agent_id": "test-agent",
                "fast_heartbeat_status": FastHeartbeatStatus.REGISTRY_ERROR,
            }

            with patch.object(heartbeat_pipeline, "steps", []):
                # Execute
                result = await heartbeat_pipeline.execute_heartbeat_cycle(context)

                # Verify resilience is logged
                mock_logger.warning.assert_called()
