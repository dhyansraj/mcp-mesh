"""TLS configuration resolved from Rust core."""

import json
import logging

logger = logging.getLogger(__name__)

_cached_config: dict | None = None


def get_tls_config() -> dict:
    """Get TLS configuration from Rust core (cached).

    Returns dict with keys: enabled, mode, cert_path, key_path, ca_path
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    try:
        import mcp_mesh_core

        raw = mcp_mesh_core.get_tls_config_py()
        _cached_config = json.loads(raw)
    except (ImportError, AttributeError):
        logger.debug("Rust core unavailable, TLS disabled")
        _cached_config = {
            "enabled": False,
            "mode": "off",
            "cert_path": None,
            "key_path": None,
            "ca_path": None,
        }

    if _cached_config.get("enabled"):
        logger.info("TLS mode: %s", _cached_config["mode"])

    return _cached_config
