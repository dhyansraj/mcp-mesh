"""
Registry Client Wrapper - Clean interface for generated OpenAPI client.

Provides a type-safe, convenient wrapper around the generated OpenAPI client
that handles conversion between simple Python dicts and Pydantic models.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Optional

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
            response_dict = self._response_to_dict(response)

            return response_dict

        except Exception as e:
            self.logger.error(
                f"Failed to send heartbeat for {health_status.agent_name}: {e}"
            )
            return None

    def parse_tool_dependencies(self, response: dict[str, Any]) -> dict[str, Any]:
        """
        Parse dependency resolution from registry response with kwargs support.

        Args:
            response: Registry response containing dependencies_resolved

        Returns:
            Dict mapping tool names to their resolved dependencies (including kwargs)
        """
        try:
            # Extract dependencies_resolved from response
            dependencies_resolved = None
            if "dependencies_resolved" in response:
                dependencies_resolved = response["dependencies_resolved"]
            elif (
                "metadata" in response
                and "dependencies_resolved" in response["metadata"]
            ):
                dependencies_resolved = response["metadata"]["dependencies_resolved"]
            else:
                return {}

            # Process each dependency to extract kwargs if present
            parsed_dependencies = {}

            for function_name, dependency_list in dependencies_resolved.items():
                if not isinstance(dependency_list, list):
                    continue

                parsed_dependencies[function_name] = []

                for dep_resolution in dependency_list:
                    if not isinstance(dep_resolution, dict):
                        continue

                    # Standard dependency fields
                    parsed_dep = {
                        "capability": dep_resolution.get("capability", ""),
                        "endpoint": dep_resolution.get("endpoint", ""),
                        "function_name": dep_resolution.get("function_name", ""),
                        "status": dep_resolution.get("status", ""),
                        "agent_id": dep_resolution.get("agent_id", ""),
                    }

                    # NEW: Extract kwargs if present (from database JSON field)
                    if "kwargs" in dep_resolution:
                        try:
                            # kwargs might be JSON string from database
                            kwargs_data = dep_resolution["kwargs"]
                            if isinstance(kwargs_data, str):
                                import json

                                kwargs_data = (
                                    json.loads(kwargs_data) if kwargs_data else {}
                                )

                            parsed_dep["kwargs"] = kwargs_data
                            self.logger.debug(
                                f"🔧 Parsed kwargs for {dep_resolution.get('capability')}: {kwargs_data}"
                            )
                        except (json.JSONDecodeError, TypeError) as e:
                            self.logger.warning(
                                f"Failed to parse kwargs for {dep_resolution.get('capability')}: {e}"
                            )
                            parsed_dep["kwargs"] = {}
                    else:
                        parsed_dep["kwargs"] = {}

                    parsed_dependencies[function_name].append(parsed_dep)

            return parsed_dependencies

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

            # Call generated client fast heartbeat check with HTTP info to get status code
            http_response = self.agents_api.fast_heartbeat_check_with_http_info(
                agent_id
            )

            # Extract the actual HTTP status code from the response
            status_code = http_response.status_code
            self.logger.debug(
                f"Fast heartbeat HEAD request for agent '{agent_id}' returned HTTP {status_code}"
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
                self.logger.debug(
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

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Gracefully unregister agent from registry.

        Args:
            agent_id: Agent identifier to unregister

        Returns:
            True if successful, False if failed
        """
        try:
            self.logger.info(f"🏁 Gracefully unregistering agent '{agent_id}'")

            # Call generated client unregister method
            response = self.agents_api.unregister_agent_with_http_info(agent_id)

            success = response.status_code == 204
            if success:
                self.logger.info(f"✅ Agent '{agent_id}' unregistered successfully")
            else:
                self.logger.warning(
                    f"⚠️ Agent '{agent_id}' unregister returned unexpected status: {response.status_code}"
                )

            return success

        except Exception as e:
            self.logger.error(f"❌ Failed to unregister agent '{agent_id}': {e}")
            return False

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

            # Extract kwargs from tool_data (non-standard fields)
            standard_fields = {
                "capability",
                "function_name",
                "tags",
                "version",
                "dependencies",
                "description",
            }
            kwargs_data = {
                k: v for k, v in tool_data.items() if k not in standard_fields
            }

            # Create tool registration with kwargs support
            tool_reg = MeshToolRegistration(
                function_name=tool_data["function_name"],
                capability=tool_data.get("capability"),
                tags=tool_data.get("tags", []),
                version=tool_data.get("version", "1.0.0"),
                dependencies=dep_registrations,
                description=tool_data.get("description"),
                kwargs=kwargs_data if kwargs_data else None,
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
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

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

            # Extract kwargs from metadata (non-standard fields)
            standard_fields = {
                "capability",
                "function_name",
                "tags",
                "version",
                "dependencies",
                "description",
            }
            kwargs_data = {
                k: v for k, v in metadata.items() if k not in standard_fields
            }

            # Extract inputSchema from FastMCP tool (Phase 2: Schema Collection)
            # First try to get FastMCP server info from DecoratorRegistry
            fastmcp_servers = DecoratorRegistry.get_fastmcp_server_info()
            input_schema = None

            if fastmcp_servers:
                # Try comprehensive extraction using server context
                input_schema = FastMCPSchemaExtractor.extract_from_fastmcp_servers(
                    decorated_func.function, fastmcp_servers
                )

            # Fallback to direct attribute check if server lookup didn't work
            if input_schema is None:
                input_schema = FastMCPSchemaExtractor.extract_input_schema(
                    decorated_func.function
                )

            # Extract llm_filter from @mesh.llm decorator (Phase 3: LLM Integration)
            llm_agents = DecoratorRegistry.get_mesh_llm_agents()
            llm_filter_data = None

            for llm_agent_id, llm_metadata in llm_agents.items():
                # Match by function name (decorated_func.function is the wrapper, need to check original)
                if llm_metadata.function.__name__ == func_name:
                    # Found matching LLM agent - extract filter config
                    raw_filter = llm_metadata.config.get("filter")
                    filter_mode = llm_metadata.config.get("filter_mode", "all")

                    # Normalize filter to array format
                    if raw_filter is None:
                        normalized_filter = []
                    elif isinstance(raw_filter, list):
                        normalized_filter = raw_filter
                    elif isinstance(raw_filter, dict):
                        # Single dict filter like {'capability': 'date_service'}
                        normalized_filter = [raw_filter]
                    elif isinstance(raw_filter, str):
                        normalized_filter = [raw_filter] if raw_filter else []
                    else:
                        normalized_filter = []

                    llm_filter_data = {
                        "filter": normalized_filter,
                        "filter_mode": filter_mode,
                    }

                    self.logger.debug(
                        f"🤖 Extracted llm_filter for {func_name}: {len(normalized_filter)} filters, mode={filter_mode}"
                    )
                    break

            # Extract llm_provider from @mesh.llm decorator (v0.6.1: LLM Mesh Delegation)
            llm_provider_data = None

            for llm_agent_id, llm_metadata in llm_agents.items():
                if llm_metadata.function.__name__ == func_name:
                    # Check if provider is a dict (mesh delegation mode)
                    provider = llm_metadata.config.get("provider")
                    if isinstance(provider, dict):
                        # Import generated client model
                        from _mcp_mesh.generated.mcp_mesh_registry_client.models.llm_provider import (
                            LLMProvider,
                        )

                        # Convert dict to LLMProvider model
                        llm_provider_data = LLMProvider(
                            capability=provider.get("capability", "llm"),
                            tags=provider.get("tags", []),
                            version=provider.get("version", ""),
                            namespace=provider.get("namespace", "default"),
                        )

                        self.logger.debug(
                            f"🔌 Extracted llm_provider for {func_name}: {llm_provider_data.model_dump()}"
                        )
                    break

            # Create tool registration with llm_filter as separate top-level field (not in kwargs)
            tool_reg = MeshToolRegistration(
                function_name=func_name,
                capability=metadata.get("capability"),
                tags=metadata.get("tags", []),
                version=metadata.get("version", "1.0.0"),
                dependencies=dep_registrations,
                description=metadata.get("description"),
                llm_filter=llm_filter_data,  # Pass llm_filter as top-level parameter
                llm_provider=llm_provider_data,  # Pass llm_provider as top-level parameter (v0.6.1)
                input_schema=input_schema,  # Pass inputSchema as top-level parameter (not in kwargs)
                kwargs=kwargs_data if kwargs_data else None,
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
