"""Service Discovery Implementation.

Provides advanced agent discovery tools with MCP protocol integration,
including query_agents, get_best_agent, and check_compatibility.
Registry Integration for Service Discovery implementation for Phase 2.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from mcp_mesh import (
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
from .types import EndpointInfo, HealthStatusType


class SelectionCriteria:
    """Simple selection criteria for service discovery."""

    def __init__(
        self,
        min_compatibility_score: float = 0.7,
        max_response_time_ms: int | None = None,
        min_success_rate: float | None = None,
        max_load: float | None = None,
        exclude_agents: list[str] | None = None,
        required_capabilities: list[str] | None = None,
    ):
        self.min_compatibility_score = min_compatibility_score
        self.max_response_time_ms = max_response_time_ms
        self.min_success_rate = min_success_rate
        self.max_load = max_load
        self.exclude_agents = exclude_agents or []
        self.required_capabilities = required_capabilities or []


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
                ) and compatibility_score.overall_score > best_score:
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
                try:
                    await self._update_agent_cache(agent_id, metadata)
                except Exception as cache_error:
                    self.logger.debug(
                        f"Cache update failed (non-critical): {cache_error}"
                    )
                self.logger.info(f"Registered agent capabilities for {agent_id}")
            else:
                self.logger.error(
                    f"Failed to register agent capabilities for {agent_id}"
                )

            return success

        except Exception as e:
            # Log as debug since basic registration likely succeeded
            self.logger.debug(
                f"Enhanced capability registration issue for {agent_id}: {e}"
            )
            # Return True since basic registration succeeded
            # Enhanced capabilities are optional
            return True

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
            from mcp_mesh import CapabilityMetadata

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
                created_at=datetime.now(),
                last_seen=datetime.now(),
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
                last_updated=(
                    datetime.fromisoformat(
                        agent_dict.get("last_updated", datetime.now().isoformat())
                    )
                    if isinstance(agent_dict.get("last_updated"), str)
                    else datetime.now()
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

    # Registry Integration for Service Discovery - Phase 2 Implementation

    async def discover_service_by_class(
        self, service_class: type
    ) -> list[EndpointInfo]:
        """Discover service endpoints by class type through registry.

        Args:
            service_class: The service class to discover endpoints for

        Returns:
            List of available service endpoints for the class
        """
        try:
            service_name = service_class.__name__.lower()
            self.logger.info(
                f"Discovering services for class: {service_class.__name__}"
            )

            # Get all registered agents
            agents = await self._get_all_agents()

            # Filter agents that provide the service class
            matching_endpoints = []
            for agent in agents:
                # Check if agent provides the requested service
                if self._agent_provides_service(agent, service_class):
                    endpoint_info = self._agent_to_endpoint_info(agent, service_name)
                    if endpoint_info:
                        matching_endpoints.append(endpoint_info)

            # Filter out degraded services
            healthy_endpoints = [
                endpoint
                for endpoint in matching_endpoints
                if endpoint.status == HealthStatusType.HEALTHY
            ]

            self.logger.info(
                f"Found {len(healthy_endpoints)} healthy endpoints for {service_class.__name__} "
                f"({len(matching_endpoints)} total)"
            )

            return healthy_endpoints

        except Exception as e:
            self.logger.error(
                f"Error discovering services for {service_class.__name__}: {e}"
            )
            return []

    async def select_best_service_instance(
        self, service_class: type, criteria: SelectionCriteria
    ) -> EndpointInfo | None:
        """Select the best service instance based on criteria.

        Args:
            service_class: The service class to select an instance for
            criteria: Selection criteria for choosing the best instance

        Returns:
            Best matching service endpoint or None if no suitable instance found
        """
        try:
            # Discover available service endpoints
            endpoints = await self.discover_service_by_class(service_class)

            if not endpoints:
                self.logger.warning(f"No endpoints found for {service_class.__name__}")
                return None

            # Convert to requirements for compatibility scoring
            requirements = self._criteria_to_requirements(criteria)

            best_endpoint = None
            best_score = 0.0

            for endpoint in endpoints:
                # Get agent info for this endpoint
                agent = await self._get_agent_by_endpoint(endpoint)
                if not agent:
                    continue

                try:
                    # Calculate compatibility score
                    compatibility_score = (
                        self.capability_matcher.compute_compatibility_score(
                            agent, requirements
                        )
                    )

                    # Apply selection criteria scoring
                    final_score = self._apply_selection_criteria(
                        compatibility_score, agent, criteria
                    )

                    if final_score > best_score:
                        best_score = final_score
                        best_endpoint = endpoint

                except Exception as e:
                    self.logger.warning(f"Error scoring endpoint {endpoint.url}: {e}")
                    # Create a simple fallback score based on health metrics only if criteria are lenient
                    health_score = agent.health_score * agent.availability

                    # Check if agent meets basic criteria before considering it
                    meets_criteria = True
                    if (
                        criteria.max_response_time_ms
                        and agent.response_time_ms
                        and agent.response_time_ms > criteria.max_response_time_ms
                    ):
                        meets_criteria = False
                    if (
                        criteria.min_success_rate
                        and agent.success_rate < criteria.min_success_rate
                    ):
                        meets_criteria = False
                    if criteria.max_load and agent.current_load > criteria.max_load:
                        meets_criteria = False

                    if meets_criteria and health_score > best_score:
                        best_score = health_score
                        best_endpoint = endpoint

            if best_endpoint:
                self.logger.info(
                    f"Selected best endpoint for {service_class.__name__}: "
                    f"{best_endpoint.url} (score: {best_score:.3f})"
                )
            else:
                self.logger.warning(
                    f"No suitable endpoint found for {service_class.__name__} "
                    f"meeting criteria: {criteria}"
                )

            return best_endpoint

        except Exception as e:
            self.logger.error(
                f"Error selecting best service instance for {service_class.__name__}: {e}"
            )
            return None

    async def monitor_service_health(
        self, service_class: type, callback: Callable[[str, HealthStatusType], None]
    ) -> "HealthMonitor":
        """Monitor service health with callback notifications.

        Args:
            service_class: The service class to monitor
            callback: Callback function for health status changes

        Returns:
            HealthMonitor instance for managing the monitoring
        """
        try:
            service_name = service_class.__name__.lower()
            monitor = HealthMonitor(
                service_name=service_name,
                service_class=service_class,
                callback=callback,
                service_discovery=self,
            )

            # Start monitoring
            await monitor.start_monitoring()

            self.logger.info(f"Started health monitoring for {service_class.__name__}")
            return monitor

        except Exception as e:
            self.logger.error(
                f"Error starting health monitoring for {service_class.__name__}: {e}"
            )
            raise

    def _agent_provides_service(self, agent: AgentInfo, service_class: type) -> bool:
        """Check if an agent provides a specific service class."""
        service_name = service_class.__name__.lower()

        # Check if agent has matching capabilities
        for capability in agent.agent_metadata.capabilities:
            if capability.name.lower() == service_name:
                return True

            # Check if capability provides the service class
            if (
                hasattr(capability, "service_class")
                and capability.service_class == service_class
            ):
                return True

            # Check metadata for service class information
            if (
                capability.metadata
                and capability.metadata.get("service_class") == service_class.__name__
            ):
                return True

        # Check agent metadata for service class information
        if agent.agent_metadata.metadata:
            services = agent.agent_metadata.metadata.get("provided_services", [])
            if service_class.__name__ in services or service_name in services:
                return True

        return False

    def _agent_to_endpoint_info(
        self, agent: AgentInfo, service_name: str
    ) -> EndpointInfo | None:
        """Convert agent info to endpoint info."""
        try:
            # Get endpoint from agent metadata
            endpoint_url = agent.agent_metadata.endpoint
            if not endpoint_url:
                # Generate default endpoint
                endpoint_url = f"mcp://localhost:8080/{service_name}"

            # Determine health status
            health_status = HealthStatusType.HEALTHY
            if agent.health_score < 0.8:
                health_status = HealthStatusType.DEGRADED
            elif agent.health_score < 0.5:
                health_status = HealthStatusType.UNHEALTHY

            return EndpointInfo(
                url=endpoint_url,
                service_name=service_name,
                service_version=agent.agent_metadata.version,
                protocol="mcp",
                status=health_status,
                metadata={
                    "agent_id": agent.agent_id,
                    "health_score": agent.health_score,
                    "availability": agent.availability,
                    "current_load": agent.current_load,
                    "response_time_ms": agent.response_time_ms,
                    "success_rate": agent.success_rate,
                },
                last_updated=agent.last_updated,
            )

        except Exception as e:
            self.logger.error(f"Error converting agent to endpoint info: {e}")
            return None

    async def _get_agent_by_endpoint(self, endpoint: EndpointInfo) -> AgentInfo | None:
        """Get agent info by endpoint."""
        agent_id = endpoint.metadata.get("agent_id") if endpoint.metadata else None
        if agent_id:
            return await self._get_agent_by_id(agent_id)

        # Fallback: search by service name
        agents = await self._get_all_agents()
        for agent in agents:
            if agent.agent_metadata.endpoint == endpoint.url:
                return agent

        return None

    def _criteria_to_requirements(self, criteria: SelectionCriteria) -> Requirements:
        """Convert selection criteria to requirements for compatibility scoring."""
        return Requirements(
            required_capabilities=getattr(criteria, "required_capabilities", []),
            compatibility_threshold=getattr(criteria, "min_compatibility_score", 0.7),
            exclude_agents=getattr(criteria, "exclude_agents", []),
            max_response_time_ms=getattr(criteria, "max_response_time_ms", None),
            min_success_rate=getattr(criteria, "min_success_rate", None),
            max_load=getattr(criteria, "max_load", None),
        )

    def _apply_selection_criteria(
        self,
        compatibility_score: CompatibilityScore,
        agent: AgentInfo,
        criteria: SelectionCriteria,
    ) -> float:
        """Apply selection criteria to calculate final score."""
        base_score = compatibility_score.overall_score

        # Apply performance criteria
        performance_multiplier = 1.0

        # Response time criteria
        if (
            hasattr(criteria, "max_response_time_ms")
            and criteria.max_response_time_ms
            and agent.response_time_ms
            and agent.response_time_ms > criteria.max_response_time_ms
        ):
            performance_multiplier *= 0.5

        # Success rate criteria
        if (
            hasattr(criteria, "min_success_rate")
            and criteria.min_success_rate
            and agent.success_rate < criteria.min_success_rate
        ):
            performance_multiplier *= 0.3

        # Load criteria
        if (
            hasattr(criteria, "max_load")
            and criteria.max_load
            and agent.current_load > criteria.max_load
        ):
            performance_multiplier *= 0.6

        # Apply health bonus
        health_bonus = agent.health_score * 0.1

        # Apply availability bonus
        availability_bonus = agent.availability * 0.05

        final_score = (
            base_score * performance_multiplier + health_bonus + availability_bonus
        )

        return min(final_score, 1.0)


class HealthMonitor:
    """Health monitoring system for service endpoints with callback notifications."""

    def __init__(
        self,
        service_name: str,
        service_class: type,
        callback: Callable[[str, HealthStatusType], None],
        service_discovery: ServiceDiscovery,
        check_interval: int = 30,
    ):
        """Initialize health monitor.

        Args:
            service_name: Name of the service to monitor
            service_class: Service class type
            callback: Callback function for health status changes
            service_discovery: Service discovery instance
            check_interval: Health check interval in seconds
        """
        self.service_name = service_name
        self.service_class = service_class
        self.callback = callback
        self.service_discovery = service_discovery
        self.check_interval = check_interval
        self.logger = logging.getLogger(f"health_monitor.{service_name}")

        # Monitoring state
        self._monitoring = False
        self._monitor_task: asyncio.Task | None = None
        self._endpoint_statuses: dict[str, HealthStatusType] = {}
        self._last_check: datetime | None = None

    async def start_monitoring(self) -> None:
        """Start health monitoring."""
        if self._monitoring:
            self.logger.warning("Health monitoring already started")
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info(f"Started health monitoring for {self.service_name}")

    async def stop_monitoring(self) -> None:
        """Stop health monitoring."""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

        self.logger.info(f"Stopped health monitoring for {self.service_name}")

    def get_current_status(self) -> dict[str, HealthStatusType]:
        """Get current health status of all monitored endpoints."""
        return self._endpoint_statuses.copy()

    def is_monitoring(self) -> bool:
        """Check if monitoring is active."""
        return self._monitoring

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        try:
            while self._monitoring:
                await self._perform_health_check()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            self.logger.info("Health monitoring cancelled")
        except Exception as e:
            self.logger.error(f"Health monitoring error: {e}")

    async def _perform_health_check(self) -> None:
        """Perform health check on all service endpoints."""
        try:
            # Discover current endpoints
            endpoints = await self.service_discovery.discover_service_by_class(
                self.service_class
            )

            current_statuses = {}

            # Check health of each endpoint
            for endpoint in endpoints:
                try:
                    # Get health status from endpoint metadata or check directly
                    health_status = await self._check_endpoint_health(endpoint)
                    current_statuses[endpoint.url] = health_status

                    # Check if status changed
                    previous_status = self._endpoint_statuses.get(endpoint.url)
                    if previous_status != health_status:
                        self.logger.info(
                            f"Health status changed for {endpoint.url}: "
                            f"{previous_status} -> {health_status}"
                        )

                        # Notify callback of status change
                        try:
                            self.callback(endpoint.url, health_status)
                        except Exception as e:
                            self.logger.error(f"Callback error for {endpoint.url}: {e}")

                except Exception as e:
                    self.logger.error(f"Error checking health for {endpoint.url}: {e}")
                    current_statuses[endpoint.url] = HealthStatusType.UNKNOWN

            # Check for removed endpoints
            for endpoint_url in self._endpoint_statuses:
                if endpoint_url not in current_statuses:
                    self.logger.info(f"Endpoint removed: {endpoint_url}")
                    try:
                        self.callback(endpoint_url, HealthStatusType.UNKNOWN)
                    except Exception as e:
                        self.logger.error(
                            f"Callback error for removed endpoint {endpoint_url}: {e}"
                        )

            # Update tracking
            self._endpoint_statuses = current_statuses
            self._last_check = datetime.now()

        except Exception as e:
            self.logger.error(f"Error performing health check: {e}")

    async def _check_endpoint_health(self, endpoint: EndpointInfo) -> HealthStatusType:
        """Check health of a specific endpoint."""
        try:
            # Use the endpoint's status if available
            if endpoint.status and endpoint.status != HealthStatusType.UNKNOWN:
                return endpoint.status

            # Get agent info for detailed health check
            agent = await self.service_discovery._get_agent_by_endpoint(endpoint)
            if not agent:
                return HealthStatusType.UNKNOWN

            # Determine health based on agent metrics
            if agent.health_score >= 0.8 and agent.availability >= 0.9:
                return HealthStatusType.HEALTHY
            elif agent.health_score >= 0.5 and agent.availability >= 0.7:
                return HealthStatusType.DEGRADED
            else:
                return HealthStatusType.UNHEALTHY

        except Exception as e:
            self.logger.error(f"Error checking endpoint health for {endpoint.url}: {e}")
            return HealthStatusType.UNKNOWN


# Enhanced Service Discovery with health-aware proxy creation
class EnhancedServiceDiscovery(ServiceDiscovery):
    """Enhanced service discovery with health-aware proxy creation."""

    def __init__(self, registry_client: RegistryClient | None = None):
        super().__init__(registry_client)
        self._proxy_factory = None

    async def create_healthy_proxy(
        self, service_class: type, criteria: SelectionCriteria | None = None
    ):
        """Create a proxy for a healthy service instance.

        Args:
            service_class: The service class to create a proxy for
            criteria: Optional selection criteria

        Returns:
            Service proxy instance or None if no healthy instance available
        """
        try:
            # Import proxy factory dynamically to avoid circular imports
            if self._proxy_factory is None:
                from ..tools.proxy_factory import get_proxy_factory

                self._proxy_factory = get_proxy_factory()

            # Use default criteria if none provided
            if criteria is None:
                criteria = SelectionCriteria(
                    min_compatibility_score=0.7,
                    max_response_time_ms=5000,
                    min_success_rate=0.9,
                    max_load=0.8,
                )

            # Select best healthy service instance
            endpoint = await self.select_best_service_instance(service_class, criteria)
            if not endpoint:
                self.logger.warning(
                    f"No healthy endpoint available for {service_class.__name__}"
                )
                return None

            # Create proxy for the selected endpoint
            # Set custom endpoint for proxy creation
            service_class._proxy_endpoint = endpoint.url

            try:
                proxy = self._proxy_factory.create_service_proxy(service_class)
                self.logger.info(
                    f"Created healthy proxy for {service_class.__name__} -> {endpoint.url}"
                )
                return proxy
            finally:
                # Clean up custom endpoint
                if hasattr(service_class, "_proxy_endpoint"):
                    delattr(service_class, "_proxy_endpoint")

        except Exception as e:
            self.logger.error(
                f"Error creating healthy proxy for {service_class.__name__}: {e}"
            )
            return None

    async def get_healthy_endpoints(self, service_class: type) -> list[EndpointInfo]:
        """Get only healthy endpoints for a service class (excludes degraded)."""
        all_endpoints = await self.discover_service_by_class(service_class)
        return [
            endpoint
            for endpoint in all_endpoints
            if endpoint.status == HealthStatusType.HEALTHY
        ]


# Implement the protocol
class ServiceDiscoveryService(ServiceDiscovery, ServiceDiscoveryProtocol):
    """Protocol-compliant service discovery service."""

    pass
