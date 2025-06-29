"""
Unit tests for MCPClientProxy - SUPPORTED MCP features.

Tests the currently working MCP protocol features in the client proxy.
These tests should all pass and represent the current MCP compatibility level.
"""

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

# Import the classes under test
from _mcp_mesh.engine.mcp_client_proxy import AsyncMCPClient, MCPClientProxy


class TestMCPClientProxyBasicProtocol:
    """Test basic MCP protocol compliance - currently supported features."""

    def test_initialization(self):
        """Test MCPClientProxy initialization."""
        proxy = MCPClientProxy("http://test-service:8080", "test_function")

        assert proxy.endpoint == "http://test-service:8080"
        assert proxy.function_name == "test_function"
        assert proxy.logger.name.endswith("proxy.test_function")

    def test_endpoint_trailing_slash_handling(self):
        """Test endpoint URL normalization."""
        proxy = MCPClientProxy("http://test-service:8080/", "test_function")
        assert proxy.endpoint == "http://test-service:8080"

    @patch("urllib.request.urlopen")
    def test_tools_call_basic_success(self, mock_urlopen):
        """Test successful tools/call with basic arguments."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": "Function executed successfully"},
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://test-service:8080", "test_function")
        result = proxy(arg1="value1", arg2="value2")

        # Verify request was made correctly
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        request = call_args[0][0]

        # Check URL
        assert request.full_url == "http://test-service:8080/mcp/"

        # Check headers
        assert request.get_header("Content-type") == "application/json"
        assert request.get_header("Accept") == "application/json, text/event-stream"

        # Check payload
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "test_function"
        assert payload["params"]["arguments"] == {"arg1": "value1", "arg2": "value2"}

        # Check result extraction - ContentExtractor treats string as multi-content
        expected_result = {
            "type": "multi_content",
            "items": list("Function executed successfully"),
            "text_summary": " ".join("Function executed successfully"),
        }
        assert result == expected_result

    @patch("urllib.request.urlopen")
    def test_tools_call_complex_arguments(self, mock_urlopen):
        """Test tools/call with complex nested arguments."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": {"nested": "data", "count": 42}},
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://test-service:8080", "complex_function")

        # Complex arguments
        complex_args = {
            "config": {
                "settings": {"debug": True, "timeout": 30},
                "filters": ["filter1", "filter2"],
            },
            "metadata": {"version": "1.0", "tags": ["test", "integration"]},
        }

        result = proxy(**complex_args)

        # Verify complex arguments were serialized correctly
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["params"]["arguments"] == complex_args

        # Check complex result extraction - ContentExtractor treats dict keys as multi-content
        expected_result = {
            "type": "multi_content",
            "items": ["nested", "count"],
            "text_summary": "nested count",
        }
        assert result == expected_result

    @patch("urllib.request.urlopen")
    def test_fastmcp_sse_response_handling(self, mock_urlopen):
        """Test Server-Sent Events response format from FastMCP."""
        # Mock SSE response
        sse_response = """event: message
data: {"jsonrpc": "2.0", "id": 1, "result": {"content": "SSE response"}}

"""
        mock_response = MagicMock()
        mock_response.read.return_value = sse_response.encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://fastmcp-service:8080", "sse_function")
        result = proxy(test="sse")

        # Verify SSE parsing worked - ContentExtractor processes as multi-content
        expected_result = {
            "type": "multi_content",
            "items": list("SSE response"),
            "text_summary": " ".join("SSE response"),
        }
        assert result == expected_result

    @patch("urllib.request.urlopen")
    def test_fastmcp_sse_multiple_data_lines(self, mock_urlopen):
        """Test SSE response with multiple data lines (takes first valid JSON)."""
        # Mock SSE response with multiple data lines
        sse_response = """event: message
data: invalid json
data: {"jsonrpc": "2.0", "id": 1, "result": {"content": "Valid response"}}
data: {"jsonrpc": "2.0", "id": 2, "result": {"content": "Second response"}}

"""
        mock_response = MagicMock()
        mock_response.read.return_value = sse_response.encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://fastmcp-service:8080", "multi_sse_function")
        result = proxy(test="multi_sse")

        # Should take first valid JSON - processed as multi-content
        expected_result = {
            "type": "multi_content",
            "items": list("Valid response"),
            "text_summary": " ".join("Valid response"),
        }
        assert result == expected_result

    @patch("urllib.request.urlopen")
    def test_plain_json_response(self, mock_urlopen):
        """Test standard JSON response (non-SSE)."""
        # Mock plain JSON response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": "Plain JSON response"}}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://json-service:8080", "json_function")
        result = proxy(format="json")

        # ContentExtractor processes as multi-content
        expected_result = {
            "type": "multi_content",
            "items": list("Plain JSON response"),
            "text_summary": " ".join("Plain JSON response"),
        }
        assert result == expected_result

    @patch("urllib.request.urlopen")
    def test_empty_result_handling(self, mock_urlopen):
        """Test handling of empty/null results."""
        # Mock response with null result
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": None}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "empty_function")
        result = proxy()

        # ContentExtractor converts None to string "None"
        assert result == "None"

    @patch("urllib.request.urlopen")
    def test_result_without_content_field(self, mock_urlopen):
        """Test result extraction when content field is missing."""
        # Mock response with direct result (no content wrapper)
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": "Direct result value"}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "direct_function")
        result = proxy()

        # ContentExtractor should handle this
        assert result == "Direct result value"


class TestMCPClientProxyErrorHandling:
    """Test error handling scenarios - currently supported."""

    @patch("urllib.request.urlopen")
    def test_jsonrpc_error_response(self, mock_urlopen):
        """Test handling of JSON-RPC error responses."""
        # Mock error response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32601,
                    "message": "Method not found",
                    "data": {"method": "unknown_function"},
                },
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "unknown_function")

        with pytest.raises(RuntimeError, match="Tool call error: Method not found"):
            proxy()

    def test_http_404_error(self):
        """Test handling of HTTP 404 errors."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="http://service:8080/mcp/",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=None,
            )

            proxy = MCPClientProxy("http://service:8080", "missing_function")

            with pytest.raises(RuntimeError, match="Error calling missing_function"):
                proxy()

    def test_http_500_error(self):
        """Test handling of HTTP 500 errors."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="http://service:8080/mcp/",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None,
            )

            proxy = MCPClientProxy("http://service:8080", "error_function")

            with pytest.raises(RuntimeError, match="Error calling error_function"):
                proxy()

    def test_network_timeout(self):
        """Test handling of network timeouts."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("timed out")

            proxy = MCPClientProxy("http://slow-service:8080", "slow_function")

            with pytest.raises(RuntimeError, match="Error calling slow_function"):
                proxy()

    @patch("urllib.request.urlopen")
    def test_malformed_json_response(self, mock_urlopen):
        """Test handling of malformed JSON responses."""
        # Mock malformed JSON response
        mock_response = MagicMock()
        mock_response.read.return_value = b"{ invalid json }"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "malformed_function")

        with pytest.raises(RuntimeError, match="Error calling malformed_function"):
            proxy()

    @patch("urllib.request.urlopen")
    def test_sse_response_without_valid_json(self, mock_urlopen):
        """Test SSE response that doesn't contain valid JSON."""
        # Mock SSE response without valid JSON
        sse_response = """event: message
data: invalid json line 1
data: still invalid json
data: not json either

"""
        mock_response = MagicMock()
        mock_response.read.return_value = sse_response.encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "invalid_sse_function")

        with pytest.raises(
            RuntimeError, match="Could not parse SSE response from FastMCP"
        ):
            proxy()


class TestMCPClientProxyFeatures:
    """Test specific features and edge cases - currently supported."""

    def test_callable_interface(self):
        """Test that proxy implements callable interface correctly."""
        proxy = MCPClientProxy("http://service:8080", "test_function")

        # Should be callable
        assert callable(proxy)

        # Should have __call__ method
        assert callable(proxy)

    def test_no_connection_pooling_design(self):
        """Test that proxy creates new connections (K8s load balancing friendly)."""
        # This is a design verification - proxy should not maintain persistent connections
        proxy = MCPClientProxy("http://service:8080", "test_function")

        # Should not have connection pool attributes
        assert not hasattr(proxy, "_connection_pool")
        assert not hasattr(proxy, "_session")
        assert not hasattr(proxy, "_client")

    @patch("urllib.request.urlopen")
    def test_timeout_configuration(self, mock_urlopen):
        """Test that timeout is properly configured in requests."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": "success"}}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "test_function")
        proxy()

        # Verify timeout was set
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        assert call_args[1]["timeout"] == 30.0  # Default timeout

    def test_logging_integration(self):
        """Test that proxy integrates with logging system."""
        proxy = MCPClientProxy("http://service:8080", "test_function")

        # Should have logger configured
        assert hasattr(proxy, "logger")
        assert proxy.logger.name.endswith("proxy.test_function")

    @patch("urllib.request.urlopen")
    def test_debug_logging_on_success(self, mock_urlopen):
        """Test debug logging on successful calls."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": "success"}}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        proxy = MCPClientProxy("http://service:8080", "test_function")

        with patch.object(proxy.logger, "debug") as mock_debug:
            proxy()

            # Should log call attempt and success
            assert mock_debug.call_count >= 2

    @patch("urllib.request.urlopen")
    def test_error_logging_on_failure(self, mock_urlopen):
        """Test error logging on failed calls."""
        mock_urlopen.side_effect = Exception("Network error")

        proxy = MCPClientProxy("http://service:8080", "test_function")

        with patch.object(proxy.logger, "error") as mock_error:
            with pytest.raises(RuntimeError):
                proxy()

            # Should log error twice (once in _sync_call, once in __call__)
            assert mock_error.call_count == 2


class TestAsyncMCPClientSupported:
    """Test AsyncMCPClient supported features."""

    @pytest.mark.asyncio
    async def test_async_client_initialization(self):
        """Test AsyncMCPClient initialization."""
        client = AsyncMCPClient("http://service:8080", timeout=45.0)

        assert client.endpoint == "http://service:8080"
        assert client.timeout == 45.0
        assert client.logger.name.endswith("client.http://service:8080")

    @pytest.mark.asyncio
    async def test_async_client_close(self):
        """Test AsyncMCPClient close method."""
        client = AsyncMCPClient("http://service:8080")

        # Should complete without error (no persistent connections to close)
        await client.close()

    @pytest.mark.asyncio
    async def test_fallback_to_sync_urllib(self):
        """Test fallback to sync urllib when httpx not available."""
        client = AsyncMCPClient("http://service:8080")

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.side_effect = ImportError("httpx not available")

            with patch.object(client, "_make_request_sync") as mock_sync:
                mock_sync.return_value = {"result": "fallback success"}

                await client._make_request({"test": "payload"})

                # Should call sync fallback
                mock_sync.assert_called_once_with({"test": "payload"})

    @pytest.mark.asyncio
    async def test_sync_fallback_implementation(self):
        """Test the sync fallback request implementation."""
        client = AsyncMCPClient("http://service:8080")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "result": {"success": True}}
            ).encode("utf-8")
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response

            result = await client._make_request_sync({"test": "payload"})

            assert result == {"success": True}

            # Verify request structure
            mock_urlopen.assert_called_once()
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.full_url == "http://service:8080/mcp"
