"""Unit tests for CLI configuration management."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.config import (
    DEFAULT_CONFIG,
    CLIConfig,
    CLIConfigManager,
)
from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.shared.configuration import (
    InvalidConfigurationError,
)


class TestCLIConfig:
    """Test CLIConfig dataclass."""

    def test_default_config_values(self):
        """Test default configuration values."""
        config = CLIConfig()

        assert config.registry_port == 8080
        assert config.registry_host == "localhost"
        assert config.db_path == "./dev_registry.db"
        assert config.log_level == "INFO"
        assert config.health_check_interval == 30
        assert config.auto_restart is True
        assert config.watch_files is True
        assert config.debug_mode is False
        assert config.startup_timeout == 30
        assert config.shutdown_timeout == 30
        assert config.enable_background is False
        assert config.pid_file == "./mcp_mesh_dev.pid"

    def test_config_validation_valid(self):
        """Test configuration validation with valid values."""
        config = CLIConfig(
            registry_port=8081,
            registry_host="0.0.0.0",
            log_level="DEBUG",
            health_check_interval=60,
            startup_timeout=45,
            shutdown_timeout=60,
        )
        # Should not raise any exception
        config.validate()

    def test_config_validation_invalid_port(self):
        """Test configuration validation with invalid port."""
        with pytest.raises(InvalidConfigurationError, match="Invalid registry_port"):
            CLIConfig(registry_port=0)

        with pytest.raises(InvalidConfigurationError, match="Invalid registry_port"):
            CLIConfig(registry_port=99999)

    def test_config_validation_invalid_host(self):
        """Test configuration validation with invalid host."""
        with pytest.raises(InvalidConfigurationError, match="registry_host must be"):
            CLIConfig(registry_host="")

        with pytest.raises(InvalidConfigurationError, match="registry_host must be"):
            CLIConfig(registry_host=None)

    def test_config_validation_invalid_log_level(self):
        """Test configuration validation with invalid log level."""
        with pytest.raises(InvalidConfigurationError, match="Invalid log_level"):
            CLIConfig(log_level="INVALID")

    def test_config_validation_invalid_timeouts(self):
        """Test configuration validation with invalid timeout values."""
        with pytest.raises(
            InvalidConfigurationError, match="health_check_interval must be positive"
        ):
            CLIConfig(health_check_interval=0)

        with pytest.raises(
            InvalidConfigurationError, match="startup_timeout must be positive"
        ):
            CLIConfig(startup_timeout=-1)

        with pytest.raises(
            InvalidConfigurationError, match="shutdown_timeout must be positive"
        ):
            CLIConfig(shutdown_timeout=0)

    def test_config_to_dict(self):
        """Test configuration conversion to dictionary."""
        config = CLIConfig(registry_port=8081, debug_mode=True)
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert config_dict["registry_port"] == 8081
        assert config_dict["debug_mode"] is True
        assert config_dict["registry_host"] == "localhost"  # Default value

    def test_config_from_dict(self):
        """Test configuration creation from dictionary."""
        config_data = {
            "registry_port": 8081,
            "registry_host": "0.0.0.0",
            "debug_mode": True,
            "unknown_field": "ignored",  # Should be filtered out
        }

        config = CLIConfig.from_dict(config_data)

        assert config.registry_port == 8081
        assert config.registry_host == "0.0.0.0"
        assert config.debug_mode is True
        # Unknown field should not cause issues
        assert not hasattr(config, "unknown_field")

    def test_config_merge(self):
        """Test configuration merging."""
        base_config = CLIConfig(registry_port=8080, debug_mode=False)
        override_config = CLIConfig(registry_port=8081, log_level="DEBUG")

        merged = base_config.merge(override_config)

        assert merged.registry_port == 8081  # Overridden
        assert merged.log_level == "DEBUG"  # Overridden
        assert merged.debug_mode is False  # From base
        assert merged.registry_host == "localhost"  # Default

    def test_config_merge_only_non_defaults(self):
        """Test configuration merging only applies non-default values."""
        base_config = CLIConfig(registry_port=8081)
        # Create override with all defaults except one field
        override_config = CLIConfig(debug_mode=True)

        merged = base_config.merge(override_config)

        assert merged.registry_port == 8081  # From base (non-default)
        assert merged.debug_mode is True  # From override (non-default)
        assert merged.registry_host == "localhost"  # Default


class TestCLIConfigManager:
    """Test CLIConfigManager class."""

    def test_default_config_path(self):
        """Test default configuration file path."""
        manager = CLIConfigManager()
        expected_path = Path.home() / ".mcp_mesh" / "cli_config.json"
        assert manager.config_path == expected_path

    def test_custom_config_path(self):
        """Test custom configuration file path."""
        custom_path = Path("/tmp/custom_config.json")
        manager = CLIConfigManager(config_path=custom_path)
        assert manager.config_path == custom_path

    def test_load_config_defaults_only(self):
        """Test loading configuration with defaults only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            config = manager.load_config(create_default=False)

            # Should return default values
            assert config.registry_port == 8080
            assert config.registry_host == "localhost"
            assert config.debug_mode is False

    def test_load_config_from_file(self):
        """Test loading configuration from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"

            # Create config file
            config_data = {
                "registry_port": 8081,
                "registry_host": "0.0.0.0",
                "debug_mode": True,
            }
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            manager = CLIConfigManager(config_path=config_path)
            config = manager.load_config()

            assert config.registry_port == 8081
            assert config.registry_host == "0.0.0.0"
            assert config.debug_mode is True

    def test_load_config_from_environment(self):
        """Test loading configuration from environment variables."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            env_vars = {
                "MCP_MESH_REGISTRY_PORT": "8081",
                "MCP_MESH_REGISTRY_HOST": "0.0.0.0",
                "MCP_MESH_DEBUG_MODE": "true",
                "MCP_MESH_LOG_LEVEL": "DEBUG",
            }

            with patch.dict("os.environ", env_vars):
                config = manager.load_config(create_default=False)

            assert config.registry_port == 8081
            assert config.registry_host == "0.0.0.0"
            assert config.debug_mode is True
            assert config.log_level == "DEBUG"

    def test_load_config_cli_overrides(self):
        """Test loading configuration with CLI argument overrides."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            cli_args = {"registry_port": 8082, "debug": True, "log_level": "WARNING"}

            config = manager.load_config(override_args=cli_args, create_default=False)

            assert config.registry_port == 8082
            assert config.debug_mode is True
            assert config.log_level == "WARNING"

    def test_load_config_precedence(self):
        """Test configuration loading precedence (CLI > file > env > defaults)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"

            # Create config file
            file_config = {"registry_port": 8081, "debug_mode": True}
            with open(config_path, "w") as f:
                json.dump(file_config, f)

            manager = CLIConfigManager(config_path=config_path)

            # Set environment variables
            env_vars = {"MCP_MESH_REGISTRY_PORT": "8082", "MCP_MESH_LOG_LEVEL": "DEBUG"}

            # CLI overrides
            cli_args = {"registry_port": 8083, "background": True}

            with patch.dict("os.environ", env_vars):
                config = manager.load_config(
                    override_args=cli_args, create_default=False
                )

            # CLI should take precedence
            assert config.registry_port == 8083
            # File should override env and defaults
            assert config.debug_mode is True
            # Env should override defaults
            assert config.log_level == "DEBUG"
            # CLI should set new values
            assert config.enable_background is True

    def test_save_config(self):
        """Test saving configuration to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            config = CLIConfig(registry_port=8081, debug_mode=True)
            manager.save_config(config)

            # Verify file was created and contains correct data
            assert config_path.exists()

            with open(config_path) as f:
                saved_data = json.load(f)

            assert saved_data["registry_port"] == 8081
            assert saved_data["debug_mode"] is True

    def test_get_config_caching(self):
        """Test configuration caching behavior."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            # First call should load config
            config1 = manager.get_config()

            # Second call should return cached config
            config2 = manager.get_config()

            assert config1 is config2

    def test_update_config(self):
        """Test updating configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            # Load initial config
            config = manager.get_config()
            assert config.registry_port == 8080

            # Update config
            manager.update_config(registry_port=8081, debug_mode=True)

            updated_config = manager.get_config()
            assert updated_config.registry_port == 8081
            assert updated_config.debug_mode is True

    def test_reset_to_defaults(self):
        """Test resetting configuration to defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            # Update config first
            manager.update_config(registry_port=8081, debug_mode=True)

            # Reset to defaults
            default_config = manager.reset_to_defaults()

            assert default_config.registry_port == 8080
            assert default_config.debug_mode is False

            # Verify get_config returns defaults too
            current_config = manager.get_config()
            assert current_config.registry_port == 8080
            assert current_config.debug_mode is False

    def test_show_config_yaml_format(self):
        """Test showing configuration in YAML format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            output = manager.show_config(format="yaml")

            assert "registry_port: 8080" in output
            assert "registry_host: localhost" in output
            assert "debug_mode: False" in output

    def test_show_config_json_format(self):
        """Test showing configuration in JSON format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            output = manager.show_config(format="json")

            # Should be valid JSON
            parsed = json.loads(output)
            assert parsed["registry_port"] == 8080
            assert parsed["registry_host"] == "localhost"
            assert parsed["debug_mode"] is False

    def test_show_config_invalid_format(self):
        """Test showing configuration with invalid format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            with pytest.raises(ValueError, match="Unsupported format"):
                manager.show_config(format="xml")

    def test_load_config_invalid_json_file(self):
        """Test loading configuration from invalid JSON file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"

            # Create invalid JSON file
            with open(config_path, "w") as f:
                f.write("invalid json content")

            manager = CLIConfigManager(config_path=config_path)

            with pytest.raises(InvalidConfigurationError, match="Invalid JSON"):
                manager.load_config()

    def test_load_config_invalid_env_values(self):
        """Test loading configuration with invalid environment values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            env_vars = {"MCP_MESH_REGISTRY_PORT": "invalid_port"}

            with patch.dict("os.environ", env_vars):
                with pytest.raises(
                    InvalidConfigurationError, match="Invalid integer value"
                ):
                    manager.load_config(create_default=False)

    def test_convert_cli_args_mapping(self):
        """Test CLI argument to config field mapping."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            cli_args = {
                "registry_port": 8081,
                "registry_host": "0.0.0.0",
                "debug": True,
                "background": True,
                "irrelevant_arg": "ignored",
            }

            converted = manager._convert_cli_args(cli_args)

            assert converted["registry_port"] == 8081
            assert converted["registry_host"] == "0.0.0.0"
            assert converted["debug_mode"] is True
            assert converted["enable_background"] is True
            assert "irrelevant_arg" not in converted


class TestEnvironmentVariableHandling:
    """Test environment variable handling."""

    def test_env_var_boolean_conversion(self):
        """Test boolean environment variable conversion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            # Test true values
            true_values = ["true", "1", "yes", "on", "TRUE", "True"]
            for value in true_values:
                env_vars = {"MCP_MESH_DEBUG_MODE": value}
                with patch.dict("os.environ", env_vars):
                    config = manager.load_config(create_default=False)
                    assert config.debug_mode is True, f"Failed for value: {value}"

            # Test false values
            false_values = ["false", "0", "no", "off", "FALSE", "False"]
            for value in false_values:
                env_vars = {"MCP_MESH_DEBUG_MODE": value}
                with patch.dict("os.environ", env_vars):
                    config = manager.load_config(create_default=False)
                    assert config.debug_mode is False, f"Failed for value: {value}"

    def test_env_var_integer_conversion(self):
        """Test integer environment variable conversion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            env_vars = {
                "MCP_MESH_REGISTRY_PORT": "8081",
                "MCP_MESH_HEALTH_CHECK_INTERVAL": "60",
                "MCP_MESH_STARTUP_TIMEOUT": "45",
            }

            with patch.dict("os.environ", env_vars):
                config = manager.load_config(create_default=False)

            assert config.registry_port == 8081
            assert config.health_check_interval == 60
            assert config.startup_timeout == 45

    def test_env_var_string_conversion(self):
        """Test string environment variable conversion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            manager = CLIConfigManager(config_path=config_path)

            env_vars = {
                "MCP_MESH_REGISTRY_HOST": "0.0.0.0",
                "MCP_MESH_DB_PATH": "/tmp/test.db",
                "MCP_MESH_LOG_LEVEL": "DEBUG",
            }

            with patch.dict("os.environ", env_vars):
                config = manager.load_config(create_default=False)

            assert config.registry_host == "0.0.0.0"
            assert config.db_path == "/tmp/test.db"
            assert config.log_level == "DEBUG"


class TestDefaultConfigConstants:
    """Test default configuration constants."""

    def test_default_config_values(self):
        """Test DEFAULT_CONFIG contains expected values."""
        assert DEFAULT_CONFIG["registry_port"] == 8080
        assert DEFAULT_CONFIG["registry_host"] == "localhost"
        assert DEFAULT_CONFIG["db_path"] == "./dev_registry.db"
        assert DEFAULT_CONFIG["log_level"] == "INFO"
        assert DEFAULT_CONFIG["health_check_interval"] == 30
        assert DEFAULT_CONFIG["auto_restart"] is True
        assert DEFAULT_CONFIG["watch_files"] is True
        assert DEFAULT_CONFIG["debug_mode"] is False
        assert DEFAULT_CONFIG["startup_timeout"] == 30
        assert DEFAULT_CONFIG["shutdown_timeout"] == 30
        assert DEFAULT_CONFIG["enable_background"] is False
        assert DEFAULT_CONFIG["pid_file"] == "./mcp_mesh_dev.pid"

    def test_default_config_matches_dataclass(self):
        """Test DEFAULT_CONFIG matches CLIConfig defaults."""
        default_config_obj = CLIConfig()
        default_dict = default_config_obj.to_dict()

        for key, value in DEFAULT_CONFIG.items():
            assert key in default_dict
            assert (
                default_dict[key] == value
            ), f"Mismatch for {key}: {default_dict[key]} != {value}"


if __name__ == "__main__":
    pytest.main([__file__])
