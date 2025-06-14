"""
Mock Registry Client for Python Testing

This module provides a mock implementation of RegistryClient for fast unit testing
without requiring a real registry service.

🤖 AI BEHAVIOR GUIDANCE:
This mock client simulates registry responses for testing Python code.

DO NOT MODIFY TO MAKE TESTS PASS:
- If your code breaks these mock behaviors, fix your code
- These mocks implement the OpenAPI contract (api/mcp-mesh-registry.openapi.yaml)
- Breaking changes here suggest API contract violations

WHEN TO MODIFY:
- Only when the user explicitly changes API requirements
- When OpenAPI spec is updated with user approval
- To add new mock features requested by user

TEST METADATA:
- requirement_type: TESTING_INFRASTRUCTURE
- breaking_change_policy: DISCUSS_WITH_USER
- contract_reference: api/mcp-mesh-registry.openapi.yaml
"""

import asyncio
import copy
import logging
from datetime import datetime, timezone
from typing import Any

from mcp_mesh.runtime.shared.types import HealthStatus, MockHTTPResponse


class MockRegistryConfig:
    """Configuration for mock registry behavior."""

    def __init__(
        self,
        simulate_latency: bool = False,
        latency_ms: int = 0,
        failure_rate: float = 0.0,
        return_errors: bool = False,
        enable_dependencies: bool = True,
        max_agents: int = 100,
        offline_mode: bool = False,
    ):
        self.simulate_latency = simulate_latency
        self.latency_ms = latency_ms
        self.failure_rate = failure_rate  # 0.0 to 1.0
        self.return_errors = return_errors
        self.enable_dependencies = enable_dependencies
        self.max_agents = max_agents
        self.offline_mode = offline_mode


class MockAgent:
    """Represents a registered agent in the mock registry."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        capabilities: list[str],
        dependencies: list[str] = None,
        endpoint: str = None,
        status: str = "healthy",
        version: str = "1.0.0",
    ):
        self.agent_id = agent_id
        self.name = name
        self.capabilities = capabilities
        self.dependencies = dependencies or []
        self.endpoint = endpoint or f"stdio://{agent_id}"
        self.status = status
        self.version = version
        self.last_seen = datetime.now(timezone.utc)
        self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert agent to dictionary format."""
        return {
            "id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "endpoint": self.endpoint,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "last_seen": self.last_seen.isoformat(),
            "version": self.version,
            "metadata": self.metadata,
        }


class MockRequest:
    """Tracks requests made to the mock registry client."""

    def __init__(self, method: str, endpoint: str, payload: dict[str, Any] = None):
        self.method = method
        self.endpoint = endpoint
        self.payload = payload or {}
        self.timestamp = datetime.now(timezone.utc)


class MockRegistryClient:
    """
    Mock implementation of RegistryClient for testing.

    🤖 AI USAGE PATTERN:

    # Basic usage:
    mock_client = MockRegistryClient()
    success = await mock_client.register_agent("test-agent", ["capability1"], [])

    # With simulated failures:
    config = MockRegistryConfig(failure_rate=0.1, return_errors=True)
    mock_client = MockRegistryClient(config)

    # Request verification:
    requests = mock_client.get_requests()
    assert len(requests) == 1
    assert requests[0].method == "POST"
    """

    def __init__(
        self, config: MockRegistryConfig = None, url: str = "http://mock-registry:8000",
        go_compatibility_mode: bool = False
    ):
        self.config = config or MockRegistryConfig()
        self.url = url
        self.logger = logging.getLogger(__name__)
        self.go_compatibility_mode = go_compatibility_mode

        # Mock state
        self.agents: dict[str, MockAgent] = {}
        self.requests: list[MockRequest] = []
        self.dependencies_resolved: dict[str, dict[str, Any]] = {}
        self.start_time = datetime.now(timezone.utc)

        # Request history for test verification
        self._request_count = 0
        self._last_heartbeat_response: dict[str, Any] | None = None
        
        # Go-compatible response templates
        self._go_responses = {}
        if go_compatibility_mode:
            self._load_go_response_templates()

    def _load_go_response_templates(self) -> None:
        """Load captured Go response templates for exact compatibility."""
        # These are captured from actual Go registry responses
        self._go_responses = {
            "register_decorators": {
                "agent_id": "agent-hello-world-123",
                "status": "success", 
                "message": "Agent registered successfully",
                "timestamp": "2025-06-14T01:01:45-04:00",
                "dependencies_resolved": [
                    {
                        "function_name": "hello_mesh_simple",
                        "capability": "greeting",
                        "dependencies": [
                            {
                                "capability": "date_service",
                                "mcp_tool_info": {
                                    "agent_id": "date-agent-456",
                                    "endpoint": "http://date-agent:8000",
                                    "name": "get_current_date"
                                },
                                "status": "resolved"
                            }
                        ]
                    },
                    {
                        "function_name": "hello_mesh_typed", 
                        "capability": "advanced_greeting",
                        "dependencies": [
                            {
                                "capability": "info",
                                "mcp_tool_info": {
                                    "agent_id": "system-agent-789",
                                    "endpoint": "http://system-agent:8000",
                                    "name": "get_system_info"
                                },
                                "status": "resolved"
                            }
                        ]
                    },
                    {
                        "function_name": "test_dependencies",
                        "capability": "dependency_test", 
                        "dependencies": [
                            {
                                "capability": "date_service",
                                "mcp_tool_info": {
                                    "agent_id": "date-agent-456",
                                    "endpoint": "http://date-agent:8000", 
                                    "name": "get_current_date"
                                },
                                "status": "resolved"
                            },
                            {
                                "capability": "info",
                                "mcp_tool_info": {
                                    "agent_id": "system-agent-789",
                                    "endpoint": "http://system-agent:8000",
                                    "name": "get_system_info"
                                },
                                "status": "resolved"
                            }
                        ]
                    }
                ]
            },
            "heartbeat_decorators": {
                "agent_id": "agent-hello-world-123",
                "status": "success",
                "message": "Heartbeat received",
                "timestamp": "2025-06-14T01:01:49-04:00",
                "dependencies_resolved": [
                    {
                        "function_name": "hello_mesh_simple",
                        "capability": "greeting",
                        "dependencies": [
                            {
                                "capability": "date_service",
                                "mcp_tool_info": {
                                    "agent_id": "date-agent-456",
                                    "endpoint": "http://date-agent:8000",
                                    "name": "get_current_date"
                                },
                                "status": "resolved"
                            }
                        ]
                    },
                    {
                        "function_name": "hello_mesh_typed", 
                        "capability": "advanced_greeting",
                        "dependencies": [
                            {
                                "capability": "info",
                                "mcp_tool_info": {
                                    "agent_id": "system-agent-789",
                                    "endpoint": "http://system-agent:8000",
                                    "name": "get_system_info"
                                },
                                "status": "resolved"
                            }
                        ]
                    },
                    {
                        "function_name": "test_dependencies",
                        "capability": "dependency_test", 
                        "dependencies": [
                            {
                                "capability": "date_service",
                                "mcp_tool_info": {
                                    "agent_id": "date-agent-456",
                                    "endpoint": "http://date-agent:8000", 
                                    "name": "get_current_date"
                                },
                                "status": "resolved"
                            },
                            {
                                "capability": "info",
                                "mcp_tool_info": {
                                    "agent_id": "system-agent-789",
                                    "endpoint": "http://system-agent:8000",
                                    "name": "get_system_info"
                                },
                                "status": "resolved"
                            }
                        ]
                    }
                ]
            }
        }

    def _should_simulate_failure(self) -> bool:
        """Determine if a failure should be simulated."""
        if self.config.failure_rate <= 0:
            return False
        # Simple pseudo-random based on request count
        return (self._request_count % 10) < (self.config.failure_rate * 10)

    async def _simulate_latency(self) -> None:
        """Simulate network latency if configured."""
        if self.config.simulate_latency and self.config.latency_ms > 0:
            await asyncio.sleep(self.config.latency_ms / 1000.0)

    def _track_request(
        self, method: str, endpoint: str, payload: dict[str, Any] = None
    ) -> None:
        """Track a request for test verification."""
        self.requests.append(MockRequest(method, endpoint, payload))
        self._request_count += 1

    def _resolve_dependencies(self, dependencies: list[str]) -> dict[str, Any]:
        """Simulate dependency resolution."""
        if not self.config.enable_dependencies or not dependencies:
            return {}

        resolved = {}
        for dep_name in dependencies:
            # Find agent that provides this capability
            for agent in self.agents.values():
                if dep_name in agent.capabilities or agent.agent_id == dep_name:
                    resolved[dep_name] = {
                        "agent_id": agent.agent_id,
                        "endpoint": agent.endpoint,
                        "status": "available",
                        "capabilities": (
                            [dep_name]
                            if dep_name in agent.capabilities
                            else agent.capabilities
                        ),
                        "version": agent.version,
                        "metadata": {},
                    }
                    break

            # If not found, mark as unavailable
            if dep_name not in resolved:
                resolved[dep_name] = {
                    "agent_id": None,
                    "endpoint": None,
                    "status": "unavailable",
                    "capabilities": [],
                    "version": None,
                    "metadata": {},
                }

        return resolved

    # Core RegistryClient interface implementation

    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str = None,
    ) -> bool:
        """
        Register agent with the registry.

        🤖 AI CONTRACT COMPLIANCE:
        This method MUST match the behavior expected by the processor.py module.
        Changes here may break agent registration in the Python runtime.
        """
        await self._simulate_latency()
        self._track_request(
            "POST",
            "/agents/register",
            {
                "agent_name": agent_name,
                "capabilities": capabilities,
                "dependencies": dependencies,
                "security_context": security_context,
            },
        )

        # Simulate failure if configured
        if self.config.return_errors and self._should_simulate_failure():
            self.logger.warning(f"Simulating registration failure for {agent_name}")
            return False

        # Check agent limit
        if len(self.agents) >= self.config.max_agents:
            self.logger.warning(f"Maximum agents ({self.config.max_agents}) reached")
            return False

        # Create mock agent
        agent = MockAgent(
            agent_id=agent_name,
            name=agent_name,
            capabilities=capabilities,
            dependencies=dependencies,
        )

        self.agents[agent_name] = agent
        self.logger.info(
            f"Mock: Registered agent {agent_name} with capabilities {capabilities}"
        )
        return True

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry."""
        await self._simulate_latency()
        self._track_request(
            "POST",
            "/heartbeat",
            {
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
                    "uptime_seconds": health_status.uptime_seconds,
                    "version": health_status.version,
                },
            },
        )

        # Simulate failure if configured
        if self.config.return_errors and self._should_simulate_failure():
            return False

        # Update agent's last seen time
        if health_status.agent_name in self.agents:
            self.agents[health_status.agent_name].last_seen = datetime.now(timezone.utc)
            self.agents[health_status.agent_name].status = (
                health_status.status.value
                if hasattr(health_status.status, "value")
                else health_status.status
            )

        return True

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """
        Send periodic heartbeat to registry and return full response.

        🤖 AI CRITICAL CONTRACT:
        This method is used by the processor.py for dependency injection updates.
        The response format MUST match what the dependency injection system expects.
        """
        await self._simulate_latency()
        self._track_request(
            "POST",
            "/heartbeat",
            {
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
                    "uptime_seconds": health_status.uptime_seconds,
                    "version": health_status.version,
                },
            },
        )

        # Simulate failure if configured
        if self.config.return_errors and self._should_simulate_failure():
            return None

        # Update agent state
        agent = self.agents.get(health_status.agent_name)
        if agent:
            agent.last_seen = datetime.now(timezone.utc)
            agent.status = (
                health_status.status.value
                if hasattr(health_status.status, "value")
                else health_status.status
            )

            # Build response with dependency resolution
            response = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Heartbeat received",
            }

            # Add dependency resolution if agent has dependencies
            if self.config.enable_dependencies and agent.dependencies:
                dependencies_resolved = self._resolve_dependencies(agent.dependencies)
                if dependencies_resolved:
                    response["dependencies_resolved"] = dependencies_resolved
                    # Store for test verification
                    self.dependencies_resolved[health_status.agent_name] = (
                        dependencies_resolved
                    )

            self._last_heartbeat_response = response
            return response

        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Agent not registered",
        }

    async def get_dependency(self, dependency_name: str) -> Any:
        """Retrieve dependency configuration from registry."""
        await self._simulate_latency()
        self._track_request("GET", f"/dependencies/{dependency_name}")

        # Return mock dependency info
        for agent in self.agents.values():
            if (
                dependency_name in agent.capabilities
                or agent.agent_id == dependency_name
            ):
                return {
                    "agent_id": agent.agent_id,
                    "endpoint": agent.endpoint,
                    "capabilities": agent.capabilities,
                    "version": agent.version,
                }

        return None

    async def register_agent_with_metadata(self, agent_id: str, metadata: Any) -> bool:
        """Register agent with enhanced metadata for capability discovery."""
        await self._simulate_latency()
        self._track_request(
            "POST",
            "/agents/register",
            {
                "agent_id": agent_id,
                "metadata": (
                    metadata.__dict__ if hasattr(metadata, "__dict__") else metadata
                ),
            },
        )

        # Simulate failure if configured
        if self.config.return_errors and self._should_simulate_failure():
            return False

        # Extract data from metadata
        capabilities = []
        dependencies = []

        if hasattr(metadata, "capabilities"):
            capabilities = [
                cap.name if hasattr(cap, "name") else str(cap)
                for cap in metadata.capabilities
            ]
        if hasattr(metadata, "dependencies"):
            dependencies = metadata.dependencies

        # Create mock agent
        agent = MockAgent(
            agent_id=agent_id,
            name=getattr(metadata, "name", agent_id),
            capabilities=capabilities,
            dependencies=dependencies,
            endpoint=getattr(metadata, "endpoint", f"stdio://{agent_id}"),
            version=getattr(metadata, "version", "1.0.0"),
        )

        self.agents[agent_id] = agent
        return True

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all registered agents."""
        await self._simulate_latency()
        self._track_request("GET", "/agents")

        return [agent.to_dict() for agent in self.agents.values()]

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get specific agent by ID."""
        await self._simulate_latency()
        self._track_request("GET", f"/agents/{agent_id}")

        agent = self.agents.get(agent_id)
        return agent.to_dict() if agent else None

    async def update_agent_health(
        self, agent_id: str, health_data: dict[str, Any]
    ) -> bool:
        """Update agent health information."""
        await self._simulate_latency()
        self._track_request("POST", f"/agents/{agent_id}/health", health_data)

        agent = self.agents.get(agent_id)
        if agent:
            agent.status = health_data.get("status", agent.status)
            agent.last_seen = datetime.now(timezone.utc)
            return True

        return False

    async def deregister_agent(self, agent_id: str) -> bool:
        """Deregister an agent from the registry."""
        await self._simulate_latency()
        self._track_request("DELETE", f"/agents/{agent_id}")

        if agent_id in self.agents:
            del self.agents[agent_id]
            return True

        return False

    async def post(
        self, endpoint: str, json: dict[str, Any] = None
    ) -> MockHTTPResponse:
        """Make a POST request to the registry."""
        await self._simulate_latency()
        self._track_request("POST", endpoint, json)

        # Simulate different responses based on endpoint
        if endpoint == "/agents/register_decorators":
            # Handle new decorator-based registration
            if self.go_compatibility_mode:
                return self._handle_decorator_registration_go_compatible(json)
            else:
                return self._handle_decorator_registration_legacy(json)
                
        elif endpoint == "/heartbeat_decorators":
            # Handle new decorator-based heartbeat
            if self.go_compatibility_mode:
                return self._handle_decorator_heartbeat_go_compatible(json)
            else:
                return self._handle_decorator_heartbeat_legacy(json)
                
        elif endpoint == "/agents/register":
            if self.config.return_errors and self._should_simulate_failure():
                return MockHTTPResponse(
                    {"error": "Simulated registration failure"}, 500
                )

            agent_id = json.get("agent_id", "unknown") if json else "unknown"

            # Extract metadata for agent creation
            metadata = json.get("metadata", {}) if json else {}
            capabilities = metadata.get("capabilities", [])
            dependencies = metadata.get("dependencies", [])

            # Create agent
            agent = MockAgent(
                agent_id=agent_id,
                name=metadata.get("name", agent_id),
                capabilities=capabilities if isinstance(capabilities, list) else [],
                dependencies=dependencies if isinstance(dependencies, list) else [],
                endpoint=metadata.get("endpoint", f"stdio://{agent_id}"),
                version=metadata.get("version", "1.0.0"),
            )

            self.agents[agent_id] = agent

            response_data = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Agent registered successfully",
                "agent_id": agent_id,
            }

            # Add dependency resolution if enabled
            if self.config.enable_dependencies and agent.dependencies:
                dependencies_resolved = self._resolve_dependencies(agent.dependencies)
                if dependencies_resolved:
                    response_data["dependencies_resolved"] = dependencies_resolved

            return MockHTTPResponse(response_data, 201)

        elif endpoint == "/heartbeat":
            if self.config.return_errors and self._should_simulate_failure():
                return MockHTTPResponse({"error": "Simulated heartbeat failure"}, 500)

            agent_id = json.get("agent_id", "unknown") if json else "unknown"
            agent = self.agents.get(agent_id)

            if agent:
                agent.last_seen = datetime.now(timezone.utc)

                response_data = {
                    "status": "success",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Heartbeat received",
                }

                # Add dependency resolution
                if self.config.enable_dependencies and agent.dependencies:
                    dependencies_resolved = self._resolve_dependencies(
                        agent.dependencies
                    )
                    if dependencies_resolved:
                        response_data["dependencies_resolved"] = dependencies_resolved

                return MockHTTPResponse(response_data, 200)
            else:
                return MockHTTPResponse({"error": "Agent not registered"}, 404)

        # Default response
        return MockHTTPResponse({"status": "ok", "message": "Mock response"}, 200)

    async def put(self, endpoint: str, json: dict[str, Any] = None) -> MockHTTPResponse:
        """Make a PUT request to the registry."""
        await self._simulate_latency()
        self._track_request("PUT", endpoint, json)

        return MockHTTPResponse({"status": "ok", "message": "Mock PUT response"}, 200)

    async def close(self) -> None:
        """Close the HTTP session."""
        # Nothing to close in mock
        pass

    # Multi-tool methods for testing new features

    async def register_multi_tool_agent(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Register agent using the new multi-tool format."""
        await self._simulate_latency()
        self._track_request(
            "POST", "/agents/register", {"agent_id": agent_id, "metadata": metadata}
        )

        if self.config.return_errors and self._should_simulate_failure():
            return None

        # Extract tools and capabilities
        tools = metadata.get("tools", [])
        capabilities = []
        dependencies = []

        for tool in tools:
            if isinstance(tool, dict):
                if "capability" in tool:
                    capabilities.append(tool["capability"])
                if "dependencies" in tool:
                    for dep in tool["dependencies"]:
                        if isinstance(dep, dict) and "capability" in dep:
                            dependencies.append(dep["capability"])

        # Create agent
        agent = MockAgent(
            agent_id=agent_id,
            name=metadata.get("name", agent_id),
            capabilities=capabilities,
            dependencies=dependencies,
            endpoint=metadata.get("endpoint", f"stdio://{agent_id}"),
        )

        self.agents[agent_id] = agent

        response = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Multi-tool agent registered successfully",
            "agent_id": agent_id,
        }

        # Add per-tool dependency resolution
        if self.config.enable_dependencies and tools:
            tool_dependencies = {}
            for tool in tools:
                if isinstance(tool, dict):
                    tool_name = tool.get("function_name", "unknown")
                    tool_deps = tool.get("dependencies", [])
                    if tool_deps:
                        tool_dependencies[tool_name] = self._resolve_dependencies(
                            [
                                dep["capability"]
                                for dep in tool_deps
                                if isinstance(dep, dict) and "capability" in dep
                            ]
                        )

            if tool_dependencies:
                response["dependencies_resolved"] = tool_dependencies

        return response

    def parse_tool_dependencies(
        self, registry_response: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Parse per-tool dependency resolution from registry response."""
        # Check new per-tool format first
        if (
            "metadata" in registry_response
            and "dependencies_resolved" in registry_response["metadata"]
        ):
            dependencies = registry_response["metadata"]["dependencies_resolved"]
            if isinstance(dependencies, dict):
                return dependencies

        # Fallback to root-level dependencies_resolved
        if "dependencies_resolved" in registry_response:
            dependencies = registry_response["dependencies_resolved"]
            if isinstance(dependencies, dict):
                # If it's old format, adapt it
                return {"legacy_tool": dependencies}

        return {}

    async def send_heartbeat_with_dependency_resolution(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """Send heartbeat and return full dependency resolution for all tools."""
        # Same as send_heartbeat_with_response for now
        return await self.send_heartbeat_with_response(health_status)

    # Test utility methods

    def get_requests(self) -> list[MockRequest]:
        """Get all requests made to the mock client."""
        return self.requests.copy()

    def get_agents(self) -> dict[str, MockAgent]:
        """Get all registered agents."""
        return self.agents.copy()

    def clear_requests(self) -> None:
        """Clear request history."""
        self.requests.clear()
        self._request_count = 0

    def clear_agents(self) -> None:
        """Remove all registered agents."""
        self.agents.clear()
        self.dependencies_resolved.clear()

    def add_agent(self, agent: MockAgent) -> None:
        """Manually add an agent (for test setup)."""
        self.agents[agent.agent_id] = agent

    def set_config(self, config: MockRegistryConfig) -> None:
        """Update mock configuration."""
        self.config = config

    def get_last_heartbeat_response(self) -> dict[str, Any] | None:
        """Get the last heartbeat response for test verification."""
        return self._last_heartbeat_response

    def simulate_agent_timeout(self, agent_id: str) -> None:
        """Simulate an agent timing out."""
        if agent_id in self.agents:
            self.agents[agent_id].status = "unhealthy"
            self.agents[agent_id].last_seen = datetime.now(timezone.utc).replace(
                minute=0
            )  # Old timestamp

    def set_dependency_resolution(
        self, agent_id: str, dependencies: dict[str, Any]
    ) -> None:
        """Manually set dependency resolution for an agent."""
        self.dependencies_resolved[agent_id] = dependencies

    # Go-compatible decorator endpoint handlers
    
    def _handle_decorator_registration_go_compatible(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle decorator registration with Go-compatible response format."""
        if self.config.return_errors and self._should_simulate_failure():
            return MockHTTPResponse({"error": "Simulated registration failure"}, 500)
            
        # Validate request format matches Go expectations
        self._validate_decorator_request(json_data, "register")
        
        # Extract agent info for storage
        agent_id = json_data.get("agent_id", "unknown")
        metadata = json_data.get("metadata", {})
        
        # Create agent with decorator info
        decorators = metadata.get("decorators", [])
        capabilities = [d.get("capability") for d in decorators if d.get("capability")]
        
        agent = MockAgent(
            agent_id=agent_id,
            name=metadata.get("name", agent_id),
            capabilities=capabilities,
            endpoint=metadata.get("endpoint", f"stdio://{agent_id}"),
            version=metadata.get("version", "1.0.0"),
        )
        self.agents[agent_id] = agent
        
        # Return exact Go response format with updated agent ID and timestamp
        response = copy.deepcopy(self._go_responses["register_decorators"])
        response["agent_id"] = agent_id
        response["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        return MockHTTPResponse(response, 201)
    
    def _handle_decorator_heartbeat_go_compatible(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle decorator heartbeat with Go-compatible response format."""
        if self.config.return_errors and self._should_simulate_failure():
            return MockHTTPResponse({"error": "Simulated heartbeat failure"}, 500)
            
        # Validate request format matches Go expectations
        self._validate_decorator_request(json_data, "heartbeat")
        
        agent_id = json_data.get("agent_id", "unknown")
        
        # Update agent last seen if it exists
        if agent_id in self.agents:
            self.agents[agent_id].last_seen = datetime.now(timezone.utc)
        
        # Return exact Go response format with updated agent ID and timestamp
        response = copy.deepcopy(self._go_responses["heartbeat_decorators"])
        response["agent_id"] = agent_id
        response["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        return MockHTTPResponse(response, 200)
    
    def _handle_decorator_registration_legacy(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle decorator registration with legacy mock behavior."""
        # Fallback to standard registration behavior if not in Go compatibility mode
        return self._handle_standard_registration(json_data)
    
    def _handle_decorator_heartbeat_legacy(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle decorator heartbeat with legacy mock behavior."""
        # Fallback to standard heartbeat behavior if not in Go compatibility mode
        return self._handle_standard_heartbeat(json_data)
    
    def _validate_decorator_request(self, json_data: dict[str, Any], request_type: str) -> None:
        """Validate that Python request matches Go's expected format."""
        required_fields = ["agent_id", "timestamp", "metadata"]
        for field in required_fields:
            if field not in json_data:
                raise ValueError(f"Missing required field: {field}")
        
        metadata = json_data["metadata"]
        required_metadata_fields = ["name", "agent_type", "namespace", "endpoint", "decorators"]
        for field in required_metadata_fields:
            if field not in metadata:
                raise ValueError(f"Missing required metadata field: {field}")
        
        # Validate decorators structure
        decorators = metadata["decorators"]
        if not isinstance(decorators, list) or len(decorators) == 0:
            raise ValueError("Decorators must be non-empty list")
            
        for decorator in decorators:
            required_decorator_fields = ["function_name", "capability", "dependencies"]
            for field in required_decorator_fields:
                if field not in decorator:
                    raise ValueError(f"Missing required decorator field: {field}")
                    
            # Validate dependencies are standardized format (objects, not strings)
            for dep in decorator["dependencies"]:
                if not isinstance(dep, dict) or "capability" not in dep:
                    raise ValueError("Dependencies must be objects with 'capability' field")
    
    def _handle_standard_registration(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle standard registration for backward compatibility."""
        # Implementation of legacy registration behavior
        agent_id = json_data.get("agent_id", "unknown")
        return MockHTTPResponse({
            "status": "success",
            "agent_id": agent_id,
            "message": "Agent registered successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, 201)
    
    def _handle_standard_heartbeat(self, json_data: dict[str, Any]) -> MockHTTPResponse:
        """Handle standard heartbeat for backward compatibility."""
        # Implementation of legacy heartbeat behavior  
        return MockHTTPResponse({
            "status": "success",
            "message": "Heartbeat received",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, 200)


# 🤖 AI TESTING PATTERNS:
#
# BASIC USAGE:
#   mock_client = MockRegistryClient()
#   success = await mock_client.register_agent("test", ["cap1"], [])
#   assert success
#
# FAILURE SIMULATION:
#   config = MockRegistryConfig(failure_rate=0.5, return_errors=True)
#   mock_client = MockRegistryClient(config)
#   # 50% of requests will fail
#
# REQUEST VERIFICATION:
#   requests = mock_client.get_requests()
#   assert len(requests) == 1
#   assert requests[0].method == "POST"
#   assert requests[0].endpoint == "/agents/register"
#
# DEPENDENCY TESTING:
#   # Set up provider agent
#   mock_client.add_agent(MockAgent("provider", "provider", ["capability1"]))
#
#   # Register dependent agent
#   await mock_client.register_agent("consumer", ["capability2"], ["capability1"])
#
#   # Verify dependency resolution in heartbeat
#   health_status = HealthStatus(agent_name="consumer", ...)
#   response = await mock_client.send_heartbeat_with_response(health_status)
#   assert "dependencies_resolved" in response
#   assert "capability1" in response["dependencies_resolved"]


def create_mock_registry_client(
    config: MockRegistryConfig = None,
    go_compatibility_mode: bool = False,
) -> MockRegistryClient:
    """
    Factory function to create a MockRegistryClient.

    🤖 AI CONVENIENCE FUNCTION:
    Use this in your tests for consistent mock creation.
    
    Args:
        config: Mock configuration options
        go_compatibility_mode: If True, returns exact Go registry response formats
    """
    return MockRegistryClient(config or MockRegistryConfig(), go_compatibility_mode=go_compatibility_mode)
