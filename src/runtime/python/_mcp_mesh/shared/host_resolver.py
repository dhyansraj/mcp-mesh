"""Centralized host resolution utility for MCP Mesh agents.

Provides clean, testable logic for determining hostnames for different purposes:
- External host: What to register with the mesh registry (for other agents to connect)
- Binding host: What address the server should bind to (usually 0.0.0.0)
"""

import logging

import mcp_mesh_core

logger = logging.getLogger(__name__)


class HostResolver:
    """Centralized host resolution for MCP Mesh agents."""

    @staticmethod
    def get_external_host() -> str:
        """Get external hostname for registry advertisement.

        This is what other agents will use to connect to this agent.
        Uses Rust core for consistent config resolution across all SDKs.

        Priority order (handled by Rust core):
        1. MCP_MESH_HTTP_HOST (explicit override - for production K8s deployments)
        2. Auto-detection (socket-based external IP - for development/testing)
        3. localhost (fallback)

        Returns:
            str: External hostname for registry advertisement
        """
        # Rust core handles: ENV > auto-detect > localhost
        host = mcp_mesh_core.resolve_config_py("http_host", None)
        logger.debug(f"Resolved external host via Rust core: {host}")
        return host

    @staticmethod
    def get_binding_host() -> str:
        """Get binding hostname for server startup.

        Returns "0.0.0.0" to bind to all interfaces, allowing the server
        to accept connections from any source.

        Returns:
            str: Always "0.0.0.0" for binding to all interfaces
        """
        return "0.0.0.0"
