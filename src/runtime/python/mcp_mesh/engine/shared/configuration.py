"""Configuration management implementation for MCP Mesh."""

import json
from pathlib import Path
from typing import Any

import yaml

try:
    from mcp_mesh import (
        ConfigurationError,
        ConfigurationProvider,
        DatabaseConfig,
        DatabaseType,
        EnvironmentConfigProvider,
        InvalidConfigurationError,
        LogLevel,
        MissingConfigurationError,
        MonitoringConfig,
        PerformanceConfig,
        RegistryConfig,
        RegistryMode,
        SecurityConfig,
        SecurityMode,
        ServerConfig,
        ServiceDiscoveryConfig,
    )
except ImportError:
    # Fallback for when mcp-mesh is not available
    from ..shared.types import (
        ConfigurationError,
        ConfigurationProvider,
        DatabaseConfig,
        DatabaseType,
        EnvironmentConfigProvider,
        InvalidConfigurationError,
        LogLevel,
        MissingConfigurationError,
        MonitoringConfig,
        PerformanceConfig,
        RegistryConfig,
        RegistryMode,
        SecurityConfig,
        SecurityMode,
        ServerConfig,
        ServiceDiscoveryConfig,
    )


class FileConfigProvider(ConfigurationProvider):
    """Configuration provider that loads from YAML/JSON files."""

    def __init__(self, config_path: str | Path, create_if_missing: bool = False):
        self.config_path = Path(config_path)
        self.create_if_missing = create_if_missing
        if not create_if_missing:
            self._validate_file_path()

    def _validate_file_path(self) -> None:
        """Validate that the configuration file exists and is readable."""
        if not self.config_path.exists():
            raise MissingConfigurationError(
                f"Configuration file not found: {self.config_path}"
            )

        if not self.config_path.is_file():
            raise InvalidConfigurationError(
                f"Configuration path is not a file: {self.config_path}"
            )

    def load_config(self) -> RegistryConfig:
        """Load configuration from file."""
        if not self.config_path.exists():
            if self.create_if_missing:
                raise MissingConfigurationError(
                    f"Configuration file not found: {self.config_path}"
                )
            else:
                raise MissingConfigurationError(
                    f"Configuration file not found: {self.config_path}"
                )

        try:
            with open(self.config_path, encoding="utf-8") as f:
                if self.config_path.suffix.lower() in [".yaml", ".yml"]:
                    data = yaml.safe_load(f)
                elif self.config_path.suffix.lower() == ".json":
                    data = json.load(f)
                else:
                    raise InvalidConfigurationError(
                        f"Unsupported configuration file format: {self.config_path.suffix}"
                    )

            return self._parse_config_dict(data)

        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise InvalidConfigurationError(f"Failed to parse configuration file: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")

    def save_config(self, config: RegistryConfig) -> None:
        """Save configuration to file."""
        try:
            # Create parent directories if they don't exist
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            config_dict = self._config_to_dict(config)

            with open(self.config_path, "w", encoding="utf-8") as f:
                if self.config_path.suffix.lower() in [".yaml", ".yml"]:
                    yaml.safe_dump(
                        config_dict, f, default_flow_style=False, sort_keys=False
                    )
                elif self.config_path.suffix.lower() == ".json":
                    json.dump(config_dict, f, indent=2, sort_keys=False)
                else:
                    raise InvalidConfigurationError(
                        f"Unsupported configuration file format: {self.config_path.suffix}"
                    )

        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {e}")

    def validate_config(self, config: RegistryConfig) -> bool:
        """Validate configuration integrity."""
        try:
            # Basic validation
            if not isinstance(config, RegistryConfig):
                return False

            # Server validation
            if config.server.port <= 0 or config.server.port >= 65536:
                return False

            # Database validation
            if config.database.connection_timeout <= 0:
                return False

            # SSL validation
            if config.server.enable_ssl:
                if not config.server.ssl_cert_path or not config.server.ssl_key_path:
                    return False
                if not Path(config.server.ssl_cert_path).exists():
                    return False
                if not Path(config.server.ssl_key_path).exists():
                    return False

            # Security validation
            return not (
                config.security.mode == SecurityMode.JWT
                and not config.security.jwt_secret
            )

        except Exception:
            return False

    def _parse_config_dict(self, data: dict[str, Any]) -> RegistryConfig:
        """Parse configuration dictionary into RegistryConfig object."""
        try:
            # Parse server config
            server_data = data.get("server", {})
            server_config = ServerConfig(
                host=server_data.get("host", "localhost"),
                port=server_data.get("port", 8000),
                workers=server_data.get("workers", 1),
                max_connections=server_data.get("max_connections", 100),
                timeout=server_data.get("timeout", 30),
                enable_ssl=server_data.get("enable_ssl", False),
                ssl_cert_path=server_data.get("ssl_cert_path"),
                ssl_key_path=server_data.get("ssl_key_path"),
                enable_cors=server_data.get("enable_cors", True),
                cors_origins=server_data.get("cors_origins", ["*"]),
                rate_limit_enabled=server_data.get("rate_limit_enabled", False),
                rate_limit_requests=server_data.get("rate_limit_requests", 100),
                rate_limit_window=server_data.get("rate_limit_window", 60),
            )

            # Parse database config
            db_data = data.get("database", {})
            database_config = DatabaseConfig(
                database_type=DatabaseType(db_data.get("database_type", "sqlite")),
                database_path=db_data.get("database_path", "mcp_mesh_registry.db"),
                connection_string=db_data.get("connection_string"),
                connection_timeout=db_data.get("connection_timeout", 30),
                busy_timeout=db_data.get("busy_timeout", 5000),
                max_connections=db_data.get("max_connections", 10),
                pool_size=db_data.get("pool_size", 5),
                journal_mode=db_data.get("journal_mode", "WAL"),
                synchronous=db_data.get("synchronous", "NORMAL"),
                cache_size=db_data.get("cache_size", 10000),
                enable_foreign_keys=db_data.get("enable_foreign_keys", True),
                enable_encryption=db_data.get("enable_encryption", False),
                backup_enabled=db_data.get("backup_enabled", False),
                backup_interval=db_data.get("backup_interval", 3600),
            )

            # Parse security config
            security_data = data.get("security", {})
            security_config = SecurityConfig(
                mode=SecurityMode(security_data.get("mode", "none")),
                api_keys=security_data.get("api_keys", []),
                jwt_secret=security_data.get("jwt_secret"),
                jwt_expiration=security_data.get("jwt_expiration", 3600),
                tls_ca_cert=security_data.get("tls_ca_cert"),
                require_client_cert=security_data.get("require_client_cert", False),
                allowed_hosts=security_data.get("allowed_hosts", []),
                enable_audit_log=security_data.get("enable_audit_log", False),
                audit_log_path=security_data.get("audit_log_path"),
            )

            # Parse service discovery config
            discovery_data = data.get("discovery", {})
            discovery_config = ServiceDiscoveryConfig(
                enable_caching=discovery_data.get("enable_caching", True),
                cache_ttl=discovery_data.get("cache_ttl", 300),
                registry_timeout=discovery_data.get("registry_timeout", 30),
                max_retries=discovery_data.get("max_retries", 3),
                retry_delay=discovery_data.get("retry_delay", 1.0),
                health_check_enabled=discovery_data.get("health_check_enabled", True),
                health_check_interval=discovery_data.get("health_check_interval", 60),
                health_check_timeout=discovery_data.get("health_check_timeout", 10),
                agent_registration_ttl=discovery_data.get(
                    "agent_registration_ttl", 3600
                ),
                auto_refresh_enabled=discovery_data.get("auto_refresh_enabled", True),
                refresh_interval=discovery_data.get("refresh_interval", 300),
            )

            # Parse monitoring config
            monitoring_data = data.get("monitoring", {})
            monitoring_config = MonitoringConfig(
                enable_metrics=monitoring_data.get("enable_metrics", True),
                metrics_port=monitoring_data.get("metrics_port", 9090),
                enable_tracing=monitoring_data.get("enable_tracing", False),
                jaeger_endpoint=monitoring_data.get("jaeger_endpoint"),
                log_level=LogLevel(monitoring_data.get("log_level", "INFO")),
                log_format=monitoring_data.get("log_format", "json"),
                log_file_path=monitoring_data.get("log_file_path"),
                enable_performance_metrics=monitoring_data.get(
                    "enable_performance_metrics", True
                ),
                metrics_retention_days=monitoring_data.get(
                    "metrics_retention_days", 30
                ),
            )

            # Parse performance config
            performance_data = data.get("performance", {})
            performance_config = PerformanceConfig(
                max_concurrent_requests=performance_data.get(
                    "max_concurrent_requests", 100
                ),
                request_timeout=performance_data.get("request_timeout", 30),
                keep_alive_timeout=performance_data.get("keep_alive_timeout", 5),
                max_request_size=performance_data.get("max_request_size", 1024 * 1024),
                enable_compression=performance_data.get("enable_compression", True),
                compression_level=performance_data.get("compression_level", 6),
                cache_enabled=performance_data.get("cache_enabled", True),
                cache_size=performance_data.get("cache_size", 1000),
                cache_ttl=performance_data.get("cache_ttl", 300),
                background_task_workers=performance_data.get(
                    "background_task_workers", 2
                ),
            )

            # Parse main config
            return RegistryConfig(
                mode=RegistryMode(data.get("mode", "standalone")),
                server=server_config,
                database=database_config,
                security=security_config,
                discovery=discovery_config,
                monitoring=monitoring_config,
                performance=performance_config,
                environment=data.get("environment", "development"),
                debug=data.get("debug", False),
                feature_flags=data.get("feature_flags", {}),
            )

        except Exception as e:
            raise InvalidConfigurationError(f"Failed to parse configuration: {e}")

    def _config_to_dict(self, config: RegistryConfig) -> dict[str, Any]:
        """Convert RegistryConfig object to dictionary for serialization."""
        return {
            "mode": config.mode.value,
            "environment": config.environment,
            "debug": config.debug,
            "feature_flags": config.feature_flags,
            "server": {
                "host": config.server.host,
                "port": config.server.port,
                "workers": config.server.workers,
                "max_connections": config.server.max_connections,
                "timeout": config.server.timeout,
                "enable_ssl": config.server.enable_ssl,
                "ssl_cert_path": config.server.ssl_cert_path,
                "ssl_key_path": config.server.ssl_key_path,
                "enable_cors": config.server.enable_cors,
                "cors_origins": config.server.cors_origins,
                "rate_limit_enabled": config.server.rate_limit_enabled,
                "rate_limit_requests": config.server.rate_limit_requests,
                "rate_limit_window": config.server.rate_limit_window,
            },
            "database": {
                "database_type": config.database.database_type.value,
                "database_path": config.database.database_path,
                "connection_string": config.database.connection_string,
                "connection_timeout": config.database.connection_timeout,
                "busy_timeout": config.database.busy_timeout,
                "max_connections": config.database.max_connections,
                "pool_size": config.database.pool_size,
                "journal_mode": config.database.journal_mode,
                "synchronous": config.database.synchronous,
                "cache_size": config.database.cache_size,
                "enable_foreign_keys": config.database.enable_foreign_keys,
                "enable_encryption": config.database.enable_encryption,
                "backup_enabled": config.database.backup_enabled,
                "backup_interval": config.database.backup_interval,
            },
            "security": {
                "mode": config.security.mode.value,
                "api_keys": config.security.api_keys,
                "jwt_secret": config.security.jwt_secret,
                "jwt_expiration": config.security.jwt_expiration,
                "tls_ca_cert": config.security.tls_ca_cert,
                "require_client_cert": config.security.require_client_cert,
                "allowed_hosts": config.security.allowed_hosts,
                "enable_audit_log": config.security.enable_audit_log,
                "audit_log_path": config.security.audit_log_path,
            },
            "discovery": {
                "enable_caching": config.discovery.enable_caching,
                "cache_ttl": config.discovery.cache_ttl,
                "registry_timeout": config.discovery.registry_timeout,
                "max_retries": config.discovery.max_retries,
                "retry_delay": config.discovery.retry_delay,
                "health_check_enabled": config.discovery.health_check_enabled,
                "health_check_interval": config.discovery.health_check_interval,
                "health_check_timeout": config.discovery.health_check_timeout,
                "agent_registration_ttl": config.discovery.agent_registration_ttl,
                "auto_refresh_enabled": config.discovery.auto_refresh_enabled,
                "refresh_interval": config.discovery.refresh_interval,
            },
            "monitoring": {
                "enable_metrics": config.monitoring.enable_metrics,
                "metrics_port": config.monitoring.metrics_port,
                "enable_tracing": config.monitoring.enable_tracing,
                "jaeger_endpoint": config.monitoring.jaeger_endpoint,
                "log_level": config.monitoring.log_level.value,
                "log_format": config.monitoring.log_format,
                "log_file_path": config.monitoring.log_file_path,
                "enable_performance_metrics": config.monitoring.enable_performance_metrics,
                "metrics_retention_days": config.monitoring.metrics_retention_days,
            },
            "performance": {
                "max_concurrent_requests": config.performance.max_concurrent_requests,
                "request_timeout": config.performance.request_timeout,
                "keep_alive_timeout": config.performance.keep_alive_timeout,
                "max_request_size": config.performance.max_request_size,
                "enable_compression": config.performance.enable_compression,
                "compression_level": config.performance.compression_level,
                "cache_enabled": config.performance.cache_enabled,
                "cache_size": config.performance.cache_size,
                "cache_ttl": config.performance.cache_ttl,
                "background_task_workers": config.performance.background_task_workers,
            },
        }


class CompositeConfigProvider(ConfigurationProvider):
    """Configuration provider that combines multiple sources with priority."""

    def __init__(self, providers: list[ConfigurationProvider]):
        self.providers = providers

    def load_config(self) -> RegistryConfig:
        """Load configuration by merging from multiple providers."""
        if not self.providers:
            raise MissingConfigurationError("No configuration providers specified")

        # Start with defaults
        config = RegistryConfig()

        # Apply configurations in order (later providers override earlier ones)
        for provider in self.providers:
            try:
                provider_config = provider.load_config()
                config = self._merge_configs(config, provider_config)
            except ConfigurationError:
                # Continue with other providers if one fails
                continue

        return config

    def save_config(self, config: RegistryConfig) -> None:
        """Save configuration to the last writable provider."""
        for provider in reversed(self.providers):
            try:
                provider.save_config(config)
                return
            except (NotImplementedError, ConfigurationError):
                continue

        raise ConfigurationError("No writable configuration provider available")

    def validate_config(self, config: RegistryConfig) -> bool:
        """Validate configuration using the first provider that supports validation."""
        for provider in self.providers:
            try:
                return provider.validate_config(config)
            except Exception:
                continue

        return False

    def _merge_configs(
        self, base: RegistryConfig, override: RegistryConfig
    ) -> RegistryConfig:
        """Merge two configuration objects, with override taking precedence."""
        # This is a simplified merge - in production you'd want more sophisticated merging
        return override


class ConfigurationManager:
    """Central configuration manager for MCP Mesh."""

    def __init__(self):
        self._config: RegistryConfig | None = None
        self._provider: ConfigurationProvider | None = None

    def load_from_file(self, config_path: str | Path) -> RegistryConfig:
        """Load configuration from a file."""
        self._provider = FileConfigProvider(config_path)
        self._config = self._provider.load_config()
        return self._config

    def load_from_environment(self, prefix: str = "MCP_MESH_") -> RegistryConfig:
        """Load configuration from environment variables."""
        self._provider = EnvironmentConfigProvider(prefix)
        self._config = self._provider.load_config()
        return self._config

    def load_from_multiple(
        self, providers: list[ConfigurationProvider]
    ) -> RegistryConfig:
        """Load configuration from multiple sources."""
        self._provider = CompositeConfigProvider(providers)
        self._config = self._provider.load_config()
        return self._config

    def get_config(self) -> RegistryConfig:
        """Get the current configuration."""
        if self._config is None:
            # Load default configuration if none loaded
            self._config = RegistryConfig()
        return self._config

    def save_config(self) -> None:
        """Save the current configuration."""
        if self._provider is None or self._config is None:
            raise ConfigurationError("No configuration loaded to save")

        self._provider.save_config(self._config)

    def validate_config(self) -> bool:
        """Validate the current configuration."""
        if self._provider is None or self._config is None:
            return False

        return self._provider.validate_config(self._config)

    def update_config(self, **kwargs) -> None:
        """Update configuration with new values."""
        if self._config is None:
            self._config = RegistryConfig()

        # Update configuration fields
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)


# Global configuration manager instance
config_manager = ConfigurationManager()


__all__ = [
    "FileConfigProvider",
    "CompositeConfigProvider",
    "ConfigurationManager",
    "config_manager",
]
