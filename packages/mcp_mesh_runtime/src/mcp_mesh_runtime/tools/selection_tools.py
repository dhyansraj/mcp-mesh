"""MCP Tools for Agent Selection.

FastMCP tools for intelligent agent selection, health monitoring,
and weight management.
"""

import logging
from typing import Any

from mcp_mesh import (
    SelectionAlgorithm,
    SelectionCriteria,
    SelectionWeights,
    WeightUpdateRequest,
)

from ..shared.agent_selection import AgentSelector


class SelectionTools:
    """MCP tools for agent selection operations."""

    def __init__(self, selector: AgentSelector | None = None):
        self.logger = logging.getLogger("selection_tools")
        self.selector = selector or AgentSelector()

    def set_registry_client(self, client):
        """Set registry client for the selector."""
        self.selector.set_registry_client(client)

    async def select_agent(
        self,
        capability: str,
        algorithm: str = "health_aware",
        requirements: dict[str, Any] | None = None,
        exclude_unhealthy: bool = True,
        exclude_draining: bool = True,
        min_health_score: float = 0.7,
        max_load_threshold: float = 0.8,
        prefer_local: bool = False,
        session_affinity: str | None = None,
    ) -> dict[str, Any]:
        """
        Select an agent based on capability and selection criteria.

        Args:
            capability: Required capability name
            algorithm: Selection algorithm (round_robin, weighted, health_aware, etc.)
            requirements: Additional requirements (optional)
            exclude_unhealthy: Exclude agents below health threshold
            exclude_draining: Exclude agents in draining state
            min_health_score: Minimum health score required (0.0-1.0)
            max_load_threshold: Maximum load threshold (0.0-1.0)
            prefer_local: Prefer agents in same namespace/region
            session_affinity: Session ID for sticky selection

        Returns:
            Dictionary containing selection result
        """
        try:
            # Parse algorithm
            try:
                selection_algorithm = SelectionAlgorithm(algorithm)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid algorithm '{algorithm}'. Valid options: {[a.value for a in SelectionAlgorithm]}",
                }

            # Parse requirements if provided
            from mcp_mesh import Requirements

            parsed_requirements = None
            if requirements:
                try:
                    parsed_requirements = Requirements(**requirements)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Invalid requirements format: {str(e)}",
                    }

            # Create selection criteria
            criteria = SelectionCriteria(
                capability=capability,
                algorithm=selection_algorithm,
                requirements=parsed_requirements,
                exclude_unhealthy=exclude_unhealthy,
                exclude_draining=exclude_draining,
                min_health_score=min_health_score,
                max_load_threshold=max_load_threshold,
                prefer_local=prefer_local,
                session_affinity=session_affinity,
            )

            # Validate criteria
            if not await self.selector.validate_selection_criteria(criteria):
                return {"success": False, "error": "Invalid selection criteria"}

            # Perform selection
            result = await self.selector.select_agent(criteria)

            # Format response
            response = {
                "success": result.selected_agent is not None,
                "algorithm_used": result.algorithm_used.value,
                "candidates_evaluated": result.candidates_evaluated,
                "selection_reason": result.selection_reason,
                "selected_at": result.selected_at.isoformat(),
            }

            if result.selected_agent:
                response["selected_agent"] = {
                    "agent_id": result.selected_agent.agent_id,
                    "name": result.selected_agent.agent_metadata.name,
                    "version": result.selected_agent.agent_metadata.version,
                    "status": result.selected_agent.status,
                    "health_score": result.selected_agent.health_score,
                    "availability": result.selected_agent.availability,
                    "current_load": result.selected_agent.current_load,
                    "response_time_ms": result.selected_agent.response_time_ms,
                    "success_rate": result.selected_agent.success_rate,
                    "endpoint": result.selected_agent.agent_metadata.endpoint,
                    "capabilities": [
                        cap.name
                        for cap in result.selected_agent.agent_metadata.capabilities
                    ],
                }

            if result.selection_score is not None:
                response["selection_score"] = result.selection_score

            if result.alternative_agents:
                response["alternatives"] = [
                    {
                        "agent_id": agent.agent_id,
                        "name": agent.agent_metadata.name,
                        "health_score": agent.health_score,
                        "current_load": agent.current_load,
                    }
                    for agent in result.alternative_agents
                ]

            if result.selection_metadata:
                response["metadata"] = result.selection_metadata

            return response

        except Exception as e:
            self.logger.error(f"Error in select_agent: {e}")
            return {"success": False, "error": f"Selection failed: {str(e)}"}

    async def get_agent_health(self, agent_id: str) -> dict[str, Any]:
        """
        Get health status for a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary containing agent health information
        """
        try:
            health_info = await self.selector.get_agent_health(agent_id)

            if not health_info:
                return {
                    "success": False,
                    "error": f"Agent '{agent_id}' not found or health data unavailable",
                }

            return {
                "success": True,
                "agent_id": health_info.agent_id,
                "status": health_info.status.value,
                "health_score": health_info.health_score,
                "last_heartbeat": (
                    health_info.last_heartbeat.isoformat()
                    if health_info.last_heartbeat
                    else None
                ),
                "response_time_ms": health_info.response_time_ms,
                "success_rate": health_info.success_rate,
                "current_load": health_info.current_load,
                "error_count": health_info.error_count,
                "uptime_percentage": health_info.uptime_percentage,
                "health_details": health_info.health_details,
                "last_updated": health_info.last_updated.isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Error getting agent health: {e}")
            return {
                "success": False,
                "error": f"Failed to get health for agent '{agent_id}': {str(e)}",
            }

    async def update_selection_weights(
        self,
        agent_id: str,
        weights: dict[str, float],
        reason: str = "Manual weight update",
        apply_globally: bool = False,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """
        Update selection weights for an agent.

        Args:
            agent_id: Agent identifier
            weights: Dictionary of weights to update
            reason: Reason for the update
            apply_globally: Apply weights globally or just for this agent
            expires_at: When these weights expire (ISO format)

        Returns:
            Dictionary containing update result
        """
        try:
            # Parse weights
            selection_weights = SelectionWeights()

            # Update provided weights
            for key, value in weights.items():
                if hasattr(selection_weights, key):
                    setattr(selection_weights, key, value)
                else:
                    # Add to custom weights
                    selection_weights.custom_weights[key] = value

            # Parse expiry date if provided
            parsed_expires_at = None
            if expires_at:
                from datetime import datetime

                try:
                    parsed_expires_at = datetime.fromisoformat(expires_at)
                except ValueError:
                    return {
                        "success": False,
                        "error": f"Invalid expires_at format: {expires_at}. Use ISO format.",
                    }

            # Create update request
            request = WeightUpdateRequest(
                agent_id=agent_id,
                weights=selection_weights,
                reason=reason,
                expires_at=parsed_expires_at,
                apply_globally=apply_globally,
            )

            # Perform update
            result = await self.selector.update_selection_weights(request)

            # Format response
            response = {
                "success": result.success,
                "agent_id": result.agent_id,
                "message": result.message,
                "updated_at": result.updated_at.isoformat(),
            }

            if result.previous_weights:
                response["previous_weights"] = result.previous_weights.dict()

            response["new_weights"] = result.new_weights.dict()

            return response

        except Exception as e:
            self.logger.error(f"Error updating selection weights: {e}")
            return {"success": False, "error": f"Failed to update weights: {str(e)}"}

    async def get_available_agents(
        self,
        capability: str,
        min_health_score: float = 0.0,
        max_load_threshold: float = 1.0,
        exclude_unhealthy: bool = False,
        exclude_draining: bool = False,
    ) -> dict[str, Any]:
        """
        Get list of available agents for a capability.

        Args:
            capability: Required capability name
            min_health_score: Minimum health score filter
            max_load_threshold: Maximum load threshold filter
            exclude_unhealthy: Exclude unhealthy agents
            exclude_draining: Exclude draining agents

        Returns:
            Dictionary containing list of available agents
        """
        try:
            # Create criteria for filtering
            criteria = SelectionCriteria(
                capability=capability,
                min_health_score=min_health_score,
                max_load_threshold=max_load_threshold,
                exclude_unhealthy=exclude_unhealthy,
                exclude_draining=exclude_draining,
            )

            # Get available agents
            agents = await self.selector.get_available_agents(capability, criteria)

            # Format response
            agent_list = []
            for agent in agents:
                agent_info = {
                    "agent_id": agent.agent_id,
                    "name": agent.agent_metadata.name,
                    "version": agent.agent_metadata.version,
                    "status": agent.status,
                    "health_score": agent.health_score,
                    "availability": agent.availability,
                    "current_load": agent.current_load,
                    "response_time_ms": agent.response_time_ms,
                    "success_rate": agent.success_rate,
                    "capabilities": [
                        cap.name for cap in agent.agent_metadata.capabilities
                    ],
                    "tags": agent.agent_metadata.tags,
                    "last_updated": agent.last_updated.isoformat(),
                }

                if agent.agent_metadata.endpoint:
                    agent_info["endpoint"] = agent.agent_metadata.endpoint

                agent_list.append(agent_info)

            return {
                "success": True,
                "capability": capability,
                "count": len(agent_list),
                "agents": agent_list,
                "filters_applied": {
                    "min_health_score": min_health_score,
                    "max_load_threshold": max_load_threshold,
                    "exclude_unhealthy": exclude_unhealthy,
                    "exclude_draining": exclude_draining,
                },
            }

        except Exception as e:
            self.logger.error(f"Error getting available agents: {e}")
            return {
                "success": False,
                "error": f"Failed to get agents for capability '{capability}': {str(e)}",
            }

    async def get_selection_stats(self) -> dict[str, Any]:
        """
        Get selection statistics and current state.

        Returns:
            Dictionary containing selection statistics
        """
        try:
            state = self.selector.state

            # Calculate statistics from selection history
            history_length = len(state.selection_history)
            unique_agents = (
                len(set(state.selection_history)) if history_length > 0 else 0
            )

            # Most frequently selected agents
            if history_length > 0:
                from collections import Counter

                agent_counts = Counter(state.selection_history)
                most_selected = agent_counts.most_common(5)
            else:
                most_selected = []

            return {
                "success": True,
                "current_algorithm": state.algorithm.value,
                "round_robin_index": state.round_robin_index,
                "selection_history_length": history_length,
                "unique_agents_selected": unique_agents,
                "most_selected_agents": [
                    {"agent_id": agent_id, "count": count}
                    for agent_id, count in most_selected
                ],
                "active_session_affinities": len(state.session_affinities),
                "global_weights": state.global_weights.dict(),
                "agent_specific_weights_count": len(state.agent_weights),
                "last_updated": state.last_updated.isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Error getting selection stats: {e}")
            return {
                "success": False,
                "error": f"Failed to get selection statistics: {str(e)}",
            }
