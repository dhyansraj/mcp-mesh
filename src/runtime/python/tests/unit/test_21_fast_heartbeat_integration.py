"""
Integration tests for fast heartbeat optimization.

Tests end-to-end scenarios including resilience patterns,
error recovery, and state preservation across multiple cycles.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from _mcp_mesh.pipeline.heartbeat.heartbeat_pipeline import HeartbeatPipeline
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus
from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus


class TestFastHeartbeatIntegrationPatterns:
    """Test integration patterns for fast heartbeat optimization."""

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Create mock registry wrapper for integration testing."""
        wrapper = Mock()
        wrapper.check_fast_heartbeat = AsyncMock()
        wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()
        wrapper.parse_tool_dependencies = Mock(return_value={})
        return wrapper

    @pytest.fixture
    def base_context(self, mock_registry_wrapper):
        """Create base context for integration testing."""
        return {
            "agent_id": "integration-test-agent",
            "registry_wrapper": mock_registry_wrapper,
            "health_status": Mock(agent_name="integration-test-agent"),
        }

    @pytest.mark.asyncio
    async def test_no_changes_sequence_optimization(
        self, base_context, mock_registry_wrapper
    ):
        """Test sequence of NO_CHANGES responses for optimization."""
        # Setup - sequence of NO_CHANGES responses
        mock_registry_wrapper.check_fast_heartbeat.return_value = (
            FastHeartbeatStatus.NO_CHANGES
        )

        pipeline = HeartbeatPipeline()

        # Execute multiple cycles
        results = []
        for i in range(3):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

        # Verify - all cycles successful, minimal work done
        for result in results:
            assert result.is_success()
            assert (
                result.context.get("fast_heartbeat_status")
                == FastHeartbeatStatus.NO_CHANGES
            )

        # Verify - fast heartbeat called multiple times
        assert mock_registry_wrapper.check_fast_heartbeat.call_count == 3

        # Verify - full heartbeat never called (optimization working)
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.assert_not_called()

    @pytest.mark.asyncio
    async def test_topology_change_detection_pattern(
        self, base_context, mock_registry_wrapper
    ):
        """Test detection and handling of topology changes."""
        # Setup - NO_CHANGES followed by TOPOLOGY_CHANGED
        mock_registry_wrapper.check_fast_heartbeat.side_effect = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
            FastHeartbeatStatus.NO_CHANGES,
        ]

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "dependencies_resolved": {
                "tool1": [{"capability": "cap1", "status": "available"}]
            }
        }

        pipeline = HeartbeatPipeline()

        # Execute sequence of cycles
        results = []
        for i in range(4):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

        # Verify - all cycles successful
        for result in results:
            assert result.is_success()

        # Verify - fast heartbeat called for all cycles
        assert mock_registry_wrapper.check_fast_heartbeat.call_count == 4

        # Verify - full heartbeat called only when topology changed (cycle 3)
        assert (
            mock_registry_wrapper.send_heartbeat_with_dependency_resolution.call_count
            == 1
        )

    @pytest.mark.asyncio
    async def test_resilience_pattern_network_errors(
        self, base_context, mock_registry_wrapper
    ):
        """Test resilience pattern during network errors."""
        # Setup - sequence with network errors
        mock_registry_wrapper.check_fast_heartbeat.side_effect = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.NETWORK_ERROR,
            FastHeartbeatStatus.NETWORK_ERROR,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
        ]

        # Setup existing dependencies to verify preservation
        base_context["existing_dependencies"] = {"preserved_tool": "preserved_endpoint"}

        pipeline = HeartbeatPipeline()

        # Execute sequence with errors
        results = []
        for i in range(4):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

        # Verify - all cycles successful (errors handled gracefully)
        for result in results:
            assert result.is_success()
            # Verify existing dependencies preserved during errors
            if (
                result.context.get("fast_heartbeat_status")
                == FastHeartbeatStatus.NETWORK_ERROR
            ):
                assert "existing_dependencies" in result.context
                assert (
                    result.context["existing_dependencies"]["preserved_tool"]
                    == "preserved_endpoint"
                )

        # Verify - full heartbeat only called when topology changed (after recovery)
        assert (
            mock_registry_wrapper.send_heartbeat_with_dependency_resolution.call_count
            == 1
        )

    @pytest.mark.asyncio
    async def test_registry_error_resilience_pattern(
        self, base_context, mock_registry_wrapper
    ):
        """Test resilience pattern during registry errors."""
        # Setup - registry errors followed by recovery
        mock_registry_wrapper.check_fast_heartbeat.side_effect = [
            FastHeartbeatStatus.REGISTRY_ERROR,
            FastHeartbeatStatus.REGISTRY_ERROR,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
        ]

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "dependencies_resolved": {}
        }

        pipeline = HeartbeatPipeline()

        # Execute sequence with registry errors
        results = []
        for i in range(3):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

        # Verify - all cycles successful
        for result in results:
            assert result.is_success()

        # Verify - full heartbeat skipped during registry errors, executed after recovery
        assert (
            mock_registry_wrapper.send_heartbeat_with_dependency_resolution.call_count
            == 1
        )

    @pytest.mark.asyncio
    async def test_agent_unknown_recovery_pattern(
        self, base_context, mock_registry_wrapper
    ):
        """Test agent unknown detection and recovery."""
        # Setup - agent unknown followed by successful re-registration
        mock_registry_wrapper.check_fast_heartbeat.side_effect = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.AGENT_UNKNOWN,
            FastHeartbeatStatus.NO_CHANGES,
        ]

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "dependencies_resolved": {}
        }

        pipeline = HeartbeatPipeline()

        # Execute sequence with agent unknown
        results = []
        for i in range(3):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

        # Verify - all cycles successful
        for result in results:
            assert result.is_success()

        # Verify - full heartbeat called for agent unknown (re-registration)
        assert (
            mock_registry_wrapper.send_heartbeat_with_dependency_resolution.call_count
            == 1
        )

    @pytest.mark.asyncio
    async def test_mixed_status_sequence_comprehensive(
        self, base_context, mock_registry_wrapper
    ):
        """Test comprehensive sequence with mixed statuses."""
        # Setup - realistic sequence of mixed statuses
        status_sequence = [
            FastHeartbeatStatus.NO_CHANGES,  # Normal operation
            FastHeartbeatStatus.NO_CHANGES,  # Normal operation
            FastHeartbeatStatus.TOPOLOGY_CHANGED,  # Change detected
            FastHeartbeatStatus.NO_CHANGES,  # Back to normal
            FastHeartbeatStatus.NETWORK_ERROR,  # Network issue
            FastHeartbeatStatus.NETWORK_ERROR,  # Network issue continues
            FastHeartbeatStatus.REGISTRY_ERROR,  # Registry issue
            FastHeartbeatStatus.TOPOLOGY_CHANGED,  # Recovery with changes
            FastHeartbeatStatus.NO_CHANGES,  # Stable again
        ]

        mock_registry_wrapper.check_fast_heartbeat.side_effect = status_sequence
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "dependencies_resolved": {}
        }

        pipeline = HeartbeatPipeline()

        # Execute comprehensive sequence
        results = []
        for i, expected_status in enumerate(status_sequence):
            result = await pipeline.execute_heartbeat_cycle(base_context)
            results.append(result)

            # Verify each result
            assert result.is_success()
            assert result.context.get("fast_heartbeat_status") == expected_status

        # Verify - full heartbeat called only for TOPOLOGY_CHANGED and AGENT_UNKNOWN
        expected_full_heartbeat_calls = status_sequence.count(
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        expected_full_heartbeat_calls += status_sequence.count(
            FastHeartbeatStatus.AGENT_UNKNOWN
        )

        actual_full_heartbeat_calls = (
            mock_registry_wrapper.send_heartbeat_with_dependency_resolution.call_count
        )
        assert actual_full_heartbeat_calls == expected_full_heartbeat_calls


class TestFastHeartbeatErrorRecovery:
    """Test error recovery scenarios for fast heartbeat."""

    @pytest.fixture
    def pipeline_with_error_handling(self):
        """Create pipeline with error handling for testing."""
        return HeartbeatPipeline()

    @pytest.mark.asyncio
    async def test_step_failure_recovery(self, pipeline_with_error_handling):
        """Test recovery from individual step failures."""
        # Setup context
        context = {
            "agent_id": "error-test-agent",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
        }

        # Mock steps with one failing
        with patch.object(pipeline_with_error_handling, "steps") as mock_steps:
            # Registry connection succeeds
            mock_registry_step = Mock()
            mock_registry_step.execute = AsyncMock(
                return_value=PipelineResult(message="Connected")
            )

            # Fast heartbeat fails
            mock_fast_step = Mock()
            mock_fast_step.execute = AsyncMock(
                return_value=PipelineResult(
                    status=PipelineStatus.FAILED, message="Fast heartbeat failed"
                )
            )

            # Other steps succeed
            mock_agent_step = Mock()
            mock_agent_step.execute = AsyncMock(
                return_value=PipelineResult(message="Agent refreshed")
            )

            mock_dep_step = Mock()
            mock_dep_step.execute = AsyncMock(
                return_value=PipelineResult(message="Dependencies resolved")
            )

            mock_steps.__iter__.return_value = [
                mock_registry_step,
                mock_fast_step,
                mock_agent_step,
                mock_dep_step,
            ]

            # Execute
            result = await pipeline_with_error_handling.execute_heartbeat_cycle(context)

            # Verify - pipeline handles failure gracefully
            assert result.status in [PipelineStatus.PARTIAL, PipelineStatus.SUCCESS]

            # Verify - subsequent steps still executed (fallback behavior)
            mock_agent_step.execute.assert_called_once()
            mock_dep_step.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_corruption_recovery(self, pipeline_with_error_handling):
        """Test recovery from context corruption."""
        # Setup - corrupted context
        context = {
            "agent_id": None,  # Invalid agent ID
            "registry_wrapper": "not_a_wrapper",  # Wrong type
        }

        # Execute
        result = await pipeline_with_error_handling.execute_heartbeat_cycle(context)

        # Verify - pipeline handles corruption gracefully
        assert result.status == PipelineStatus.FAILED
        assert result.errors
        assert "agent_id" in str(result.errors) or "registry_wrapper" in str(
            result.errors
        )


class TestFastHeartbeatStatePreservation:
    """Test state preservation during fast heartbeat optimization."""

    @pytest.mark.asyncio
    async def test_dependency_state_preservation(self):
        """Test that dependency state is preserved during optimization."""
        # Setup - context with existing dependencies
        context = {
            "agent_id": "state-test-agent",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
            "existing_dependencies": {
                "tool1": {"endpoint": "http://service1", "status": "active"},
                "tool2": {"endpoint": "http://service2", "status": "active"},
            },
            "dependency_hash": "abc123",
        }

        # Mock registry wrapper for NO_CHANGES
        context["registry_wrapper"].check_fast_heartbeat = AsyncMock(
            return_value=FastHeartbeatStatus.NO_CHANGES
        )

        pipeline = HeartbeatPipeline()

        # Execute optimization cycle
        result = await pipeline.execute_heartbeat_cycle(context)

        # Verify - existing state preserved
        assert result.is_success()
        assert "existing_dependencies" in result.context
        assert (
            result.context["existing_dependencies"]["tool1"]["endpoint"]
            == "http://service1"
        )
        assert (
            result.context["existing_dependencies"]["tool2"]["endpoint"]
            == "http://service2"
        )
        assert result.context.get("dependency_hash") == "abc123"

    @pytest.mark.asyncio
    async def test_agent_metadata_preservation(self):
        """Test that agent metadata is preserved during optimization."""
        # Setup - context with agent metadata
        context = {
            "agent_id": "metadata-test-agent",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
            "agent_metadata": {
                "version": "1.2.3",
                "capabilities": ["cap1", "cap2"],
                "last_update": "2024-01-01T00:00:00Z",
            },
        }

        # Mock registry wrapper for NO_CHANGES
        context["registry_wrapper"].check_fast_heartbeat = AsyncMock(
            return_value=FastHeartbeatStatus.NO_CHANGES
        )

        pipeline = HeartbeatPipeline()

        # Execute optimization cycle
        result = await pipeline.execute_heartbeat_cycle(context)

        # Verify - metadata preserved
        assert result.is_success()
        assert "agent_metadata" in result.context
        assert result.context["agent_metadata"]["version"] == "1.2.3"
        assert result.context["agent_metadata"]["capabilities"] == ["cap1", "cap2"]
        assert result.context["agent_metadata"]["last_update"] == "2024-01-01T00:00:00Z"


class TestFastHeartbeatPerformanceCharacteristics:
    """Test performance characteristics of fast heartbeat optimization."""

    @pytest.mark.asyncio
    async def test_minimal_work_during_optimization(self):
        """Test that minimal work is performed during optimization cycles."""
        # Setup
        context = {
            "agent_id": "performance-test-agent",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
        }

        # Mock registry wrapper for NO_CHANGES
        context["registry_wrapper"].check_fast_heartbeat = AsyncMock(
            return_value=FastHeartbeatStatus.NO_CHANGES
        )

        pipeline = HeartbeatPipeline()

        # Track method calls
        with patch.object(pipeline, "steps") as mock_steps:
            # Only registry connection and fast heartbeat steps
            mock_registry_step = Mock()
            mock_registry_step.execute = AsyncMock(
                return_value=PipelineResult(message="Connected")
            )

            mock_fast_step = Mock()
            fast_result = PipelineResult(message="No changes")
            fast_result.add_context(
                "fast_heartbeat_status", FastHeartbeatStatus.NO_CHANGES
            )
            mock_fast_step.execute = AsyncMock(return_value=fast_result)

            mock_expensive_step = Mock()
            mock_expensive_step.execute = AsyncMock(
                return_value=PipelineResult(message="Expensive work")
            )

            mock_steps.__iter__.return_value = [
                mock_registry_step,
                mock_fast_step,
                mock_expensive_step,
            ]

            # Execute
            result = await pipeline.execute_heartbeat_cycle(context)

            # Verify - expensive step not called
            assert result.is_success()
            mock_registry_step.execute.assert_called_once()
            mock_fast_step.execute.assert_called_once()
            mock_expensive_step.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_count_optimization_ratio(self):
        """Test the ratio of optimized vs full cycles."""
        # Setup - mostly NO_CHANGES with occasional changes
        status_sequence = [FastHeartbeatStatus.NO_CHANGES] * 9 + [  # 9 optimized cycles
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        ]  # 1 full cycle

        context = {
            "agent_id": "ratio-test-agent",
            "registry_wrapper": Mock(),
            "health_status": Mock(),
        }

        context["registry_wrapper"].check_fast_heartbeat.side_effect = status_sequence
        context[
            "registry_wrapper"
        ].send_heartbeat_with_dependency_resolution.return_value = {}

        pipeline = HeartbeatPipeline()

        # Execute sequence
        for _ in range(len(status_sequence)):
            result = await pipeline.execute_heartbeat_cycle(context)
            assert result.is_success()

        # Verify optimization ratio
        fast_heartbeat_calls = len(status_sequence)  # Called every cycle
        full_heartbeat_calls = context[
            "registry_wrapper"
        ].send_heartbeat_with_dependency_resolution.call_count

        assert fast_heartbeat_calls == 10
        assert full_heartbeat_calls == 1  # Only when topology changed

        # 90% optimization rate
        optimization_rate = (
            fast_heartbeat_calls - full_heartbeat_calls
        ) / fast_heartbeat_calls
        assert optimization_rate == 0.9
