"""MCP Mesh Shared Types

Core types and data structures used across the mesh with comprehensive type annotations.
Only includes actively used types - unused infrastructure has been removed.
"""

import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from pydantic.types import NonNegativeInt, StrictStr


class HealthStatusType(str, Enum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthStatus(BaseModel):
    """Health status information for mesh agents."""

    agent_name: StrictStr = Field(..., description="Agent name")
    status: HealthStatusType = Field(..., description="Overall health status")
    capabilities: list[StrictStr] = Field(..., description="Agent capabilities")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Status timestamp"
    )
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Individual check results"
    )
    errors: list[StrictStr] = Field(default_factory=list, description="Error messages")
    uptime_seconds: NonNegativeInt = Field(0, description="Agent uptime in seconds")
    version: StrictStr | None = Field(None, description="Agent version")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        """Validate capabilities list is not empty."""
        if not v:
            raise ValueError("Agent must have at least one capability")
        return v

    def is_healthy(self) -> bool:
        """Check if agent is healthy."""
        return self.status == HealthStatusType.HEALTHY

    def get_failed_checks(self) -> list[str]:
        """Get list of failed check names."""
        return [name for name, passed in self.checks.items() if not passed]


class DependencyConfig(BaseModel):
    """Configuration for dependency injection (simplified version)."""

    name: StrictStr = Field(..., description="Dependency name")
    type: StrictStr = Field(..., description="Dependency type")
    value: Any = Field(..., description="Dependency value")
    required: bool = Field(True, description="Whether dependency is required")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate dependency name format."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "Dependency name must be alphanumeric with underscores or hyphens"
            )
        return v


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

    @field_validator("name")
    @classmethod
    def validate_capability_name(cls, v):
        """Validate capability name format."""
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", v):
            raise ValueError(
                "Capability name must start with letter and contain only letters, numbers, underscore, hyphen"
            )
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        """Validate semantic version format."""
        import re

        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9-]+)?$", v):
            raise ValueError("Version must follow semantic versioning (x.y.z)")
        return v

    @field_validator("stability")
    @classmethod
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resource_version: str = Field(default_factory=lambda: str(int(time.time() * 1000)))

    # Agent information
    endpoint: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    # Health and lifecycle
    status: str = "pending"  # pending, healthy, degraded, expired, offline
    last_heartbeat: datetime | None = None
    health_interval: int = 5  # seconds - uses centralized MeshDefaults.HEALTH_INTERVAL
    timeout_threshold: int = 60  # seconds until marked degraded
    eviction_threshold: int = 120  # seconds until marked expired/evicted
    agent_type: str = "default"  # for type-specific timeout configuration

    # Configuration
    config: dict[str, Any] = Field(default_factory=dict)
    security_context: str | None = None

    @field_validator("name")
    @classmethod
    def validate_agent_name(cls, v):
        """Validate agent name follows Kubernetes naming convention."""
        import re

        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Agent name must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Agent name must be 63 characters or less")
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v):
        """Validate namespace follows Kubernetes naming convention."""
        import re

        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Namespace must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Namespace must be 63 characters or less")
        return v


class MockHTTPResponse:
    """Mock HTTP response for fallback scenarios."""

    def __init__(self, data: Any, status: int = 200):
        self.status = status
        self.status_code = status  # Add status_code for compatibility
        self._data = data

    async def json(self) -> Any:
        """Return JSON data."""
        return self._data

    async def text(self) -> str:
        """Return text representation."""
        return str(self._data)
