"""
Configuration value resolver with validation rules.

Delegates config resolution to Rust core for MCP Mesh config keys to ensure
consistent behavior across all language SDKs. Non-mesh config uses Python fallback.

Resolution priority (handled by Rust core): ENV > override > default
"""

import logging
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import mcp_mesh_core

logger = logging.getLogger(__name__)

# Map env var names to Rust config key names
_ENV_TO_RUST_KEY: dict[str, str] = {
    "MCP_MESH_REGISTRY_URL": "registry_url",
    "MCP_MESH_HTTP_HOST": "http_host",
    "MCP_MESH_HTTP_PORT": "http_port",
    "MCP_MESH_NAMESPACE": "namespace",
    "MCP_MESH_AGENT_NAME": "agent_name",
    "MCP_MESH_HEALTH_INTERVAL": "health_interval",
    "MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "distributed_tracing_enabled",
    "REDIS_URL": "redis_url",
}


class ValidationRule(Enum):
    """Validation rules for configuration values."""

    PORT_RULE = "port"  # 0-65535
    TRUTHY_RULE = "truthy"  # boolean-like values
    NONZERO_RULE = "nonzero"  # positive integers ≥1
    STRING_RULE = "string"  # any string
    FLOAT_RULE = "float"  # float values
    URL_RULE = "url"  # URL validation


class ConfigResolutionError(Exception):
    """Raised when config value validation fails."""

    pass


def get_config_value(
    env_var: str,
    override: Any = None,
    default: Any = None,
    rule: ValidationRule = ValidationRule.STRING_RULE,
) -> Any:
    """
    Resolve configuration value with precedence: ENV > override > default
    Then validate against the specified rule.

    For MCP Mesh config keys (MCP_MESH_*, REDIS_URL), resolution is delegated
    to Rust core for consistency across all language SDKs.

    Args:
        env_var: Environment variable name
        override: Programmatic override value
        default: Default fallback value
        rule: Validation rule to apply

    Returns:
        Validated configuration value

    Raises:
        ConfigResolutionError: If validation fails and no valid default
    """
    # Check if this is a known mesh config key - delegate to Rust core
    rust_key = _ENV_TO_RUST_KEY.get(env_var)
    if rust_key is not None:
        raw_value = _resolve_via_rust(rust_key, override, default, rule)
    else:
        # Non-mesh config - use Python fallback
        raw_value = _resolve_via_python(env_var, override, default)

    # Validate and convert the value
    try:
        return _validate_value(raw_value, rule, env_var)
    except ConfigResolutionError as e:
        logger.error(f"Config validation failed for {env_var}: {e}")
        # Try fallback to default if validation failed
        if default is not None and raw_value != default:
            try:
                return _validate_value(default, rule, env_var)
            except ConfigResolutionError:
                pass
        return None


def _resolve_via_rust(
    rust_key: str, override: Any, default: Any, rule: ValidationRule
) -> Any:
    """Resolve config value via Rust core."""
    # Convert override to string for Rust (it expects Option<String>)
    param_str = str(override) if override is not None else None

    # Use appropriate Rust function based on validation rule
    if rule == ValidationRule.TRUTHY_RULE:
        # Boolean resolution
        param_bool = None
        if override is not None:
            if isinstance(override, bool):
                param_bool = override
            elif isinstance(override, str):
                param_bool = override.lower() in ("true", "1", "yes", "on")
            else:
                param_bool = bool(override)
        return mcp_mesh_core.resolve_config_bool_py(rust_key, param_bool)

    elif rule in (ValidationRule.PORT_RULE, ValidationRule.NONZERO_RULE):
        # Integer resolution
        param_int = None
        if override is not None:
            try:
                param_int = int(override)
            except (ValueError, TypeError):
                pass
        result = mcp_mesh_core.resolve_config_int_py(rust_key, param_int)
        return result if result is not None else default

    else:
        # String resolution (default)
        return mcp_mesh_core.resolve_config_py(rust_key, param_str)


def _resolve_via_python(env_var: str, override: Any, default: Any) -> Any:
    """Resolve config value via Python os.environ (fallback for non-mesh config)."""
    import os

    env_value = os.environ.get(env_var)
    if env_value is not None:
        return env_value
    elif override is not None:
        return override
    else:
        return default


def _validate_value(value: Any, rule: ValidationRule, env_var: str) -> Any:
    """
    Validate a value against the specified rule.

    Args:
        value: Value to validate
        rule: Validation rule to apply
        env_var: Environment variable name (for error messages)

    Returns:
        Validated and possibly converted value

    Raises:
        ConfigResolutionError: If validation fails
    """
    if value is None:
        return None

    if rule == ValidationRule.STRING_RULE:
        return str(value)

    elif rule == ValidationRule.PORT_RULE:
        try:
            port_val = int(value)
            if not (0 <= port_val <= 65535):
                raise ConfigResolutionError(
                    f"{env_var} must be between 0 and 65535, got {port_val}"
                )
            return port_val
        except ValueError as e:
            raise ConfigResolutionError(
                f"{env_var} must be a valid integer, got '{value}'"
            ) from e

    elif rule == ValidationRule.TRUTHY_RULE:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower_val = value.lower()
            if lower_val in ("true", "1", "yes", "on"):
                return True
            elif lower_val in ("false", "0", "no", "off"):
                return False
            else:
                raise ConfigResolutionError(
                    f"{env_var} must be a boolean value (true/false, 1/0, yes/no, on/off), got '{value}'"
                )
        else:
            # For non-string values, use Python's truthiness
            return bool(value)

    elif rule == ValidationRule.NONZERO_RULE:
        try:
            int_val = int(value)
            if int_val < 1:
                raise ConfigResolutionError(
                    f"{env_var} must be at least 1, got {int_val}"
                )
            return int_val
        except ValueError as e:
            raise ConfigResolutionError(
                f"{env_var} must be a valid positive integer, got '{value}'"
            ) from e

    elif rule == ValidationRule.FLOAT_RULE:
        try:
            return float(value)
        except ValueError as e:
            raise ConfigResolutionError(
                f"{env_var} must be a valid float, got '{value}'"
            ) from e

    elif rule == ValidationRule.URL_RULE:
        try:
            url_str = str(value)
            parsed = urlparse(url_str)
            if not parsed.scheme or not parsed.netloc:
                raise ConfigResolutionError(
                    f"{env_var} must be a valid URL with scheme and netloc, got '{value}'"
                )
            return url_str
        except Exception as e:
            raise ConfigResolutionError(
                f"{env_var} must be a valid URL, got '{value}'"
            ) from e

    else:
        raise ConfigResolutionError(f"Unknown validation rule: {rule}")
