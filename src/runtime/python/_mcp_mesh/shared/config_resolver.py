"""
Configuration value resolver with validation rules.

Provides centralized environment variable handling with consistent validation
and graceful error handling with fallback to defaults.
"""

import logging
import os
from enum import Enum
from typing import Any, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


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
    # Step 1: Determine raw value following precedence order
    raw_value = None
    source = "default"

    # Check environment variable first (highest precedence)
    env_value = os.environ.get(env_var)
    if env_value is not None:
        raw_value = env_value
        source = "environment"
    # Check override value second
    elif override is not None:
        raw_value = override
        source = "override"
    # Use default value last
    else:
        raw_value = default
        source = "default"

    # Step 2: Validate and convert the value
    try:
        validated_value = _validate_value(raw_value, rule, env_var)
        return validated_value

    except ConfigResolutionError as e:
        # If validation fails, log error and try to fall back following precedence order
        logger.error(f"Config validation failed for {env_var}: {e}")

        # Try fallback in precedence order: env > override > default
        if source == "environment" and override is not None:
            # Environment failed, try override
            try:
                logger.warning(
                    f"Falling back to override value for {env_var}: {override}"
                )
                validated_override = _validate_value(override, rule, env_var)
                return validated_override
            except ConfigResolutionError:
                # Override also failed, try default
                if default is not None:
                    try:
                        logger.warning(
                            f"Falling back to default value for {env_var}: {default}"
                        )
                        validated_default = _validate_value(default, rule, env_var)
                        return validated_default
                    except ConfigResolutionError:
                        logger.error(
                            f"All values for {env_var} are invalid, using None"
                        )
                        return None
                else:
                    logger.error(
                        f"Override and default values for {env_var} are invalid, using None"
                    )
                    return None
        elif source == "environment" and default is not None:
            # Environment failed and no override, try default
            try:
                logger.warning(
                    f"Falling back to default value for {env_var}: {default}"
                )
                validated_default = _validate_value(default, rule, env_var)
                return validated_default
            except ConfigResolutionError:
                logger.error(f"Default value for {env_var} is also invalid, using None")
                return None
        elif source == "override" and default is not None:
            # Override failed, try default
            try:
                logger.warning(
                    f"Falling back to default value for {env_var}: {default}"
                )
                validated_default = _validate_value(default, rule, env_var)
                return validated_default
            except ConfigResolutionError:
                logger.error(f"Default value for {env_var} is also invalid, using None")
                return None
        else:
            # Already tried the last option or no fallbacks available
            logger.error(f"No valid fallback for {env_var}, using None")
            return None


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
