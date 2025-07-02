"""
Registry Client Wrapper - Clean interface for generated OpenAPI client.

Provides a type-safe, convenient wrapper around the generated OpenAPI client
that handles conversion between simple Python dicts and Pydantic models.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from _mcp_mesh.generated.mcp_mesh_registry_client.api.agents_api import AgentsApi
from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_agent_registration import (
    MeshAgentRegistration,
)
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_dependency_registration import (
    MeshToolDependencyRegistration,
)
from _mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_tool_registration import (
    MeshToolRegistration,
)
from _mcp_mesh.shared.fast_heartbeat_status import (
    FastHeartbeatStatus,
    FastHeartbeatStatusUtil,
)
from _mcp_mesh.shared.support_types import HealthStatus


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

            # Debug: Log full registration payload
            import json

            # Convert agent_registration to dict for logging
            if hasattr(agent_registration, "model_dump"):
                registration_dict = agent_registration.model_dump(
                    mode="json", exclude_none=True
                )
            else:
                registration_dict = (
                    agent_registration.__dict__
                    if hasattr(agent_registration, "__dict__")
                    else str(agent_registration)
                )

            registration_json = json.dumps(registration_dict, indent=2, default=str)
            self.logger.debug(
                f"🔍 Full heartbeat registration payload:\n{registration_json}"
            )

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

    async def check_fast_heartbeat(self, agent_id: str) -> FastHeartbeatStatus:
        """
        Perform fast heartbeat check using HEAD request.

        Args:
            agent_id: Unique agent identifier

        Returns:
            FastHeartbeatStatus indicating required action
        """
        try:
            self.logger.debug(
                f"🚀 Performing fast heartbeat check for agent '{agent_id}'"
            )

            # Call generated client fast heartbeat check
            response = self.agents_api.fast_heartbeat_check(agent_id)

            # The fast_heartbeat_check HEAD request returns None for successful responses
            # since HEAD requests don't have response bodies. The actual HTTP status
            # is communicated through exceptions for non-200 status codes.
            if response is None:
                # Successful HEAD request - this means 200 OK (no changes)
                status_code = 200
                self.logger.debug(
                    f"Fast heartbeat HEAD request successful for agent '{agent_id}' - 200 OK"
                )
            else:
                # Unexpected non-None response - extract status if available
                status_code = getattr(response, "status", 200)
                self.logger.debug(
                    f"Fast heartbeat HEAD request returned response for agent '{agent_id}': {response}"
                )

            # Convert HTTP status to semantic status
            status = FastHeartbeatStatusUtil.from_http_code(status_code)

            self.logger.debug(
                f"✅ Fast heartbeat check completed for agent '{agent_id}': {status.value}"
            )
            return status

        except ValueError as e:
            # HTTP status code not supported
            self.logger.warning(
                f"Unsupported HTTP status in fast heartbeat for agent '{agent_id}': {e}"
            )
            return FastHeartbeatStatus.NETWORK_ERROR

        except Exception as e:
            # Check if this is an HTTP error with a specific status code
            error_str = str(e)

            # Handle 410 Gone specifically (agent unknown)
            if "(410)" in error_str or "Gone" in error_str:
                self.logger.info(
                    f"🔍 Fast heartbeat: Agent '{agent_id}' unknown (410 Gone) - re-registration needed"
                )
                return FastHeartbeatStatus.AGENT_UNKNOWN

            # Handle 503 Service Unavailable specifically (registry error)
            if "(503)" in error_str or "Service Unavailable" in error_str:
                self.logger.warning(
                    f"⚠️ Fast heartbeat: Registry error for agent '{agent_id}' (503) - skipping for resilience"
                )
                return FastHeartbeatStatus.REGISTRY_ERROR

            # Handle 202 Accepted specifically (topology changed)
            if "(202)" in error_str or "Accepted" in error_str:
                self.logger.info(
                    f"🔄 Fast heartbeat: Topology changed for agent '{agent_id}' (202) - full refresh needed"
                )
                return FastHeartbeatStatus.TOPOLOGY_CHANGED

            # All other errors treated as network errors
            self.logger.warning(
                f"Fast heartbeat check failed for agent '{agent_id}': {e}"
            )
            return FastHeartbeatStatusUtil.from_exception(e)

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
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

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

        # Use external endpoint information for registry advertisement (not binding address)
        external_host = agent_metadata.get("external_host")
        external_port = agent_metadata.get("external_port")
        external_endpoint = agent_metadata.get("external_endpoint")

        # Parse external endpoint if provided
        if external_endpoint:
            from urllib.parse import urlparse

            parsed = urlparse(external_endpoint)
            http_host = parsed.hostname or external_host or "localhost"
            http_port = (
                parsed.port or external_port or agent_metadata.get("http_port", 8080)
            )
        else:
            http_host = external_host or agent_metadata.get("http_host", "localhost")
            http_port = external_port or agent_metadata.get("http_port", 8080)

        # Fallback to localhost if we somehow get 0.0.0.0 (binding address)
        if http_host == "0.0.0.0":
            http_host = "localhost"

        return MeshAgentRegistration(
            agent_id=health_status.agent_name,
            agent_type="mcp_agent",
            name=health_status.agent_name,
            version=health_status.version,
            http_host=http_host,
            http_port=http_port,
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
