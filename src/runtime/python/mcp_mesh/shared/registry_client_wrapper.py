"""
Registry Client Wrapper - Clean interface for generated OpenAPI client.

Provides a type-safe, convenient wrapper around the generated OpenAPI client
that handles conversion between simple Python dicts and Pydantic models.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from mcp_mesh.generated.mcp_mesh_registry_client.api.agents_api import AgentsApi
from mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
from mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_agent_registration import (
    MeshAgentRegistration,
)
from mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_dependency_registration import (
    MeshToolDependencyRegistration,
)
from mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import (
    MeshToolRegistration,
)
from mcp_mesh.shared.support_types import HealthStatus


class RegistryClientWrapper:
    """
    Wrapper around the generated OpenAPI client for clean, type-safe registry operations.

    Provides convenience methods that convert between simple Python dicts and
    generated Pydantic models, while maintaining full type safety.
    """

    def __init__(self, api_client: ApiClient) -> None:
        self.api_client = api_client
        self.agents_api = AgentsApi(api_client)
        self.logger = logging.getLogger(__name__)

    async def register_multi_tool_agent(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """
        Register an agent with multiple tools.

        Args:
            agent_id: Unique agent identifier
            metadata: Agent metadata with tools array

        Returns:
            Registry response as dict or None if failed
        """
        try:
            # Convert metadata to MeshAgentRegistration
            agent_registration = self._build_agent_registration(agent_id, metadata)

            # Call generated client
            response = self.agents_api.register_agent(agent_registration)

            # Convert response to dict
            return self._response_to_dict(response)

        except Exception as e:
            self.logger.error(f"Failed to register multi-tool agent {agent_id}: {e}")
            return None

    async def send_heartbeat_with_dependency_resolution(
        self, health_status: HealthStatus
    ) -> Optional[dict[str, Any]]:
        """
        Send heartbeat and get dependency resolution updates.

        Args:
            health_status: Current health status of the agent

        Returns:
            Registry response with dependencies_resolved or None if failed
        """
        try:
            # Build heartbeat registration from health status
            agent_registration = self._build_heartbeat_registration(health_status)

            # Call generated client
            response = self.agents_api.send_heartbeat(agent_registration)

            # Convert response to dict
            return self._response_to_dict(response)

        except Exception as e:
            self.logger.error(
                f"Failed to send heartbeat for {health_status.agent_name}: {e}"
            )
            return None

    def parse_tool_dependencies(self, response: dict[str, Any]) -> dict[str, Any]:
        """
        Parse dependency resolution from registry response.

        Args:
            response: Registry response containing dependencies_resolved

        Returns:
            Dict mapping tool names to their resolved dependencies
        """
        try:
            # Extract dependencies_resolved from response
            if "dependencies_resolved" in response:
                return response["dependencies_resolved"]

            # Handle legacy format if needed
            if (
                "metadata" in response
                and "dependencies_resolved" in response["metadata"]
            ):
                return response["metadata"]["dependencies_resolved"]

            return {}

        except Exception as e:
            self.logger.error(f"Failed to parse tool dependencies: {e}")
            return {}

    def _build_agent_registration(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> MeshAgentRegistration:
        """Build MeshAgentRegistration from agent metadata."""

        # Build tools array
        tools = []
        for tool_data in metadata.get("tools", []):
            # Convert dependencies
            dep_registrations = []
            for dep in tool_data.get("dependencies", []):
                if isinstance(dep, dict):
                    dep_reg = MeshToolDependencyRegistration(
                        capability=dep["capability"],
                        tags=dep.get("tags", []),
                        version=dep.get("version", ""),
                        namespace=dep.get("namespace", "default"),
                    )
                    dep_registrations.append(dep_reg)

            # Create tool registration
            tool_reg = MeshToolRegistration(
                function_name=tool_data["function_name"],
                capability=tool_data.get("capability"),
                tags=tool_data.get("tags", []),
                version=tool_data.get("version", "1.0.0"),
                dependencies=dep_registrations,
                description=tool_data.get("description"),
            )
            tools.append(tool_reg)

        # Create agent registration
        return MeshAgentRegistration(
            agent_id=agent_id,
            agent_type="mcp_agent",
            name=metadata.get("name", agent_id),
            version=metadata.get("version", "1.0.0"),
            http_host=metadata.get("http_host", "0.0.0.0"),
            http_port=metadata.get("http_port", 0),
            timestamp=datetime.now(UTC),
            namespace=metadata.get("namespace", "default"),
            tools=tools,
        )

    def _build_heartbeat_registration(
        self, health_status: HealthStatus
    ) -> MeshAgentRegistration:
        """Build MeshAgentRegistration from health status for heartbeat."""

        # Import here to avoid circular imports
        from mcp_mesh import DecoratorRegistry

        # Get current tools from registry
        mesh_tools = DecoratorRegistry.get_mesh_tools()

        # Build tools array with current metadata
        tools = []
        for func_name, decorated_func in mesh_tools.items():
            metadata = decorated_func.metadata

            # Convert dependencies
            dep_registrations = []
            for dep in metadata.get("dependencies", []):
                if isinstance(dep, dict):
                    dep_reg = MeshToolDependencyRegistration(
                        capability=dep["capability"],
                        tags=dep.get("tags", []),
                        version=dep.get("version", ""),
                        namespace=dep.get("namespace", "default"),
                    )
                    dep_registrations.append(dep_reg)
                elif isinstance(dep, str) and dep:
                    dep_reg = MeshToolDependencyRegistration(
                        capability=dep,
                        tags=[],
                        version="",
                        namespace="default",
                    )
                    dep_registrations.append(dep_reg)

            # Create tool registration
            tool_reg = MeshToolRegistration(
                function_name=func_name,
                capability=metadata.get("capability"),
                tags=metadata.get("tags", []),
                version=metadata.get("version", "1.0.0"),
                dependencies=dep_registrations,
                description=metadata.get("description"),
            )
            tools.append(tool_reg)

        # Extract host/port from health status metadata
        agent_metadata = health_status.metadata or {}

        return MeshAgentRegistration(
            agent_id=health_status.agent_name,
            agent_type="mcp_agent",
            name=health_status.agent_name,
            version=health_status.version,
            http_host=agent_metadata.get("http_host", "0.0.0.0"),
            http_port=agent_metadata.get("http_port", 0),
            timestamp=health_status.timestamp,
            namespace=agent_metadata.get("namespace", "default"),
            tools=tools,
        )

    def _response_to_dict(self, response) -> dict[str, Any]:
        """Convert Pydantic response model to dict."""
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json", exclude_none=True)
        else:
            # Fallback for non-Pydantic responses
            return {"status": "success", "dependencies_resolved": {}}
