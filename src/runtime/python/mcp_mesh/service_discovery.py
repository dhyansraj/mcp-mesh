"""Service Discovery interfaces and types for MCP Mesh.

This module defines the core interfaces for advanced service discovery with decorator
pattern integration, including capability hierarchies, semantic matching, and
compatibility scoring.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator


class QueryOperator(str, Enum):
    """Query operators for capability queries."""

    AND = "and"
    OR = "or"
    NOT = "not"
    CONTAINS = "contains"
    MATCHES = "matches"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUALS = "eq"


class MatchingStrategy(str, Enum):
    """Strategy for capability matching."""

    EXACT = "exact"
    PARTIAL = "partial"
    SEMANTIC = "semantic"
    FUZZY = "fuzzy"
    HIERARCHICAL = "hierarchical"


class CapabilityMetadata(BaseModel):
    """Metadata for a capability with inheritance support."""

    name: str = Field(..., description="Capability name")
    version: str = Field("1.0.0", description="Capability version")
    description: str | None = Field(None, description="Capability description")
    parent_capabilities: list[str] = Field(
        default_factory=list, description="Parent capabilities for inheritance"
    )
    tags: list[str] = Field(default_factory=list, description="Capability tags")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Capability parameters and constraints"
    )
    performance_metrics: dict[str, float] = Field(
        default_factory=dict, description="Performance characteristics"
    )
    security_level: str = Field("standard", description="Required security level")
    resource_requirements: dict[str, Any] = Field(
        default_factory=dict, description="Resource requirements"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate capability name format."""
        if not v.replace("_", "").replace("-", "").replace(".", "").isalnum():
            raise ValueError(
                "Capability name must be alphanumeric with underscores, hyphens, or dots"
            )
        return v


class CapabilityHierarchy(BaseModel):
    """Hierarchical structure of capabilities with inheritance."""

    root_capabilities: list[CapabilityMetadata] = Field(
        default_factory=list, description="Root level capabilities"
    )
    inheritance_map: dict[str, list[str]] = Field(
        default_factory=dict, description="Mapping of capability to its children"
    )

    def get_inherited_capabilities(self, capability_name: str) -> list[str]:
        """Get all capabilities inherited by a given capability."""
        inherited = []
        for cap in self.root_capabilities:
            if cap.name == capability_name:
                inherited.extend(cap.parent_capabilities)
                break
        return inherited

    def is_compatible(self, required: str, provided: str) -> bool:
        """Check if a provided capability satisfies a required one through inheritance."""
        if required == provided:
            return True

        # Check if provided capability inherits from required
        inherited = self.get_inherited_capabilities(provided)
        return required in inherited


class CapabilityQuery(BaseModel):
    """Complex query structure for capability search."""

    operator: QueryOperator = Field(..., description="Query operator")
    field: str | None = Field(None, description="Field to query on")
    value: Any = Field(None, description="Value to match against")
    subqueries: list["CapabilityQuery"] = Field(
        default_factory=list, description="Nested subqueries"
    )
    matching_strategy: MatchingStrategy = Field(
        MatchingStrategy.SEMANTIC, description="Matching strategy to use"
    )
    weight: float = Field(1.0, ge=0.0, le=1.0, description="Query weight for scoring")

    def evaluate(self, capability: CapabilityMetadata) -> bool:
        """Evaluate query against a capability (placeholder for interface)."""
        # This is a no-op in the types package
        return True


class Requirements(BaseModel):
    """Requirements specification for agent selection."""

    required_capabilities: list[str] = Field(
        ..., description="List of required capabilities"
    )
    preferred_capabilities: list[str] = Field(
        default_factory=list, description="List of preferred capabilities"
    )
    performance_requirements: dict[str, float] = Field(
        default_factory=dict, description="Performance requirements"
    )
    security_requirements: dict[str, str] = Field(
        default_factory=dict, description="Security requirements"
    )
    resource_constraints: dict[str, Any] = Field(
        default_factory=dict, description="Resource constraints"
    )
    exclude_agents: list[str] = Field(
        default_factory=list, description="Agents to exclude from selection"
    )
    max_latency_ms: float | None = Field(None, description="Maximum acceptable latency")
    min_availability: float | None = Field(
        None, ge=0.0, le=1.0, description="Minimum availability requirement"
    )
    compatibility_threshold: float = Field(
        0.7, ge=0.0, le=1.0, description="Minimum compatibility score"
    )


class MeshAgentMetadata(BaseModel):
    """Enhanced metadata from @mesh_agent decorator."""

    name: str = Field(..., description="Agent name")
    version: str = Field("1.0.0", description="Agent version")
    description: str | None = Field(None, description="Agent description")
    capabilities: list[CapabilityMetadata] = Field(
        ..., description="Agent capabilities with metadata"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Agent dependencies"
    )
    health_interval: int = Field(30, description="Health check interval in seconds")
    security_context: str | None = Field(None, description="Security context")
    endpoint: str | None = Field(None, description="Agent endpoint URL")
    tags: list[str] = Field(default_factory=list, description="Agent tags")
    performance_profile: dict[str, float] = Field(
        default_factory=dict, description="Performance characteristics"
    )
    resource_usage: dict[str, Any] = Field(
        default_factory=dict, description="Resource usage information"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="Registration timestamp"
    )
    last_seen: datetime = Field(
        default_factory=datetime.now, description="Last health check timestamp"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class AgentInfo(BaseModel):
    """Information about a registered agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    agent_metadata: MeshAgentMetadata = Field(..., description="Agent metadata")
    status: str = Field(..., description="Current agent status")
    health_score: float = Field(1.0, ge=0.0, le=1.0, description="Current health score")
    availability: float = Field(1.0, ge=0.0, le=1.0, description="Agent availability")
    current_load: float = Field(0.0, ge=0.0, description="Current processing load")
    response_time_ms: float | None = Field(
        None, description="Average response time in milliseconds"
    )
    success_rate: float = Field(
        1.0, ge=0.0, le=1.0, description="Operation success rate"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last update timestamp"
    )


class CompatibilityScore(BaseModel):
    """Compatibility score between agent and requirements."""

    agent_id: str = Field(..., description="Agent identifier")
    overall_score: float = Field(
        ..., ge=0.0, le=1.0, description="Overall compatibility score"
    )
    capability_score: float = Field(
        ..., ge=0.0, le=1.0, description="Capability match score"
    )
    performance_score: float = Field(
        ..., ge=0.0, le=1.0, description="Performance compatibility score"
    )
    security_score: float = Field(
        ..., ge=0.0, le=1.0, description="Security compatibility score"
    )
    availability_score: float = Field(
        ..., ge=0.0, le=1.0, description="Availability score"
    )
    detailed_breakdown: dict[str, float] = Field(
        default_factory=dict, description="Detailed scoring breakdown"
    )
    missing_capabilities: list[str] = Field(
        default_factory=list, description="Missing required capabilities"
    )
    matching_capabilities: list[str] = Field(
        default_factory=list, description="Matching capabilities"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Improvement recommendations"
    )
    computed_at: datetime = Field(
        default_factory=datetime.now, description="Score computation timestamp"
    )

    def is_compatible(self, threshold: float = 0.7) -> bool:
        """Check if agent is compatible based on threshold."""
        return self.overall_score >= threshold


class AgentMatch(BaseModel):
    """Result of agent matching against query."""

    agent_info: AgentInfo = Field(..., description="Matched agent information")
    compatibility_score: CompatibilityScore = Field(
        ..., description="Compatibility assessment"
    )
    rank: int = Field(..., description="Ranking in search results")
    match_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the match"
    )
    matching_reason: str = Field(..., description="Reason for the match")
    alternative_suggestions: list[str] = Field(
        default_factory=list, description="Alternative agent suggestions"
    )


# Protocol definitions for type checking
class ServiceDiscoveryProtocol(Protocol):
    """Protocol for service discovery operations."""

    async def query_agents(self, query: CapabilityQuery) -> list[AgentMatch]:
        """Query agents based on capability requirements."""
        ...

    async def get_best_agent(self, requirements: Requirements) -> AgentInfo | None:
        """Get the best matching agent for given requirements."""
        ...

    async def check_compatibility(
        self, agent_id: str, requirements: Requirements
    ) -> CompatibilityScore:
        """Check compatibility between agent and requirements."""
        ...

    async def register_agent_capabilities(
        self, agent_id: str, metadata: MeshAgentMetadata
    ) -> bool:
        """Register agent capabilities from decorator metadata."""
        ...

    async def update_agent_health(
        self, agent_id: str, health_data: dict[str, Any]
    ) -> bool:
        """Update agent health information."""
        ...


class CapabilityMatchingProtocol(Protocol):
    """Protocol for capability matching operations."""

    def score_capability_match(
        self, required: CapabilityMetadata, provided: CapabilityMetadata
    ) -> float:
        """Score the match between required and provided capabilities."""
        ...

    def build_capability_hierarchy(
        self, capabilities: list[CapabilityMetadata]
    ) -> CapabilityHierarchy:
        """Build hierarchical structure from capabilities."""
        ...

    def evaluate_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate query against agent metadata."""
        ...

    def compute_compatibility_score(
        self, agent_info: AgentInfo, requirements: Requirements
    ) -> CompatibilityScore:
        """Compute comprehensive compatibility score."""
        ...


# Enable forward references
CapabilityQuery.model_rebuild()
