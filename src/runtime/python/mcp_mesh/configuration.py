"""Configuration interfaces for MCP Mesh registry and services."""

import os
from abc import ABC, abstractmethod
from enum import Enum


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseType(str, Enum):
    """Supported database types."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class SecurityMode(str, Enum):
    """Security modes for registry."""

    NONE = "none"
    API_KEY = "api_key"
    JWT = "jwt"
    MUTUAL_TLS = "mutual_tls"


class RegistryMode(str, Enum):
    """Registry operation modes."""

    STANDALONE = "standalone"
    CLUSTERED = "clustered"
    FEDERATED = "federated"


class ServerConfig:
    """Server configuration interface."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        workers: int = 1,
        max_connections: int = 100,
        timeout: int = 30,
        enable_ssl: bool = False,
        ssl_cert_path: str | None = None,
        ssl_key_path: str | None = None,
        enable_cors: bool = True,
        cors_origins: list[str] | None = None,
        rate_limit_enabled: bool = False,
        rate_limit_requests: int = 100,
        rate_limit_window: int = 60,
    ):
        self.host = host
        self.port = port
        self.workers = workers
        self.max_connections = max_connections
        self.timeout = timeout
        self.enable_ssl = enable_ssl
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.enable_cors = enable_cors
        self.cors_origins = cors_origins or ["*"]
        self.rate_limit_enabled = rate_limit_enabled
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_window = rate_limit_window


class DatabaseConfig:
    """Database configuration interface."""

    def __init__(
        self,
        database_type: DatabaseType = DatabaseType.SQLITE,
        database_path: str = "mcp_mesh_registry.db",
        connection_string: str | None = None,
        connection_timeout: int = 30,
        busy_timeout: int = 5000,
        max_connections: int = 10,
        pool_size: int = 5,
        journal_mode: str = "WAL",
        synchronous: str = "NORMAL",
        cache_size: int = 10000,
        enable_foreign_keys: bool = True,
        enable_encryption: bool = False,
        backup_enabled: bool = False,
        backup_interval: int = 3600,
    ):
        self.database_type = database_type
        self.database_path = database_path
        self.connection_string = connection_string
        self.connection_timeout = connection_timeout
        self.busy_timeout = busy_timeout
        self.max_connections = max_connections
        self.pool_size = pool_size
        self.journal_mode = journal_mode
        self.synchronous = synchronous
        self.cache_size = cache_size
        self.enable_foreign_keys = enable_foreign_keys
        self.enable_encryption = enable_encryption
        self.backup_enabled = backup_enabled
        self.backup_interval = backup_interval


class SecurityConfig:
    """Security configuration interface."""

    def __init__(
        self,
        mode: SecurityMode = SecurityMode.NONE,
        api_keys: list[str] | None = None,
        jwt_secret: str | None = None,
        jwt_expiration: int = 3600,
        tls_ca_cert: str | None = None,
        require_client_cert: bool = False,
        allowed_hosts: list[str] | None = None,
        enable_audit_log: bool = False,
        audit_log_path: str | None = None,
    ):
        self.mode = mode
        self.api_keys = api_keys or []
        self.jwt_secret = jwt_secret
        self.jwt_expiration = jwt_expiration
        self.tls_ca_cert = tls_ca_cert
        self.require_client_cert = require_client_cert
        self.allowed_hosts = allowed_hosts or []
        self.enable_audit_log = enable_audit_log
        self.audit_log_path = audit_log_path


class ServiceDiscoveryConfig:
    """Service discovery configuration interface."""

    def __init__(
        self,
        enable_caching: bool = True,
        cache_ttl: int = 300,
        registry_timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        health_check_enabled: bool = True,
        health_check_interval: int = 60,
        health_check_timeout: int = 10,
        agent_registration_ttl: int = 3600,
        auto_refresh_enabled: bool = True,
        refresh_interval: int = 300,
    ):
        self.enable_caching = enable_caching
        self.cache_ttl = cache_ttl
        self.registry_timeout = registry_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.health_check_enabled = health_check_enabled
        self.health_check_interval = health_check_interval
        self.health_check_timeout = health_check_timeout
        self.agent_registration_ttl = agent_registration_ttl
        self.auto_refresh_enabled = auto_refresh_enabled
        self.refresh_interval = refresh_interval


class MonitoringConfig:
    """Monitoring and observability configuration interface."""

    def __init__(
        self,
        enable_metrics: bool = True,
        metrics_port: int = 9090,
        enable_tracing: bool = False,
        jaeger_endpoint: str | None = None,
        log_level: LogLevel = LogLevel.INFO,
        log_format: str = "json",
        log_file_path: str | None = None,
        enable_performance_metrics: bool = True,
        metrics_retention_days: int = 30,
    ):
        self.enable_metrics = enable_metrics
        self.metrics_port = metrics_port
        self.enable_tracing = enable_tracing
        self.jaeger_endpoint = jaeger_endpoint
        self.log_level = log_level
        self.log_format = log_format
        self.log_file_path = log_file_path
        self.enable_performance_metrics = enable_performance_metrics
        self.metrics_retention_days = metrics_retention_days


class PerformanceConfig:
    """Performance tuning configuration interface."""

    def __init__(
        self,
        max_concurrent_requests: int = 100,
        request_timeout: int = 30,
        keep_alive_timeout: int = 5,
        max_request_size: int = 1024 * 1024,  # 1MB
        enable_compression: bool = True,
        compression_level: int = 6,
        cache_enabled: bool = True,
        cache_size: int = 1000,
        cache_ttl: int = 300,
        background_task_workers: int = 2,
    ):
        self.max_concurrent_requests = max_concurrent_requests
        self.request_timeout = request_timeout
        self.keep_alive_timeout = keep_alive_timeout
        self.max_request_size = max_request_size
        self.enable_compression = enable_compression
        self.compression_level = compression_level
        self.cache_enabled = cache_enabled
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl
        self.background_task_workers = background_task_workers


class RegistryConfig:
    """Complete registry configuration interface."""

    def __init__(
        self,
        mode: RegistryMode = RegistryMode.STANDALONE,
        server: ServerConfig | None = None,
        database: DatabaseConfig | None = None,
        security: SecurityConfig | None = None,
        discovery: ServiceDiscoveryConfig | None = None,
        monitoring: MonitoringConfig | None = None,
        performance: PerformanceConfig | None = None,
        environment: str = "development",
        debug: bool = False,
        feature_flags: dict[str, bool] | None = None,
    ):
        self.mode = mode
        self.server = server or ServerConfig()
        self.database = database or DatabaseConfig()
        self.security = security or SecurityConfig()
        self.discovery = discovery or ServiceDiscoveryConfig()
        self.monitoring = monitoring or MonitoringConfig()
        self.performance = performance or PerformanceConfig()
        self.environment = environment
        self.debug = debug
        self.feature_flags = feature_flags or {}


class ConfigurationProvider(ABC):
    """Abstract base class for configuration providers."""

    @abstractmethod
    def load_config(self) -> RegistryConfig:
        """Load configuration from the provider source."""
        pass

    @abstractmethod
    def save_config(self, config: RegistryConfig) -> None:
        """Save configuration to the provider source."""
        pass

    @abstractmethod
    def validate_config(self, config: RegistryConfig) -> bool:
        """Validate configuration integrity."""
        pass


class EnvironmentConfigProvider(ConfigurationProvider):
    """Configuration provider that loads from environment variables."""

    def __init__(self, prefix: str = "MCP_MESH_"):
        self.prefix = prefix

    def load_config(self) -> RegistryConfig:
        """Load configuration from environment variables."""
        return RegistryConfig(
            server=ServerConfig(
                host=os.getenv(f"{self.prefix}HOST", "localhost"),
                port=int(os.getenv(f"{self.prefix}PORT", "8000")),
                workers=int(os.getenv(f"{self.prefix}WORKERS", "1")),
                enable_ssl=os.getenv(f"{self.prefix}ENABLE_SSL", "false").lower()
                == "true",
                ssl_cert_path=os.getenv(f"{self.prefix}SSL_CERT_PATH"),
                ssl_key_path=os.getenv(f"{self.prefix}SSL_KEY_PATH"),
            ),
            database=DatabaseConfig(
                database_path=os.getenv(
                    f"{self.prefix}DB_PATH", "mcp_mesh_registry.db"
                ),
                connection_timeout=int(os.getenv(f"{self.prefix}DB_TIMEOUT", "30")),
                max_connections=int(
                    os.getenv(f"{self.prefix}DB_MAX_CONNECTIONS", "10")
                ),
            ),
            security=SecurityConfig(
                mode=SecurityMode(os.getenv(f"{self.prefix}SECURITY_MODE", "none")),
                api_keys=(
                    os.getenv(f"{self.prefix}API_KEYS", "").split(",")
                    if os.getenv(f"{self.prefix}API_KEYS")
                    else []
                ),
                jwt_secret=os.getenv(f"{self.prefix}JWT_SECRET"),
            ),
            environment=os.getenv(f"{self.prefix}ENVIRONMENT", "development"),
            debug=os.getenv(f"{self.prefix}DEBUG", "false").lower() == "true",
        )

    def save_config(self, config: RegistryConfig) -> None:
        """Environment variables are read-only, cannot save."""
        raise NotImplementedError("Cannot save to environment variables")

    def validate_config(self, config: RegistryConfig) -> bool:
        """Basic configuration validation."""
        return (
            config.server.port > 0
            and config.server.port < 65536
            and config.database.connection_timeout > 0
            and config.performance.max_concurrent_requests > 0
        )


class ConfigurationError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""

    pass


class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing."""

    pass


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration values are invalid."""

    pass


__all__ = [
    "LogLevel",
    "DatabaseType",
    "SecurityMode",
    "RegistryMode",
    "ServerConfig",
    "DatabaseConfig",
    "SecurityConfig",
    "ServiceDiscoveryConfig",
    "MonitoringConfig",
    "PerformanceConfig",
    "RegistryConfig",
    "ConfigurationProvider",
    "EnvironmentConfigProvider",
    "ConfigurationError",
    "MissingConfigurationError",
    "InvalidConfigurationError",
]
