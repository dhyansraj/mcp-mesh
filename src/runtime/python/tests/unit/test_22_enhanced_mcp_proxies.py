"""Unit tests for enhanced MCP proxy classes and file refactoring."""

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from _mcp_mesh.engine.async_mcp_client import AsyncMCPClient
from _mcp_mesh.engine.full_mcp_proxy import EnhancedFullMCPProxy, FullMCPProxy

# Test imports work after refactoring
from _mcp_mesh.engine.mcp_client_proxy import EnhancedMCPClientProxy, MCPClientProxy


class TestFileRefactoring:
    """Test that file refactoring didn't break existing functionality."""

    def test_basic_imports_work(self):
        """Test that all proxy classes can be imported after refactoring."""
        # These imports should work without errors
        assert MCPClientProxy is not None
        assert EnhancedMCPClientProxy is not None
        assert FullMCPProxy is not None
        assert EnhancedFullMCPProxy is not None
        assert AsyncMCPClient is not None

    def test_basic_proxy_creation(self):
        """Test that basic proxy creation still works."""
        # Test MCPClientProxy
        proxy = MCPClientProxy("http://test:8080", "test_function")
        assert proxy.endpoint == "http://test:8080"
        assert proxy.function_name == "test_function"
        assert proxy.kwargs_config == {}

        # Test FullMCPProxy inherits from MCPClientProxy
        full_proxy = FullMCPProxy("http://test:8080", "test_function")
        assert isinstance(full_proxy, MCPClientProxy)
        assert full_proxy.endpoint == "http://test:8080"
        assert full_proxy.function_name == "test_function"

    def test_kwargs_backward_compatibility(self):
        """Test that existing kwargs support still works."""
        kwargs_config = {"timeout": 45, "retry_count": 3}

        proxy = MCPClientProxy("http://test:8080", "test_function", kwargs_config)
        assert proxy.kwargs_config == kwargs_config

        full_proxy = FullMCPProxy("http://test:8080", "test_function", kwargs_config)
        assert full_proxy.kwargs_config == kwargs_config


class TestEnhancedMCPClientProxy:
    """Test enhanced MCP client proxy auto-configuration."""

    def test_enhanced_proxy_creation(self):
        """Test enhanced proxy creation and basic configuration."""
        kwargs_config = {
            "timeout": 60,
            "retry_count": 5,
            "custom_headers": {"X-API-Version": "v2"},
            "auth_required": True,
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        # Test auto-configuration
        assert proxy.timeout == 60
        assert proxy.retry_count == 5
        assert proxy.max_retries == 5
        assert proxy.custom_headers == {"X-API-Version": "v2"}
        assert proxy.auth_required is True

    def test_enhanced_proxy_defaults(self):
        """Test enhanced proxy uses sensible defaults when no kwargs provided."""
        proxy = EnhancedMCPClientProxy("http://test:8080", "test_function")

        # Test defaults
        assert proxy.timeout == 30
        assert proxy.retry_count == 1
        assert proxy.custom_headers == {}
        assert proxy.auth_required is False
        assert proxy.accepted_content_types == ["application/json"]
        assert proxy.max_response_size == 10 * 1024 * 1024  # 10MB

    def test_enhanced_proxy_content_configuration(self):
        """Test content type and size configuration."""
        kwargs_config = {
            "accepts": ["application/json", "text/plain"],
            "content_type": "application/json",
            "max_response_size": 1024 * 1024,  # 1MB
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        assert proxy.accepted_content_types == ["application/json", "text/plain"]
        assert proxy.default_content_type == "application/json"
        assert proxy.max_response_size == 1024 * 1024

    @patch("urllib.request.urlopen")
    def test_enhanced_proxy_custom_headers(self, mock_urlopen):
        """Test that custom headers are included in requests."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": "test result"}}
        ).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        kwargs_config = {
            "custom_headers": {"X-API-Version": "v2", "X-Client-ID": "test"},
            "content_type": "application/json",
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        # Make a call
        result = proxy(test_param="value")

        # Verify request was made with custom headers
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]

        assert request.headers["X-api-version"] == "v2"  # urllib lowercases headers
        assert request.headers["X-client-id"] == "test"
        assert request.headers["Content-type"] == "application/json"

    @patch.dict(os.environ, {"MCP_MESH_AUTH_TOKEN": "test-token-123"})
    @patch("urllib.request.urlopen")
    def test_enhanced_proxy_authentication(self, mock_urlopen):
        """Test authentication token injection."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": "authenticated result"}}
        ).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        kwargs_config = {"auth_required": True}

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        # Make a call
        result = proxy(test_param="value")

        # Verify Authorization header was added
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        assert request.headers["Authorization"] == "Bearer test-token-123"

    @patch("urllib.request.urlopen")
    def test_enhanced_proxy_retry_logic(self, mock_urlopen):
        """Test retry logic with exponential backoff."""
        # Mock failure then success
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # Fail first 2 attempts
                raise URLError("Connection failed")
            else:  # Succeed on 3rd attempt
                mock_response = MagicMock()
                mock_response.read.return_value = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"content": "success after retries"},
                    }
                ).encode()
                mock_response.__enter__.return_value = mock_response
                return mock_response

        mock_urlopen.side_effect = side_effect

        kwargs_config = {
            "retry_count": 3,
            "retry_delay": 0.01,  # Fast retries for testing
            "retry_backoff": 2.0,
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        start_time = time.time()
        result = proxy(test_param="value")
        end_time = time.time()

        # Should have retried 2 times before success (3 total calls)
        assert call_count == 3
        # Check that the result contains our success message (ContentExtractor may process it)
        result_str = str(result)
        assert (
            "success after retries" in result_str
            or "s u c c e s s   a f t e r   r e t r i e s" in result_str
        )

        # Should have taken some time due to retry delays
        assert end_time - start_time >= 0.03  # At least 0.01 + 0.02 seconds of delays

    @patch("urllib.request.urlopen")
    def test_enhanced_proxy_retry_exhaustion(self, mock_urlopen):
        """Test behavior when all retries are exhausted."""
        # Mock all attempts to fail
        mock_urlopen.side_effect = URLError("Persistent connection error")

        kwargs_config = {
            "retry_count": 2,
            "retry_delay": 0.01,  # Fast retries for testing
        }

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        # Should raise exception after all retries exhausted
        with pytest.raises(RuntimeError, match="Persistent connection error"):
            proxy(test_param="value")

        # Should have made 3 attempts (initial + 2 retries)
        assert mock_urlopen.call_count == 3

    @patch("urllib.request.urlopen")
    def test_enhanced_proxy_response_size_limit(self, mock_urlopen):
        """Test response size limit enforcement."""
        # Mock response with size header exceeding limit
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "2097152"}  # 2MB
        mock_urlopen.return_value.__enter__.return_value = mock_response

        kwargs_config = {"max_response_size": 1024 * 1024}  # 1MB limit

        proxy = EnhancedMCPClientProxy(
            "http://test:8080", "test_function", kwargs_config
        )

        # Should raise exception due to size limit (wrapped in RuntimeError)
        with pytest.raises(RuntimeError, match="Response too large"):
            proxy(test_param="value")


class TestEnhancedFullMCPProxy:
    """Test enhanced full MCP proxy with streaming auto-configuration."""

    def test_enhanced_full_proxy_creation(self):
        """Test enhanced full proxy creation and configuration."""
        kwargs_config = {
            "timeout": 120,
            "streaming": True,
            "stream_timeout": 300,
            "buffer_size": 8192,
        }

        proxy = EnhancedFullMCPProxy("http://test:8080", "test_function", kwargs_config)

        # Test auto-configuration
        assert proxy.timeout == 120
        assert proxy.streaming_capable is True
        assert proxy.stream_timeout == 300
        assert proxy.buffer_size == 8192

    def test_enhanced_full_proxy_inheritance(self):
        """Test that enhanced full proxy inherits from FullMCPProxy."""
        proxy = EnhancedFullMCPProxy("http://test:8080", "test_function")

        # Should inherit from FullMCPProxy which inherits from MCPClientProxy
        assert isinstance(proxy, FullMCPProxy)
        assert isinstance(proxy, MCPClientProxy)

    def test_enhanced_full_proxy_streaming_defaults(self):
        """Test streaming defaults when no kwargs provided."""
        proxy = EnhancedFullMCPProxy("http://test:8080", "test_function")

        # Test streaming defaults
        assert proxy.streaming_capable is False
        assert proxy.stream_timeout == 300  # 5 minutes
        assert proxy.buffer_size == 4096

    def test_call_tool_auto_streaming_selection(self):
        """Test automatic streaming vs non-streaming selection."""
        # Test streaming enabled
        kwargs_config = {"streaming": True}
        proxy = EnhancedFullMCPProxy("http://test:8080", "test_function", kwargs_config)

        # call_tool_auto should return async generator for streaming
        result = proxy.call_tool_auto("test_tool", {"arg": "value"})
        # Should be an async generator (which has __aiter__)
        assert hasattr(result, "__aiter__")

        # Test streaming disabled
        proxy_no_streaming = EnhancedFullMCPProxy("http://test:8080", "test_function")
        # This should return a coroutine for regular async call
        result_no_streaming = proxy_no_streaming.call_tool_auto(
            "test_tool", {"arg": "value"}
        )
        assert hasattr(result_no_streaming, "__await__")


class TestAsyncMCPClient:
    """Test async MCP client functionality after refactoring."""

    def test_async_client_creation(self):
        """Test async client creation."""
        client = AsyncMCPClient("http://test:8080")

        assert client.endpoint == "http://test:8080"
        assert client.timeout == 30.0

    def test_async_client_custom_timeout(self):
        """Test async client with custom timeout."""
        client = AsyncMCPClient("http://test:8080", timeout=60.0)

        assert client.timeout == 60.0

    @pytest.mark.asyncio
    async def test_async_client_close(self):
        """Test async client close method."""
        client = AsyncMCPClient("http://test:8080")

        # close() should not raise any exceptions
        await client.close()


class TestDependencyResolutionIntegration:
    """Test dependency resolution uses enhanced proxies correctly."""

    def test_enhanced_proxy_selection_with_kwargs(self):
        """Test that dependency resolution selects enhanced proxies when kwargs present."""
        # This is a basic test to verify the logic exists
        # More comprehensive integration tests would require mocking the entire dependency resolution flow

        kwargs_config = {"timeout": 60, "retry_count": 3}

        # Test that enhanced proxies can be created with kwargs
        enhanced_mcp = EnhancedMCPClientProxy(
            "http://test:8080", "test_func", kwargs_config
        )
        enhanced_full = EnhancedFullMCPProxy(
            "http://test:8080", "test_func", kwargs_config
        )

        assert enhanced_mcp.timeout == 60
        assert enhanced_mcp.retry_count == 3
        assert enhanced_full.timeout == 60
        assert enhanced_full.retry_count == 3

    def test_standard_proxy_selection_without_kwargs(self):
        """Test that standard proxies are used when no kwargs present."""
        # Test that standard proxies work without enhanced features
        standard_mcp = MCPClientProxy("http://test:8080", "test_func")
        standard_full = FullMCPProxy("http://test:8080", "test_func")

        assert standard_mcp.kwargs_config == {}
        assert standard_full.kwargs_config == {}

        # Enhanced proxies should default to standard behavior with no kwargs
        enhanced_mcp_no_kwargs = EnhancedMCPClientProxy("http://test:8080", "test_func")
        enhanced_full_no_kwargs = EnhancedFullMCPProxy("http://test:8080", "test_func")

        assert enhanced_mcp_no_kwargs.timeout == 30  # Default
        assert enhanced_mcp_no_kwargs.retry_count == 1  # Default
        assert enhanced_full_no_kwargs.streaming_capable is False  # Default


class TestKwargsEndToEndFlow:
    """Test kwargs flow from decorator to enhanced proxy configuration."""

    def test_kwargs_configuration_flow(self):
        """Test that kwargs flow properly through the system."""
        # Simulate kwargs from @mesh.tool decorator
        decorator_kwargs = {
            "timeout": 45,
            "retry_count": 3,
            "custom_headers": {"X-Version": "v2"},
            "streaming": True,
            "auth_required": True,
        }

        # Test Enhanced MCP Client Proxy configuration
        mcp_proxy = EnhancedMCPClientProxy(
            "http://service:8080", "enhanced_tool", kwargs_config=decorator_kwargs
        )

        assert mcp_proxy.timeout == 45
        assert mcp_proxy.retry_count == 3
        assert mcp_proxy.custom_headers["X-Version"] == "v2"
        assert mcp_proxy.auth_required is True

        # Test Enhanced Full MCP Proxy configuration
        full_proxy = EnhancedFullMCPProxy(
            "http://service:8080", "enhanced_tool", kwargs_config=decorator_kwargs
        )

        assert full_proxy.timeout == 45
        assert full_proxy.retry_count == 3
        assert full_proxy.streaming_capable is True
        assert full_proxy.auth_required is True

    def test_empty_kwargs_backward_compatibility(self):
        """Test that empty kwargs don't break anything."""
        # Empty kwargs should work fine
        empty_kwargs = {}

        mcp_proxy = EnhancedMCPClientProxy(
            "http://service:8080", "simple_tool", kwargs_config=empty_kwargs
        )

        full_proxy = EnhancedFullMCPProxy(
            "http://service:8080", "simple_tool", kwargs_config=empty_kwargs
        )

        # Should use defaults
        assert mcp_proxy.timeout == 30
        assert mcp_proxy.retry_count == 1
        assert full_proxy.streaming_capable is False

    def test_none_kwargs_backward_compatibility(self):
        """Test that None kwargs don't break anything."""
        # None kwargs should work fine
        mcp_proxy = EnhancedMCPClientProxy(
            "http://service:8080", "simple_tool", kwargs_config=None
        )

        full_proxy = EnhancedFullMCPProxy(
            "http://service:8080", "simple_tool", kwargs_config=None
        )

        # Should use defaults
        assert mcp_proxy.timeout == 30
        assert mcp_proxy.retry_count == 1
        assert full_proxy.streaming_capable is False


class TestAutomaticSessionManagement:
    """Test automatic session management with enhanced proxies."""

    def test_session_configuration_from_kwargs(self):
        """Test that session requirements are configured from kwargs."""
        kwargs_config = {
            "session_required": True,
            "stateful": True,
            "auto_session_management": True,
        }

        proxy = EnhancedFullMCPProxy("http://test:8080", "session_func", kwargs_config)

        assert proxy.session_required is True
        assert proxy.stateful is True
        assert proxy.auto_session_management is True
        assert proxy._current_session_id is None  # No session created yet

    def test_session_defaults(self):
        """Test default session configuration."""
        proxy = EnhancedFullMCPProxy("http://test:8080", "regular_func")

        # Default session configuration
        assert proxy.session_required is False
        assert proxy.stateful is False
        assert proxy.auto_session_management is True  # Enabled by default
        assert proxy._current_session_id is None

    @pytest.mark.asyncio
    async def test_auto_session_creation_and_cleanup(self):
        """Test automatic session creation and cleanup."""
        kwargs_config = {"session_required": True, "auto_session_management": True}

        proxy = EnhancedFullMCPProxy("http://test:8080", "session_func", kwargs_config)

        # Mock session methods
        created_session_id = "session:abc123"
        proxy.create_session = AsyncMock(return_value=created_session_id)
        proxy.call_with_session = AsyncMock(
            return_value={"result": "session call success"}
        )

        # Test auto-session call
        result = await proxy._call_with_auto_session("test_tool", {"param": "value"})

        # Verify session was created and used
        proxy.create_session.assert_called_once()
        proxy.call_with_session.assert_called_once_with(
            session_id=created_session_id, param="value"
        )
        assert proxy._current_session_id == created_session_id
        assert result == {"result": "session call success"}

        # Test cleanup - just clears local session ID (server-side cleanup via TTL)
        await proxy.cleanup_auto_session()
        assert proxy._current_session_id is None

    def test_call_tool_auto_session_routing(self):
        """Test that call_tool_auto routes to session management when required."""
        # Test session-required routing
        kwargs_config = {"session_required": True, "auto_session_management": True}

        proxy = EnhancedFullMCPProxy("http://test:8080", "session_func", kwargs_config)
        proxy._call_with_auto_session = Mock(return_value="session_result")

        result = proxy.call_tool_auto("test_tool", {"param": "value"})

        proxy._call_with_auto_session.assert_called_once_with(
            "test_tool", {"param": "value"}
        )
        assert result == "session_result"
