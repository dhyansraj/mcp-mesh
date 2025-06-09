"""
MCP Mesh Registry Client

Client for communicating with the mesh registry service.
"""

import asyncio
import os
from datetime import datetime
from typing import Any

try:
    import aiohttp
except ImportError:
    aiohttp = None

from mcp_mesh import MeshAgentMetadata

from .exceptions import RegistryConnectionError, RegistryTimeoutError
from .types import HealthStatus


class RegistryClient:
    """Client for communicating with the mesh registry service."""

    def __init__(
        self, url: str | None = None, timeout: int = 30, retry_attempts: int = 3
    ):
        self.url = url or self._get_registry_url_from_env()
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session: Any | None = None

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
        payload = health_status.dict()
        result = await self._make_request("POST", "/agents/heartbeat", payload)
        return result is not None

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

        result = await self._make_request(
            "POST", "/agents/register_with_metadata", payload
        )
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
        print(f"🐛 DEBUG (Python): Making {method} request to {endpoint}")
        print(f"🐛 DEBUG (Python): Payload: {payload}")

        if aiohttp is None:
            # Fallback mode: simulate successful requests
            print("🐛 DEBUG (Python): aiohttp is None, using fallback mode")
            return {"status": "ok", "message": "fallback mode"}

        try:
            session = await self._get_session()
            url = f"{self.url}{endpoint}"
            print(f"🐛 DEBUG (Python): Full URL: {url}")

            for attempt in range(self.retry_attempts):
                try:
                    print(
                        f"🐛 DEBUG (Python): Attempt {attempt + 1}/{self.retry_attempts}"
                    )

                    if method == "GET":
                        async with session.get(url) as response:
                            print(
                                f"🐛 DEBUG (Python): GET response status: {response.status}"
                            )
                            if response.status == 200:
                                return await response.json()
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                    elif method == "POST":
                        print("🐛 DEBUG (Python): Sending POST request...")
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

                except asyncio.TimeoutError:
                    if attempt == self.retry_attempts - 1:
                        raise RegistryTimeoutError(
                            f"Registry request timed out after {self.retry_attempts} attempts"
                        )
                except Exception as e:
                    if attempt == self.retry_attempts - 1:
                        raise RegistryConnectionError(
                            f"Failed to connect to registry: {e}"
                        )

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

            # Create a mock response object that has status and json() method
            class MockResponse:
                def __init__(self, data, status=201):
                    self.status = status
                    self._data = data

                async def json(self):
                    return self._data

                async def text(self):
                    return str(self._data)

            if result:
                return MockResponse(result, 201)
            else:
                return MockResponse({"error": "Failed to connect to registry"}, 500)

        except Exception as e:

            class MockResponse:
                def __init__(self, error, status=500):
                    self.status = status
                    self._error = error

                async def json(self):
                    return {"error": str(self._error)}

                async def text(self):
                    return str(self._error)

            return MockResponse(e, 500)

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8080")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
