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

            # Build tools list for registration
            tools_list = self._build_tools_list(mesh_tools)

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

    def _build_tools_list(self, mesh_tools: dict[str, Any]) -> list[dict[str, Any]]:
        """Build tools list from mesh_tools, validating function signatures."""
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

            # Build tool registration data
            tool_data = {
                "function_name": func_name,
                "capability": metadata.get("capability"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "dependencies": self._process_dependencies(dependencies),
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
