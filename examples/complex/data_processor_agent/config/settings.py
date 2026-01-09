"""Settings and configuration management for the data processor agent."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ProcessingLimits:
    """Limits for data processing operations."""

    max_file_size_mb: int = 100
    max_rows: int = 100000
    max_columns: int = 1000
    timeout_seconds: int = 300


@dataclass
class ExportConfig:
    """Configuration for data export operations."""

    supported_formats: list[str] = field(
        default_factory=lambda: ["csv", "json", "xlsx", "parquet"]
    )
    default_format: str = "csv"
    compression: bool = True
    include_metadata: bool = True


@dataclass
class Settings:
    """Main configuration settings for the data processor agent."""

    # Agent identification
    agent_name: str = "data-processor"
    http_port: int = 9092
    version: str = "1.0.0"

    # Processing configuration
    processing: ProcessingLimits = field(default_factory=ProcessingLimits)
    export: ExportConfig = field(default_factory=ExportConfig)

    # External service dependencies
    dependencies: list[str] = field(
        default_factory=lambda: ["weather-service", "llm-service"]
    )

    # Storage and caching
    temp_dir: str = "/tmp/data_processor"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # Logging and monitoring
    log_level: str = "INFO"
    metrics_enabled: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables."""
        return cls(
            agent_name=os.getenv("AGENT_NAME", "data-processor"),
            http_port=int(os.getenv("HTTP_PORT", "9090")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            cache_enabled=os.getenv("CACHE_ENABLED", "true").lower() == "true",
            metrics_enabled=os.getenv("METRICS_ENABLED", "true").lower() == "true",
        )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def configure_settings(settings: Settings) -> None:
    """Configure the global settings instance."""
    global _settings
    _settings = settings
