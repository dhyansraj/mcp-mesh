"""
Pydantic models for MCP Mesh Registry

Contains all data models used by the registry service to avoid circular imports.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, validator


class AgentCapability(BaseModel):
    """Represents a capability that an agent provides."""

    name: str
    description: str | None = None
    version: str = "1.0.0"
    compatibility_versions: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, Any] | None = None
    security_requirements: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    stability: str = "stable"  # stable, beta, alpha, deprecated

    @validator("name")
    def validate_capability_name(cls, v):
        """Validate capability name format."""
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", v):
            raise ValueError(
                "Capability name must start with letter and contain only letters, numbers, underscore, hyphen"
            )
        return v

    @validator("version")
    def validate_version(cls, v):
        """Validate semantic version format."""
        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9-]+)?$", v):
            raise ValueError("Version must follow semantic versioning (x.y.z)")
        return v

    @validator("stability")
    def validate_stability(cls, v):
        """Validate stability level."""
        if v not in ["stable", "beta", "alpha", "deprecated"]:
            raise ValueError(
                "Stability must be one of: stable, beta, alpha, deprecated"
            )
        return v


class AgentRegistration(BaseModel):
    """Agent registration information following Kubernetes resource pattern."""

    # Kubernetes-style metadata
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    # Registration metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_version: str = Field(default_factory=lambda: str(int(time.time() * 1000)))

    # Agent information
    endpoint: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    # Health and lifecycle
    status: str = "pending"  # pending, healthy, degraded, expired, offline
    last_heartbeat: datetime | None = None
    health_interval: int = 30  # seconds
    timeout_threshold: int = 60  # seconds until marked degraded
    eviction_threshold: int = 120  # seconds until marked expired/evicted
    agent_type: str = "default"  # for type-specific timeout configuration

    # Configuration
    config: dict[str, Any] = Field(default_factory=dict)
    security_context: str | None = None

    @validator("name")
    def validate_agent_name(cls, v):
        """Validate agent name follows Kubernetes naming convention."""
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Agent name must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Agent name must be 63 characters or less")
        return v

    @validator("namespace")
    def validate_namespace(cls, v):
        """Validate namespace follows Kubernetes naming convention."""
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Namespace must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Namespace must be 63 characters or less")
        return v

    @validator("endpoint")
    def validate_endpoint(cls, v):
        """Validate endpoint URL format."""
        if not re.match(r"^https?://.+", v):
            raise ValueError("Endpoint must be a valid HTTP/HTTPS URL")
        return v

    @validator("status")
    def validate_status(cls, v):
        """Validate agent status."""
        valid_statuses = ["pending", "healthy", "degraded", "expired", "offline"]
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {", ".join(valid_statuses)}')
        return v

    @validator("agent_type")
    def validate_agent_type(cls, v):
        """Validate agent type."""
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError("Agent type must be lowercase alphanumeric with hyphens")
        return v


class HealthConfiguration(BaseModel):
    """Configuration for health monitoring system."""

    default_timeout_threshold: int = 60  # seconds
    default_eviction_threshold: int = 120  # seconds
    check_interval: int = 30  # seconds between health checks

    # Type-specific configurations
    agent_type_configs: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "file-agent": {"timeout_threshold": 90, "eviction_threshold": 180},
            "worker": {"timeout_threshold": 45, "eviction_threshold": 90},
            "critical": {"timeout_threshold": 30, "eviction_threshold": 60},
        }
    )

    def get_timeout_threshold(self, agent_type: str) -> int:
        """Get timeout threshold for specific agent type."""
        return self.agent_type_configs.get(agent_type, {}).get(
            "timeout_threshold", self.default_timeout_threshold
        )

    def get_eviction_threshold(self, agent_type: str) -> int:
        """Get eviction threshold for specific agent type."""
        return self.agent_type_configs.get(agent_type, {}).get(
            "eviction_threshold", self.default_eviction_threshold
        )


class HealthStatus(BaseModel):
    """Health status information for an agent."""

    agent_id: str
    status: str  # healthy, degraded, expired, offline
    last_heartbeat: datetime | None = None
    next_heartbeat_expected: datetime | None = None
    time_since_heartbeat: float | None = None  # seconds
    timeout_threshold: int
    eviction_threshold: int
    is_expired: bool = False
    message: str | None = None


class RegistryMetrics(BaseModel):
    """Registry metrics and statistics."""

    total_agents: int = 0
    healthy_agents: int = 0
    degraded_agents: int = 0
    expired_agents: int = 0
    offline_agents: int = 0
    pending_agents: int = 0

    total_capabilities: int = 0
    unique_capability_types: int = 0

    uptime_seconds: float = 0
    heartbeats_processed: int = 0
    registrations_processed: int = 0

    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ServiceDiscoveryQuery(BaseModel):
    """Query for service discovery following Kubernetes selector pattern."""

    capabilities: list[str] | None = None
    labels: dict[str, str] | None = None
    namespace: str | None = None
    status: str | None = "healthy"
    # New filtering options
    capability_category: str | None = None
    capability_stability: str | None = None
    capability_tags: list[str] | None = None
    fuzzy_match: bool = False
    version_constraint: str | None = None  # e.g., ">=1.0.0", "~1.2.0"


class CapabilitySearchQuery(BaseModel):
    """Enhanced query for capability-specific search."""

    name: str | None = None
    description_contains: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    stability: str | None = None
    version_constraint: str | None = None
    fuzzy_match: bool = False
    include_deprecated: bool = False
    agent_namespace: str | None = None
    agent_status: str | None = "healthy"

    @validator("stability")
    def validate_stability_filter(cls, v):
        """Validate stability filter."""
        if v and v not in ["stable", "beta", "alpha", "deprecated"]:
            raise ValueError(
                "Stability must be one of: stable, beta, alpha, deprecated"
            )
        return v
