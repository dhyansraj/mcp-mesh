"""
MCP Lifecycle Tools

Registry-level lifecycle management tools following MCP SDK compliance.
Provides register_agent, deregister_agent, and drain_agent operations.
"""

from typing import Any

from mcp_mesh import (
    AgentInfo,
    LifecycleStatus,
)

from ..shared.lifecycle_manager import LifecycleManager


class LifecycleTools:
    """MCP tools for registry lifecycle management."""

    def __init__(self, lifecycle_manager: LifecycleManager):
        self.lifecycle_manager = lifecycle_manager

    async def register_agent(self, agent_info: dict[str, Any]) -> dict[str, Any]:
        """
        Register agent with the service mesh registry.

        Args:
            agent_info: Dictionary containing agent information with fields:
                - id: str - Unique agent identifier
                - name: str - Agent name
                - namespace: str - Agent namespace (default: "default")
                - endpoint: str - Agent endpoint URL
                - capabilities: List[str] - List of capability names
                - dependencies: List[str] - List of dependencies (default: [])
                - health_interval: int - Health check interval in seconds (default: 30)
                - security_context: Optional[str] - Security context
                - metadata: Dict[str, Any] - Additional metadata (default: {})
                - labels: Dict[str, str] - Labels for categorization (default: {})
                - annotations: Dict[str, str] - Annotations (default: {})

        Returns:
            RegistrationResult with success status, agent_id, resource_version, etc.
        """
        try:
            # Validate required fields
            required_fields = ["id", "name", "endpoint"]
            for field in required_fields:
                if field not in agent_info:
                    return {
                        "success": False,
                        "agent_id": agent_info.get("id", "unknown"),
                        "resource_version": "",
                        "message": f"Missing required field: {field}",
                        "lifecycle_status": LifecycleStatus.FAILED.value,
                        "errors": [f"Missing required field: {field}"],
                    }

            # Create AgentInfo object with defaults
            agent = AgentInfo(
                id=agent_info["id"],
                name=agent_info["name"],
                namespace=agent_info.get("namespace", "default"),
                endpoint=agent_info["endpoint"],
                capabilities=agent_info.get("capabilities", []),
                dependencies=agent_info.get("dependencies", []),
                health_interval=agent_info.get("health_interval", 30),
                security_context=agent_info.get("security_context"),
                metadata=agent_info.get("metadata", {}),
                labels=agent_info.get("labels", {}),
                annotations=agent_info.get("annotations", {}),
            )

            # Register with lifecycle manager
            result = await self.lifecycle_manager.register_agent(agent)

            # Convert to dict for MCP response
            return {
                "success": result.success,
                "agent_id": result.agent_id,
                "resource_version": result.resource_version,
                "message": result.message,
                "warnings": result.warnings,
                "lifecycle_status": result.lifecycle_status.value,
                "registered_at": result.registered_at.isoformat(),
                "errors": result.errors,
            }

        except Exception as e:
            return {
                "success": False,
                "agent_id": agent_info.get("id", "unknown"),
                "resource_version": "",
                "message": f"Registration failed: {str(e)}",
                "lifecycle_status": LifecycleStatus.FAILED.value,
                "errors": [str(e)],
            }

    async def deregister_agent(
        self, agent_id: str, graceful: bool = True
    ) -> dict[str, Any]:
        """
        Deregister agent from the service mesh registry.

        Args:
            agent_id: Unique identifier of the agent to deregister
            graceful: Whether to perform graceful deregistration (drain first)

        Returns:
            DeregistrationResult with success status, cleanup info, etc.
        """
        try:
            # Validate agent_id
            if not agent_id or not isinstance(agent_id, str):
                return {
                    "success": False,
                    "agent_id": str(agent_id) if agent_id else "unknown",
                    "message": "Invalid agent_id provided",
                    "graceful": graceful,
                    "errors": ["Invalid agent_id provided"],
                }

            # Deregister with lifecycle manager
            result = await self.lifecycle_manager.deregister_agent(agent_id, graceful)

            # Convert to dict for MCP response
            return {
                "success": result.success,
                "agent_id": result.agent_id,
                "message": result.message,
                "graceful": result.graceful,
                "deregistered_at": result.deregistered_at.isoformat(),
                "cleanup_completed": result.cleanup_completed,
                "errors": result.errors,
            }

        except Exception as e:
            return {
                "success": False,
                "agent_id": str(agent_id) if agent_id else "unknown",
                "message": f"Deregistration failed: {str(e)}",
                "graceful": graceful,
                "errors": [str(e)],
            }

    async def drain_agent(self, agent_id: str) -> dict[str, Any]:
        """
        Drain agent by removing from selection pool gracefully.

        Args:
            agent_id: Unique identifier of the agent to drain

        Returns:
            DrainResult with success status, connection info, timing, etc.
        """
        try:
            # Validate agent_id
            if not agent_id or not isinstance(agent_id, str):
                return {
                    "success": False,
                    "agent_id": str(agent_id) if agent_id else "unknown",
                    "message": "Invalid agent_id provided",
                    "errors": ["Invalid agent_id provided"],
                }

            # Drain with lifecycle manager
            result = await self.lifecycle_manager.drain_agent(agent_id)

            # Convert to dict for MCP response
            return {
                "success": result.success,
                "agent_id": result.agent_id,
                "message": result.message,
                "connections_terminated": result.connections_terminated,
                "pending_requests": result.pending_requests,
                "drain_started_at": result.drain_started_at.isoformat(),
                "drain_completed_at": (
                    result.drain_completed_at.isoformat()
                    if result.drain_completed_at
                    else None
                ),
                "drain_timeout_seconds": result.drain_timeout_seconds,
                "errors": result.errors,
            }

        except Exception as e:
            return {
                "success": False,
                "agent_id": str(agent_id) if agent_id else "unknown",
                "message": f"Drain failed: {str(e)}",
                "errors": [str(e)],
            }

    async def get_agent_lifecycle_status(self, agent_id: str) -> dict[str, Any]:
        """
        Get current lifecycle status of an agent.

        Args:
            agent_id: Unique identifier of the agent

        Returns:
            Dictionary with lifecycle status information
        """
        try:
            if not agent_id or not isinstance(agent_id, str):
                return {
                    "success": False,
                    "agent_id": str(agent_id) if agent_id else "unknown",
                    "message": "Invalid agent_id provided",
                    "errors": ["Invalid agent_id provided"],
                }

            status = await self.lifecycle_manager.get_agent_lifecycle_status(agent_id)

            if status is None:
                return {
                    "success": False,
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} not found or no lifecycle status available",
                    "errors": ["Agent not found"],
                }

            return {
                "success": True,
                "agent_id": agent_id,
                "lifecycle_status": status.value,
                "message": f"Agent {agent_id} is in {status.value} state",
            }

        except Exception as e:
            return {
                "success": False,
                "agent_id": str(agent_id) if agent_id else "unknown",
                "message": f"Failed to get lifecycle status: {str(e)}",
                "errors": [str(e)],
            }

    async def list_agents_by_lifecycle_status(self, status: str) -> dict[str, Any]:
        """
        List agents by lifecycle status.

        Args:
            status: Lifecycle status to filter by (registering, active, draining, deregistering, removed, failed)

        Returns:
            Dictionary with list of agent IDs and count
        """
        try:
            # Validate status
            try:
                lifecycle_status = LifecycleStatus(status)
            except ValueError:
                valid_statuses = [s.value for s in LifecycleStatus]
                return {
                    "success": False,
                    "message": f"Invalid status '{status}'. Valid statuses: {valid_statuses}",
                    "errors": [f"Invalid status: {status}"],
                }

            agent_ids = await self.lifecycle_manager.list_agents_by_lifecycle_status(
                lifecycle_status
            )

            return {
                "success": True,
                "status": status,
                "agent_ids": agent_ids,
                "count": len(agent_ids),
                "message": f"Found {len(agent_ids)} agents in {status} state",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to list agents by status: {str(e)}",
                "errors": [str(e)],
            }


# Tool function wrappers for FastMCP integration
def create_lifecycle_tools(lifecycle_manager: LifecycleManager) -> LifecycleTools:
    """Create lifecycle tools instance."""
    return LifecycleTools(lifecycle_manager)


# MCP Tool Definitions for FastMCP
async def register_agent_tool(
    lifecycle_tools: LifecycleTools, agent_info: dict[str, Any]
) -> dict[str, Any]:
    """MCP tool: Register agent with the service mesh."""
    return await lifecycle_tools.register_agent(agent_info)


async def deregister_agent_tool(
    lifecycle_tools: LifecycleTools, agent_id: str, graceful: bool = True
) -> dict[str, Any]:
    """MCP tool: Deregister agent from the service mesh."""
    return await lifecycle_tools.deregister_agent(agent_id, graceful)


async def drain_agent_tool(
    lifecycle_tools: LifecycleTools, agent_id: str
) -> dict[str, Any]:
    """MCP tool: Drain agent by removing from selection pool."""
    return await lifecycle_tools.drain_agent(agent_id)


async def get_agent_lifecycle_status_tool(
    lifecycle_tools: LifecycleTools, agent_id: str
) -> dict[str, Any]:
    """MCP tool: Get agent lifecycle status."""
    return await lifecycle_tools.get_agent_lifecycle_status(agent_id)


async def list_agents_by_lifecycle_status_tool(
    lifecycle_tools: LifecycleTools, status: str
) -> dict[str, Any]:
    """MCP tool: List agents by lifecycle status."""
    return await lifecycle_tools.list_agents_by_lifecycle_status(status)
