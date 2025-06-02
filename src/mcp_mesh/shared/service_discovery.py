"""Service Discovery Implementation.

Provides advanced agent discovery tools with MCP protocol integration,
including query_agents, get_best_agent, and check_compatibility.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from mcp_mesh_types import (
    AgentInfo,
    AgentMatch,
    CapabilityQuery,
    CompatibilityScore,
    MeshAgentMetadata,
    Requirements,
    ServiceDiscoveryProtocol,
)

from .capability_matching import CapabilityMatcher
from .registry_client import RegistryClient


class ServiceDiscovery:
    """Advanced service discovery with capability matching."""

    def __init__(self, registry_client: RegistryClient | None = None):
        self.logger = logging.getLogger("service_discovery")
        self.registry_client = registry_client or RegistryClient()
        self.capability_matcher = CapabilityMatcher()

        # Cache for agent information
        self._agent_cache: dict[str, AgentInfo] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._last_cache_update: datetime | None = None

    async def query_agents(self, query: CapabilityQuery) -> list[AgentMatch]:
        """Query agents based on capability requirements."""
        try:
            # Get all registered agents
            agents = await self._get_all_agents()

            # Filter agents based on query
            matching_agents = []
            for agent in agents:
                if self.capability_matcher.evaluate_query(query, agent.agent_metadata):
                    # Calculate basic compatibility score
                    requirements = self._query_to_requirements(query)
                    compatibility_score = (
                        self.capability_matcher.compute_compatibility_score(
                            agent, requirements
                        )
                    )

                    # Calculate match confidence based on query complexity
                    match_confidence = self._calculate_match_confidence(
                        query, agent.agent_metadata, compatibility_score
                    )

                    match = AgentMatch(
                        agent_info=agent,
                        compatibility_score=compatibility_score,
                        rank=0,  # Will be set after sorting
                        match_confidence=match_confidence,
                        matching_reason=self._generate_matching_reason(
                            query, agent.agent_metadata
                        ),
                        alternative_suggestions=[],
                    )
                    matching_agents.append(match)

            # Sort by compatibility score and confidence
            matching_agents.sort(
                key=lambda x: (x.compatibility_score.overall_score, x.match_confidence),
                reverse=True,
            )

            # Set ranks and add alternative suggestions
            for i, match in enumerate(matching_agents):
                match.rank = i + 1
                if i < len(matching_agents) - 1:
                    # Add next best agents as alternatives
                    match.alternative_suggestions = [
                        agents[j].agent_id
                        for j in range(i + 1, min(i + 4, len(matching_agents)))
                    ]

            self.logger.info(f"Found {len(matching_agents)} matching agents for query")
            return matching_agents

        except Exception as e:
            self.logger.error(f"Error querying agents: {e}")
            return []

    async def get_best_agent(self, requirements: Requirements) -> AgentInfo | None:
        """Get the best matching agent for given requirements."""
        try:
            # Get all registered agents
            agents = await self._get_all_agents()

            if not agents:
                return None

            # Filter out excluded agents
            if requirements.exclude_agents:
                agents = [
                    agent
                    for agent in agents
                    if agent.agent_id not in requirements.exclude_agents
                ]

            best_agent = None
            best_score = 0.0

            for agent in agents:
                compatibility_score = (
                    self.capability_matcher.compute_compatibility_score(
                        agent, requirements
                    )
                )

                # Check minimum compatibility threshold
                if (
                    compatibility_score.overall_score
                    >= requirements.compatibility_threshold
                ):
                    if compatibility_score.overall_score > best_score:
                        best_score = compatibility_score.overall_score
                        best_agent = agent

            if best_agent:
                self.logger.info(
                    f"Best agent found: {best_agent.agent_id} with score {best_score:.3f}"
                )
            else:
                self.logger.warning("No agent meets the compatibility threshold")

            return best_agent

        except Exception as e:
            self.logger.error(f"Error finding best agent: {e}")
            return None

    async def check_compatibility(
        self, agent_id: str, requirements: Requirements
    ) -> CompatibilityScore:
        """Check compatibility between agent and requirements."""
        try:
            # Get agent information
            agent = await self._get_agent_by_id(agent_id)
            if not agent:
                # Return a low compatibility score for missing agent
                return CompatibilityScore(
                    agent_id=agent_id,
                    overall_score=0.0,
                    capability_score=0.0,
                    performance_score=0.0,
                    security_score=0.0,
                    availability_score=0.0,
                    detailed_breakdown={"error": "Agent not found"},
                    missing_capabilities=requirements.required_capabilities,
                    matching_capabilities=[],
                    recommendations=["Agent is not registered or unavailable"],
                    computed_at=datetime.now(),
                )

            compatibility_score = self.capability_matcher.compute_compatibility_score(
                agent, requirements
            )

            self.logger.info(
                f"Compatibility check for {agent_id}: {compatibility_score.overall_score:.3f}"
            )
            return compatibility_score

        except Exception as e:
            self.logger.error(f"Error checking compatibility for {agent_id}: {e}")
            # Return error score
            return CompatibilityScore(
                agent_id=agent_id,
                overall_score=0.0,
                capability_score=0.0,
                performance_score=0.0,
                security_score=0.0,
                availability_score=0.0,
                detailed_breakdown={"error": str(e)},
                missing_capabilities=requirements.required_capabilities,
                matching_capabilities=[],
                recommendations=[f"Error occurred: {str(e)}"],
                computed_at=datetime.now(),
            )

    async def register_agent_capabilities(
        self, agent_id: str, metadata: MeshAgentMetadata
    ) -> bool:
        """Register agent capabilities from decorator metadata."""
        try:
            # Build capability hierarchy for this agent
            if metadata.capabilities:
                hierarchy = self.capability_matcher.build_capability_hierarchy(
                    metadata.capabilities
                )
                # Store hierarchy in agent metadata
                metadata.metadata["capability_hierarchy"] = hierarchy.dict()

            # Register with registry
            success = await self.registry_client.register_agent_with_metadata(
                agent_id=agent_id, metadata=metadata
            )

            if success:
                # Update local cache
                await self._update_agent_cache(agent_id, metadata)
                self.logger.info(f"Registered agent capabilities for {agent_id}")
            else:
                self.logger.error(
                    f"Failed to register agent capabilities for {agent_id}"
                )

            return success

        except Exception as e:
            self.logger.error(
                f"Error registering agent capabilities for {agent_id}: {e}"
            )
            return False

    async def update_agent_health(
        self, agent_id: str, health_data: dict[str, Any]
    ) -> bool:
        """Update agent health information."""
        try:
            # Update health data in registry
            success = await self.registry_client.update_agent_health(
                agent_id, health_data
            )

            if success:
                # Update local cache if agent exists
                if agent_id in self._agent_cache:
                    agent = self._agent_cache[agent_id]
                    agent.health_score = health_data.get(
                        "health_score", agent.health_score
                    )
                    agent.availability = health_data.get(
                        "availability", agent.availability
                    )
                    agent.current_load = health_data.get(
                        "current_load", agent.current_load
                    )
                    agent.response_time_ms = health_data.get(
                        "response_time_ms", agent.response_time_ms
                    )
                    agent.success_rate = health_data.get(
                        "success_rate", agent.success_rate
                    )
                    agent.last_updated = datetime.now()

                self.logger.debug(f"Updated health data for agent {agent_id}")

            return success

        except Exception as e:
            self.logger.error(f"Error updating health data for {agent_id}: {e}")
            return False

    async def _get_all_agents(self) -> list[AgentInfo]:
        """Get all registered agents with caching."""
        # Check cache freshness
        if (
            self._last_cache_update
            and datetime.now() - self._last_cache_update < self._cache_ttl
            and self._agent_cache
        ):
            return list(self._agent_cache.values())

        try:
            # Fetch from registry
            agent_data = await self.registry_client.get_all_agents()

            # Convert to AgentInfo objects
            agents = []
            for agent_dict in agent_data:
                agent_info = self._dict_to_agent_info(agent_dict)
                if agent_info:
                    agents.append(agent_info)
                    self._agent_cache[agent_info.agent_id] = agent_info

            self._last_cache_update = datetime.now()
            return agents

        except Exception as e:
            self.logger.error(f"Error fetching agents from registry: {e}")
            # Return cached data if available
            return list(self._agent_cache.values())

    async def _get_agent_by_id(self, agent_id: str) -> AgentInfo | None:
        """Get specific agent by ID."""
        # Check cache first
        if agent_id in self._agent_cache:
            return self._agent_cache[agent_id]

        try:
            # Fetch from registry
            agent_data = await self.registry_client.get_agent(agent_id)
            if agent_data:
                agent_info = self._dict_to_agent_info(agent_data)
                if agent_info:
                    self._agent_cache[agent_id] = agent_info
                    return agent_info

            return None

        except Exception as e:
            self.logger.error(f"Error fetching agent {agent_id}: {e}")
            return None

    async def _update_agent_cache(self, agent_id: str, metadata: MeshAgentMetadata):
        """Update agent cache with new metadata."""
        # Create or update AgentInfo
        agent_info = AgentInfo(
            agent_id=agent_id,
            agent_metadata=metadata,
            status="active",
            health_score=1.0,
            availability=1.0,
            current_load=0.0,
            response_time_ms=None,
            success_rate=1.0,
            last_updated=datetime.now(),
        )

        self._agent_cache[agent_id] = agent_info

    def _dict_to_agent_info(self, agent_dict: dict[str, Any]) -> AgentInfo | None:
        """Convert dictionary to AgentInfo object."""
        try:
            # Extract metadata
            metadata_dict = agent_dict.get("metadata", {})

            # Build MeshAgentMetadata
            from mcp_mesh_types import CapabilityMetadata

            capabilities = []
            for cap_dict in metadata_dict.get("capabilities", []):
                if isinstance(cap_dict, dict):
                    capabilities.append(CapabilityMetadata(**cap_dict))
                elif isinstance(cap_dict, str):
                    # Simple capability name
                    capabilities.append(CapabilityMetadata(name=cap_dict))

            mesh_metadata = MeshAgentMetadata(
                name=metadata_dict.get("name", agent_dict.get("agent_id", "unknown")),
                version=metadata_dict.get("version", "1.0.0"),
                description=metadata_dict.get("description"),
                capabilities=capabilities,
                dependencies=metadata_dict.get("dependencies", []),
                health_interval=metadata_dict.get("health_interval", 30),
                security_context=metadata_dict.get("security_context"),
                endpoint=metadata_dict.get("endpoint"),
                tags=metadata_dict.get("tags", []),
                performance_profile=metadata_dict.get("performance_profile", {}),
                resource_usage=metadata_dict.get("resource_usage", {}),
                metadata=metadata_dict.get("metadata", {}),
            )

            # Build AgentInfo
            agent_info = AgentInfo(
                agent_id=agent_dict["agent_id"],
                agent_metadata=mesh_metadata,
                status=agent_dict.get("status", "unknown"),
                health_score=agent_dict.get("health_score", 1.0),
                availability=agent_dict.get("availability", 1.0),
                current_load=agent_dict.get("current_load", 0.0),
                response_time_ms=agent_dict.get("response_time_ms"),
                success_rate=agent_dict.get("success_rate", 1.0),
                last_updated=datetime.fromisoformat(
                    agent_dict.get("last_updated", datetime.now().isoformat())
                ),
            )

            return agent_info

        except Exception as e:
            self.logger.error(f"Error converting agent dict to AgentInfo: {e}")
            return None

    def _query_to_requirements(self, query: CapabilityQuery) -> Requirements:
        """Convert a capability query to requirements for scoring."""
        # Extract capabilities from query
        required_capabilities = []

        if query.operator == "contains" and query.field == "capabilities":
            if isinstance(query.value, str):
                required_capabilities.append(query.value)
            elif isinstance(query.value, list):
                required_capabilities.extend(query.value)

        # Handle nested queries
        for subquery in query.subqueries:
            sub_requirements = self._query_to_requirements(subquery)
            required_capabilities.extend(sub_requirements.required_capabilities)

        return Requirements(
            required_capabilities=required_capabilities,
            compatibility_threshold=0.0,  # Don't filter here, just score
        )

    def _calculate_match_confidence(
        self,
        query: CapabilityQuery,
        agent_metadata: MeshAgentMetadata,
        compatibility_score: CompatibilityScore,
    ) -> float:
        """Calculate confidence in the match."""
        base_confidence = compatibility_score.overall_score

        # Adjust based on query complexity
        query_complexity = self._calculate_query_complexity(query)
        if query_complexity > 3:
            # More complex queries should have higher confidence if they match
            base_confidence = min(base_confidence * 1.1, 1.0)

        # Adjust based on agent health
        health_factor = (
            agent_metadata.metadata.get("health_score", 1.0) * 0.1
            + compatibility_score.availability_score * 0.1
        )

        return min(base_confidence + health_factor, 1.0)

    def _calculate_query_complexity(self, query: CapabilityQuery) -> int:
        """Calculate complexity of a query."""
        complexity = 1

        if query.subqueries:
            complexity += sum(
                self._calculate_query_complexity(subquery)
                for subquery in query.subqueries
            )

        # Bonus for complex operators
        if query.operator in ["and", "or", "not"]:
            complexity += 1

        return complexity

    def _generate_matching_reason(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> str:
        """Generate human-readable reason for the match."""
        if query.operator == "contains" and query.field == "capabilities":
            capability_names = [cap.name for cap in agent_metadata.capabilities]
            if isinstance(query.value, str) and query.value in capability_names:
                return f"Agent provides required capability: {query.value}"
            elif isinstance(query.value, list):
                matching = [val for val in query.value if val in capability_names]
                if matching:
                    return f"Agent provides capabilities: {', '.join(matching)}"

        elif query.operator == "matches":
            return f"Agent matches pattern in {query.field}"

        elif query.operator == "equals":
            return f"Agent has exact match for {query.field} = {query.value}"

        return "Agent meets query criteria"


# Implement the protocol
class ServiceDiscoveryService(ServiceDiscovery, ServiceDiscoveryProtocol):
    """Protocol-compliant service discovery service."""

    pass
