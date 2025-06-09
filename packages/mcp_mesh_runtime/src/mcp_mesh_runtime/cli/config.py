"""Configuration management for MCP Mesh Developer CLI."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..shared.configuration import (
    ConfigurationError,
    InvalidConfigurationError,
)


@dataclass
class CLIConfig:
    """Configuration class for MCP Mesh Developer CLI."""

    # Registry settings
    registry_port: int = 8080
    registry_host: str = "localhost"

    # Database settings
    db_path: str = "./dev_registry.db"

    # Logging settings
    log_level: str = "INFO"

    # Health monitoring
    health_check_interval: int = 30

    # Development settings
    auto_restart: bool = True
    watch_files: bool = True
    debug_mode: bool = False

    # Timeout settings
    startup_timeout: int = 30
    shutdown_timeout: int = 30

    # Background service settings
    enable_background: bool = False
    pid_file: str = "./mcp_mesh_dev.pid"

    def __post_init__(self):
        """Validate configuration after initialization."""
        self.validate()

    def validate(self) -> None:
        """Validate configuration values."""
        errors = []

        # Validate port
        if not (1 <= self.registry_port <= 65535):
            errors.append(
                f"Invalid registry_port: {self.registry_port}. Must be between 1 and 65535."
            )

        # Validate host
        if not self.registry_host or not isinstance(self.registry_host, str):
            errors.append("registry_host must be a non-empty string.")

        # Validate log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            errors.append(
                f"Invalid log_level: {self.log_level}. Must be one of {valid_log_levels}."
            )

        # Validate timeouts
        if self.health_check_interval <= 0:
            errors.append("health_check_interval must be positive.")

        if self.startup_timeout <= 0:
            errors.append("startup_timeout must be positive.")

        if self.shutdown_timeout <= 0:
            errors.append("shutdown_timeout must be positive.")

        # Validate paths
        try:
            db_path = Path(self.db_path)
            if db_path.exists() and not db_path.is_file():
                errors.append(f"db_path exists but is not a file: {self.db_path}")

            # Ensure parent directory exists or can be created
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Invalid db_path: {self.db_path}. Error: {e}")

        if errors:
            raise InvalidConfigurationError(
                f"Configuration validation failed: {'; '.join(errors)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CLIConfig":
        """Create configuration from dictionary."""
        # Filter out unknown keys
        known_keys = {field.name for field in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_keys}
        return cls(**filtered_data)

    def merge(self, other: "CLIConfig") -> "CLIConfig":
        """Merge this configuration with another, with other taking precedence."""
        merged_data = self.to_dict()
        other_data = other.to_dict()

        # Only override with non-default values
        for key, value in other_data.items():
            if value != getattr(CLIConfig(), key, None):
                merged_data[key] = value

        return CLIConfig.from_dict(merged_data)


class CLIConfigManager:
    """Manager for CLI configuration with multiple sources."""

    DEFAULT_CONFIG_PATH = Path.home() / ".mcp_mesh" / "cli_config.json"

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: CLIConfig | None = None

    def load_config(
        self,
        override_args: dict[str, Any] | None = None,
        create_default: bool = True,
    ) -> CLIConfig:
        """Load configuration from multiple sources with precedence:
        1. Command-line arguments (highest priority)
        2. Configuration file
        3. Environment variables
        4. Defaults (lowest priority)
        """
        # Start with defaults
        config = CLIConfig()

        # Apply environment variables
        env_config = self._load_from_environment()
        if env_config:
            config = config.merge(env_config)

        # Apply configuration file
        file_config = self._load_from_file()
        if file_config:
            config = config.merge(file_config)

        # Apply command-line overrides
        if override_args:
            # Convert command-line args to config format
            cli_overrides = self._convert_cli_args(override_args)
            if cli_overrides:
                override_config = CLIConfig.from_dict(cli_overrides)
                config = config.merge(override_config)

        # Validate final configuration
        config.validate()

        # Save default config if it doesn't exist and create_default is True
        if create_default and not self.config_path.exists():
            self.save_config(config)

        self._config = config
        return config

    def save_config(self, config: CLIConfig) -> None:
        """Save configuration to file."""
        try:
            # Ensure parent directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, sort_keys=True)

        except Exception as e:
            raise ConfigurationError(
                f"Failed to save configuration to {self.config_path}: {e}"
            )

    def _load_from_file(self) -> CLIConfig | None:
        """Load configuration from JSON file."""
        if not self.config_path.exists():
            return None

        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)

            return CLIConfig.from_dict(data)

        except json.JSONDecodeError as e:
            raise InvalidConfigurationError(
                f"Invalid JSON in config file {self.config_path}: {e}"
            )
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load config file {self.config_path}: {e}"
            )

    def _load_from_environment(self) -> CLIConfig | None:
        """Load configuration from environment variables."""
        env_mapping = {
            "MCP_MESH_REGISTRY_PORT": "registry_port",
            "MCP_MESH_REGISTRY_HOST": "registry_host",
            "MCP_MESH_DB_PATH": "db_path",
            "MCP_MESH_LOG_LEVEL": "log_level",
            "MCP_MESH_HEALTH_CHECK_INTERVAL": "health_check_interval",
            "MCP_MESH_AUTO_RESTART": "auto_restart",
            "MCP_MESH_WATCH_FILES": "watch_files",
            "MCP_MESH_DEBUG_MODE": "debug_mode",
            "MCP_MESH_STARTUP_TIMEOUT": "startup_timeout",
            "MCP_MESH_SHUTDOWN_TIMEOUT": "shutdown_timeout",
            "MCP_MESH_ENABLE_BACKGROUND": "enable_background",
            "MCP_MESH_PID_FILE": "pid_file",
        }

        config_data = {}

        for env_var, config_key in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert string values to appropriate types
                if config_key in [
                    "registry_port",
                    "health_check_interval",
                    "startup_timeout",
                    "shutdown_timeout",
                ]:
                    try:
                        config_data[config_key] = int(value)
                    except ValueError:
                        raise InvalidConfigurationError(
                            f"Invalid integer value for {env_var}: {value}"
                        )
                elif config_key in [
                    "auto_restart",
                    "watch_files",
                    "debug_mode",
                    "enable_background",
                ]:
                    config_data[config_key] = value.lower() in (
                        "true",
                        "1",
                        "yes",
                        "on",
                    )
                else:
                    config_data[config_key] = value

        return CLIConfig.from_dict(config_data) if config_data else None

    def _convert_cli_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Convert command-line arguments to configuration format."""
        # Map CLI argument names to config field names
        arg_mapping = {
            "registry_port": "registry_port",
            "registry_host": "registry_host",
            "db_path": "db_path",
            "log_level": "log_level",
            "health_check_interval": "health_check_interval",
            "debug": "debug_mode",
            "background": "enable_background",
            "startup_timeout": "startup_timeout",
            "shutdown_timeout": "shutdown_timeout",
        }

        config_data = {}

        for arg_name, config_key in arg_mapping.items():
            if arg_name in args and args[arg_name] is not None:
                config_data[config_key] = args[arg_name]

        return config_data

    def get_config(self) -> CLIConfig:
        """Get the current configuration."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def update_config(self, **kwargs) -> None:
        """Update configuration with new values."""
        if self._config is None:
            self._config = self.load_config()

        # Create new config with updates
        current_data = self._config.to_dict()
        current_data.update(kwargs)

        self._config = CLIConfig.from_dict(current_data)
        self._config.validate()

    def reset_to_defaults(self) -> CLIConfig:
        """Reset configuration to defaults."""
        self._config = CLIConfig()
        return self._config

    def show_config(self, format: str = "yaml") -> str:
        """Show current configuration in specified format."""
        config = self.get_config()

        if format.lower() == "json":
            return json.dumps(config.to_dict(), indent=2, sort_keys=True)
        elif format.lower() == "yaml":
            # Simple YAML-like output without requiring PyYAML
            lines = []
            for key, value in sorted(config.to_dict().items()):
                lines.append(f"{key}: {value}")
            return "\n".join(lines)
        else:
            raise ValueError(f"Unsupported format: {format}")


# Default configuration constants
DEFAULT_CONFIG = {
    "registry_port": 8080,
    "registry_host": "localhost",
    "db_path": "./dev_registry.db",
    "log_level": "INFO",
    "health_check_interval": 30,
    "auto_restart": True,
    "watch_files": True,
    "debug_mode": False,
    "startup_timeout": 30,
    "shutdown_timeout": 30,
    "enable_background": False,
    "pid_file": "./mcp_mesh_dev.pid",
}


# Global configuration manager instance
cli_config_manager = CLIConfigManager()


__all__ = [
    "CLIConfig",
    "CLIConfigManager",
    "cli_config_manager",
    "DEFAULT_CONFIG",
]
