"""
Centralized system defaults for MCP Mesh.

This module provides access to default configuration values. For config keys
that exist in Rust core (registry_url, namespace, health_interval, etc.),
defaults are fetched from Rust to ensure consistency across all SDKs.

Python-specific defaults (like AUTO_RUN, HTTP_ENABLED) remain here as they
are not applicable to other language SDKs.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Try to import the Rust core module for defaults
try:
    import mcp_mesh_core

    _RUST_CORE_AVAILABLE = True
except ImportError:
    mcp_mesh_core = None  # type: ignore[assignment]
    _RUST_CORE_AVAILABLE = False
    logger.debug("mcp_mesh_core not available - using Python-only defaults")


def _get_rust_default(key: str, fallback: Any = None) -> Any:
    """Get default value from Rust core, with fallback for when core is unavailable."""
    if _RUST_CORE_AVAILABLE and mcp_mesh_core is not None:
        result = mcp_mesh_core.get_default_py(key)
        if result is not None:
            return result
    return fallback


def _get_rust_default_int(key: str, fallback: int) -> int:
    """Get integer default value from Rust core."""
    if _RUST_CORE_AVAILABLE and mcp_mesh_core is not None:
        result = mcp_mesh_core.get_default_py(key)
        if result is not None:
            try:
                return int(result)
            except (ValueError, TypeError):
                pass
    return fallback


class MeshDefaults:
    """Centralized defaults for all MCP Mesh configuration values.

    Config keys that exist in Rust core fetch their defaults from Rust.
    Python-specific config values have their defaults defined here.
    """

    # ==========================================================================
    # Defaults from Rust core (fetched dynamically)
    # ==========================================================================

    @classmethod
    @property
    def HEALTH_INTERVAL(cls) -> int:
        """Heartbeat interval in seconds. From Rust core."""
        return _get_rust_default_int("health_interval", 5)

    @classmethod
    @property
    def NAMESPACE(cls) -> str:
        """Default namespace. From Rust core."""
        return _get_rust_default("namespace", "default")

    @classmethod
    @property
    def REGISTRY_URL(cls) -> str:
        """Default registry URL. From Rust core."""
        return _get_rust_default("registry_url", "http://localhost:8000")

    @classmethod
    @property
    def REDIS_URL(cls) -> str:
        """Default Redis URL. From Rust core."""
        return _get_rust_default("redis_url", "redis://localhost:6379")

    # ==========================================================================
    # Python-specific defaults (not in Rust core)
    # ==========================================================================

    # HTTP server configuration
    HTTP_HOST = "0.0.0.0"  # Binding address (Rust core has auto-detect for external IP)
    HTTP_PORT = 0  # Auto-assign port
    HTTP_ENABLED = True

    # Agent behavior configuration
    AUTO_RUN = True  # Auto-start agent after decoration
    AUTO_RUN_INTERVAL = 10  # seconds - debounce for auto-run

    # Version
    VERSION = "1.0.0"

    # Registry configuration
    REGISTRY_TIMEOUT = 30  # seconds

    @classmethod
    def get_all_defaults(cls) -> dict[str, Any]:
        """
        Get all default values as a dictionary.

        Returns:
            Dictionary of all default configuration values
        """
        return {
            # From Rust core
            "health_interval": cls.HEALTH_INTERVAL,
            "namespace": cls.NAMESPACE,
            "registry_url": cls.REGISTRY_URL,
            "redis_url": cls.REDIS_URL,
            # Python-specific
            "auto_run_interval": cls.AUTO_RUN_INTERVAL,
            "http_host": cls.HTTP_HOST,
            "http_port": cls.HTTP_PORT,
            "http_enabled": cls.HTTP_ENABLED,
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
