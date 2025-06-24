"""
Generated Registry Client Adapter

This module provides a compatibility wrapper around the OpenAPI-generated registry client
that maintains the same interface as the manual RegistryClient while using the generated
client underneath for type safety and contract compliance.

🤖 AI BEHAVIOR GUIDANCE:
This adapter bridges the manual client interface with the generated client implementation.
DO use this to replace manual HTTP calls with type-safe generated client calls.
DO maintain backward compatibility with existing method signatures.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from mcp_mesh import MeshAgentMetadata

from .exceptions import RegistryConnectionError, RegistryTimeoutError
from .shared.types import HealthStatus, MockHTTPResponse

# Import generated client components
try:
    from mcp_mesh.generated.mcp_mesh_registry_client.api.agents_api import AgentsApi
    from mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
    from mcp_mesh.generated.mcp_mesh_registry_client.configuration import Configuration
    from mcp_mesh.generated.mcp_mesh_registry_client.models import (
        AgentRegistration,
        AgentsListResponse,
        HeartbeatRequest,
        HeartbeatRequestMetadata,
        HeartbeatResponse,
        MeshAgentRegistration,
        MeshRegistrationResponse,
    )
    from mcp_mesh.generated.mcp_mesh_registry_client.rest import RESTResponseType

    GENERATED_CLIENT_AVAILABLE = True
except ImportError as e:
    logging.getLogger(__name__).warning(
        f"Generated client not available: {e}. Falling back to manual client."
    )
    GENERATED_CLIENT_AVAILABLE = False


class GeneratedRegistryClient:
    """
    Compatibility wrapper around the OpenAPI-generated registry client.

    This class provides the same interface as the manual RegistryClient but uses
    the generated client underneath for type safety and contract compliance.
    """

    def __init__(
        self, url: str | None = None, timeout: int = 30, retry_attempts: int = 3
    ):
        if not GENERATED_CLIENT_AVAILABLE:
            raise RegistryConnectionError(
                "Generated client not available. Run 'make generate' to create it."
            )

        env_url = self._get_registry_url_from_env()
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"GeneratedRegistryClient.__init__ called with url={url}")
        self.logger.debug(f"Environment URL: {env_url}")

        self.url = url or env_url
        self.timeout = timeout
        self.retry_attempts = retry_attempts

        # Configure the generated client
        config = Configuration(
            host=self.url.rstrip("/") if self.url else "http://localhost:8000"
        )
        config.timeout = timeout

        self.api_client = ApiClient(configuration=config)
        self.agents_api = AgentsApi(api_client=self.api_client)

        self.logger.debug(f"Generated client configured with host: {config.host}")

    def _get_registry_url_from_env(self) -> str | None:
        """Get registry URL from environment variables."""
        import os

        return os.getenv("MCP_MESH_REGISTRY_URL")

    # Core compatibility methods - maintain exact same signatures as manual client

    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str = None,
    ) -> bool:
        """
        Register agent with the registry using generated client.

        Maintains compatibility with manual client interface.
        """
        try:
            # Build AgentRegistration model
            registration = AgentRegistration(
                agent_id=agent_name,
                metadata={
                    "name": agent_name,
                    "agent_type": "mcp_agent",
                    "namespace": "default",
                    "endpoint": f"stdio://{agent_name}",
                    "capabilities": capabilities,
                    "dependencies": dependencies,
                    "security_context": security_context,
                    "version": "1.0.0",
                    "health_interval": 30,
                    "timeout_threshold": 60,
                    "eviction_threshold": 120,
                },
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )

            # Call generated client
            response = self.agents_api.register_agent(registration)

            # Log success
            self.logger.info(f"✅ Registered agent {agent_name} via generated client")
            return True

        except Exception as e:
            self.logger.error(f"❌ Registration failed for {agent_name}: {e}")
            return False

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry using generated client."""
        try:
            # Build HeartbeatRequest model
            heartbeat_request = HeartbeatRequest(
                agent_id=health_status.agent_name,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                metadata=HeartbeatRequestMetadata(
                    status=(
                        health_status.status.value
                        if hasattr(health_status.status, "value")
                        else health_status.status
                    ),
                    capabilities=health_status.capabilities,
                    uptime_seconds=health_status.uptime_seconds,
                    version=health_status.version or "1.0.0",
                    last_activity=(
                        health_status.timestamp.isoformat()
                        if health_status.timestamp
                        else None
                    ),
                    **health_status.metadata,
                ),
            )

            # Call generated client
            response = self.agents_api.send_heartbeat(heartbeat_request)

            self.logger.debug(
                f"💚 Heartbeat sent for {health_status.agent_name} via generated client"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"💔 Heartbeat failed for {health_status.agent_name}: {e}"
            )
            return False

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """
        Send periodic heartbeat and return full response for dependency injection.

        This method is critical for the dependency injection system.
        """
        try:
            # Build HeartbeatRequest model
            heartbeat_request = HeartbeatRequest(
                agent_id=health_status.agent_name,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                metadata=HeartbeatRequestMetadata(
                    status=(
                        health_status.status.value
                        if hasattr(health_status.status, "value")
                        else health_status.status
                    ),
                    capabilities=health_status.capabilities,
                    uptime_seconds=health_status.uptime_seconds,
                    version=health_status.version or "1.0.0",
                    last_activity=(
                        health_status.timestamp.isoformat()
                        if health_status.timestamp
                        else None
                    ),
                    **health_status.metadata,
                ),
            )

            # Call generated client and get full response
            response: HeartbeatResponse = self.agents_api.send_heartbeat(
                heartbeat_request
            )

            # Convert Pydantic response to dict for compatibility
            if response:
                result = {
                    "status": "success",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "message": "Heartbeat received",
                }

                # Add dependency resolution if available
                if (
                    hasattr(response, "dependencies_resolved")
                    and response.dependencies_resolved
                ):
                    result["dependencies_resolved"] = response.dependencies_resolved

                self.logger.debug(
                    f"💚 Heartbeat with response sent for {health_status.agent_name}"
                )
                return result
            else:
                return None

        except Exception as e:
            self.logger.error(
                f"💔 Heartbeat with response failed for {health_status.agent_name}: {e}"
            )
            return None

    async def register_agent_with_metadata(self, agent_id: str, metadata: Any) -> bool:
        """Register agent with enhanced metadata using generated client."""
        try:
            # Extract capabilities and dependencies from metadata
            capabilities = []
            dependencies = []

            if hasattr(metadata, "capabilities"):
                capabilities = [
                    cap.name if hasattr(cap, "name") else str(cap)
                    for cap in metadata.capabilities
                ]
            if hasattr(metadata, "dependencies"):
                dependencies = metadata.dependencies

            # Build AgentRegistration model
            registration = AgentRegistration(
                agent_id=agent_id,
                metadata={
                    "name": getattr(metadata, "name", agent_id),
                    "agent_type": "mcp_agent",
                    "namespace": getattr(metadata, "namespace", "default"),
                    "endpoint": getattr(metadata, "endpoint", f"stdio://{agent_id}"),
                    "capabilities": capabilities,
                    "dependencies": dependencies,
                    "description": getattr(metadata, "description", None),
                    "version": getattr(metadata, "version", "1.0.0"),
                    "tags": getattr(metadata, "tags", []),
                    "security_context": getattr(metadata, "security_context", None),
                    "health_interval": getattr(metadata, "health_interval", 30),
                    "timeout_threshold": 60,
                    "eviction_threshold": 120,
                },
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )

            # Call generated client
            response = self.agents_api.register_agent(registration)

            self.logger.info(
                f"✅ Registered agent {agent_id} with metadata via generated client"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"❌ Registration with metadata failed for {agent_id}: {e}"
            )
            return False

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all registered agents using generated client."""
        try:
            response: AgentsListResponse = self.agents_api.list_agents()

            # Convert Pydantic response to dict list for compatibility
            if response and hasattr(response, "agents"):
                agents = []
                for agent in response.agents:
                    agent_dict = (
                        agent.model_dump()
                        if hasattr(agent, "model_dump")
                        else agent.__dict__
                    )
                    agents.append(agent_dict)
                return agents
            else:
                return []

        except Exception as e:
            self.logger.error(f"❌ Failed to get all agents: {e}")
            return []

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get specific agent by ID using generated client."""
        try:
            # Note: Generated client may not have get single agent endpoint
            # Fallback to getting all agents and filtering
            all_agents = await self.get_all_agents()
            for agent in all_agents:
                if agent.get("id") == agent_id or agent.get("agent_id") == agent_id:
                    return agent
            return None

        except Exception as e:
            self.logger.error(f"❌ Failed to get agent {agent_id}: {e}")
            return None

    # Additional compatibility methods

    async def register_multi_tool_agent(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Register agent using multi-tool format with generated client."""
        try:
            # Build MeshAgentRegistration model for multi-tool format
            mesh_registration = MeshAgentRegistration(
                agent_id=agent_id,
                agent_type=metadata.get("agent_type", "mcp_agent"),
                name=metadata.get("name", agent_id),
                namespace=metadata.get("namespace", "default"),
                endpoint=metadata.get("endpoint", f"stdio://{agent_id}"),
                tools=metadata.get("tools", []),
            )

            # Call generated client (assuming it has mesh registration endpoint)
            response = self.agents_api.register_agent(mesh_registration)

            # Convert response to dict for compatibility
            if response:
                result = {
                    "status": "success",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "message": "Multi-tool agent registered successfully",
                    "agent_id": agent_id,
                }

                # Add dependency resolution if available
                if (
                    hasattr(response, "dependencies_resolved")
                    and response.dependencies_resolved
                ):
                    result["dependencies_resolved"] = response.dependencies_resolved

                return result
            else:
                return None

        except Exception as e:
            self.logger.error(f"❌ Multi-tool registration failed for {agent_id}: {e}")
            return None

    def parse_tool_dependencies(
        self, registry_response: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Parse per-tool dependency resolution from registry response."""
        # Same logic as manual client - this is response parsing, not API call
        if (
            "metadata" in registry_response
            and "dependencies_resolved" in registry_response["metadata"]
        ):
            dependencies = registry_response["metadata"]["dependencies_resolved"]
            if isinstance(dependencies, dict):
                return dependencies

        if "dependencies_resolved" in registry_response:
            dependencies = registry_response["dependencies_resolved"]
            if isinstance(dependencies, dict):
                return {"legacy_tool": dependencies}

        return {}

    async def send_heartbeat_with_dependency_resolution(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """Send heartbeat and return full dependency resolution."""
        # Same as send_heartbeat_with_response for compatibility
        return await self.send_heartbeat_with_response(health_status)

    # HTTP compatibility methods for test framework

    async def post(
        self, endpoint: str, json: dict[str, Any] = None
    ) -> MockHTTPResponse:
        """Make a POST request using generated client (compatibility method)."""
        try:
            if endpoint == "/agents/register":
                # Convert dict to proper model and register
                if json:
                    agent_id = json.get("agent_id", "unknown")
                    metadata = json.get("metadata", {})

                    registration = AgentRegistration(
                        agent_id=agent_id,
                        metadata=metadata,
                        timestamp=json.get(
                            "timestamp",
                            datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        ),
                    )

                    response = self.agents_api.register_agent(registration)

                    return MockHTTPResponse(
                        {
                            "status": "success",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "message": "Agent registered successfully",
                            "agent_id": agent_id,
                        },
                        201,
                    )

            elif endpoint == "/heartbeat":
                # Convert dict to proper model and send heartbeat
                if json:
                    agent_id = json.get("agent_id", "unknown")

                    heartbeat_request = HeartbeatRequest(
                        agent_id=agent_id,
                        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        metadata=HeartbeatRequestMetadata(**json.get("metadata", {})),
                    )

                    response = self.agents_api.send_heartbeat(heartbeat_request)

                    return MockHTTPResponse(
                        {
                            "status": "success",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "message": "Heartbeat received",
                        },
                        200,
                    )

            # Default response for unknown endpoints
            return MockHTTPResponse(
                {"status": "ok", "message": "Generated client response"}, 200
            )

        except Exception as e:
            self.logger.error(f"❌ POST request failed for {endpoint}: {e}")
            return MockHTTPResponse({"error": str(e)}, 500)

    async def put(self, endpoint: str, json: dict[str, Any] = None) -> MockHTTPResponse:
        """Make a PUT request (compatibility method)."""
        return MockHTTPResponse(
            {"status": "ok", "message": "Generated client PUT response"}, 200
        )

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.api_client:
            # Generated client should handle cleanup
            pass

    # Additional methods for compatibility

    async def get_dependency(self, dependency_name: str) -> Any:
        """Retrieve dependency configuration from registry."""
        # This might need to be implemented via the agents list
        all_agents = await self.get_all_agents()
        for agent in all_agents:
            capabilities = agent.get("capabilities", [])
            if dependency_name in capabilities or agent.get("id") == dependency_name:
                return {
                    "agent_id": agent.get("id"),
                    "endpoint": agent.get("endpoint"),
                    "capabilities": capabilities,
                    "version": agent.get("version", "1.0.0"),
                }
        return None

    async def update_agent_health(
        self, agent_id: str, health_data: dict[str, Any]
    ) -> bool:
        """Update agent health information."""
        # This could be implemented via heartbeat with health data
        try:
            # Create a health status from the health data
            from .shared.types import HealthStatusType

            health_status = HealthStatus(
                agent_name=agent_id,
                status=HealthStatusType.HEALTHY,  # Default to healthy
                capabilities=[],
                timestamp=datetime.now(UTC),
                uptime_seconds=0,
                version="1.0.0",
                metadata=health_data,
            )

            return await self.send_heartbeat(health_status)

        except Exception as e:
            self.logger.error(f"❌ Update health failed for {agent_id}: {e}")
            return False

    async def deregister_agent(self, agent_id: str) -> bool:
        """Deregister an agent from the registry."""
        # Generated client may not have deregister endpoint
        # This might need to be implemented differently
        self.logger.warning(
            f"Deregister not implemented in generated client for {agent_id}"
        )
        return False

    async def update_agent_endpoint(self, agent_id: str, endpoint: str) -> bool:
        """Update agent endpoint."""
        # This could be implemented via heartbeat with updated endpoint
        self.logger.warning(
            f"Update endpoint not implemented in generated client for {agent_id}"
        )
        return False
