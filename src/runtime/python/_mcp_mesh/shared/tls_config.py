"""TLS configuration resolved from Rust core."""

import json
import logging

logger = logging.getLogger(__name__)

_cached_config: dict | None = None


def prepare_tls(agent_name: str) -> dict:
    """Resolve TLS credentials for the agent (fetches from Vault if configured).

    Must be called before get_tls_config() when using non-file providers.
    Writes secure temp files and caches the result globally.

    Args:
        agent_name: Agent ID for certificate CN (e.g., "greeter-abc123")

    Returns:
        dict with keys: enabled, mode, provider, cert_path, key_path, ca_path
    """
    global _cached_config

    try:
        import mcp_mesh_core

        raw = mcp_mesh_core.prepare_tls_py(agent_name)
        _cached_config = json.loads(raw)
    except (ImportError, AttributeError) as e:
        logger.debug("Rust core prepare_tls unavailable: %s", e)
        _cached_config = _fallback_config()
    except Exception as e:
        logger.error("Failed to prepare TLS: %s", e)
        _cached_config = _fallback_config()

    if _cached_config.get("enabled"):
        logger.info(
            "TLS prepared: mode=%s provider=%s cert=%s",
            _cached_config["mode"],
            _cached_config.get("provider", "file"),
            _cached_config.get("cert_path", "none"),
        )

    return _cached_config


def get_tls_config() -> dict:
    """Get TLS configuration from Rust core (cached).

    Returns dict with keys: enabled, mode, provider, cert_path, key_path, ca_path
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
        _cached_config = _fallback_config()

    if _cached_config.get("enabled"):
        logger.info("TLS mode: %s", _cached_config["mode"])

    return _cached_config


def _fallback_config() -> dict:
    return {
        "enabled": False,
        "mode": "off",
        "provider": "file",
        "cert_path": None,
        "key_path": None,
        "ca_path": None,
    }
