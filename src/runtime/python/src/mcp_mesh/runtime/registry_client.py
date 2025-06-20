"""
MCP Mesh Registry Client

Client for communicating with the mesh registry service.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
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
        env_url = self._get_registry_url_from_env()
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"RegistryClient.__init__ called with url={url}")
        self.logger.debug(f"Environment URL: {env_url}")
        self.url = url or env_url
        self.logger.debug(f"Final URL set to: {self.url}")
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session: Any | None = None

    async def _get_session(self) -> Any:
        """Get or create HTTP session."""
        if aiohttp is None:
            raise RegistryConnectionError("aiohttp is required for registry client")

        if not self._session:
            # Create session with connector that doesn't register atexit handlers
            connector = aiohttp.TCPConnector()
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), connector=connector
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
        # Format according to OpenAPI AgentRegistration schema
        payload = {
            "agent_id": agent_name,  # Use agent_name as agent_id
            "metadata": {
                "name": agent_name,
                "agent_type": "mcp_agent",  # Required field
                "namespace": "default",  # Required field
                "endpoint": "stdio://localhost",  # Default for MCP agents
                "capabilities": capabilities,  # Simple string array
                "dependencies": dependencies,  # Simple string array
                "security_context": security_context,
            },
            "timestamp": datetime.now().isoformat()
            + "Z",  # RFC3339 format required by Go
        }

        result = await self._make_request("POST", "/agents/register", payload)
        return result is not None

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry using same format as registration."""
        # Build MeshAgentRegistration payload for unified /heartbeat endpoint
        from datetime import datetime

        # Get cached agent data from DecoratorRegistry
        agent_id = health_status.agent_name

        # Convert capabilities to tools format (same as registration)
        tools = []
        for capability in health_status.capabilities:
            tools.append(
                {
                    "function_name": capability,  # Required field
                    "capability": capability,  # Required field
                    "version": "1.0.0",
                    "tags": [],
                    "dependencies": [],
                    "description": f"Tool {capability}",
                }
            )

        # Build same MeshAgentRegistration format as registration
        payload = {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "namespace": "default",
            "endpoint": health_status.metadata.get("endpoint", f"stdio://{agent_id}"),
            "tools": tools,  # Required field in new schema
            "health_interval": health_status.metadata.get("health_interval", 30),
            "tags": [],
            "version": health_status.version or "1.0.0",
            "description": health_status.metadata.get("description"),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        self.logger.debug(f"💓 HEARTBEAT REQUEST for agent: {agent_id}")
        self.logger.debug(f"   Tools count: {len(tools)}")
        self.logger.debug(f"   Payload: {payload}")

        # Send to /heartbeat endpoint with MeshAgentRegistration format
        result = await self._make_request("POST", "/heartbeat", payload)

        if result:
            self.logger.debug(f"💓 HEARTBEAT SUCCESS for agent: {agent_id}")
            self.logger.debug(f"   Response: {result}")
        else:
            self.logger.debug(f"💓 HEARTBEAT FAILED for agent: {agent_id}")

        return result is not None

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict | None:
        """Send periodic heartbeat to registry using same format as registration and return full response."""
        # Build MeshAgentRegistration payload for unified /heartbeat endpoint
        from datetime import datetime

        # Get cached agent data from DecoratorRegistry
        agent_id = health_status.agent_name

        # Convert capabilities to tools format (same as registration)
        tools = []
        for capability in health_status.capabilities:
            tools.append(
                {
                    "function_name": capability,  # Required field
                    "capability": capability,  # Required field
                    "version": "1.0.0",
                    "tags": [],
                    "dependencies": [],
                    "description": f"Tool {capability}",
                }
            )

        # Build same MeshAgentRegistration format as registration
        payload = {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "namespace": "default",
            "endpoint": health_status.metadata.get("endpoint", f"stdio://{agent_id}"),
            "tools": tools,  # Required field in new schema
            "health_interval": health_status.metadata.get("health_interval", 30),
            "tags": [],
            "version": health_status.version or "1.0.0",
            "description": health_status.metadata.get("description"),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Send to /heartbeat endpoint with MeshAgentRegistration format
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

        # Convert complex capabilities to simple string array for OpenAPI compliance
        simple_capabilities = (
            [cap.name for cap in capabilities_data] if capabilities_data else []
        )

        # Format according to OpenAPI AgentRegistration schema - only valid fields
        payload = {
            "agent_id": agent_id,
            "metadata": {
                # Required fields per OpenAPI AgentMetadata schema
                "name": metadata.name or agent_id,
                "agent_type": "mcp_agent",  # Required: enum value
                "namespace": "default",  # Required: agent namespace
                "endpoint": metadata.endpoint or "stdio://localhost",  # Required
                "capabilities": simple_capabilities,  # Required: simple string array
                # Optional fields per OpenAPI schema
                "dependencies": metadata.dependencies,
                "description": metadata.description,
                "version": metadata.version,
                "tags": metadata.tags,
                "security_context": metadata.security_context,
                "health_interval": metadata.health_interval,
                "timeout_threshold": 60,
                "eviction_threshold": 120,
            },
            "timestamp": datetime.now().isoformat()
            + "Z",  # RFC3339 format required by Go
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
            "timestamp": datetime.now().isoformat()
            + "Z",  # RFC3339 format required by Go
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
        self.logger.debug(f"Registry URL: {self.url}")
        self.logger.debug(f"Full URL will be: {self.url}{endpoint}")
        self.logger.debug(f"Payload: {payload}")

        if aiohttp is None:
            # Fallback mode: simulate successful requests
            self.logger.warning("aiohttp is None, using fallback mode")
            return {"status": "success", "message": "fallback mode"}

        try:
            session = await self._get_session()
            url = f"{self.url}{endpoint}"
            self.logger.debug(f"Full URL: {url}")

            for attempt in range(self.retry_attempts):
                try:
                    self.logger.debug(f"Attempt {attempt + 1}/{self.retry_attempts}")

                    if method == "GET":
                        self.logger.debug(f"Making GET request to {url}")
                        async with session.get(url) as response:
                            self.logger.debug(f"GET response status: {response.status}")
                            if response.status == 200:
                                result = await response.json()
                                self.logger.debug(f"GET success, result: {result}")
                                return result
                            else:
                                raise RegistryConnectionError(
                                    f"Registry returned {response.status}"
                                )

                    elif method == "POST":
                        self.logger.debug("Sending POST request...")
                        try:
                            self.logger.debug("AIOHTTP POST REQUEST")
                            self.logger.debug(f"URL: {url}")
                            self.logger.debug(f"Payload: {payload}")

                            async with session.post(url, json=payload) as response:
                                self.logger.debug("AIOHTTP RESPONSE RECEIVED")
                                self.logger.debug(f"Status: {response.status}")

                                if response.status in [200, 201]:
                                    response_data = (
                                        await response.json()
                                        if response.content_length
                                        else {"status": "ok"}
                                    )
                                    self.logger.debug(f"   Response: {response_data}")
                                    return response_data
                                else:
                                    error_text = await response.text()
                                    self.logger.error(
                                        f"❌ POST FAILED - Status: {response.status}, Error: {error_text}"
                                    )
                                    raise RegistryConnectionError(
                                        f"Registry returned {response.status}: {error_text}"
                                    )
                        except TimeoutError as e:
                            self.logger.error(
                                f"POST request timed out on attempt {attempt + 1}: {e}"
                            )
                            raise
                        except RuntimeError as e:
                            if "can't register atexit after shutdown" in str(e):
                                self.logger.warning(
                                    f"Python shutting down, falling back to simple HTTP for attempt {attempt + 1}"
                                )
                                # Fall back to requests or urllib if available
                                return await self._fallback_post_request(url, payload)
                            else:
                                self.logger.error(
                                    f"POST request failed on attempt {attempt + 1}: {type(e).__name__}: {e}"
                                )
                                raise
                        except Exception as e:
                            self.logger.error(
                                f"POST request failed on attempt {attempt + 1}: {type(e).__name__}: {e}"
                            )
                            raise

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

    async def _fallback_post_request(self, url: str, payload: dict) -> dict:
        """Fallback HTTP POST using urllib when aiohttp fails during shutdown."""
        import json
        import urllib.parse
        import urllib.request

        try:
            self.logger.debug("🔄 FALLBACK POST REQUEST")
            self.logger.debug(f"   URL: {url}")
            self.logger.debug(f"   Payload: {payload}")

            # Prepare the request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            req.add_header("Content-Type", "application/json")

            # Make the request
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_data = response.read().decode("utf-8")
                result = (
                    json.loads(response_data) if response_data else {"status": "ok"}
                )
                self.logger.debug("🎯 FALLBACK RESPONSE SUCCESS")
                self.logger.debug(f"   Status: {response.status}")
                self.logger.debug(f"   Response: {result}")
                return result

        except Exception as e:
            self.logger.error(f"❌ FALLBACK REQUEST FAILED: {e}")
            raise RegistryConnectionError(f"Fallback request failed: {e}") from e

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
            "timestamp": datetime.now().isoformat()
            + "Z",  # RFC3339 format required by Go
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

    async def update_agent_endpoint(
        self, endpoint_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Update agent registration with HTTP endpoint information.

        Args:
            endpoint_data: Dictionary containing:
                - agent_id: ID of the agent
                - http_host: HTTP host
                - http_port: HTTP port
                - endpoint: Full HTTP endpoint URL
                - timestamp: Update timestamp

        Returns:
            Update response from registry
        """
        self.logger.debug(
            f"Updating endpoint for {endpoint_data.get('agent_id')} to {endpoint_data.get('endpoint')}"
        )

        # Use PUT method to update existing agent registration
        result = await self._make_request(
            "PUT", f"/agents/{endpoint_data['agent_id']}/endpoint", endpoint_data
        )
        return result
