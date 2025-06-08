"""Agent Selection interfaces and types for MCP Mesh.

This module defines the core interfaces for intelligent agent selection algorithms,
including selection strategies, health-aware filtering, and weighted selection.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from .service_discovery import AgentInfo, Requirements


class SelectionAlgorithm(str, Enum):
    """Agent selection algorithms."""

    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    HEALTH_AWARE = "health_aware"
    CAPABILITY_OPTIMIZED = "capability_optimized"
    PERFORMANCE_BASED = "performance_based"
    RANDOM = "random"


class HealthStatus(str, Enum):
    """Agent health statuses."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    EXPIRED = "expired"
    OFFLINE = "offline"
    DRAINING = "draining"


class SelectionCriteria(BaseModel):
    """Criteria for agent selection."""

    capability: str = Field(..., description="Required capability name")
    algorithm: SelectionAlgorithm = Field(
        SelectionAlgorithm.HEALTH_AWARE, description="Selection algorithm to use"
    )
    requirements: Requirements | None = Field(
        None, description="Additional requirements for selection"
    )
    exclude_unhealthy: bool = Field(
        True, description="Exclude unhealthy agents from selection"
    )
    exclude_draining: bool = Field(
        True, description="Exclude draining agents from selection"
    )
    min_health_score: float = Field(
        0.7, ge=0.0, le=1.0, description="Minimum health score required"
    )
    max_load_threshold: float = Field(
        0.8, ge=0.0, le=1.0, description="Maximum load threshold"
    )
    prefer_local: bool = Field(
        False, description="Prefer agents in the same namespace/region"
    )
    session_affinity: str | None = Field(
        None, description="Session ID for sticky selection"
    )


class SelectionWeights(BaseModel):
    """Weights for weighted selection algorithms."""

    health_weight: float = Field(
        0.3, ge=0.0, le=1.0, description="Weight for health score"
    )
    performance_weight: float = Field(
        0.25, ge=0.0, le=1.0, description="Weight for performance metrics"
    )
    availability_weight: float = Field(
        0.2, ge=0.0, le=1.0, description="Weight for availability"
    )
    capability_weight: float = Field(
        0.15, ge=0.0, le=1.0, description="Weight for capability match"
    )
    load_weight: float = Field(
        0.1, ge=0.0, le=1.0, description="Weight for current load (inverse)"
    )
    custom_weights: dict[str, float] = Field(
        default_factory=dict, description="Custom weights for specific metrics"
    )

    @field_validator(
        "health_weight",
        "performance_weight",
        "availability_weight",
        "capability_weight",
        "load_weight",
    )
    @classmethod
    def validate_weights(cls, v: float) -> float:
        """Validate weight values."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        return v

    def normalize(self) -> "SelectionWeights":
        """Normalize weights to sum to 1.0."""
        total = (
            self.health_weight
            + self.performance_weight
            + self.availability_weight
            + self.capability_weight
            + self.load_weight
        )

        if total == 0:
            # Default equal weights
            return SelectionWeights(
                health_weight=0.2,
                performance_weight=0.2,
                availability_weight=0.2,
                capability_weight=0.2,
                load_weight=0.2,
            )

        return SelectionWeights(
            health_weight=self.health_weight / total,
            performance_weight=self.performance_weight / total,
            availability_weight=self.availability_weight / total,
            capability_weight=self.capability_weight / total,
            load_weight=self.load_weight / total,
            custom_weights=self.custom_weights,
        )


class AgentSelectionResult(BaseModel):
    """Result of agent selection operation."""

    selected_agent: AgentInfo | None = Field(
        None, description="Selected agent (None if no suitable agent found)"
    )
    selection_reason: str = Field(..., description="Reason for selection")
    algorithm_used: SelectionAlgorithm = Field(..., description="Algorithm used")
    candidates_evaluated: int = Field(..., description="Number of candidates evaluated")
    selection_score: float | None = Field(
        None, description="Selection score for the chosen agent"
    )
    alternative_agents: list[AgentInfo] = Field(
        default_factory=list, description="Alternative agent options"
    )
    selection_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional selection metadata"
    )
    selected_at: datetime = Field(
        default_factory=datetime.now, description="Selection timestamp"
    )


class AgentHealthInfo(BaseModel):
    """Health information for an agent."""

    agent_id: str = Field(..., description="Agent identifier")
    status: HealthStatus = Field(..., description="Current health status")
    health_score: float = Field(
        ..., ge=0.0, le=1.0, description="Numerical health score"
    )
    last_heartbeat: datetime | None = Field(
        None, description="Last heartbeat timestamp"
    )
    response_time_ms: float | None = Field(None, description="Average response time")
    success_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="Operation success rate"
    )
    current_load: float = Field(0.0, ge=0.0, description="Current processing load")
    error_count: int = Field(0, description="Recent error count")
    uptime_percentage: float = Field(
        100.0, ge=0.0, le=100.0, description="Uptime percentage"
    )
    health_details: dict[str, Any] = Field(
        default_factory=dict, description="Detailed health metrics"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last health update"
    )


class WeightUpdateRequest(BaseModel):
    """Request to update selection weights for an agent."""

    agent_id: str = Field(..., description="Agent identifier")
    weights: SelectionWeights = Field(..., description="New weights to apply")
    reason: str = Field(..., description="Reason for weight update")
    expires_at: datetime | None = Field(None, description="When these weights expire")
    apply_globally: bool = Field(
        False, description="Apply weights globally or just for this agent"
    )


class WeightUpdateResult(BaseModel):
    """Result of weight update operation."""

    agent_id: str = Field(..., description="Agent identifier")
    success: bool = Field(..., description="Whether update was successful")
    previous_weights: SelectionWeights | None = Field(
        None, description="Previous weights before update"
    )
    new_weights: SelectionWeights = Field(..., description="New weights applied")
    message: str = Field(..., description="Update result message")
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Update timestamp"
    )


class SelectionState(BaseModel):
    """Internal state for selection algorithms."""

    algorithm: SelectionAlgorithm = Field(..., description="Algorithm type")
    round_robin_index: int = Field(0, description="Current round robin index")
    agent_weights: dict[str, SelectionWeights] = Field(
        default_factory=dict, description="Per-agent weights"
    )
    global_weights: SelectionWeights = Field(
        default_factory=SelectionWeights, description="Global default weights"
    )
    session_affinities: dict[str, str] = Field(
        default_factory=dict, description="Session ID to agent ID mapping"
    )
    selection_history: list[str] = Field(
        default_factory=list, description="Recent selection history"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last state update"
    )


# Protocol definitions for type checking
class AgentSelectionProtocol(Protocol):
    """Protocol for agent selection operations."""

    async def select_agent(self, criteria: SelectionCriteria) -> AgentSelectionResult:
        """Select an agent based on criteria."""
        ...

    async def get_agent_health(self, agent_id: str) -> AgentHealthInfo | None:
        """Get health status for a specific agent."""
        ...

    async def update_selection_weights(
        self, request: WeightUpdateRequest
    ) -> WeightUpdateResult:
        """Update selection weights for an agent."""
        ...

    async def get_available_agents(
        self, capability: str, criteria: SelectionCriteria | None = None
    ) -> list[AgentInfo]:
        """Get list of available agents for a capability."""
        ...

    async def validate_selection_criteria(self, criteria: SelectionCriteria) -> bool:
        """Validate selection criteria."""
        ...


class SelectionAlgorithmProtocol(Protocol):
    """Protocol for specific selection algorithms."""

    async def select(
        self,
        candidates: list[AgentInfo],
        criteria: SelectionCriteria,
        state: SelectionState,
    ) -> AgentSelectionResult:
        """Perform agent selection from candidates."""
        ...

    def get_algorithm_name(self) -> SelectionAlgorithm:
        """Get the algorithm identifier."""
        ...

    def supports_criteria(self, criteria: SelectionCriteria) -> bool:
        """Check if algorithm supports given criteria."""
        ...


class HealthMonitoringProtocol(Protocol):
    """Protocol for health monitoring operations."""

    async def check_agent_health(self, agent_id: str) -> AgentHealthInfo:
        """Check health of a specific agent."""
        ...

    async def get_unhealthy_agents(self) -> list[str]:
        """Get list of unhealthy agent IDs."""
        ...

    async def update_health_status(
        self, agent_id: str, health_info: AgentHealthInfo
    ) -> bool:
        """Update health status for an agent."""
        ...

    async def get_health_summary(self) -> dict[str, Any]:
        """Get overall health summary."""
        ...
