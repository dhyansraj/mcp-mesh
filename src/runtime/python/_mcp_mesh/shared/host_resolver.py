"""Centralized host resolution utility for MCP Mesh agents.

Provides clean, testable logic for determining hostnames for different purposes:
- External host: What to register with the mesh registry (for other agents to connect)
- Binding host: What address the server should bind to (usually 0.0.0.0)
"""

import logging
import os
import socket

logger = logging.getLogger(__name__)


class HostResolver:
    """Centralized host resolution for MCP Mesh agents."""

    @staticmethod
    def get_external_host() -> str:
        """Get external hostname for registry advertisement.

        This is what other agents will use to connect to this agent.

        Priority order:
        1. MCP_MESH_HTTP_HOST (explicit override - for production K8s deployments)
        2. Auto-detection (socket-based external IP - for development/testing)
        3. localhost (fallback)

        Returns:
            str: External hostname for registry advertisement
        """
        # Priority 1: Explicit override for production deployments
        explicit_host = os.getenv("MCP_MESH_HTTP_HOST")
        if explicit_host:
            logger.debug(f"Using explicit external host: {explicit_host}")
            return explicit_host

        # Priority 2: Auto-detection for development/testing
        try:
            auto_detected = HostResolver._auto_detect_external_ip()
            logger.debug(f"Auto-detected external host: {auto_detected}")
            return auto_detected
        except Exception as e:
            logger.warning(f"Failed to auto-detect external IP: {e}")

        # Priority 3: Fallback
        logger.debug("Using fallback external host: localhost")
        return "localhost"

    @staticmethod
    def get_binding_host() -> str:
        """Get binding hostname for server startup.

        Returns "0.0.0.0" to bind to all interfaces, allowing the server
        to accept connections from any source.

        Returns:
            str: Always "0.0.0.0" for binding to all interfaces
        """
        return "0.0.0.0"

    @staticmethod
    def _auto_detect_external_ip() -> str:
        """Auto-detect external IP by connecting to a public DNS server.

        This determines what IP address would be used for outbound connections,
        which is typically the correct IP for other services to connect back to.

        Returns:
            str: Auto-detected external IP address

        Raises:
            Exception: If auto-detection fails
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Connect to a public DNS server to determine our outbound IP
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]

            # Validate the IP isn't localhost
            if local_ip.startswith("127."):
                raise Exception(
                    "Auto-detected IP is localhost, not useful for external connections"
                )

            return local_ip
