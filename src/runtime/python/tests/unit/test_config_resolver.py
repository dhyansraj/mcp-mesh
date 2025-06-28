"""
Tests for the configuration resolver utility.
"""

import os
from unittest.mock import patch

import pytest

from _mcp_mesh.shared.config_resolver import (
    ConfigResolutionError,
    ValidationRule,
    get_config_value,
)


class TestConfigResolver:
    """Test the configuration resolver utility."""

    def test_string_rule_validation(self):
        """Test STRING_RULE validation."""
        # Valid strings
        assert (
            get_config_value(
                "TEST_VAR", override="hello", rule=ValidationRule.STRING_RULE
            )
            == "hello"
        )
        assert (
            get_config_value("TEST_VAR", override=123, rule=ValidationRule.STRING_RULE)
            == "123"
        )

    def test_port_rule_validation(self):
        """Test PORT_RULE validation."""
        # Valid ports
        assert (
            get_config_value("TEST_VAR", override=8080, rule=ValidationRule.PORT_RULE)
            == 8080
        )
        assert (
            get_config_value("TEST_VAR", override=0, rule=ValidationRule.PORT_RULE) == 0
        )
        assert (
            get_config_value("TEST_VAR", override=65535, rule=ValidationRule.PORT_RULE)
            == 65535
        )

        # Invalid port - should fall back to default
        result = get_config_value(
            "TEST_VAR", override=70000, default=8080, rule=ValidationRule.PORT_RULE
        )
        assert result == 8080  # Falls back to default

    def test_truthy_rule_validation(self):
        """Test TRUTHY_RULE validation."""
        # Valid boolean values
        assert (
            get_config_value(
                "TEST_VAR", override="true", rule=ValidationRule.TRUTHY_RULE
            )
            == True
        )
        assert (
            get_config_value(
                "TEST_VAR", override="false", rule=ValidationRule.TRUTHY_RULE
            )
            == False
        )
        assert (
            get_config_value("TEST_VAR", override="1", rule=ValidationRule.TRUTHY_RULE)
            == True
        )
        assert (
            get_config_value("TEST_VAR", override="0", rule=ValidationRule.TRUTHY_RULE)
            == False
        )
        assert (
            get_config_value(
                "TEST_VAR", override="yes", rule=ValidationRule.TRUTHY_RULE
            )
            == True
        )
        assert (
            get_config_value("TEST_VAR", override="no", rule=ValidationRule.TRUTHY_RULE)
            == False
        )
        assert (
            get_config_value("TEST_VAR", override="on", rule=ValidationRule.TRUTHY_RULE)
            == True
        )
        assert (
            get_config_value(
                "TEST_VAR", override="off", rule=ValidationRule.TRUTHY_RULE
            )
            == False
        )

        # Case insensitive
        assert (
            get_config_value(
                "TEST_VAR", override="TRUE", rule=ValidationRule.TRUTHY_RULE
            )
            == True
        )
        assert (
            get_config_value(
                "TEST_VAR", override="False", rule=ValidationRule.TRUTHY_RULE
            )
            == False
        )

        # Invalid boolean - should fall back to default
        result = get_config_value(
            "TEST_VAR",
            override="invalid",
            default=True,
            rule=ValidationRule.TRUTHY_RULE,
        )
        assert result == True  # Falls back to default

    def test_nonzero_rule_validation(self):
        """Test NONZERO_RULE validation."""
        # Valid positive integers
        assert (
            get_config_value("TEST_VAR", override=1, rule=ValidationRule.NONZERO_RULE)
            == 1
        )
        assert (
            get_config_value("TEST_VAR", override=100, rule=ValidationRule.NONZERO_RULE)
            == 100
        )

        # Invalid nonzero - should fall back to default
        result = get_config_value(
            "TEST_VAR", override=0, default=30, rule=ValidationRule.NONZERO_RULE
        )
        assert result == 30  # Falls back to default

        result = get_config_value(
            "TEST_VAR", override=-5, default=30, rule=ValidationRule.NONZERO_RULE
        )
        assert result == 30  # Falls back to default

    def test_float_rule_validation(self):
        """Test FLOAT_RULE validation."""
        # Valid floats
        assert (
            get_config_value("TEST_VAR", override=1.5, rule=ValidationRule.FLOAT_RULE)
            == 1.5
        )
        assert (
            get_config_value(
                "TEST_VAR", override="3.14", rule=ValidationRule.FLOAT_RULE
            )
            == 3.14
        )
        assert (
            get_config_value("TEST_VAR", override=42, rule=ValidationRule.FLOAT_RULE)
            == 42.0
        )

        # Invalid float - should fall back to default
        result = get_config_value(
            "TEST_VAR", override="invalid", default=1.0, rule=ValidationRule.FLOAT_RULE
        )
        assert result == 1.0  # Falls back to default

    def test_url_rule_validation(self):
        """Test URL_RULE validation."""
        # Valid URLs
        assert (
            get_config_value(
                "TEST_VAR",
                override="http://localhost:8080",
                rule=ValidationRule.URL_RULE,
            )
            == "http://localhost:8080"
        )
        assert (
            get_config_value(
                "TEST_VAR", override="https://example.com", rule=ValidationRule.URL_RULE
            )
            == "https://example.com"
        )

        # Invalid URL - should fall back to default
        result = get_config_value(
            "TEST_VAR",
            override="not-a-url",
            default="http://localhost",
            rule=ValidationRule.URL_RULE,
        )
        assert result == "http://localhost"  # Falls back to default

    def test_precedence_order(self):
        """Test that precedence order is ENV > override > default."""
        with patch.dict(os.environ, {"TEST_PRECEDENCE": "env_value"}):
            # Environment variable should take precedence
            result = get_config_value(
                "TEST_PRECEDENCE",
                override="override_value",
                default="default_value",
                rule=ValidationRule.STRING_RULE,
            )
            assert result == "env_value"

        # Without environment variable, override should be used
        result = get_config_value(
            "TEST_PRECEDENCE_MISSING",
            override="override_value",
            default="default_value",
            rule=ValidationRule.STRING_RULE,
        )
        assert result == "override_value"

        # Without environment variable or override, default should be used
        result = get_config_value(
            "TEST_PRECEDENCE_MISSING",
            default="default_value",
            rule=ValidationRule.STRING_RULE,
        )
        assert result == "default_value"

    def test_fallback_on_validation_failure(self):
        """Test fallback behavior when validation fails."""
        # Environment variable is invalid, should fall back to override
        with patch.dict(os.environ, {"TEST_FALLBACK": "invalid_port"}):
            result = get_config_value(
                "TEST_FALLBACK",
                override=8080,
                default=3000,
                rule=ValidationRule.PORT_RULE,
            )
            assert result == 8080  # Falls back to override

        # Environment variable and override are invalid, should fall back to default
        with patch.dict(os.environ, {"TEST_FALLBACK": "invalid_port"}):
            result = get_config_value(
                "TEST_FALLBACK",
                override=70000,  # Invalid port
                default=3000,
                rule=ValidationRule.PORT_RULE,
            )
            assert result == 3000  # Falls back to default

        # All values are invalid, should return None
        with patch.dict(os.environ, {"TEST_FALLBACK": "invalid_port"}):
            result = get_config_value(
                "TEST_FALLBACK",
                override=70000,  # Invalid port
                default=70000,  # Also invalid port
                rule=ValidationRule.PORT_RULE,
            )
            assert result is None  # All values invalid

    def test_none_handling(self):
        """Test handling of None values."""
        # None values should be returned as-is
        assert (
            get_config_value(
                "TEST_NONE", override=None, rule=ValidationRule.STRING_RULE
            )
            is None
        )
        assert (
            get_config_value("TEST_NONE", default=None, rule=ValidationRule.PORT_RULE)
            is None
        )
