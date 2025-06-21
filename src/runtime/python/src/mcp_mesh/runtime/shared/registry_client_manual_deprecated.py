"""
DEPRECATED: Manual Registry Client

This is the old manually-implemented registry client.
It has been replaced by a generated client from OpenAPI specification.

🤖 AI BEHAVIOR GUIDANCE:
DO NOT use this deprecated client.
DO use the generated client from: mcp_mesh.runtime.shared.registry_client_generated

MIGRATION PATH:
1. Import: from mcp_mesh.runtime.shared.registry_client_generated import GeneratedRegistryClient
2. Replace RegistryClient with GeneratedRegistryClient
3. Update method calls to match generated client interface

This file is kept for reference only.
"""

import asyncio
import os
from datetime import datetime
from typing import Any

try:
    import aiohttp
except ImportError:
    aiohttp = None

# Import at function level to avoid circular import
# from mcp_mesh import MeshAgentMetadata

from .exceptions import RegistryConnectionError, RegistryTimeoutError
from .types import HealthStatus, MockHTTPResponse


class RegistryClient:
    """Client for communicating with the mesh registry service."""

    def __init__(
        self, url: str | None = None, timeout: int = 30, retry_attempts: int = 3
    ):
        self.url = url or self._get_registry_url_from_env()
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session: Any | None = None
        self._response_cache: dict[str, tuple[Any, float]] = (
            {}
        )  # Simple cache with timestamps
        self._cache_ttl = 60.0  # Cache responses for 60 seconds

    async def _get_session(self) -> Any:
        """Get or create HTTP session."""
        if aiohttp is None:
            raise RegistryConnectionError("aiohttp is required for registry client")

        if not self._session:
            # Create session with connection pooling
            connector = aiohttp.TCPConnector(
                limit=100,  # Total connection pool size
                limit_per_host=30,  # Per-host connection limit
                ttl_dns_cache=300,  # DNS cache TTL
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
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

    async def get_dependency(self, dependency_name: str) -> Any:
        """Retrieve dependency configuration from registry."""
        response = await self._make_request("GET", f"/dependencies/{dependency_name}")
        return response.get("value") if response else None

    async def register_agent_with_metadata(
        self,
        agent_id: str,
        metadata: Any,  # MeshAgentMetadata
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
        # Check cache first
        cache_key = "GET:/agents"
        cached_result = self._get_cached_response(cache_key)
        if cached_result is not None:
            return cached_result.get("agents", [])

        response = await self._make_request("GET", "/agents")
        if response:
            self._cache_response(cache_key, response)
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
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"Making {method} request to {endpoint}")
        logger.debug(f"Payload: {payload}")

        if aiohttp is None:
            # Fallback mode: simulate successful requests
            logger.warning("aiohttp is None, using fallback mode")
            return {"status": "ok", "message": "fallback mode"}

        try:
            session = await self._get_session()
            url = f"{self.url}{endpoint}"
            logger.debug(f"Full URL: {url}")

            for attempt in range(self.retry_attempts):
                try:
                    logger.debug(f"Attempt {attempt + 1}/{self.retry_attempts}")

                    if method == "GET":
                        async with session.get(url) as response:
                            logger.debug(f"GET response status: {response.status}")
                            if response.status == 200:
                                return await response.json()
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                    elif method == "POST":
                        logger.debug("Sending POST request...")
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

                except TimeoutError:
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

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8080")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
        self._response_cache.clear()

    def _get_cached_response(self, key: str) -> Any | None:
        """Get cached response if still valid."""
        import time

        if key in self._response_cache:
            response, timestamp = self._response_cache[key]
            if time.time() - timestamp < self._cache_ttl:
                import logging

                logger = logging.getLogger(__name__)
                logger.debug(f"Cache hit for {key}")
                return response
            else:
                # Remove expired entry
                del self._response_cache[key]
        return None

    def _cache_response(self, key: str, response: Any) -> None:
        """Cache a response with current timestamp."""
        import time

        self._response_cache[key] = (response, time.time())
