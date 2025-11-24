import inspect
import logging
import re
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from ...engine.decorator_registry import DecoratorRegistry
from ...engine.signature_analyzer import validate_mesh_dependencies
from ...shared.config_resolver import ValidationRule, get_config_value
from ...shared.support_types import HealthStatus, HealthStatusType
from ...utils.fastmcp_schema_extractor import FastMCPSchemaExtractor
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class HeartbeatPreparationStep(PipelineStep):
    """
    Prepares heartbeat data for registry communication.

    Builds the complete agent registration payload including tools,
    dependencies, and metadata.
    """

    def __init__(self):
        super().__init__(
            name="heartbeat-preparation",
            required=True,
            description="Prepare heartbeat payload with tools and metadata",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Prepare heartbeat data using DecoratorRegistry."""
        self.logger.debug("Preparing heartbeat payload...")

        result = PipelineResult(message="Heartbeat preparation completed")

        try:
            # Get data directly from DecoratorRegistry instead of pipeline context
            mesh_tools = DecoratorRegistry.get_mesh_tools()
            agent_config = DecoratorRegistry.get_resolved_agent_config()
            agent_id = agent_config["agent_id"]

            # Get FastMCP server info from context (set by fastmcp-server-discovery step)
            fastmcp_server_info = context.get("fastmcp_server_info", [])

            # Convert server_info list to dict for schema extractor
            fastmcp_servers = {}
            for server_info in fastmcp_server_info:
                server_name = server_info.get("server_name", "unknown")
                fastmcp_servers[server_name] = server_info

            # Build tools list for registration (with FastMCP schemas)
            tools_list = self._build_tools_list(mesh_tools, fastmcp_servers)

            # Build agent registration payload
            registration_data = self._build_registration_payload(
                agent_id, agent_config, tools_list
            )

            # Build health status for heartbeat
            health_status = self._build_health_status(
                agent_id, agent_config, tools_list
            )

            # Store in context
            result.add_context("registration_data", registration_data)
            result.add_context("health_status", health_status)
            result.add_context("tools_list", tools_list)
            result.add_context("tool_count", len(tools_list))

            result.message = f"Heartbeat prepared for agent '{agent_id}' with {len(tools_list)} tools"
            self.logger.info(
                f"💓 Heartbeat prepared: agent='{agent_id}', tools={len(tools_list)}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Heartbeat preparation failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Heartbeat preparation failed: {e}")

        return result

    def _build_tools_list(
        self, mesh_tools: dict[str, Any], fastmcp_servers: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """Build tools list from mesh_tools, validating function signatures and extracting schemas."""
        tools_list = []
        skipped_tools = []

        for func_name, decorated_func in mesh_tools.items():
            metadata = decorated_func.metadata
            current_function = decorated_func.function
            dependencies = metadata.get("dependencies", [])

            # Validate function signature if it has dependencies
            if dependencies:
                is_valid, error_message = validate_mesh_dependencies(
                    current_function, dependencies
                )
                if not is_valid:
                    self.logger.warning(
                        f"⚠️ Skipping tool '{func_name}' from heartbeat: {error_message}"
                    )
                    skipped_tools.append(func_name)
                    continue

            # Extract inputSchema from FastMCP tool (if available)
            # First try matching with FastMCP servers, then fallback to direct attribute
            input_schema = FastMCPSchemaExtractor.extract_from_fastmcp_servers(
                current_function, fastmcp_servers
            )
            if input_schema is None:
                input_schema = FastMCPSchemaExtractor.extract_input_schema(
                    current_function
                )

            # Check if this function has @mesh.llm decorator (Phase 3)
            llm_filter_data = None
            llm_provider_data = None
            llm_agents = DecoratorRegistry.get_mesh_llm_agents()
            self.logger.debug(
                f"🤖 Checking for LLM filter: function={func_name}, total_llm_agents_registered={len(llm_agents)}"
            )

            for llm_agent_id, llm_metadata in llm_agents.items():
                if llm_metadata.function.__name__ == func_name:
                    # Found matching LLM agent - extract filter config
                    raw_filter = llm_metadata.config.get("filter")
                    filter_mode = llm_metadata.config.get("filter_mode", "all")

                    # Normalize filter to array format (OpenAPI schema requirement)
                    if raw_filter is None:
                        normalized_filter = []
                    elif isinstance(raw_filter, str):
                        normalized_filter = [raw_filter]
                    elif isinstance(raw_filter, dict):
                        normalized_filter = [raw_filter]
                    elif isinstance(raw_filter, list):
                        normalized_filter = raw_filter
                    else:
                        self.logger.warning(
                            f"⚠️ Invalid filter type for {func_name}: {type(raw_filter)}"
                        )
                        normalized_filter = []

                    llm_filter_data = {
                        "filter": normalized_filter,
                        "filter_mode": filter_mode,
                    }
                    self.logger.debug(
                        f"🤖 LLM filter found for {func_name}: {len(normalized_filter)} filters, mode={filter_mode}, raw_filter={raw_filter}"
                    )

                    # Check if provider is a dict (mesh delegation mode - v0.6.1)
                    # If so, add it as llm_provider field (NOT in dependencies array)
                    provider = llm_metadata.config.get("provider")
                    if isinstance(provider, dict):
                        self.logger.debug(
                            f"🔌 LLM provider is dict (mesh delegation) for {func_name}: {provider}"
                        )
                        # Set llm_provider field (separate from dependencies)
                        # Registry will resolve this to an actual provider agent
                        llm_provider_data = {
                            "capability": provider.get("capability", "llm"),
                            "tags": provider.get("tags", []),
                            "version": provider.get("version", ""),
                            "namespace": provider.get("namespace", "default"),
                        }
                        self.logger.debug(
                            f"✅ LLM provider spec prepared for {func_name}: {llm_provider_data}"
                        )

                    break

            # Build tool registration data
            self.logger.debug(
                f"Building tool_data for {func_name}, dependencies={dependencies}"
            )
            processed_deps = self._process_dependencies(dependencies)
            self.logger.debug(
                f"Processed dependencies for {func_name}: {processed_deps}"
            )

            # Extract kwargs (any extra fields not in standard set)
            standard_fields = {
                "capability",
                "tags",
                "version",
                "description",
                "dependencies",
            }
            kwargs_data = {
                k: v for k, v in metadata.items() if k not in standard_fields
            }

            tool_data = {
                "function_name": func_name,
                "capability": metadata.get("capability"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "dependencies": processed_deps,
                "input_schema": input_schema,  # Add inputSchema for LLM integration (Phase 2)
                "llm_filter": llm_filter_data,  # Add LLM filter for LLM integration (Phase 3)
                "llm_provider": llm_provider_data,  # Add LLM provider for mesh delegation (v0.6.1)
                "kwargs": (
                    kwargs_data if kwargs_data else None
                ),  # Add kwargs for vendor and other metadata
            }

            # Add debug pointer information only if debug flag is enabled
            if get_config_value(
                "MCP_MESH_DEBUG", default=False, rule=ValidationRule.TRUTHY_RULE
            ):
                debug_pointers = self._get_function_pointer_debug_info(
                    current_function, func_name
                )
                tool_data["debug_pointers"] = debug_pointers

            tools_list.append(tool_data)

        # Log summary of validation results
        if skipped_tools:
            self.logger.warning(
                f"🚫 Excluded {len(skipped_tools)} invalid tools from heartbeat: {skipped_tools}"
            )

        self.logger.info(
            f"✅ Validated {len(tools_list)} tools for heartbeat (excluded {len(skipped_tools)})"
        )

        return tools_list

    def _process_dependencies(self, dependencies: list[Any]) -> list[dict[str, Any]]:
        """Process and normalize dependencies."""
        processed = []

        for dep in dependencies:
            if isinstance(dep, str):
                processed.append(
                    {
                        "capability": dep,
                        "tags": [],
                        "version": "",
                        "namespace": "default",
                    }
                )
            elif isinstance(dep, dict):
                processed.append(
                    {
                        "capability": dep.get("capability", ""),
                        "tags": dep.get("tags", []),
                        "version": dep.get("version", ""),
                        "namespace": dep.get("namespace", "default"),
                    }
                )

        return processed

    def _get_function_pointer_debug_info(
        self, current_function: Any, func_name: str
    ) -> dict[str, Any]:
        """Get function pointer debug information for wrapper verification."""
        debug_info = {
            "current_function": str(current_function),
            "current_function_id": hex(id(current_function)),
            "current_function_type": type(current_function).__name__,
        }

        # Check if this is a wrapper function with original function stored
        original_function = None
        if hasattr(current_function, "_mesh_original_func"):
            original_function = current_function._mesh_original_func
            debug_info["original_function"] = str(original_function)
            debug_info["original_function_id"] = hex(id(original_function))
            debug_info["is_wrapped"] = True
        else:
            debug_info["original_function"] = None
            debug_info["original_function_id"] = None
            debug_info["is_wrapped"] = False

        # Check for dependency injection attributes
        debug_info["has_injection_wrapper"] = hasattr(
            current_function, "_mesh_injection_wrapper"
        )
        debug_info["has_mesh_injected_deps"] = hasattr(
            current_function, "_mesh_injected_deps"
        )
        debug_info["has_mesh_update_dependency"] = hasattr(
            current_function, "_mesh_update_dependency"
        )
        debug_info["has_mesh_dependencies"] = hasattr(
            current_function, "_mesh_dependencies"
        )
        debug_info["has_mesh_positions"] = hasattr(current_function, "_mesh_positions")

        # If there are mesh dependencies, show them
        if hasattr(current_function, "_mesh_dependencies"):
            debug_info["mesh_dependencies"] = getattr(
                current_function, "_mesh_dependencies", []
            )

        # If there are mesh injected deps, show them
        if hasattr(current_function, "_mesh_injected_deps"):
            debug_info["mesh_injected_deps"] = getattr(
                current_function, "_mesh_injected_deps", {}
            )

        # Show function name and module for verification
        if hasattr(current_function, "__name__"):
            debug_info["function_name"] = current_function.__name__
        if hasattr(current_function, "__module__"):
            debug_info["function_module"] = current_function.__module__

        # Pointer comparison
        if original_function:
            debug_info["pointers_match"] = id(current_function) == id(original_function)
        else:
            debug_info["pointers_match"] = None

        return debug_info

    def _build_registration_payload(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build agent registration payload."""
        from ...shared.host_resolver import HostResolver

        return {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "version": agent_config.get("version", "1.0.0"),
            "http_host": HostResolver.get_external_host(),
            "http_port": agent_config.get("http_port", 0),
            "timestamp": datetime.now(UTC),
            "namespace": agent_config.get("namespace", "default"),
            "tools": tools_list,
        }

    def _extract_capabilities(self, tools_list: list[dict[str, Any]]) -> list[str]:
        """Extract capabilities from tools list."""
        capabilities = []
        for tool in tools_list:
            capability = tool.get("capability")
            if capability:
                capabilities.append(capability)

        # Ensure we have at least one capability for validation
        if not capabilities:
            capabilities = ["default"]

        return capabilities

    def _build_health_status(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
    ) -> HealthStatus:
        """Build health status for heartbeat."""
        # Extract capabilities from tools list
        capabilities = self._extract_capabilities(tools_list)

        # Build metadata from agent config
        metadata = dict(agent_config)  # Copy agent config

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=capabilities,
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=metadata,
        )
