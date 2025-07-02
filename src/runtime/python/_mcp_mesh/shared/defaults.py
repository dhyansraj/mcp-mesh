"""
Centralized system defaults for MCP Mesh.

This module provides a single source of truth for all default configuration values
in the MCP Mesh system. All defaults should be defined here and accessed through
the config_resolver system to ensure consistent precedence handling.
"""

from typing import Any


class MeshDefaults:
    """Centralized defaults for all MCP Mesh configuration values."""

    # Health and heartbeat configuration
    HEALTH_INTERVAL = 5  # seconds - fast heartbeat optimization
    AUTO_RUN_INTERVAL = 10  # seconds

    # HTTP server configuration
    HTTP_HOST = "0.0.0.0"
    HTTP_PORT = 0  # auto-assign
    HTTP_ENABLED = True

    # Agent configuration
    NAMESPACE = "default"
    AUTO_RUN = True
    VERSION = "1.0.0"

    # Registry configuration defaults (if needed in future)
    REGISTRY_TIMEOUT = 30  # seconds

    @classmethod
    def get_all_defaults(cls) -> dict[str, Any]:
        """
        Get all default values as a dictionary.

        Returns:
            Dictionary of all default configuration values
        """
        return {
            "health_interval": cls.HEALTH_INTERVAL,
            "auto_run_interval": cls.AUTO_RUN_INTERVAL,
            "http_host": cls.HTTP_HOST,
            "http_port": cls.HTTP_PORT,
            "http_enabled": cls.HTTP_ENABLED,
            "namespace": cls.NAMESPACE,
            "auto_run": cls.AUTO_RUN,
            "version": cls.VERSION,
            "registry_timeout": cls.REGISTRY_TIMEOUT,
        }

    @classmethod
    def get_default(cls, key: str) -> Any:
        """
        Get a specific default value by key.

        Args:
            key: Configuration key to get default for

        Returns:
            Default value for the key, or None if not found
        """
        defaults = cls.get_all_defaults()
        return defaults.get(key)
