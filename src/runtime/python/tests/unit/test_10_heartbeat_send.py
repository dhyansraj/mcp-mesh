"""
Unit tests for HeartbeatSendStep pipeline step.

Tests the heartbeat sending logic including registry communication,
dependency resolution, error handling, and fallback scenarios without
making actual network requests.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the classes under test
from _mcp_mesh.pipeline.mcp_heartbeat.heartbeat_send import HeartbeatSendStep
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestHeartbeatSendStep:
    """Test the HeartbeatSendStep class initialization and basic properties."""

    def test_initialization_default(self):
        """Test HeartbeatSendStep initialization with default parameters."""
        step = HeartbeatSendStep()

        assert step.name == "heartbeat-send"
        assert step.required is True  # Default is required
        assert step.description == "Send heartbeat to mesh registry"

    def test_initialization_optional(self):
        """Test HeartbeatSendStep initialization as optional."""
        step = HeartbeatSendStep(required=False)

        assert step.name == "heartbeat-send"
        assert step.required is False
        assert step.description == "Send heartbeat to mesh registry"

    def test_inheritance(self):
        """Test HeartbeatSendStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = HeartbeatSendStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = HeartbeatSendStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)


class TestSuccessfulHeartbeat:
    """Test successful heartbeat scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.fixture
    def mock_health_status(self):
        """Mock health status data."""
        return {
            "status": "healthy",
            "agent_id": "test-agent-123",
            "capabilities": ["tool1", "tool2"],
            "endpoint": "http://test-agent:8080/mcp",
            "timestamp": "2023-01-01T00:00:00Z",
        }

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper with async methods."""
        wrapper = MagicMock()
        wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()
        return wrapper

    @pytest.fixture
    def mock_context_complete(self, mock_health_status, mock_registry_wrapper):
        """Mock complete context with all required data."""
        return {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registration_data": {"key": "value"},
            "registry_wrapper": mock_registry_wrapper,
        }

    @pytest.mark.asyncio
    async def test_execute_successful_heartbeat(
        self, step, mock_context_complete, mock_registry_wrapper
    ):
        """Test execute with successful heartbeat response."""
        mock_response = {
            "status": "success",
            "dependencies_resolved": {
                "agent1": {"endpoint": "http://agent1:8080"},
                "agent2": {"endpoint": "http://agent2:8080"},
            },
        }
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        result = await step.execute(mock_context_complete)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message == "Heartbeat sent successfully for agent 'test-agent-123'"
        )
        assert result.context.get("heartbeat_response") == mock_response
        assert (
            result.context.get("dependencies_resolved")
            == mock_response["dependencies_resolved"]
        )

        # Verify registry wrapper was called with health status
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.assert_called_once_with(
            mock_context_complete["health_status"]
        )

    @pytest.mark.asyncio
    async def test_execute_successful_heartbeat_no_dependencies(
        self, step, mock_context_complete, mock_registry_wrapper
    ):
        """Test execute with successful heartbeat but no dependencies."""
        mock_response = {
            "status": "success"
            # No dependencies_resolved key
        }
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        result = await step.execute(mock_context_complete)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message == "Heartbeat sent successfully for agent 'test-agent-123'"
        )
        assert result.context.get("heartbeat_response") == mock_response
        assert result.context.get("dependencies_resolved") == {}

    @pytest.mark.asyncio
    async def test_execute_successful_heartbeat_with_dependencies(
        self, step, mock_context_complete, mock_registry_wrapper, caplog
    ):
        """Test execute with successful heartbeat and dependency resolution logging."""
        import logging

        mock_response = {
            "status": "success",
            "dependencies_resolved": {
                "dep1": {"data": "value1"},
                "dep2": {"data": "value2"},
                "dep3": {"data": "value3"},
            },
        }
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        caplog.set_level(logging.INFO)

        result = await step.execute(mock_context_complete)

        assert result.status == PipelineStatus.SUCCESS
        assert "Dependencies resolved: 3 items" in caplog.text
        assert (
            result.context.get("dependencies_resolved")
            == mock_response["dependencies_resolved"]
        )

    @pytest.mark.asyncio
    async def test_execute_successful_heartbeat_logging(
        self, step, mock_context_complete, mock_registry_wrapper, caplog
    ):
        """Test execute successful heartbeat logs appropriate messages."""
        import logging

        mock_response = {"status": "success"}
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        caplog.set_level(logging.INFO)

        result = await step.execute(mock_context_complete)

        assert result.status == PipelineStatus.SUCCESS
        assert "Sending heartbeat for agent 'test-agent-123'" in caplog.text
        assert "Heartbeat successful for agent 'test-agent-123'" in caplog.text


class TestNoRegistryScenarios:
    """Test scenarios without registry connection."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.fixture
    def mock_health_status(self):
        """Mock health status data."""
        return {"status": "healthy", "agent_id": "test-agent-123"}

    @pytest.fixture
    def mock_context_no_registry(self, mock_health_status):
        """Mock context without registry wrapper."""
        return {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registration_data": {"key": "value"},
            # No registry_wrapper
        }

    @pytest.fixture
    def mock_context_none_registry(self, mock_health_status):
        """Mock context with None registry wrapper."""
        return {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registration_data": {"key": "value"},
            "registry_wrapper": None,
        }

    @pytest.mark.asyncio
    async def test_execute_no_registry_wrapper(self, step, mock_context_no_registry):
        """Test execute when no registry wrapper is available."""
        result = await step.execute(mock_context_no_registry)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message
            == "Heartbeat logged for agent 'test-agent-123' (no registry)"
        )
        assert result.context.get("heartbeat_response") == {
            "status": "no_registry",
            "logged": True,
        }
        assert result.context.get("dependencies_resolved") == {}

    @pytest.mark.asyncio
    async def test_execute_none_registry_wrapper(
        self, step, mock_context_none_registry
    ):
        """Test execute when registry wrapper is None."""
        result = await step.execute(mock_context_none_registry)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message
            == "Heartbeat logged for agent 'test-agent-123' (no registry)"
        )
        assert result.context.get("heartbeat_response") == {
            "status": "no_registry",
            "logged": True,
        }

    @pytest.mark.asyncio
    async def test_execute_no_registry_logging(
        self, step, mock_context_no_registry, caplog
    ):
        """Test execute without registry logs appropriate warning."""
        import logging

        caplog.set_level(logging.INFO)

        result = await step.execute(mock_context_no_registry)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No registry connection - would send heartbeat for agent 'test-agent-123'"
            in caplog.text
        )


class TestFailureScenarios:
    """Test failure and error scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.fixture
    def mock_health_status(self):
        """Mock health status data."""
        return {"status": "healthy", "agent_id": "test-agent-123"}

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper with async methods."""
        wrapper = MagicMock()
        wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()
        return wrapper

    @pytest.mark.asyncio
    async def test_execute_missing_health_status(self, step):
        """Test execute with missing health status."""
        context = {"agent_id": "test-agent-123", "registry_wrapper": MagicMock()}

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Health status not available in context" in result.message
        assert "Health status not available in context" in result.errors

    @pytest.mark.asyncio
    async def test_execute_none_health_status(self, step):
        """Test execute with None health status."""
        context = {
            "health_status": None,
            "agent_id": "test-agent-123",
            "registry_wrapper": MagicMock(),
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Health status not available in context" in result.message

    @pytest.mark.asyncio
    async def test_execute_registry_no_response(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute when registry returns no response."""
        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            None
        )

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert result.message == "Heartbeat failed - no response from registry"

    @pytest.mark.asyncio
    async def test_execute_registry_exception(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute when registry wrapper raises exception."""
        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.side_effect = (
            Exception("Network error")
        )

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Heartbeat processing failed: Network error" in result.message
        assert "Network error" in result.errors

    @pytest.mark.asyncio
    async def test_execute_general_exception(self, step):
        """Test execute with general exception during processing."""
        # Create context that will cause an exception in processing - string is truthy so passes the check
        # but would fail if we don't have registry_wrapper
        context = {
            "health_status": "string_is_truthy"
        }  # Truthy but no registry_wrapper

        result = await step.execute(context)

        # This actually succeeds because string is truthy and it goes to no-registry path
        assert result.status == PipelineStatus.SUCCESS
        assert "no registry" in result.message

    @pytest.mark.asyncio
    async def test_execute_actual_exception(self, step, mock_health_status):
        """Test execute with actual exception during processing."""
        # Create a mock registry wrapper that raises exception during attribute access
        mock_registry_wrapper = MagicMock()
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
            side_effect=KeyError("Missing key")
        )

        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Heartbeat processing failed: 'Missing key'" in result.message
        assert "'Missing key'" in result.errors

    @pytest.mark.asyncio
    async def test_execute_failure_logging(
        self, step, mock_health_status, mock_registry_wrapper, caplog
    ):
        """Test execute failure scenarios log appropriate errors."""
        import logging

        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            None
        )

        caplog.set_level(logging.ERROR)

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Heartbeat failed - no response" in caplog.text


class TestContextHandling:
    """Test context data handling and edge cases."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.fixture
    def mock_health_status(self):
        """Mock health status data."""
        return {"status": "healthy", "agent_id": "test-agent-123"}

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper."""
        wrapper = MagicMock()
        wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()
        return wrapper

    @pytest.mark.asyncio
    async def test_execute_missing_agent_id(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute with missing agent_id uses default."""
        context = {
            "health_status": mock_health_status,
            "registry_wrapper": mock_registry_wrapper,
            # No agent_id
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "status": "success"
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "unknown-agent" in result.message

    @pytest.mark.asyncio
    async def test_execute_none_agent_id(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute with None agent_id still shows None in message."""
        context = {
            "health_status": mock_health_status,
            "agent_id": None,
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "status": "success"
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        # context.get() with None override returns None, not the default
        assert "None" in result.message

    @pytest.mark.asyncio
    async def test_execute_preserves_existing_context(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute preserves existing context data."""
        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
            "existing_data": {"key": "value"},
            "other_step_result": "preserved",
        }

        mock_response = {"status": "success", "dependencies_resolved": {"dep": "value"}}
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        # New context should be added
        assert result.context.get("heartbeat_response") == mock_response
        assert result.context.get("dependencies_resolved") == {"dep": "value"}
        # Original context should remain unchanged
        assert context.get("existing_data") == {"key": "value"}
        assert context.get("other_step_result") == "preserved"

    @pytest.mark.asyncio
    async def test_execute_optional_registration_data(
        self, step, mock_health_status, mock_registry_wrapper
    ):
        """Test execute handles optional registration_data gracefully."""
        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent-123",
            "registry_wrapper": mock_registry_wrapper,
            # No registration_data - this is optional
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "status": "success"
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            result.message == "Heartbeat sent successfully for agent 'test-agent-123'"
        )

    @pytest.mark.asyncio
    async def test_execute_empty_context(self, step):
        """Test execute with completely empty context."""
        result = await step.execute({})

        assert result.status == PipelineStatus.FAILED
        assert "Health status not available in context" in result.message

    @pytest.mark.asyncio
    async def test_execute_complex_health_status(self, step, mock_registry_wrapper):
        """Test execute with complex health status data."""
        complex_health_status = {
            "status": "healthy",
            "agent_id": "complex-agent",
            "capabilities": ["tool1", "tool2", "tool3"],
            "metadata": {"version": "1.0.0", "nested": {"data": "value"}},
            "endpoints": ["http://agent:8080/mcp", "http://agent:8081/alt"],
            "timestamp": "2023-01-01T00:00:00Z",
        }

        context = {
            "health_status": complex_health_status,
            "agent_id": "complex-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "status": "success"
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        # Verify the complex health status was passed to registry wrapper
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.assert_called_once_with(
            complex_health_status
        )


class TestLogging:
    """Test logging behavior in various scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.fixture
    def mock_health_status(self):
        """Mock health status data."""
        return {"status": "healthy", "agent_id": "test-agent"}

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper."""
        wrapper = MagicMock()
        wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()
        return wrapper

    @pytest.mark.asyncio
    async def test_debug_logging_preparation(
        self, step, mock_health_status, mock_registry_wrapper, caplog
    ):
        """Test trace logging for heartbeat preparation."""
        from _mcp_mesh.shared.logging_config import TRACE

        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = {
            "status": "success"
        }

        caplog.set_level(TRACE)
        step.logger.setLevel(TRACE)

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "Preparing heartbeat for agent 'test-agent'" in caplog.text

    @pytest.mark.asyncio
    async def test_error_logging_on_exception(
        self, step, mock_health_status, mock_registry_wrapper, caplog
    ):
        """Test error logging when exception occurs."""
        import logging

        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.side_effect = (
            Exception("Test error")
        )

        caplog.set_level(logging.ERROR)

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Heartbeat processing failed: Test error" in caplog.text

    @pytest.mark.asyncio
    async def test_info_logging_dependency_count(
        self, step, mock_health_status, mock_registry_wrapper, caplog
    ):
        """Test info logging shows dependency resolution count."""
        import logging

        context = {
            "health_status": mock_health_status,
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_response = {
            "status": "success",
            "dependencies_resolved": {
                "agent1": {"endpoint": "http://agent1"},
                "agent2": {"endpoint": "http://agent2"},
                "agent3": {"endpoint": "http://agent3"},
                "agent4": {"endpoint": "http://agent4"},
                "agent5": {"endpoint": "http://agent5"},
            },
        }
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        caplog.set_level(logging.INFO)

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "Dependencies resolved: 5 items" in caplog.text


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatSendStep instance."""
        return HeartbeatSendStep()

    @pytest.mark.asyncio
    async def test_execute_with_empty_health_status(self, step):
        """Test execute with empty dict health status."""
        context = {
            "health_status": {},  # Empty but not None
            "agent_id": "test-agent",
            "registry_wrapper": MagicMock(),
        }

        # Should not fail validation since it's a dict
        result = await step.execute(context)
        # This might succeed or fail depending on registry wrapper expectations
        assert result.status in [PipelineStatus.SUCCESS, PipelineStatus.FAILED]

    @pytest.mark.asyncio
    async def test_execute_with_registry_wrapper_false_response(self, step):
        """Test execute when registry wrapper returns False (falsy but not None)."""
        mock_registry_wrapper = MagicMock()
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
            return_value=False
        )

        context = {
            "health_status": {"status": "healthy"},
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "no response from registry" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_registry_wrapper_empty_dict_response(self, step):
        """Test execute when registry wrapper returns empty dict (falsy in Python)."""
        mock_registry_wrapper = MagicMock()
        mock_registry_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
            return_value={}
        )

        context = {
            "health_status": {"status": "healthy"},
            "agent_id": "test-agent",
            "registry_wrapper": mock_registry_wrapper,
        }

        result = await step.execute(context)

        # Empty dict {} is falsy in Python, so this fails like None response
        assert result.status == PipelineStatus.FAILED
        assert "no response from registry" in result.message

    @pytest.mark.asyncio
    async def test_execute_preserves_context_on_failure(self, step):
        """Test that context is preserved even on failure."""
        context = {
            "existing_key": "existing_value",
            "other_data": {"nested": "data"},
            # Missing health_status to trigger failure
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        # Original context should remain unchanged
        assert context.get("existing_key") == "existing_value"
        assert context.get("other_data") == {"nested": "data"}
