"""Unit tests for MCP Client Proxy implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_mesh.engine.mcp_client_proxy import AsyncMCPClient, MCPClientProxy
from mcp_mesh.shared.content_extractor import ContentExtractor


class TestContentExtractor:
    """Test content extractor for various MCP response formats."""

    def test_extract_text_content(self):
        """Test extracting simple text content."""
        result = {"content": [{"type": "text", "text": "Hello World"}]}
        extracted = ContentExtractor.extract_content(result)
        assert extracted == "Hello World"

    def test_extract_json_text_content(self):
        """Test extracting JSON from text content."""
        result = {
            "content": [{"type": "text", "text": '{"message": "Hello", "count": 42}'}]
        }
        extracted = ContentExtractor.extract_content(result)
        assert extracted == {"message": "Hello", "count": 42}

    def test_extract_image_content(self):
        """Test extracting image content."""
        result = {
            "content": [
                {"type": "image", "data": "base64data", "mimeType": "image/png"}
            ]
        }
        extracted = ContentExtractor.extract_content(result)
        assert extracted == {
            "type": "image",
            "data": "base64data",
            "mimeType": "image/png",
        }

    def test_extract_resource_content(self):
        """Test extracting resource content."""
        result = {
            "content": [
                {
                    "type": "resource",
                    "resource": {"uri": "file://test.txt"},
                    "text": "Resource content",
                }
            ]
        }
        extracted = ContentExtractor.extract_content(result)
        assert extracted == {
            "type": "resource",
            "resource": {"uri": "file://test.txt"},
            "text": "Resource content",
        }

    def test_extract_multi_content(self):
        """Test extracting multiple content items."""
        result = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ]
        }
        extracted = ContentExtractor.extract_content(result)
        assert extracted["type"] == "multi_content"
        assert len(extracted["items"]) == 2
        assert "Hello" in extracted["text_summary"]
        assert "World" in extracted["text_summary"]

    def test_extract_fastmcp_object_format(self):
        """Test extracting FastMCP object format."""
        result = {"content": [{"object": {"key": "value", "number": 123}}]}
        extracted = ContentExtractor.extract_content(result)
        assert extracted == {"key": "value", "number": 123}

    def test_handle_error_result(self):
        """Test handling error results."""
        result = MagicMock()
        result.isError = True
        result.error = "Test error message"

        with pytest.raises(RuntimeError, match="MCP Error: Test error message"):
            ContentExtractor.extract_content(result)

    def test_handle_empty_content(self):
        """Test handling empty content."""
        result = {"content": []}
        extracted = ContentExtractor.extract_content(result)
        assert extracted == ""

    def test_handle_non_standard_response(self):
        """Test handling non-standard response format."""
        result = "plain string response"
        extracted = ContentExtractor.extract_content(result)
        assert extracted == "plain string response"


class TestMCPClientProxy:
    """Test MCP Client Proxy functionality."""

    def test_proxy_initialization(self):
        """Test proxy initialization with endpoint and function name."""
        proxy = MCPClientProxy("http://example.com:8080", "test_function")
        assert proxy.endpoint == "http://example.com:8080"
        assert proxy.function_name == "test_function"

    def test_proxy_strips_trailing_slash(self):
        """Test that proxy strips trailing slash from endpoint."""
        proxy = MCPClientProxy("http://example.com:8080/", "test_function")
        assert proxy.endpoint == "http://example.com:8080"

    @patch("mcp_mesh.engine.mcp_client_proxy.AsyncMCPClient")
    @patch("asyncio.run")
    def test_proxy_call_interface(self, mock_asyncio_run, mock_async_client):
        """Test that proxy maintains callable interface."""
        # Setup mocks
        mock_client_instance = AsyncMock()
        mock_client_instance.call_tool.return_value = {
            "content": [{"type": "text", "text": "test result"}]
        }
        mock_async_client.return_value = mock_client_instance
        mock_asyncio_run.return_value = "test result"

        proxy = MCPClientProxy("http://example.com:8080", "test_function")
        result = proxy(arg1="value1", arg2="value2")

        # Verify asyncio.run was called
        mock_asyncio_run.assert_called_once()
        assert result == "test result"

    @patch("mcp_mesh.engine.mcp_client_proxy.AsyncMCPClient")
    @patch("asyncio.run")
    def test_proxy_error_handling(self, mock_asyncio_run, mock_async_client):
        """Test proxy error handling and cleanup."""
        # Setup mocks to raise exception
        mock_client_instance = AsyncMock()
        mock_client_instance.call_tool.side_effect = Exception("Connection failed")
        mock_async_client.return_value = mock_client_instance
        mock_asyncio_run.side_effect = RuntimeError(
            "Error calling test_function: Connection failed"
        )

        proxy = MCPClientProxy("http://example.com:8080", "test_function")

        with pytest.raises(RuntimeError, match="Error calling test_function"):
            proxy(arg1="value1")


class TestAsyncMCPClient:
    """Test AsyncMCP Client functionality."""

    def test_client_initialization(self):
        """Test client initialization."""
        client = AsyncMCPClient("http://example.com:8080")
        assert client.endpoint == "http://example.com:8080"
        assert client._session is None
        assert client._transport_cleanup is None

    @pytest.mark.asyncio
    @patch("mcp_mesh.engine.mcp_client_proxy.streamablehttp_client")
    @patch("mcp_mesh.engine.mcp_client_proxy.ClientSession")
    async def test_client_connect(self, mock_session_class, mock_transport):
        """Test client connection setup."""
        # Setup mocks
        mock_transport_context = AsyncMock()
        mock_transport.return_value = mock_transport_context
        mock_transport_context.__aenter__.return_value = (
            AsyncMock(),  # read_stream
            AsyncMock(),  # write_stream
            None,  # additional
        )

        mock_session = AsyncMock()
        mock_session_class.return_value = mock_session

        client = AsyncMCPClient("http://example.com:8080")
        await client._connect()

        # Verify transport was called correctly
        mock_transport.assert_called_once_with("http://example.com:8080/mcp")
        mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcp_mesh.engine.mcp_client_proxy.streamablehttp_client")
    @patch("mcp_mesh.engine.mcp_client_proxy.ClientSession")
    async def test_client_call_tool(self, mock_session_class, mock_transport):
        """Test tool calling functionality."""
        # Setup mocks
        mock_transport_context = AsyncMock()
        mock_transport.return_value = mock_transport_context
        mock_transport_context.__aenter__.return_value = (
            AsyncMock(),
            AsyncMock(),
            None,
        )

        mock_session = AsyncMock()
        mock_session.call_tool.return_value = {"result": "success"}
        mock_session_class.return_value = mock_session

        client = AsyncMCPClient("http://example.com:8080")
        result = await client.call_tool("test_tool", {"arg": "value"})

        # Verify tool was called correctly
        mock_session.call_tool.assert_called_once_with("test_tool", {"arg": "value"})
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_client_close(self):
        """Test client cleanup."""
        client = AsyncMCPClient("http://example.com:8080")

        # Mock session and cleanup
        mock_session = AsyncMock()
        mock_cleanup = AsyncMock()
        client._session = mock_session
        client._transport_cleanup = mock_cleanup

        await client.close()

        # Verify cleanup was called
        mock_session.__aexit__.assert_called_once()
        mock_cleanup.assert_called_once()
        assert client._session is None
        assert client._transport_cleanup is None
