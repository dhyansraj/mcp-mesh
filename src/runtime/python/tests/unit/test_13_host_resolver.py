"""
Unit tests for HostResolver utility.

Tests the centralized host resolution logic for different deployment scenarios.
Since host resolution is delegated to Rust core, these tests mock the Rust core
functions rather than Python's socket module.
"""

from unittest.mock import patch

import mcp_mesh_core
from _mcp_mesh.shared.host_resolver import HostResolver


class TestHostResolver:
    """Test the HostResolver utility class."""

    def test_get_binding_host_always_returns_all_interfaces(self):
        """Test get_binding_host always returns 0.0.0.0."""
        result = HostResolver.get_binding_host()
        assert result == "0.0.0.0"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="localhost")
    def test_get_external_host_fallback_to_localhost(self, mock_resolve):
        """Test get_external_host falls back to localhost when Rust core returns localhost."""
        result = HostResolver.get_external_host()
        assert result == "localhost"
        mock_resolve.assert_called_once_with("http_host", None)

    @patch.object(
        mcp_mesh_core,
        "resolve_config_py",
        return_value="my-service.default.svc.cluster.local",
    )
    def test_get_external_host_uses_explicit_override(self, mock_resolve):
        """Test get_external_host uses value from Rust core (which handles MCP_MESH_HTTP_HOST)."""
        result = HostResolver.get_external_host()
        assert result == "my-service.default.svc.cluster.local"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="localhost")
    def test_get_external_host_explicit_localhost(self, mock_resolve):
        """Test get_external_host respects explicit localhost setting."""
        result = HostResolver.get_external_host()
        assert result == "localhost"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="192.168.1.100")
    def test_get_external_host_auto_detection_success(self, mock_resolve):
        """Test get_external_host with auto-detected IP from Rust core."""
        result = HostResolver.get_external_host()
        assert result == "192.168.1.100"
        mock_resolve.assert_called_once_with("http_host", None)


class TestHostResolverPriorityOrder:
    """Test that Rust core handles the priority order correctly."""

    @patch.object(
        mcp_mesh_core, "resolve_config_py", return_value="priority-1.example.com"
    )
    def test_priority_order_explicit_host_wins(self, mock_resolve):
        """Test that Rust core returns explicit host when set via env var."""
        result = HostResolver.get_external_host()
        assert result == "priority-1.example.com"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="192.168.1.100")
    def test_priority_order_auto_detection_second(self, mock_resolve):
        """Test that Rust core returns auto-detected IP when no env var is set."""
        result = HostResolver.get_external_host()
        assert result == "192.168.1.100"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="localhost")
    def test_priority_order_localhost_fallback(self, mock_resolve):
        """Test that Rust core returns localhost as fallback."""
        result = HostResolver.get_external_host()
        assert result == "localhost"


class TestHostResolverIntegration:
    """Integration-style tests for realistic scenarios."""

    @patch.object(
        mcp_mesh_core,
        "resolve_config_py",
        return_value="hello-world.default.svc.cluster.local",
    )
    def test_kubernetes_production_scenario(self, mock_resolve):
        """Test typical Kubernetes production configuration."""
        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "hello-world.default.svc.cluster.local"
        assert binding_host == "0.0.0.0"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="192.168.1.50")
    def test_local_development_scenario(self, mock_resolve):
        """Test local development scenario with auto-detection."""
        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "192.168.1.50"
        assert binding_host == "0.0.0.0"

    @patch.object(mcp_mesh_core, "resolve_config_py", return_value="localhost")
    def test_explicit_localhost_scenario(self, mock_resolve):
        """Test explicit localhost configuration."""
        external_host = HostResolver.get_external_host()
        binding_host = HostResolver.get_binding_host()

        assert external_host == "localhost"
        assert binding_host == "0.0.0.0"


class TestHostResolverRustCoreDelegation:
    """Test that HostResolver correctly delegates to Rust core."""

    def test_get_external_host_calls_rust_core(self):
        """Test that get_external_host calls Rust core with correct parameters."""
        with patch.object(
            mcp_mesh_core, "resolve_config_py", return_value="10.0.0.1"
        ) as mock_resolve:
            result = HostResolver.get_external_host()

            # Verify Rust core is called with "http_host" key and None for param
            mock_resolve.assert_called_once_with("http_host", None)
            assert result == "10.0.0.1"

    def test_rust_core_receives_none_param(self):
        """Test that Rust core receives None for param (Rust handles ENV vars)."""
        with patch.object(
            mcp_mesh_core, "resolve_config_py", return_value="auto-detected-ip"
        ) as mock_resolve:
            HostResolver.get_external_host()

            # The second argument should always be None (SDK doesn't set host explicitly)
            args = mock_resolve.call_args[0]
            assert args[0] == "http_host"
            assert args[1] is None
