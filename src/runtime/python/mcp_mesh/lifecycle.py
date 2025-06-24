"""
MCP Mesh Lifecycle Management Types

Defines interfaces and types for registry-level lifecycle management.
Focus on registration events, not server start/stop operations.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class LifecycleEvent(str, Enum):
    """Registry lifecycle events for agents."""

    REGISTRATION_STARTED = "registration_started"
    REGISTRATION_COMPLETED = "registration_completed"
    REGISTRATION_FAILED = "registration_failed"
    DEREGISTRATION_STARTED = "deregistration_started"
    DEREGISTRATION_COMPLETED = "deregistration_completed"
    DRAIN_STARTED = "drain_started"
    DRAIN_COMPLETED = "drain_completed"
    HEALTH_STATUS_CHANGED = "health_status_changed"
    CAPABILITIES_UPDATED = "capabilities_updated"


class LifecycleStatus(str, Enum):
    """Status of agent during lifecycle transitions."""

    REGISTERING = "registering"
    ACTIVE = "active"
    DRAINING = "draining"
    DEREGISTERING = "deregistering"
    REMOVED = "removed"
    FAILED = "failed"


class RegistrationResult(BaseModel):
    """Result of agent registration operation."""

    success: bool
    agent_id: str
    resource_version: str
    message: str
    warnings: list[str] = Field(default_factory=list)
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    errors: list[str] = Field(default_factory=list)


class DeregistrationResult(BaseModel):
    """Result of agent deregistration operation."""

    success: bool
    agent_id: str
    message: str
    graceful: bool = True
    deregistered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cleanup_completed: bool = True
    errors: list[str] = Field(default_factory=list)


class DrainResult(BaseModel):
    """Result of agent drain operation."""

    success: bool
    agent_id: str
    message: str
    connections_terminated: int = 0
    pending_requests: int = 0
    drain_started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    drain_completed_at: datetime | None = None
    drain_timeout_seconds: int = 300
    errors: list[str] = Field(default_factory=list)


class AgentInfo(BaseModel):
    """Enhanced agent information for lifecycle management."""

    id: str
    name: str
    namespace: str = "default"
    endpoint: str
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    health_interval: int = 30
    security_context: str | None = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.REGISTERING
    metadata: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class LifecycleEventData(BaseModel):
    """Event data for lifecycle notifications."""

    event_type: LifecycleEvent
    agent_id: str
    agent_name: str
    namespace: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    old_status: LifecycleStatus | None = None
    new_status: LifecycleStatus | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LifecycleTransition(BaseModel):
    """Represents a lifecycle state transition."""

    from_status: LifecycleStatus
    to_status: LifecycleStatus
    event_type: LifecycleEvent
    allowed: bool = True
    requires_confirmation: bool = False
    timeout_seconds: int | None = None


class LifecycleProtocol(Protocol):
    """Protocol for registry lifecycle management."""

    async def register_agent(self, agent_info: AgentInfo) -> RegistrationResult:
        """Register an agent with the registry."""
        ...

    async def deregister_agent(
        self, agent_id: str, graceful: bool = True
    ) -> DeregistrationResult:
        """Deregister an agent from the registry."""
        ...

    async def drain_agent(self, agent_id: str) -> DrainResult:
        """Drain agent by removing from selection pool gracefully."""
        ...

    async def get_agent_lifecycle_status(self, agent_id: str) -> LifecycleStatus | None:
        """Get current lifecycle status of an agent."""
        ...

    async def list_agents_by_lifecycle_status(
        self, status: LifecycleStatus
    ) -> list[str]:
        """List agents by lifecycle status."""
        ...


class LifecycleEventProtocol(Protocol):
    """Protocol for lifecycle event handling."""

    async def emit_lifecycle_event(self, event_data: LifecycleEventData) -> None:
        """Emit a lifecycle event."""
        ...

    async def subscribe_to_lifecycle_events(
        self,
        agent_id: str | None = None,
        event_types: list[LifecycleEvent] | None = None,
    ) -> Any:
        """Subscribe to lifecycle events."""
        ...


class HealthTransitionTrigger(BaseModel):
    """Triggers for health-based lifecycle transitions."""

    timeout_threshold: int = 60  # seconds
    eviction_threshold: int = 120  # seconds
    failure_count_threshold: int = 3
    recovery_threshold: int = 2  # consecutive successful checks


class LifecycleConfiguration(BaseModel):
    """Configuration for lifecycle management."""

    default_drain_timeout: int = 300  # seconds
    default_deregistration_timeout: int = 60  # seconds
    enable_graceful_transitions: bool = True
    health_transitions: HealthTransitionTrigger = Field(
        default_factory=HealthTransitionTrigger
    )
    allowed_transitions: list[LifecycleTransition] = Field(default_factory=list)

    def __post_init__(self):
        """Initialize default allowed transitions."""
        if not self.allowed_transitions:
            self.allowed_transitions = [
                LifecycleTransition(
                    from_status=LifecycleStatus.REGISTERING,
                    to_status=LifecycleStatus.ACTIVE,
                    event_type=LifecycleEvent.REGISTRATION_COMPLETED,
                ),
                LifecycleTransition(
                    from_status=LifecycleStatus.ACTIVE,
                    to_status=LifecycleStatus.DRAINING,
                    event_type=LifecycleEvent.DRAIN_STARTED,
                ),
                LifecycleTransition(
                    from_status=LifecycleStatus.DRAINING,
                    to_status=LifecycleStatus.DEREGISTERING,
                    event_type=LifecycleEvent.DEREGISTRATION_STARTED,
                ),
                LifecycleTransition(
                    from_status=LifecycleStatus.DEREGISTERING,
                    to_status=LifecycleStatus.REMOVED,
                    event_type=LifecycleEvent.DEREGISTRATION_COMPLETED,
                ),
                LifecycleTransition(
                    from_status=LifecycleStatus.ACTIVE,
                    to_status=LifecycleStatus.DEREGISTERING,
                    event_type=LifecycleEvent.DEREGISTRATION_STARTED,
                ),
                LifecycleTransition(
                    from_status=LifecycleStatus.REGISTERING,
                    to_status=LifecycleStatus.FAILED,
                    event_type=LifecycleEvent.REGISTRATION_FAILED,
                ),
            ]
