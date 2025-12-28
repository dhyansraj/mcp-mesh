"""
Unit tests for Registry Client Wrapper fast heartbeat functionality.

Tests the fast heartbeat method in RegistryClientWrapper that calls
the generated OpenAPI client and handles error conversion.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus
from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper


class TestRegistryClientWrapperFastHeartbeat:
    """Test RegistryClientWrapper fast heartbeat method."""

    @pytest.fixture
    def mock_api_client(self):
        """Create mock API client."""
        return Mock()

    @pytest.fixture
    def mock_agents_api(self):
        """Create mock agents API."""
        api = Mock()
        api.fast_heartbeat_check = Mock()
        return api

    @pytest.fixture
    def registry_wrapper(self, mock_api_client, mock_agents_api):
        """Create RegistryClientWrapper with mocked dependencies."""
        wrapper = RegistryClientWrapper(mock_api_client)
        wrapper.agents_api = mock_agents_api
        return wrapper

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_200_ok(self, registry_wrapper, mock_agents_api):
        """Test fast heartbeat check with 200 OK response."""
        # Setup - mock successful response with HTTP info
        mock_response = Mock()
        mock_response.status_code = 200
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.NO_CHANGES
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_202_accepted(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with 202 Accepted response."""
        # Setup - mock topology changed response
        mock_response = Mock()
        mock_response.status_code = 202
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.TOPOLOGY_CHANGED
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_410_gone(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with 410 Gone response."""
        # Setup - mock agent unknown response
        mock_response = Mock()
        mock_response.status_code = 410
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.AGENT_UNKNOWN
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_503_service_unavailable(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with 503 Service Unavailable response."""
        # Setup - mock registry error response
        mock_response = Mock()
        mock_response.status_code = 503
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.REGISTRY_ERROR
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_connection_error(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with connection error."""
        # Setup - mock connection exception
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = (
            ConnectionError("Network failure")
        )

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.NETWORK_ERROR
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_timeout_error(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with timeout error."""
        # Setup - mock timeout exception
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = TimeoutError(
            "Request timeout"
        )

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.NETWORK_ERROR
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_generic_exception(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with generic exception."""
        # Setup - mock generic exception
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = Exception(
            "Unexpected error"
        )

        # Execute
        result = await registry_wrapper.check_fast_heartbeat("test-agent-123")

        # Verify
        assert result == FastHeartbeatStatus.NETWORK_ERROR
        mock_agents_api.fast_heartbeat_check_with_http_info.assert_called_once_with(
            "test-agent-123"
        )

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_different_agent_ids(
        self, registry_wrapper, mock_agents_api
    ):
        """Test fast heartbeat check with different agent IDs."""
        # Setup
        mock_response = Mock()
        mock_response.status_code = 200
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        agent_ids = ["agent-1", "agent-2", "special-agent-123"]

        for agent_id in agent_ids:
            # Execute
            result = await registry_wrapper.check_fast_heartbeat(agent_id)

            # Verify
            assert result == FastHeartbeatStatus.NO_CHANGES

        # Verify all calls were made with correct agent IDs
        expected_calls = [(agent_id,) for agent_id in agent_ids]
        actual_calls = [
            call.args
            for call in mock_agents_api.fast_heartbeat_check_with_http_info.call_args_list
        ]
        assert actual_calls == expected_calls

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_logging(
        self, registry_wrapper, mock_agents_api
    ):
        """Test that appropriate log messages are generated."""
        # Setup
        mock_response = Mock()
        mock_response.status_code = 200
        mock_agents_api.fast_heartbeat_check_with_http_info.return_value = mock_response

        with patch.object(registry_wrapper, "logger") as mock_logger:
            # Execute
            result = await registry_wrapper.check_fast_heartbeat("test-agent")

            # Verify logging occurred (verbose logs moved to TRACE level)
            assert result == FastHeartbeatStatus.NO_CHANGES
            mock_logger.trace.assert_called()

    @pytest.mark.asyncio
    async def test_check_fast_heartbeat_error_logging(
        self, registry_wrapper, mock_agents_api
    ):
        """Test that error cases log appropriately."""
        # Setup - simulate exception
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = (
            ConnectionError("Network failure")
        )

        with patch.object(registry_wrapper, "logger") as mock_logger:
            # Execute
            result = await registry_wrapper.check_fast_heartbeat("test-agent")

            # Verify error logging occurred
            assert result == FastHeartbeatStatus.NETWORK_ERROR
            mock_logger.warning.assert_called()


class TestRegistryClientWrapperFastHeartbeatIntegration:
    """Test RegistryClientWrapper fast heartbeat integration scenarios."""

    @pytest.fixture
    def registry_wrapper(self):
        """Create RegistryClientWrapper with mock API client."""
        mock_api_client = Mock()
        return RegistryClientWrapper(mock_api_client)

    @pytest.mark.asyncio
    async def test_api_client_response_handling(self, registry_wrapper):
        """Test handling of different API client response formats."""
        # Setup - mock agents API with different response formats
        mock_agents_api = Mock()
        registry_wrapper.agents_api = mock_agents_api

        # Test cases for different response formats
        test_cases = [
            # Standard response object with status_code attribute
            (Mock(status_code=200), FastHeartbeatStatus.NO_CHANGES),
            (Mock(status_code=202), FastHeartbeatStatus.TOPOLOGY_CHANGED),
            (Mock(status_code=410), FastHeartbeatStatus.AGENT_UNKNOWN),
            (Mock(status_code=503), FastHeartbeatStatus.REGISTRY_ERROR),
        ]

        for mock_response, expected_status in test_cases:
            mock_agents_api.fast_heartbeat_check_with_http_info.return_value = (
                mock_response
            )

            result = await registry_wrapper.check_fast_heartbeat("test-agent")
            assert result == expected_status

    @pytest.mark.asyncio
    async def test_multiple_consecutive_calls(self, registry_wrapper):
        """Test multiple consecutive fast heartbeat calls."""
        # Setup
        mock_agents_api = Mock()
        registry_wrapper.agents_api = mock_agents_api

        # Simulate sequence of responses
        responses = [
            Mock(status_code=200),  # NO_CHANGES
            Mock(status_code=200),  # NO_CHANGES
            Mock(status_code=202),  # TOPOLOGY_CHANGED
            Mock(status_code=200),  # NO_CHANGES
        ]
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = responses

        expected_statuses = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
            FastHeartbeatStatus.NO_CHANGES,
        ]

        # Execute multiple calls
        for expected_status in expected_statuses:
            result = await registry_wrapper.check_fast_heartbeat("test-agent")
            assert result == expected_status

        # Verify all calls were made
        assert mock_agents_api.fast_heartbeat_check_with_http_info.call_count == 4

    @pytest.mark.asyncio
    async def test_error_recovery(self, registry_wrapper):
        """Test that errors don't break subsequent successful calls."""
        # Setup
        mock_agents_api = Mock()
        registry_wrapper.agents_api = mock_agents_api

        # Simulate error followed by successful response
        mock_agents_api.fast_heartbeat_check_with_http_info.side_effect = [
            ConnectionError("Network failure"),  # First call fails
            Mock(status_code=200),  # Second call succeeds
        ]

        # Execute - first call should handle error gracefully
        result1 = await registry_wrapper.check_fast_heartbeat("test-agent")
        assert result1 == FastHeartbeatStatus.NETWORK_ERROR

        # Execute - second call should succeed
        result2 = await registry_wrapper.check_fast_heartbeat("test-agent")
        assert result2 == FastHeartbeatStatus.NO_CHANGES

        # Verify both calls were attempted
        assert mock_agents_api.fast_heartbeat_check_with_http_info.call_count == 2
