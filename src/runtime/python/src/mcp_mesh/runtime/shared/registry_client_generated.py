"""
Generated Registry Client Wrapper

This module provides a wrapper around the auto-generated OpenAPI client
to maintain compatibility with the existing MCP Mesh runtime.

🤖 AI BEHAVIOR GUIDANCE:
This wrapper bridges the generated client with existing code.

DO NOT modify the generated client code directly.
DO extend functionality through this wrapper.

TO UPDATE CLIENT:
1. Update api/mcp-mesh-registry.openapi.yaml
2. Run: make generate
3. Update wrapper methods if needed (this file)
4. Update tests to match new contract
"""

from datetime import datetime
from typing import Any

# Import generated client (will be available after generation)
try:
    from mcp_mesh.registry_client_generated import ApiClient, Configuration, DefaultApi
    from mcp_mesh.registry_client_generated.models import (
        AgentRegistration,
        AgentsListResponse,
        HealthResponse,
        HeartbeatRequest,
        HeartbeatResponse,
        RegistrationResponse,
    )

    GENERATED_CLIENT_AVAILABLE = True
except ImportError:
    GENERATED_CLIENT_AVAILABLE = False

from .exceptions import RegistryConnectionError
from .types import HealthStatus


class GeneratedRegistryClient:
    """
    Wrapper around the auto-generated OpenAPI client.

    This provides a compatibility layer between the generated client
    and the existing MCP Mesh runtime interface.
    """

    def __init__(self, url: str, timeout: int = 30):
        if not GENERATED_CLIENT_AVAILABLE:
            raise RegistryConnectionError(
                "Generated client not available. Run 'make generate' first."
            )

        # Configure the generated client
        configuration = Configuration(host=url)
        self.api_client = ApiClient(configuration)
        self.api = DefaultApi(self.api_client)
        self.timeout = timeout

    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str | None = None,
    ) -> bool:
        """Register agent with the registry using generated client."""
        try:
            registration = AgentRegistration(
                agent_id=agent_name,
                metadata={
                    "name": agent_name,
                    "agent_type": "mesh_agent",
                    "namespace": "default",
                    "endpoint": f"stdio://{agent_name}",
                    "capabilities": capabilities,
                    "dependencies": dependencies,
                    "health_interval": 30,
                    "version": "1.0.0",
                },
                timestamp=datetime.now().isoformat(),
            )

            response: RegistrationResponse = await self.api.register_agent(registration)
            return response.status == "success"

        except Exception as e:
            raise RegistryConnectionError(f"Registration failed: {e}")

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send heartbeat using generated client."""
        try:
            heartbeat = HeartbeatRequest(
                agent_id=health_status.agent_name,
                status=(
                    health_status.status.value
                    if hasattr(health_status.status, "value")
                    else health_status.status
                ),
                metadata={
                    "capabilities": health_status.capabilities,
                    "timestamp": (
                        health_status.timestamp.isoformat()
                        if health_status.timestamp
                        else None
                    ),
                    "uptime_seconds": health_status.uptime_seconds,
                    "version": health_status.version,
                },
            )

            response: HeartbeatResponse = await self.api.send_heartbeat(heartbeat)
            return response.status == "success"

        except Exception as e:
            raise RegistryConnectionError(f"Heartbeat failed: {e}")

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """Send heartbeat and return full response."""
        try:
            heartbeat = HeartbeatRequest(
                agent_id=health_status.agent_name,
                status=(
                    health_status.status.value
                    if hasattr(health_status.status, "value")
                    else health_status.status
                ),
                metadata={
                    "capabilities": health_status.capabilities,
                    "timestamp": (
                        health_status.timestamp.isoformat()
                        if health_status.timestamp
                        else None
                    ),
                    "uptime_seconds": health_status.uptime_seconds,
                    "version": health_status.version,
                },
            )

            response: HeartbeatResponse = await self.api.send_heartbeat(heartbeat)

            # Convert generated model to dict for compatibility
            return {
                "status": response.status,
                "timestamp": response.timestamp,
                "message": response.message,
                "dependencies_resolved": getattr(
                    response, "dependencies_resolved", None
                ),
            }

        except Exception as e:
            raise RegistryConnectionError(f"Heartbeat failed: {e}")

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all registered agents."""
        try:
            response: AgentsListResponse = await self.api.list_agents()

            # Convert generated models to dicts
            return [
                {
                    "id": agent.id,
                    "name": agent.name,
                    "status": agent.status,
                    "endpoint": agent.endpoint,
                    "capabilities": agent.capabilities,
                    "dependencies": getattr(agent, "dependencies", []),
                    "last_seen": getattr(agent, "last_seen", None),
                    "version": getattr(agent, "version", None),
                }
                for agent in response.agents
            ]

        except Exception as e:
            raise RegistryConnectionError(f"Failed to get agents: {e}")

    async def close(self) -> None:
        """Close the client session."""
        if hasattr(self.api_client, "close"):
            await self.api_client.close()


# Factory function for backward compatibility
def create_generated_registry_client(url: str, **kwargs) -> GeneratedRegistryClient:
    """Create a generated registry client with the specified URL."""
    return GeneratedRegistryClient(url, **kwargs)
