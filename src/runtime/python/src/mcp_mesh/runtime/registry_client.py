"""
MCP Mesh Registry Client

Client for communicating with the mesh registry service.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

try:
    import aiohttp
except ImportError:
    aiohttp = None

from mcp_mesh import MeshAgentMetadata

from .exceptions import RegistryConnectionError, RegistryTimeoutError
from .shared.types import HealthStatus, MockHTTPResponse


class RegistryClient:
    """Client for communicating with the mesh registry service."""

    def __init__(
        self, url: str | None = None, timeout: int = 30, retry_attempts: int = 3
    ):
        self.url = url or self._get_registry_url_from_env()
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session: Any | None = None
        self.logger = logging.getLogger(__name__)

    async def _get_session(self) -> Any:
        """Get or create HTTP session."""
        if aiohttp is None:
            raise RegistryConnectionError("aiohttp is required for registry client")

        if not self._session:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str | None = None,
    ) -> bool:
        """Register agent with the registry."""
        payload = {
            "agent_name": agent_name,
            "capabilities": capabilities,
            "dependencies": dependencies,
            "security_context": security_context,
            "timestamp": datetime.now().isoformat(),
        }

        result = await self._make_request("POST", "/agents/register", payload)
        return result is not None

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry."""
        # Convert to Go registry format - expects agent_id, status, and metadata
        payload = {
            "agent_id": health_status.agent_name,  # Go registry expects agent_id
            "status": (
                health_status.status.value
                if hasattr(health_status.status, "value")
                else health_status.status
            ),
            "metadata": {
                "capabilities": health_status.capabilities,
                "timestamp": (
                    health_status.timestamp.isoformat()
                    if health_status.timestamp
                    else None
                ),
                "checks": health_status.checks,
                "errors": health_status.errors,
                "uptime_seconds": health_status.uptime_seconds,
                "version": health_status.version,
                **health_status.metadata,  # Include any additional metadata
            },
        }
        # Use /heartbeat endpoint (not /agents/heartbeat)
        result = await self._make_request("POST", "/heartbeat", payload)
        return result is not None

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict | None:
        """Send periodic heartbeat to registry and return full response."""
        # Convert to Go registry format - expects agent_id, status, and metadata
        payload = {
            "agent_id": health_status.agent_name,  # Go registry expects agent_id
            "status": (
                health_status.status.value
                if hasattr(health_status.status, "value")
                else health_status.status
            ),
            "metadata": {
                "capabilities": health_status.capabilities,
                "timestamp": (
                    health_status.timestamp.isoformat()
                    if health_status.timestamp
                    else None
                ),
                "checks": health_status.checks,
                "errors": health_status.errors,
                "uptime_seconds": health_status.uptime_seconds,
                "version": health_status.version,
                **health_status.metadata,  # Include any additional metadata
            },
        }
        # Use /heartbeat endpoint (not /agents/heartbeat)
        return await self._make_request("POST", "/heartbeat", payload)

    async def get_dependency(self, dependency_name: str) -> Any:
        """Retrieve dependency configuration from registry."""
        response = await self._make_request("GET", f"/dependencies/{dependency_name}")
        return response.get("value") if response else None

    async def register_agent_with_metadata(
        self, agent_id: str, metadata: MeshAgentMetadata
    ) -> bool:
        """Register agent with enhanced metadata for capability discovery."""
        # Convert capability metadata to dict format
        capabilities_data = []
        for cap in metadata.capabilities:
            capabilities_data.append(
                {
                    "name": cap.name,
                    "version": cap.version,
                    "description": cap.description,
                    "parent_capabilities": cap.parent_capabilities,
                    "tags": cap.tags,
                    "parameters": cap.parameters,
                    "performance_metrics": cap.performance_metrics,
                    "security_level": cap.security_level,
                    "resource_requirements": cap.resource_requirements,
                    "metadata": cap.metadata,
                }
            )

        payload = {
            "agent_id": agent_id,
            "metadata": {
                # Required fields for Agent model
                "id": agent_id,
                "name": metadata.name or agent_id,  # Use agent_id as fallback name
                "endpoint": metadata.endpoint
                or "stdio://localhost",  # Default endpoint for MCP
                "namespace": "default",  # Default namespace
                "status": "healthy",  # Initial status
                # Health configuration
                "health_interval": metadata.health_interval,
                "timeout_threshold": 60,  # Default 60 seconds
                "eviction_threshold": 120,  # Default 120 seconds
                "agent_type": "mcp_agent",  # Default agent type
                # Optional security context
                "security_context": metadata.security_context,
                # Enhanced metadata
                "version": metadata.version,
                "description": metadata.description,
                "capabilities": capabilities_data,
                "dependencies": metadata.dependencies,
                "tags": metadata.tags,
                "performance_profile": metadata.performance_profile,
                "resource_usage": metadata.resource_usage,
                "created_at": metadata.created_at.isoformat(),
                "last_seen": metadata.last_seen.isoformat(),
                "metadata": metadata.metadata,
            },
            "timestamp": datetime.now().isoformat(),
        }

        result = await self._make_request("POST", "/agents/register", payload)
        return result is not None

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all registered agents."""
        response = await self._make_request("GET", "/agents")
        return response.get("agents", []) if response else []

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get specific agent by ID."""
        response = await self._make_request("GET", f"/agents/{agent_id}")
        return response if response else None

    async def update_agent_health(
        self, agent_id: str, health_data: dict[str, Any]
    ) -> bool:
        """Update agent health information."""
        payload = {
            "agent_id": agent_id,
            "health_data": health_data,
            "timestamp": datetime.now().isoformat(),
        }

        result = await self._make_request("POST", f"/agents/{agent_id}/health", payload)
        return result is not None

    async def deregister_agent(self, agent_id: str) -> bool:
        """Deregister an agent from the registry."""
        result = await self._make_request("DELETE", f"/agents/{agent_id}")
        return result is not None

    async def _make_request(
        self, method: str, endpoint: str, payload: dict | None = None
    ) -> dict | None:
        """Make HTTP request to registry with retry logic."""
        self.logger.debug(f"Making {method} request to {endpoint}")
        self.logger.debug(f"Payload: {payload}")

        if aiohttp is None:
            # Fallback mode: simulate successful requests
            self.logger.warning("aiohttp is None, using fallback mode")
            return {"status": "ok", "message": "fallback mode"}

        try:
            session = await self._get_session()
            url = f"{self.url}{endpoint}"
            self.logger.debug(f"Full URL: {url}")

            for attempt in range(self.retry_attempts):
                try:
                    self.logger.debug(f"Attempt {attempt + 1}/{self.retry_attempts}")

                    if method == "GET":
                        async with session.get(url) as response:
                            self.logger.debug(f"GET response status: {response.status}")
                            if response.status == 200:
                                return await response.json()
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                    elif method == "POST":
                        self.logger.debug("Sending POST request...")
                        async with session.post(url, json=payload) as response:
                            if response.status in [200, 201]:
                                return (
                                    await response.json()
                                    if response.content_length
                                    else {"status": "ok"}
                                )
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                    elif method == "PUT":
                        self.logger.debug("Sending PUT request...")
                        async with session.put(url, json=payload) as response:
                            if response.status in [200, 201]:
                                return (
                                    await response.json()
                                    if response.content_length
                                    else {"status": "ok"}
                                )
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                except asyncio.TimeoutError:
                    if attempt == self.retry_attempts - 1:
                        raise RegistryTimeoutError(
                            f"Registry request timed out after {self.retry_attempts} attempts"
                        ) from None
                except Exception as e:
                    if attempt == self.retry_attempts - 1:
                        raise RegistryConnectionError(
                            f"Failed to connect to registry: {e}"
                        ) from e

                # Exponential backoff
                await asyncio.sleep(2**attempt)

        except Exception:
            # In fallback mode, return None to allow graceful degradation
            return None

        return None

    async def post(self, endpoint: str, json: dict | None = None) -> Any:
        """Make a POST request to the registry."""
        try:
            result = await self._make_request("POST", endpoint, json)
            if result:
                return MockHTTPResponse(result, 201)
            else:
                return MockHTTPResponse({"error": "Failed to connect to registry"}, 500)
        except Exception as e:
            return MockHTTPResponse({"error": str(e)}, 500)

    async def put(self, endpoint: str, json: dict | None = None) -> Any:
        """Make a PUT request to the registry."""
        try:
            result = await self._make_request("PUT", endpoint, json)
            if result:
                return MockHTTPResponse(result, 200)
            else:
                return MockHTTPResponse({"error": "Failed to connect to registry"}, 500)
        except Exception as e:
            return MockHTTPResponse({"error": str(e)}, 500)

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()

    # NEW MULTI-TOOL METHODS (TDD Implementation)

    async def register_multi_tool_agent(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Register agent using the new multi-tool format.

        Args:
            agent_id: Unique identifier for the agent
            metadata: Agent metadata including tools array

        Expected metadata format:
        {
            "name": "agent-name",
            "endpoint": "http://localhost:8080",
            "timeout_threshold": 60,
            "eviction_threshold": 120,
            "tools": [
                {
                    "function_name": "tool_name",
                    "capability": "capability_name",
                    "version": "1.0.0",
                    "tags": ["tag1", "tag2"],
                    "dependencies": [
                        {
                            "capability": "required_capability",
                            "version": ">=1.0.0",
                            "tags": ["production"]
                        }
                    ]
                }
            ]
        }

        Returns:
            Registration response with per-tool dependency resolution
        """
        payload = {
            "agent_id": agent_id,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
        }

        self.logger.info(
            f"Registering multi-tool agent {agent_id} with {len(metadata.get('tools', []))} tools"
        )

        result = await self._make_request("POST", "/agents/register", payload)
        return result

    def parse_tool_dependencies(
        self, registry_response: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """
        Parse per-tool dependency resolution from registry response.

        Args:
            registry_response: Response from registry registration or heartbeat

        Returns:
            Dict mapping tool names to their resolved dependencies:
            {
                "tool_name": {
                    "dependency_capability": {
                        "agent_id": "provider-id",
                        "tool_name": "provider-tool",
                        "endpoint": "http://provider:8080",
                        "version": "1.0.0"
                    }
                }
            }
        """
        try:
            # Check for new per-tool format first
            if (
                "metadata" in registry_response
                and "dependencies_resolved" in registry_response["metadata"]
            ):
                dependencies = registry_response["metadata"]["dependencies_resolved"]
                if isinstance(dependencies, dict):
                    return dependencies

            # Fallback to root-level dependencies_resolved for backward compatibility
            if "dependencies_resolved" in registry_response:
                dependencies = registry_response["dependencies_resolved"]
                if isinstance(dependencies, dict):
                    # If it's old format, try to adapt it
                    return {"legacy_tool": dependencies}

            return {}
        except Exception as e:
            self.logger.warning(f"Failed to parse tool dependencies: {e}")
            return {}

    async def send_heartbeat_with_dependency_resolution(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """
        Send heartbeat and return full dependency resolution for all tools.

        This is the core method for getting updated dependency information.
        The Go registry always returns the full dependency state, and Python
        handles comparing with previous state.

        Args:
            health_status: Current health status of the agent

        Returns:
            Heartbeat response including full dependency resolution:
            {
                "status": "success",
                "timestamp": "2023-12-20T10:30:45Z",
                "dependencies_resolved": {
                    "tool1": {"dep1": {...}},
                    "tool2": {"dep2": {...}}
                }
            }
        """
        # Convert to Go registry format - same as existing heartbeat
        payload = {
            "agent_id": health_status.agent_name,
            "status": (
                health_status.status.value
                if hasattr(health_status.status, "value")
                else health_status.status
            ),
            "metadata": {
                "capabilities": health_status.capabilities,
                "timestamp": (
                    health_status.timestamp.isoformat()
                    if health_status.timestamp
                    else None
                ),
                "checks": health_status.checks,
                "errors": health_status.errors,
                "uptime_seconds": health_status.uptime_seconds,
                "version": health_status.version,
                **health_status.metadata,
            },
        }

        self.logger.debug(
            f"Sending heartbeat for {health_status.agent_name} with dependency resolution"
        )

        # Use /heartbeat endpoint - Go registry returns full dependency state
        result = await self._make_request("POST", "/heartbeat", payload)
        return result
