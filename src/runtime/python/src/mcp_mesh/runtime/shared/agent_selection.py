"""Agent Selection Engine and Algorithms.

Implementation of intelligent agent selection with multiple algorithms including
round-robin, weighted selection, and health-aware filtering.
"""

import logging
from datetime import datetime

from mcp_mesh import (
    AgentHealthInfo,
    AgentInfo,
    AgentSelectionProtocol,
    AgentSelectionResult,
    HealthStatus,
    SelectionAlgorithm,
    SelectionCriteria,
    SelectionState,
    WeightUpdateRequest,
    WeightUpdateResult,
)


class RoundRobinSelector:
    """Round-robin selection algorithm."""

    def __init__(self):
        self.algorithm = SelectionAlgorithm.ROUND_ROBIN
        self.logger = logging.getLogger("round_robin_selector")

    async def select(
        self,
        candidates: list[AgentInfo],
        criteria: SelectionCriteria,
        state: SelectionState,
    ) -> AgentSelectionResult:
        """Perform round-robin selection."""
        if not candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No candidates available",
                algorithm_used=self.algorithm,
                candidates_evaluated=0,
            )

        # Filter healthy candidates if requested
        filtered_candidates = self._filter_candidates(candidates, criteria)

        if not filtered_candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No healthy candidates available",
                algorithm_used=self.algorithm,
                candidates_evaluated=len(candidates),
            )

        # Round-robin selection
        index = state.round_robin_index % len(filtered_candidates)
        selected = filtered_candidates[index]

        # Update state
        state.round_robin_index = (state.round_robin_index + 1) % len(
            filtered_candidates
        )
        state.selection_history.append(selected.agent_id)
        if len(state.selection_history) > 100:  # Keep last 100 selections
            state.selection_history = state.selection_history[-100:]

        return AgentSelectionResult(
            selected_agent=selected,
            selection_reason=f"Round-robin selection (index {index})",
            algorithm_used=self.algorithm,
            candidates_evaluated=len(candidates),
            alternative_agents=(
                filtered_candidates[:3] if len(filtered_candidates) > 1 else []
            ),
            selection_metadata={"round_robin_index": index},
        )

    def _filter_candidates(
        self, candidates: list[AgentInfo], criteria: SelectionCriteria
    ) -> list[AgentInfo]:
        """Filter candidates based on health criteria."""
        filtered = []

        for agent in candidates:
            # Check health status
            if (
                criteria.exclude_unhealthy
                and agent.health_score < criteria.min_health_score
            ):
                continue

            # Check load threshold
            if agent.current_load > criteria.max_load_threshold:
                continue

            # Check if agent is draining
            if criteria.exclude_draining and agent.status == "draining":
                continue

            filtered.append(agent)

        return filtered


class WeightedSelector:
    """Weighted selection algorithm based on multiple factors."""

    def __init__(self):
        self.algorithm = SelectionAlgorithm.WEIGHTED
        self.logger = logging.getLogger("weighted_selector")

    async def select(
        self,
        candidates: list[AgentInfo],
        criteria: SelectionCriteria,
        state: SelectionState,
    ) -> AgentSelectionResult:
        """Perform weighted selection."""
        if not candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No candidates available",
                algorithm_used=self.algorithm,
                candidates_evaluated=0,
            )

        # Filter and score candidates
        scored_candidates = []

        for agent in candidates:
            if not self._passes_filter(agent, criteria):
                continue

            score = self._calculate_weighted_score(agent, criteria, state)
            scored_candidates.append((agent, score))

        if not scored_candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No candidates passed filtering criteria",
                algorithm_used=self.algorithm,
                candidates_evaluated=len(candidates),
            )

        # Sort by score (highest first) and select
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        selected_agent, selection_score = scored_candidates[0]

        # Update selection history
        state.selection_history.append(selected_agent.agent_id)
        if len(state.selection_history) > 100:
            state.selection_history = state.selection_history[-100:]

        # Prepare alternatives
        alternatives = [agent for agent, _ in scored_candidates[1:4]]

        return AgentSelectionResult(
            selected_agent=selected_agent,
            selection_reason=f"Weighted selection (score: {selection_score:.3f})",
            algorithm_used=self.algorithm,
            candidates_evaluated=len(candidates),
            selection_score=selection_score,
            alternative_agents=alternatives,
            selection_metadata={
                "all_scores": {
                    agent.agent_id: score for agent, score in scored_candidates[:10]
                }
            },
        )

    def _passes_filter(self, agent: AgentInfo, criteria: SelectionCriteria) -> bool:
        """Check if agent passes basic filtering criteria."""
        if (
            criteria.exclude_unhealthy
            and agent.health_score < criteria.min_health_score
        ):
            return False

        if agent.current_load > criteria.max_load_threshold:
            return False

        return not (criteria.exclude_draining and agent.status == "draining")

    def _calculate_weighted_score(
        self, agent: AgentInfo, criteria: SelectionCriteria, state: SelectionState
    ) -> float:
        """Calculate weighted score for an agent."""
        # Get weights for this agent or use global defaults
        weights = state.agent_weights.get(agent.agent_id, state.global_weights)

        # Normalize weights
        weights = weights.normalize()

        # Calculate component scores
        health_score = agent.health_score

        # Performance score (inverse of response time, normalized)
        performance_score = 1.0
        if agent.response_time_ms is not None and agent.response_time_ms > 0:
            # Normalize response time (assume 1000ms is baseline)
            performance_score = min(1000.0 / agent.response_time_ms, 1.0)

        availability_score = agent.availability

        # Capability score (based on success rate)
        capability_score = agent.success_rate

        # Load score (inverse of current load)
        load_score = max(0.0, 1.0 - agent.current_load)

        # Calculate weighted sum
        total_score = (
            weights.health_weight * health_score
            + weights.performance_weight * performance_score
            + weights.availability_weight * availability_score
            + weights.capability_weight * capability_score
            + weights.load_weight * load_score
        )

        # Apply custom weights if any
        for metric, weight in weights.custom_weights.items():
            if hasattr(agent, metric):
                value = getattr(agent, metric)
                if isinstance(value, int | float):
                    total_score += weight * min(value, 1.0)

        # Bonus for local preference
        if criteria.prefer_local:
            # Simplified local check - could be enhanced with actual locality logic
            if "local" in agent.agent_metadata.tags:
                total_score *= 1.1

        return min(total_score, 1.0)


class HealthAwareSelector:
    """Health-aware selection with degradation handling."""

    def __init__(self):
        self.algorithm = SelectionAlgorithm.HEALTH_AWARE
        self.logger = logging.getLogger("health_aware_selector")

    async def select(
        self,
        candidates: list[AgentInfo],
        criteria: SelectionCriteria,
        state: SelectionState,
    ) -> AgentSelectionResult:
        """Perform health-aware selection."""
        if not candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No candidates available",
                algorithm_used=self.algorithm,
                candidates_evaluated=0,
            )

        # Categorize agents by health
        healthy_agents = []
        degraded_agents = []

        for agent in candidates:
            if agent.health_score >= 0.8 and agent.current_load < 0.7:
                healthy_agents.append(agent)
            elif agent.health_score >= criteria.min_health_score:
                degraded_agents.append(agent)

        # Prefer healthy agents, fall back to degraded if needed
        preferred_candidates = healthy_agents if healthy_agents else degraded_agents

        if not preferred_candidates:
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason="No agents meet minimum health criteria",
                algorithm_used=self.algorithm,
                candidates_evaluated=len(candidates),
            )

        # Sort by health score and select best
        preferred_candidates.sort(
            key=lambda x: (x.health_score, -x.current_load), reverse=True
        )
        selected = preferred_candidates[0]

        # Update selection history
        state.selection_history.append(selected.agent_id)
        if len(state.selection_history) > 100:
            state.selection_history = state.selection_history[-100:]

        selection_reason = "Health-aware selection"
        if selected in degraded_agents:
            selection_reason += " (using degraded agent - no healthy agents available)"

        return AgentSelectionResult(
            selected_agent=selected,
            selection_reason=selection_reason,
            algorithm_used=self.algorithm,
            candidates_evaluated=len(candidates),
            selection_score=selected.health_score,
            alternative_agents=preferred_candidates[1:4],
            selection_metadata={
                "healthy_count": len(healthy_agents),
                "degraded_count": len(degraded_agents),
            },
        )


class AgentSelectionEngine:
    """Main agent selection engine with multiple algorithms."""

    def __init__(self):
        self.logger = logging.getLogger("agent_selection")
        self.selectors = {
            SelectionAlgorithm.ROUND_ROBIN: RoundRobinSelector(),
            SelectionAlgorithm.WEIGHTED: WeightedSelector(),
            SelectionAlgorithm.HEALTH_AWARE: HealthAwareSelector(),
        }
        self.state = SelectionState(algorithm=SelectionAlgorithm.HEALTH_AWARE)
        self._registry_client = None

    def set_registry_client(self, client):
        """Set registry client for agent queries."""
        self._registry_client = client

    async def select_agent(self, criteria: SelectionCriteria) -> AgentSelectionResult:
        """Select an agent based on criteria."""
        try:
            # Get available agents for the capability
            candidates = await self._get_candidates(criteria.capability, criteria)

            if not candidates:
                return AgentSelectionResult(
                    selected_agent=None,
                    selection_reason=f"No agents found for capability '{criteria.capability}'",
                    algorithm_used=criteria.algorithm,
                    candidates_evaluated=0,
                )

            # Check for session affinity
            if criteria.session_affinity:
                if criteria.session_affinity in self.state.session_affinities:
                    preferred_agent_id = self.state.session_affinities[
                        criteria.session_affinity
                    ]
                    preferred_agent = next(
                        (a for a in candidates if a.agent_id == preferred_agent_id),
                        None,
                    )
                    if preferred_agent and self._agent_is_suitable(
                        preferred_agent, criteria
                    ):
                        return AgentSelectionResult(
                            selected_agent=preferred_agent,
                            selection_reason="Session affinity selection",
                            algorithm_used=criteria.algorithm,
                            candidates_evaluated=len(candidates),
                            selection_metadata={
                                "session_id": criteria.session_affinity
                            },
                        )

            # Use appropriate selector
            selector = self.selectors.get(criteria.algorithm)
            if not selector:
                return AgentSelectionResult(
                    selected_agent=None,
                    selection_reason=f"Algorithm '{criteria.algorithm}' not supported",
                    algorithm_used=criteria.algorithm,
                    candidates_evaluated=len(candidates),
                )

            result = await selector.select(candidates, criteria, self.state)

            # Update session affinity if selection was successful
            if result.selected_agent and criteria.session_affinity:
                self.state.session_affinities[criteria.session_affinity] = (
                    result.selected_agent.agent_id
                )

            return result

        except Exception as e:
            self.logger.error(f"Error in agent selection: {e}")
            return AgentSelectionResult(
                selected_agent=None,
                selection_reason=f"Selection error: {str(e)}",
                algorithm_used=criteria.algorithm,
                candidates_evaluated=0,
            )

    async def get_agent_health(self, agent_id: str) -> AgentHealthInfo | None:
        """Get health status for a specific agent."""
        try:
            if not self._registry_client:
                return None

            # Get agent info from registry
            agent_data = await self._registry_client.get_agent(agent_id)
            if not agent_data:
                return None

            # Convert to health info
            health_status = HealthStatus.HEALTHY
            if agent_data.get("status") == "degraded":
                health_status = HealthStatus.DEGRADED
            elif agent_data.get("status") == "unhealthy":
                health_status = HealthStatus.UNHEALTHY
            elif agent_data.get("status") == "expired":
                health_status = HealthStatus.EXPIRED
            elif agent_data.get("status") == "offline":
                health_status = HealthStatus.OFFLINE
            elif agent_data.get("status") == "draining":
                health_status = HealthStatus.DRAINING

            return AgentHealthInfo(
                agent_id=agent_id,
                status=health_status,
                health_score=agent_data.get("health_score", 1.0),
                last_heartbeat=agent_data.get("last_heartbeat"),
                response_time_ms=agent_data.get("response_time_ms"),
                success_rate=agent_data.get("success_rate", 1.0),
                current_load=agent_data.get("current_load", 0.0),
                uptime_percentage=agent_data.get("uptime_percentage", 100.0),
                health_details=agent_data.get("health_details", {}),
            )

        except Exception as e:
            self.logger.error(f"Error getting agent health: {e}")
            return None

    async def update_selection_weights(
        self, request: WeightUpdateRequest
    ) -> WeightUpdateResult:
        """Update selection weights for an agent."""
        try:
            previous_weights = self.state.agent_weights.get(request.agent_id)

            if request.apply_globally:
                self.state.global_weights = request.weights.normalize()
                message = "Global weights updated successfully"
            else:
                self.state.agent_weights[request.agent_id] = request.weights.normalize()
                message = f"Weights updated for agent {request.agent_id}"

            self.state.last_updated = datetime.now()

            return WeightUpdateResult(
                agent_id=request.agent_id,
                success=True,
                previous_weights=previous_weights,
                new_weights=request.weights.normalize(),
                message=message,
            )

        except Exception as e:
            self.logger.error(f"Error updating weights: {e}")
            return WeightUpdateResult(
                agent_id=request.agent_id,
                success=False,
                previous_weights=None,
                new_weights=request.weights,
                message=f"Failed to update weights: {str(e)}",
            )

    async def _get_candidates(
        self, capability: str, criteria: SelectionCriteria
    ) -> list[AgentInfo]:
        """Get candidate agents for a capability."""
        if not self._registry_client:
            return []

        try:
            # Query registry for agents with the capability
            agents_data = await self._registry_client.get_all_agents()
            candidates = []

            for agent_data in agents_data:
                # Check if agent has the required capability
                agent_capabilities = []
                if "capabilities" in agent_data:
                    if isinstance(agent_data["capabilities"], list):
                        agent_capabilities = [
                            cap.get("name", "") for cap in agent_data["capabilities"]
                        ]
                    else:
                        agent_capabilities = [agent_data["capabilities"]]

                if capability not in agent_capabilities:
                    continue

                # Convert to AgentInfo (simplified)
                agent_info = self._convert_to_agent_info(agent_data)
                if agent_info:
                    candidates.append(agent_info)

            return candidates

        except Exception as e:
            self.logger.error(f"Error getting candidates: {e}")
            return []

    def _convert_to_agent_info(self, agent_data: dict) -> AgentInfo | None:
        """Convert registry agent data to AgentInfo."""
        try:
            # This is a simplified conversion - in real implementation,
            # this would use proper data mapping
            from mcp_mesh import CapabilityMetadata, MeshAgentMetadata

            # Create minimal metadata
            capabilities = []
            if "capabilities" in agent_data:
                for cap_data in agent_data.get("capabilities", []):
                    if isinstance(cap_data, dict):
                        capabilities.append(
                            CapabilityMetadata(
                                name=cap_data.get("name", ""),
                                version=cap_data.get("version", "1.0.0"),
                                description=cap_data.get("description"),
                            )
                        )

            metadata = MeshAgentMetadata(
                name=agent_data.get("name", ""),
                version=agent_data.get("version", "1.0.0"),
                capabilities=capabilities,
                description=agent_data.get("description"),
                tags=agent_data.get("tags", []),
            )

            return AgentInfo(
                agent_id=agent_data.get("id", ""),
                agent_metadata=metadata,
                status=agent_data.get("status", "healthy"),
                health_score=agent_data.get("health_score", 1.0),
                availability=agent_data.get("availability", 1.0),
                current_load=agent_data.get("current_load", 0.0),
                response_time_ms=agent_data.get("response_time_ms"),
                success_rate=agent_data.get("success_rate", 1.0),
            )

        except Exception as e:
            self.logger.error(f"Error converting agent data: {e}")
            # Return None instead of creating invalid object
            return None

    def _agent_is_suitable(self, agent: AgentInfo, criteria: SelectionCriteria) -> bool:
        """Check if agent is suitable based on criteria."""
        if (
            criteria.exclude_unhealthy
            and agent.health_score < criteria.min_health_score
        ):
            return False

        if agent.current_load > criteria.max_load_threshold:
            return False

        return not (criteria.exclude_draining and agent.status == "draining")


# Implement the protocol
class AgentSelector(AgentSelectionEngine, AgentSelectionProtocol):
    """Protocol-compliant agent selector."""

    async def get_available_agents(
        self, capability: str, criteria: SelectionCriteria | None = None
    ) -> list[AgentInfo]:
        """Get list of available agents for a capability."""
        if criteria is None:
            criteria = SelectionCriteria(capability=capability)
        return await self._get_candidates(capability, criteria)

    async def validate_selection_criteria(self, criteria: SelectionCriteria) -> bool:
        """Validate selection criteria."""
        try:
            # Basic validation
            if not criteria.capability:
                return False

            if not (0.0 <= criteria.min_health_score <= 1.0):
                return False

            if not (0.0 <= criteria.max_load_threshold <= 1.0):
                return False

            return criteria.algorithm in self.selectors

        except Exception:
            return False
