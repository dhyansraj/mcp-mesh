"""
Unit tests for HostResolver utility.

Tests the centralized host resolution logic for different deployment scenarios.
"""

from unittest.mock import MagicMock, patch

import pytest

# Import the class under test
from _mcp_mesh.shared.host_resolver import HostResolver


class TestHostResolver:
    """Test the HostResolver utility class."""

    def test_get_binding_host_always_returns_all_interfaces(self):
        """Test get_binding_host always returns 0.0.0.0."""
        result = HostResolver.get_binding_host()
        assert result == "0.0.0.0"

    @patch.dict("os.environ", {}, clear=True)
    def test_get_external_host_fallback_to_localhost(self):
        """Test get_external_host falls back to localhost when auto-detection fails."""
        with patch.object(
            HostResolver,
            "_auto_detect_external_ip",
            side_effect=Exception("Network error"),
        ):
            result = HostResolver.get_external_host()
            assert result == "localhost"

    @patch.dict(
        "os.environ", {"MCP_MESH_HTTP_HOST": "my-service.default.svc.cluster.local"}
    )
    def test_get_external_host_uses_explicit_override(self):
        """Test get_external_host uses MCP_MESH_HTTP_HOST when provided."""
        result = HostResolver.get_external_host()
        assert result == "my-service.default.svc.cluster.local"

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "localhost"})
    def test_get_external_host_explicit_localhost(self):
        """Test get_external_host respects explicit localhost setting."""
        result = HostResolver.get_external_host()
        assert result == "localhost"

    @patch.dict("os.environ", {}, clear=True)
    @patch("socket.socket")
    def test_get_external_host_auto_detection_success(self, mock_socket_class):
        """Test get_external_host auto-detection when successful."""
        # Mock socket behavior
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.getsockname.return_value = ("192.168.1.100", 12345)
        mock_socket_class.return_value = mock_socket

        result = HostResolver.get_external_host()

        assert result == "192.168.1.100"
        mock_socket.connect.assert_called_once_with(("8.8.8.8", 80))

    @patch.dict("os.environ", {}, clear=True)
    @patch("socket.socket")
    def test_get_external_host_auto_detection_localhost_ip_fails(
        self, mock_socket_class
    ):
        """Test get_external_host auto-detection fails when detecting localhost IP."""
        # Mock socket to return localhost IP
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.getsockname.return_value = ("127.0.0.1", 12345)
        mock_socket_class.return_value = mock_socket

        result = HostResolver.get_external_host()

        # Should fall back to localhost when auto-detection gives 127.x
        assert result == "localhost"

    @patch.dict("os.environ", {}, clear=True)
    @patch("socket.socket")
    def test_get_external_host_auto_detection_network_error(self, mock_socket_class):
        """Test get_external_host auto-detection falls back on network error."""
        # Mock socket to raise exception
        mock_socket_class.side_effect = Exception("Network unreachable")

        result = HostResolver.get_external_host()

        assert result == "localhost"

    @patch("socket.socket")
    def test_auto_detect_external_ip_success(self, mock_socket_class):
        """Test _auto_detect_external_ip successful detection."""
        # Mock socket behavior
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.getsockname.return_value = ("10.0.0.5", 12345)
        mock_socket_class.return_value = mock_socket

        result = HostResolver._auto_detect_external_ip()

        assert result == "10.0.0.5"
        mock_socket.connect.assert_called_once_with(("8.8.8.8", 80))

    @patch("socket.socket")
    def test_auto_detect_external_ip_rejects_localhost(self, mock_socket_class):
        """Test _auto_detect_external_ip rejects localhost IPs."""
        # Mock socket to return localhost IP
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.getsockname.return_value = ("127.0.0.1", 12345)
        mock_socket_class.return_value = mock_socket

        with pytest.raises(Exception, match="Auto-detected IP is localhost"):
            HostResolver._auto_detect_external_ip()

    @patch("socket.socket")
    def test_auto_detect_external_ip_network_error(self, mock_socket_class):
        """Test _auto_detect_external_ip handles network errors."""
        # Mock socket to raise exception
        mock_socket_class.side_effect = Exception("Network unreachable")

        with pytest.raises(Exception):
            HostResolver._auto_detect_external_ip()


class TestHostResolverPriorityOrder:
    """Test the priority order of host resolution."""

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "priority-1.example.com"})
    @patch.object(
        HostResolver, "_auto_detect_external_ip", return_value="192.168.1.100"
    )
    def test_priority_order_explicit_host_wins(self, mock_auto_detect):
        """Test that MCP_MESH_HTTP_HOST takes highest priority."""
        result = HostResolver.get_external_host()

        assert result == "priority-1.example.com"
        # Auto-detection should not be called when explicit host is set
        mock_auto_detect.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    @patch.object(
        HostResolver, "_auto_detect_external_ip", return_value="192.168.1.100"
    )
    def test_priority_order_auto_detection_second(self, mock_auto_detect):
        """Test that auto-detection is used when no explicit host is set."""
        result = HostResolver.get_external_host()

        assert result == "192.168.1.100"
        mock_auto_detect.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    @patch.object(
        HostResolver, "_auto_detect_external_ip", side_effect=Exception("Network error")
    )
    def test_priority_order_localhost_fallback(self, mock_auto_detect):
        """Test that localhost is used as final fallback."""
        result = HostResolver.get_external_host()

        assert result == "localhost"
        mock_auto_detect.assert_called_once()


class TestHostResolverIntegration:
    """Integration-style tests for realistic scenarios."""

    @patch.dict(
        "os.environ", {"MCP_MESH_HTTP_HOST": "hello-world.default.svc.cluster.local"}
    )
    def test_kubernetes_production_scenario(self):
        """Test typical Kubernetes production configuration."""
        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "hello-world.default.svc.cluster.local"
        assert binding_host == "0.0.0.0"

    @patch.dict("os.environ", {}, clear=True)
    @patch("socket.socket")
    def test_local_development_scenario(self, mock_socket_class):
        """Test local development scenario with auto-detection."""
        # Mock successful auto-detection
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.getsockname.return_value = ("192.168.1.50", 12345)
        mock_socket_class.return_value = mock_socket

        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "192.168.1.50"
        assert binding_host == "0.0.0.0"

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "localhost"})
    def test_explicit_localhost_scenario(self):
        """Test explicit localhost configuration."""
        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "localhost"
        assert binding_host == "0.0.0.0"
