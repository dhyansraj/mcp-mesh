"""
Unit tests for heartbeat lifespan integration.

Tests the heartbeat_lifespan_task function including configuration parsing,
standalone mode handling, orchestrator integration, error resilience, and
cancellation handling without running long-running background tasks.
"""

import asyncio
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Import the function under test
from _mcp_mesh.pipeline.heartbeat.lifespan_integration import heartbeat_lifespan_task


class TestLifespanIntegrationConfig:
    """Test configuration parsing and validation."""

    @pytest.fixture
    def mock_heartbeat_config_minimal(self):
        """Mock minimal heartbeat configuration."""
        return {
            "registry_wrapper": None,
            "agent_id": "test-agent-123",
            "interval": 30,
            "context": {"some": "context"},
            "standalone_mode": False,
        }

    @pytest.fixture
    def mock_heartbeat_config_full(self):
        """Mock complete heartbeat configuration."""
        mock_registry = MagicMock()
        return {
            "registry_wrapper": mock_registry,
            "agent_id": "test-agent-456",
            "interval": 45,
            "context": {"agent_config": {"name": "test"}, "capabilities": []},
            "standalone_mode": False,
        }

    @pytest.mark.asyncio
    async def test_config_parameter_extraction(self, mock_heartbeat_config_full):
        """Test that all parameters are correctly extracted from config."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):  # Exit after setup

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config_full)
            except asyncio.CancelledError:
                pass  # Expected to exit quickly

            # Verify orchestrator was created
            mock_orchestrator_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_missing_standalone_mode_defaults_false(self):
        """Test that missing standalone_mode defaults to False."""
        config_without_standalone = {
            "registry_wrapper": None,
            "agent_id": "test-agent",
            "interval": 30,
            "context": {},
            # standalone_mode missing
        }

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            try:
                await heartbeat_lifespan_task(config_without_standalone)
            except asyncio.CancelledError:
                pass

            # Should have created orchestrator (not standalone mode)
            mock_orchestrator_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_with_none_registry_wrapper(
        self, mock_heartbeat_config_minimal
    ):
        """Test handling of None registry_wrapper."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config_minimal)
            except asyncio.CancelledError:
                pass

            # Should still work with None registry_wrapper
            mock_orchestrator_class.assert_called_once()


class TestLifespanIntegrationStandalone:
    """Test standalone mode handling."""

    @pytest.fixture
    def mock_standalone_config(self):
        """Mock configuration for standalone mode."""
        return {
            "registry_wrapper": None,
            "agent_id": "standalone-agent",
            "interval": 30,
            "context": {},
            "standalone_mode": True,
        }

    @pytest.mark.asyncio
    async def test_standalone_mode_early_return(self, mock_standalone_config):
        """Test that standalone mode returns early without creating orchestrator."""
        with patch(
            "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
        ) as mock_orchestrator_class:

            result = await heartbeat_lifespan_task(mock_standalone_config)

            # Should return None and not create orchestrator
            assert result is None
            mock_orchestrator_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_standalone_mode_logging(self, mock_standalone_config, caplog):
        """Test that standalone mode logs appropriate message."""
        with patch(
            "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
        ):

            # Set log level to capture INFO messages
            caplog.set_level(
                logging.INFO, logger="_mcp_mesh.pipeline.heartbeat.lifespan_integration"
            )

            await heartbeat_lifespan_task(mock_standalone_config)

            # Check for standalone mode log message
            assert "Starting heartbeat pipeline in standalone mode" in caplog.text
            assert "standalone-agent" in caplog.text
            assert "no registry communication" in caplog.text

    @pytest.mark.asyncio
    async def test_standalone_false_continues_to_orchestrator(self):
        """Test that standalone_mode=False continues to orchestrator creation."""
        config = {
            "registry_wrapper": None,
            "agent_id": "normal-agent",
            "interval": 30,
            "context": {},
            "standalone_mode": False,
        }

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            try:
                await heartbeat_lifespan_task(config)
            except asyncio.CancelledError:
                pass

            # Should create orchestrator when not in standalone mode
            mock_orchestrator_class.assert_called_once()


class TestLifespanIntegrationOrchestrator:
    """Test orchestrator creation and interaction."""

    @pytest.fixture
    def mock_heartbeat_config(self):
        """Mock heartbeat configuration."""
        return {
            "registry_wrapper": MagicMock(),
            "agent_id": "test-agent",
            "interval": 30,
            "context": {"test": "context"},
            "standalone_mode": False,
        }

    @pytest.mark.asyncio
    async def test_orchestrator_creation(self, mock_heartbeat_config):
        """Test that HeartbeatOrchestrator is created correctly."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Verify orchestrator was instantiated
            mock_orchestrator_class.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_orchestrator_execute_heartbeat_called(self, mock_heartbeat_config):
        """Test that orchestrator.execute_heartbeat is called with correct parameters."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            # Let it run one cycle then cancel
            call_count = 0

            def sleep_side_effect(interval):
                nonlocal call_count
                call_count += 1
                if call_count >= 1:  # After first heartbeat
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)  # Don't actually sleep

            mock_sleep.side_effect = sleep_side_effect

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Verify execute_heartbeat was called with correct parameters
            mock_orchestrator.execute_heartbeat.assert_called_with(
                "test-agent", {"test": "context"}
            )

    @pytest.mark.asyncio
    async def test_heartbeat_interval_respected(self, mock_heartbeat_config):
        """Test that the heartbeat interval is passed to asyncio.sleep."""
        mock_heartbeat_config["interval"] = 45  # Custom interval

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            # Cancel after first sleep call
            mock_sleep.side_effect = asyncio.CancelledError()

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Verify sleep was called with correct interval
            mock_sleep.assert_called_with(45)

    @pytest.mark.asyncio
    async def test_startup_logging(self, mock_heartbeat_config, caplog):
        """Test that startup logging includes agent_id."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            # Set up proper AsyncMock
            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat = AsyncMock(return_value=True)
            mock_orchestrator_class.return_value = mock_orchestrator

            # Set log level to capture INFO messages
            caplog.set_level(
                logging.INFO, logger="_mcp_mesh.pipeline.heartbeat.lifespan_integration"
            )

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Check for startup log message
            assert (
                "Starting heartbeat pipeline task for agent 'test-agent'" in caplog.text
            )


class TestLifespanIntegrationErrorHandling:
    """Test error handling and resilience."""

    @pytest.fixture
    def mock_heartbeat_config(self):
        """Mock heartbeat configuration."""
        return {
            "registry_wrapper": MagicMock(),
            "agent_id": "error-test-agent",
            "interval": 30,
            "context": {},
            "standalone_mode": False,
        }

    @pytest.mark.asyncio
    async def test_heartbeat_failure_continues_loop(
        self, mock_heartbeat_config, caplog
    ):
        """Test that heartbeat execution failure doesn't stop the loop."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            # First heartbeat fails, second succeeds, then cancel
            call_count = 0

            async def execute_side_effect(agent_id, context):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return False  # First heartbeat fails
                return True  # Second succeeds

            mock_orchestrator.execute_heartbeat.side_effect = execute_side_effect

            # Cancel after second sleep
            sleep_call_count = 0

            def sleep_side_effect(interval):
                nonlocal sleep_call_count
                sleep_call_count += 1
                if sleep_call_count >= 2:
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)

            mock_sleep.side_effect = sleep_side_effect

            # Set log level to capture DEBUG messages
            caplog.set_level(
                logging.DEBUG,
                logger="_mcp_mesh.pipeline.heartbeat.lifespan_integration",
            )

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Should have called execute_heartbeat twice
            assert mock_orchestrator.execute_heartbeat.call_count == 2

            # Should log the failure but continue
            assert (
                "Heartbeat pipeline failed for agent 'error-test-agent' - continuing to next cycle"
                in caplog.text
            )

    @pytest.mark.asyncio
    async def test_heartbeat_exception_continues_loop(
        self, mock_heartbeat_config, caplog
    ):
        """Test that heartbeat execution exception doesn't stop the loop."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            # First heartbeat raises exception, second succeeds, then cancel
            call_count = 0

            def execute_side_effect(agent_id, context):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("Heartbeat execution error")
                return True

            mock_orchestrator.execute_heartbeat.side_effect = execute_side_effect

            # Cancel after second sleep
            sleep_call_count = 0

            def sleep_side_effect(interval):
                nonlocal sleep_call_count
                sleep_call_count += 1
                if sleep_call_count >= 2:
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)

            mock_sleep.side_effect = sleep_side_effect

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Should have called execute_heartbeat twice
            assert mock_orchestrator.execute_heartbeat.call_count == 2

            # Should log the exception but continue
            assert (
                "Heartbeat pipeline execution error for agent 'error-test-agent': Heartbeat execution error"
                in caplog.text
            )

    @pytest.mark.asyncio
    async def test_multiple_errors_resilience(self, mock_heartbeat_config):
        """Test that multiple consecutive errors don't crash the task."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            # All heartbeats fail
            mock_orchestrator.execute_heartbeat.return_value = False

            # Cancel after 3 cycles
            sleep_call_count = 0

            def sleep_side_effect(interval):
                nonlocal sleep_call_count
                sleep_call_count += 1
                if sleep_call_count >= 3:
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)

            mock_sleep.side_effect = sleep_side_effect

            try:
                await heartbeat_lifespan_task(mock_heartbeat_config)
            except asyncio.CancelledError:
                pass

            # Should have attempted 3 heartbeats despite all failing
            assert mock_orchestrator.execute_heartbeat.call_count == 3


class TestLifespanIntegrationCancellation:
    """Test cancellation handling."""

    @pytest.fixture
    def mock_heartbeat_config(self):
        """Mock heartbeat configuration."""
        return {
            "registry_wrapper": MagicMock(),
            "agent_id": "cancel-test-agent",
            "interval": 30,
            "context": {},
            "standalone_mode": False,
        }

    @pytest.mark.asyncio
    async def test_cancellation_during_sleep(self, mock_heartbeat_config, caplog):
        """Test proper handling of cancellation during sleep."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat = AsyncMock(return_value=True)
            mock_orchestrator_class.return_value = mock_orchestrator

            # Set log level to capture INFO messages
            caplog.set_level(
                logging.INFO, logger="_mcp_mesh.pipeline.heartbeat.lifespan_integration"
            )

            with pytest.raises(asyncio.CancelledError):
                await heartbeat_lifespan_task(mock_heartbeat_config)

            # Should log cancellation message
            assert (
                "Heartbeat pipeline task cancelled for agent 'cancel-test-agent'"
                in caplog.text
            )

    @pytest.mark.asyncio
    async def test_cancellation_during_heartbeat_execution(
        self, mock_heartbeat_config, caplog
    ):
        """Test proper handling of cancellation during heartbeat execution."""
        with patch(
            "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
        ) as mock_orchestrator_class:

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.side_effect = asyncio.CancelledError()
            mock_orchestrator_class.return_value = mock_orchestrator

            # Set log level to capture INFO messages
            caplog.set_level(
                logging.INFO, logger="_mcp_mesh.pipeline.heartbeat.lifespan_integration"
            )

            with pytest.raises(asyncio.CancelledError):
                await heartbeat_lifespan_task(mock_heartbeat_config)

            # Should log cancellation message
            assert (
                "Heartbeat pipeline task cancelled for agent 'cancel-test-agent'"
                in caplog.text
            )

    @pytest.mark.asyncio
    async def test_cancellation_reraises_exception(self, mock_heartbeat_config):
        """Test that CancelledError is properly re-raised."""
        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):

            # Should re-raise CancelledError, not catch it
            with pytest.raises(asyncio.CancelledError):
                await heartbeat_lifespan_task(mock_heartbeat_config)

    @pytest.mark.asyncio
    async def test_task_cancellation_from_outside(self, mock_heartbeat_config):
        """Test that external task cancellation is handled properly."""

        async def run_and_cancel():
            # Start the heartbeat task
            task = asyncio.create_task(heartbeat_lifespan_task(mock_heartbeat_config))

            # Give it a moment to start
            await asyncio.sleep(0.01)

            # Cancel the task
            task.cancel()

            # Wait for cancellation
            try:
                await task
            except asyncio.CancelledError:
                pass

            return task.cancelled()

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep", return_value=None),
        ):  # Don't actually sleep

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            cancelled = await run_and_cancel()
            assert cancelled is True


class TestLifespanIntegrationIntegration:
    """Test integration scenarios with realistic configurations."""

    @pytest.mark.asyncio
    async def test_normal_heartbeat_cycle(self):
        """Test a normal heartbeat cycle with successful execution."""
        config = {
            "registry_wrapper": MagicMock(),
            "agent_id": "integration-test-agent",
            "interval": 10,  # Short interval for testing
            "context": {
                "agent_config": {"name": "test-agent"},
                "capabilities": ["test-capability"],
            },
            "standalone_mode": False,
        }

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator.execute_heartbeat.return_value = True
            mock_orchestrator_class.return_value = mock_orchestrator

            # Run 2 cycles then cancel
            call_count = 0

            def sleep_side_effect(interval):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)

            mock_sleep.side_effect = sleep_side_effect

            try:
                await heartbeat_lifespan_task(config)
            except asyncio.CancelledError:
                pass

            # Should have executed 2 heartbeats
            assert mock_orchestrator.execute_heartbeat.call_count == 2

            # Should have slept twice
            assert mock_sleep.call_count >= 2

    @pytest.mark.asyncio
    async def test_mixed_success_failure_cycle(self):
        """Test a cycle with mixed success and failure results."""
        config = {
            "registry_wrapper": MagicMock(),
            "agent_id": "mixed-test-agent",
            "interval": 5,
            "context": {},
            "standalone_mode": False,
        }

        with (
            patch(
                "_mcp_mesh.pipeline.heartbeat.heartbeat_orchestrator.HeartbeatOrchestrator"
            ) as mock_orchestrator_class,
            patch("asyncio.sleep") as mock_sleep,
        ):

            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator

            # Alternate between success and failure
            results = [True, False, True, False]
            result_index = 0

            def execute_side_effect(agent_id, context):
                nonlocal result_index
                result = results[result_index % len(results)]
                result_index += 1
                return result

            mock_orchestrator.execute_heartbeat.side_effect = execute_side_effect

            # Cancel after 4 cycles
            call_count = 0

            def sleep_side_effect(interval):
                nonlocal call_count
                call_count += 1
                if call_count >= 4:
                    raise asyncio.CancelledError()
                return asyncio.sleep(0)

            mock_sleep.side_effect = sleep_side_effect

            try:
                await heartbeat_lifespan_task(config)
            except asyncio.CancelledError:
                pass

            # Should have executed 4 heartbeats
            assert mock_orchestrator.execute_heartbeat.call_count == 4
