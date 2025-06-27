"""
Pipeline step implementations for MCP Mesh processing.

Provides concrete implementations of common processing steps like
decorator collection, configuration resolution, and heartbeat preparation.
"""

import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Optional

from ..decorator_registry import DecoratorRegistry
from ..shared.registry_client_wrapper import RegistryClientWrapper
from ..shared.support_types import HealthStatus, HealthStatusType
from .pipeline import PipelineResult, PipelineStatus

logger = logging.getLogger(__name__)


class PipelineStep(ABC):
    """
    Abstract base class for pipeline steps.

    Each step performs a specific operation and can access/modify
    the shared pipeline context.
    """

    def __init__(self, name: str, required: bool = True, description: str = ""):
        self.name = name
        self.required = required
        self.description = description
        self.logger = logging.getLogger(f"{__name__}.{name}")

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Execute this pipeline step.

        Args:
            context: Shared pipeline context that can be read/modified

        Returns:
            Result of step execution
        """
        pass

    def __str__(self) -> str:
        return f"PipelineStep(name='{self.name}', required={self.required})"


class DecoratorCollectionStep(PipelineStep):
    """
    Collects all registered decorators from DecoratorRegistry.

    This step reads the current state of decorator registrations and
    makes them available for subsequent processing steps.
    """

    def __init__(self):
        super().__init__(
            name="decorator-collection",
            required=True,
            description="Collect all registered @mesh.agent and @mesh.tool decorators",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Collect decorators from registry."""
        self.logger.debug("Collecting decorators from DecoratorRegistry...")

        result = PipelineResult(message="Decorator collection completed")

        try:
            # Get all registered decorators
            mesh_agents = DecoratorRegistry.get_mesh_agents()
            mesh_tools = DecoratorRegistry.get_mesh_tools()

            # Store in context for subsequent steps
            result.add_context("mesh_agents", mesh_agents)
            result.add_context("mesh_tools", mesh_tools)
            result.add_context("agent_count", len(mesh_agents))
            result.add_context("tool_count", len(mesh_tools))

            # Update result message
            result.message = (
                f"Collected {len(mesh_agents)} agents and {len(mesh_tools)} tools"
            )

            self.logger.info(
                f"📦 Collected decorators: {len(mesh_agents)} @mesh.agent, {len(mesh_tools)} @mesh.tool"
            )

            # Validate we have something to process
            if len(mesh_agents) == 0 and len(mesh_tools) == 0:
                result.status = PipelineStatus.SKIPPED
                result.message = "No decorators found to process"
                self.logger.warning("⚠️ No decorators found in registry")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to collect decorators: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Decorator collection failed: {e}")

        return result


class ConfigurationStep(PipelineStep):
    """
    Resolves configuration for the agent.

    Applies defaults from @mesh.agent decorator or creates synthetic defaults
    when only @mesh.tool decorators are present.
    """

    def __init__(self):
        super().__init__(
            name="configuration",
            required=True,
            description="Resolve agent configuration with defaults",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Resolve agent configuration."""
        self.logger.debug("Resolving agent configuration...")

        result = PipelineResult(message="Configuration resolution completed")

        try:
            mesh_agents = context.get("mesh_agents", {})
            mesh_tools = context.get("mesh_tools", {})

            # Check if we have explicit @mesh.agent configuration
            agent_config = None
            if mesh_agents:
                # Use first agent configuration found
                for agent_name, decorated_func in mesh_agents.items():
                    agent_config = decorated_func.metadata.copy()
                    self.logger.debug(
                        f"Using @mesh.agent configuration from {agent_name}"
                    )
                    break

            # Apply defaults for missing configuration
            final_config = self._apply_defaults(agent_config, mesh_tools)

            # Store resolved configuration
            result.add_context("agent_config", final_config)
            result.add_context("has_explicit_agent", agent_config is not None)

            # Generate agent ID
            agent_id = self._generate_agent_id(final_config.get("name"))
            result.add_context("agent_id", agent_id)

            result.message = f"Configuration resolved for agent '{agent_id}'"
            self.logger.info(
                f"⚙️ Configuration resolved: agent_id='{agent_id}', explicit_agent={agent_config is not None}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Configuration resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Configuration resolution failed: {e}")

        return result

    def _apply_defaults(
        self, agent_config: Optional[dict[str, Any]], mesh_tools: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply default configuration values."""
        # Start with defaults (matching @mesh.agent parameter defaults)
        defaults = {
            "name": None,  # Will be generated if None
            "version": "1.0.0",
            "description": None,
            "http_host": "0.0.0.0",
            "http_port": 0,  # Auto-assign
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
            "auto_run": True,  # This is the key default!
            "auto_run_interval": 10,
        }

        # Apply environment variable overrides
        env_overrides = self._get_env_overrides()
        defaults.update(env_overrides)

        # Apply explicit agent config if available
        if agent_config:
            defaults.update(agent_config)

        return defaults

    def _get_env_overrides(self) -> dict[str, Any]:
        """Get configuration overrides from environment variables."""
        overrides = {}

        if "MCP_MESH_HTTP_HOST" in os.environ:
            overrides["http_host"] = os.environ["MCP_MESH_HTTP_HOST"]

        if "MCP_MESH_HTTP_PORT" in os.environ:
            try:
                overrides["http_port"] = int(os.environ["MCP_MESH_HTTP_PORT"])
            except ValueError:
                self.logger.warning("Invalid MCP_MESH_HTTP_PORT value, ignoring")

        if "MCP_MESH_ENABLE_HTTP" in os.environ:
            overrides["enable_http"] = os.environ["MCP_MESH_ENABLE_HTTP"].lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        if "MCP_MESH_NAMESPACE" in os.environ:
            overrides["namespace"] = os.environ["MCP_MESH_NAMESPACE"]

        if "MCP_MESH_AUTO_RUN" in os.environ:
            overrides["auto_run"] = os.environ["MCP_MESH_AUTO_RUN"].lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        return overrides

    def _generate_agent_id(self, agent_name: Optional[str]) -> str:
        """Generate agent ID using same logic as decorators."""
        import uuid

        # Precedence: env var > agent_name > default "agent"
        if "MCP_MESH_AGENT_NAME" in os.environ:
            prefix = os.environ["MCP_MESH_AGENT_NAME"]
        elif agent_name is not None:
            prefix = agent_name
        else:
            prefix = "agent"

        uuid_suffix = str(uuid.uuid4())[:8]
        return f"{prefix}-{uuid_suffix}"


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
        """Prepare heartbeat data."""
        self.logger.debug("Preparing heartbeat payload...")

        result = PipelineResult(message="Heartbeat preparation completed")

        try:
            mesh_tools = context.get("mesh_tools", {})
            agent_config = context.get("agent_config", {})
            agent_id = context.get("agent_id", "unknown-agent")

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
        """Build tools list from mesh_tools."""
        tools_list = []

        for func_name, decorated_func in mesh_tools.items():
            metadata = decorated_func.metadata
            current_function = decorated_func.function

            # Build tool registration data
            tool_data = {
                "function_name": func_name,
                "capability": metadata.get("capability"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "dependencies": self._process_dependencies(
                    metadata.get("dependencies", [])
                ),
            }

            # Add debug pointer information
            debug_pointers = self._get_function_pointer_debug_info(
                current_function, func_name
            )
            tool_data["debug_pointers"] = debug_pointers

            tools_list.append(tool_data)

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
        return {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "version": agent_config.get("version", "1.0.0"),
            "http_host": agent_config.get("http_host", "0.0.0.0"),
            "http_port": agent_config.get("http_port", 0),
            "timestamp": datetime.now(UTC),
            "namespace": agent_config.get("namespace", "default"),
            "tools": tools_list,
        }

    def _build_health_status(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
    ) -> HealthStatus:
        """Build health status for heartbeat."""
        # Extract capabilities from tools list
        capabilities = []

        for tool in tools_list:
            capability = tool.get("capability")
            if capability:
                capabilities.append(capability)

        # Ensure we have at least one capability for validation
        if not capabilities:
            capabilities = ["default"]

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=capabilities,
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
        )


class FastMCPServerDiscoveryStep(PipelineStep):
    """
    Discovers user's FastMCP server instances and prepares for takeover.

    This step searches the global namespace for FastMCP instances,
    extracts their registered functions, and prepares for server startup.
    """

    def __init__(self):
        super().__init__(
            name="fastmcp-server-discovery",
            required=False,  # Optional - may not have FastMCP instances
            description="Discover FastMCP server instances and prepare for takeover",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Discover FastMCP servers."""
        self.logger.debug("Discovering FastMCP server instances...")

        result = PipelineResult(message="FastMCP server discovery completed")

        try:
            # Discover FastMCP instances from the main module
            discovered_servers = self._discover_fastmcp_instances()

            if not discovered_servers:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastMCP server instances found"
                self.logger.info("⚠️ No FastMCP instances discovered")
                return result

            # Extract server information
            server_info = []
            total_registered_functions = 0

            for server_name, server_instance in discovered_servers.items():
                info = self._extract_server_info(server_name, server_instance)
                server_info.append(info)
                total_registered_functions += info.get("function_count", 0)

                self.logger.info(
                    f"📡 Discovered FastMCP server '{server_name}': "
                    f"{info.get('function_count', 0)} functions"
                )

            # Store in context for subsequent steps
            result.add_context("fastmcp_servers", discovered_servers)
            result.add_context("fastmcp_server_info", server_info)
            result.add_context("fastmcp_server_count", len(discovered_servers))
            result.add_context("fastmcp_total_functions", total_registered_functions)

            result.message = (
                f"Discovered {len(discovered_servers)} FastMCP servers "
                f"with {total_registered_functions} total functions"
            )

            self.logger.info(
                f"🎯 FastMCP discovery complete: {len(discovered_servers)} servers, "
                f"{total_registered_functions} functions"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastMCP server discovery failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastMCP server discovery failed: {e}")

        return result

    def _discover_fastmcp_instances(self) -> dict[str, Any]:
        """
        Discover FastMCP instances in the global namespace.

        This looks in multiple modules for FastMCP instances.
        """
        discovered = {}

        try:
            import sys

            # First check the main module
            main_module = sys.modules.get("__main__")
            if main_module:
                discovered.update(
                    self._search_module_for_fastmcp(main_module, "__main__")
                )

            # Also search recently imported modules that might contain FastMCP instances
            # Look for modules that were likely user modules (not built-ins)
            # Exclude common system/library modules but include all user modules
            system_modules = {
                "sys",
                "os",
                "logging",
                "asyncio",
                "json",
                "datetime",
                "time",
                "threading",
                "functools",
                "inspect",
                "collections",
                "typing",
                "uuid",
                "weakref",
                "signal",
                "atexit",
                "gc",
                "warnings",
                "importlib",
                "pkgutil",
            }

            for module_name, module in sys.modules.items():
                if (
                    module
                    and not module_name.startswith("_")
                    and module_name not in system_modules
                    and not module_name.startswith("mcp_mesh")  # Skip our own modules
                    and not module_name.startswith("mesh")  # Skip our own modules
                    and not module_name.startswith(
                        "fastmcp."
                    )  # Skip FastMCP library modules
                    and not module_name.startswith("mcp.")  # Skip MCP library modules
                    and hasattr(module, "__file__")
                    and module.__file__
                    and not module.__file__.endswith(".so")
                ):  # Skip binary extensions

                    found_in_module = self._search_module_for_fastmcp(
                        module, module_name
                    )
                    if found_in_module:
                        self.logger.debug(
                            f"Found {len(found_in_module)} FastMCP instances in module {module_name}"
                        )
                        discovered.update(found_in_module)

            self.logger.debug(
                f"FastMCP discovery complete: {len(discovered)} instances found"
            )
            return discovered

        except Exception as e:
            self.logger.error(f"Error discovering FastMCP instances: {e}")
            return discovered

    def _search_module_for_fastmcp(
        self, module: Any, module_name: str
    ) -> dict[str, Any]:
        """Search a specific module for FastMCP instances."""
        found = {}

        try:
            if not hasattr(module, "__dict__"):
                return found

            module_globals = vars(module)
            self.logger.debug(
                f"Searching module {module_name} with {len(module_globals)} variables"
            )

            for var_name, var_value in module_globals.items():
                if self._is_fastmcp_instance(var_value):
                    instance_key = f"{module_name}.{var_name}"
                    found[instance_key] = var_value
                    self.logger.debug(
                        f"✅ Found FastMCP instance: {instance_key} = {var_value}"
                    )
                elif hasattr(var_value, "__class__") and "FastMCP" in str(
                    type(var_value)
                ):
                    self.logger.debug(
                        f"🔍 Potential FastMCP-like object in {module_name}: {var_name} = {var_value}"
                    )

        except Exception as e:
            self.logger.debug(f"Error searching module {module_name}: {e}")

        return found

    def _is_fastmcp_instance(self, obj: Any) -> bool:
        """Check if an object is a FastMCP server instance."""
        try:
            # Check if it's a FastMCP instance by looking at class name and attributes
            if hasattr(obj, "__class__"):
                class_name = obj.__class__.__name__
                if class_name == "FastMCP":
                    # Verify it has the expected FastMCP attributes
                    return (
                        hasattr(obj, "name")
                        and hasattr(obj, "_tool_manager")
                        and hasattr(obj, "tool")  # The decorator method
                    )
            return False
        except Exception:
            return False

    def _extract_server_info(
        self, server_name: str, server_instance: Any
    ) -> dict[str, Any]:
        """Extract detailed information from a FastMCP server instance."""
        info = {
            "server_name": server_name,
            "server_instance": server_instance,
            "fastmcp_name": getattr(server_instance, "name", "unknown"),
            "function_count": 0,
            "tools": {},
            "prompts": {},
            "resources": {},
            "tool_manager": None,
        }

        try:
            # Extract tool manager
            if hasattr(server_instance, "_tool_manager"):
                tool_manager = server_instance._tool_manager
                info["tool_manager"] = tool_manager

                # Extract registered tools
                if hasattr(tool_manager, "_tools"):
                    tools = tool_manager._tools
                    info["tools"] = tools
                    info["function_count"] += len(tools)

                    self.logger.debug(f"Server '{server_name}' has {len(tools)} tools:")
                    for tool_name, tool in tools.items():
                        function_ptr = getattr(tool, "fn", None)
                        self.logger.debug(f"  - {tool_name}: {function_ptr}")

            # Extract prompts if available
            if hasattr(server_instance, "_prompt_manager"):
                prompt_manager = server_instance._prompt_manager
                if hasattr(prompt_manager, "_prompts"):
                    prompts = prompt_manager._prompts
                    info["prompts"] = prompts
                    info["function_count"] += len(prompts)

                    self.logger.debug(
                        f"Server '{server_name}' has {len(prompts)} prompts"
                    )

            # Extract resources if available
            if hasattr(server_instance, "_resource_manager"):
                resource_manager = server_instance._resource_manager
                if hasattr(resource_manager, "_resources"):
                    resources = resource_manager._resources
                    info["resources"] = resources
                    info["function_count"] += len(resources)

                    self.logger.debug(
                        f"Server '{server_name}' has {len(resources)} resources"
                    )

        except Exception as e:
            self.logger.error(f"Error extracting server info for '{server_name}': {e}")

        return info


class FastMCPServerStartupStep(PipelineStep):
    """
    Starts discovered FastMCP server instances with HTTP transport.

    Handles local binding configuration and prepares external advertisement info.
    Binds servers locally (0.0.0.0) while preparing external endpoints for registry.
    """

    def __init__(self):
        super().__init__(
            name="fastmcp-server-startup",
            required=False,  # Optional - may not have FastMCP instances
            description="Start FastMCP servers with HTTP transport",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Start FastMCP servers."""
        self.logger.debug("Starting FastMCP server instances...")

        result = PipelineResult(message="FastMCP server startup completed")

        try:
            # Get discovered servers from previous step
            fastmcp_servers = context.get("fastmcp_servers", {})
            agent_config = context.get("agent_config", {})

            if not fastmcp_servers:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastMCP servers to start"
                self.logger.info("⚠️ No FastMCP servers found to start")
                return result

            # Check if HTTP transport is enabled
            http_enabled = self._is_http_enabled()
            if not http_enabled:
                result.status = PipelineStatus.SKIPPED
                result.message = "HTTP transport disabled"
                self.logger.info("⚠️ HTTP transport disabled via MCP_MESH_HTTP_ENABLED")
                return result

            # Resolve binding and advertisement configuration
            binding_config = self._resolve_binding_config(agent_config)
            advertisement_config = self._resolve_advertisement_config(agent_config)

            # Start each FastMCP server
            running_servers = {}
            server_endpoints = {}
            actual_ports = {}

            for server_key, server_instance in fastmcp_servers.items():
                try:
                    startup_result = await self._start_fastmcp_server(
                        server_key,
                        server_instance,
                        binding_config,
                        advertisement_config,
                    )

                    running_servers[server_key] = startup_result["server_instance"]
                    actual_ports[server_key] = startup_result["actual_port"]
                    server_endpoints[server_key] = startup_result["external_endpoint"]

                    self.logger.info(
                        f"🚀 Started FastMCP server '{server_key}' on {startup_result['bind_address']} "
                        f"(external: {startup_result['external_endpoint']})"
                    )

                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to start FastMCP server '{server_key}': {e}"
                    )
                    result.add_error(f"Server startup failed for '{server_key}': {e}")

            # Store results in context
            result.add_context("running_fastmcp_servers", running_servers)
            result.add_context("fastmcp_actual_ports", actual_ports)
            result.add_context("fastmcp_server_endpoints", server_endpoints)
            result.add_context("fastmcp_binding_config", binding_config)
            result.add_context("fastmcp_advertisement_config", advertisement_config)

            if running_servers:
                result.message = f"Started {len(running_servers)} FastMCP servers"
                self.logger.info(
                    f"🎯 FastMCP startup complete: {len(running_servers)} servers running"
                )
            else:
                result.status = PipelineStatus.FAILED
                result.message = "No FastMCP servers started successfully"

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastMCP server startup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastMCP server startup failed: {e}")

        return result

    def _is_http_enabled(self) -> bool:
        """Check if HTTP transport is enabled."""
        import os

        return os.getenv("MCP_MESH_HTTP_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def _resolve_binding_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Resolve local server binding configuration."""
        import os

        # Local binding - always use 0.0.0.0 to bind to all interfaces
        bind_host = "0.0.0.0"

        # Port from agent config or environment
        bind_port = int(os.getenv("MCP_MESH_HTTP_PORT", 0)) or agent_config.get(
            "http_port", 8080
        )

        return {
            "bind_host": bind_host,
            "bind_port": bind_port,
        }

    def _resolve_advertisement_config(
        self, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve external advertisement configuration for registry."""
        import os

        # External hostname - for registry advertisement
        external_host = (
            os.getenv("MCP_MESH_HTTP_HOST")
            or os.getenv("POD_IP")
            or self._auto_detect_external_ip()
        )

        # Full endpoint override
        external_endpoint = os.getenv("MCP_MESH_HTTP_ENDPOINT")

        return {
            "external_host": external_host,
            "external_endpoint": external_endpoint,  # May be None - will build dynamically
        }

    def _auto_detect_external_ip(self) -> str:
        """Auto-detect external IP address for advertisement."""
        try:
            import socket

            # Try to get the IP that would be used to reach external hosts
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                self.logger.debug(f"Auto-detected external IP: {local_ip}")
                return local_ip

        except Exception as e:
            self.logger.warning(
                f"Failed to auto-detect external IP: {e}, using localhost"
            )
            return "localhost"

    async def _start_fastmcp_server(
        self,
        server_key: str,
        server_instance: Any,
        binding_config: dict[str, Any],
        advertisement_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Start a single FastMCP server instance."""
        bind_host = binding_config["bind_host"]
        bind_port = binding_config["bind_port"]
        external_host = advertisement_config["external_host"]
        external_endpoint = advertisement_config["external_endpoint"]

        try:
            # Verify server has required async methods
            if not (
                hasattr(server_instance, "run_http_async")
                and callable(server_instance.run_http_async)
            ):
                raise Exception(
                    f"Server '{server_key}' does not have run_http_async method"
                )

            self.logger.debug(
                f"Starting FastMCP HTTP server '{server_key}' on {bind_host}:{bind_port}"
            )

            # Start FastMCP HTTP server in background task
            # NOTE: We're starting it as a background task so the pipeline can continue
            import asyncio

            async def run_server():
                try:
                    await server_instance.run_http_async(host=bind_host, port=bind_port)
                except Exception as e:
                    self.logger.error(
                        f"FastMCP server '{server_key}' stopped with error: {e}"
                    )

            # Start server as background task
            server_task = asyncio.create_task(run_server())

            # Give server a moment to start up
            await asyncio.sleep(0.1)

            # Determine actual port (for now, assume it started on requested port)
            # TODO: In the future, we could inspect the server to get the actual bound port
            actual_port = bind_port if bind_port != 0 else 8080

            # Build external endpoint
            final_external_endpoint = (
                external_endpoint or f"http://{external_host}:{actual_port}"
            )

            self.logger.info(
                f"FastMCP server '{server_key}' starting on {bind_host}:{actual_port}"
            )

            return {
                "server_instance": server_instance,
                "server_task": server_task,  # Store task reference for lifecycle management
                "actual_port": actual_port,
                "bind_address": f"{bind_host}:{actual_port}",
                "external_endpoint": final_external_endpoint,
            }

        except Exception as e:
            self.logger.error(f"Failed to start server '{server_key}': {e}")
            raise


class FastAPIServerSetupStep(PipelineStep):
    """
    Sets up FastAPI server with K8s endpoints and mounts FastMCP servers.

    FastAPI server binds to the port specified in @mesh.agent configuration.
    FastMCP servers are mounted at /mcp endpoint for MCP protocol communication.
    Includes Kubernetes health endpoints (/health, /ready, /metrics).
    """

    def __init__(self):
        super().__init__(
            name="fastapi-server-setup",
            required=False,  # Optional - may not have FastMCP instances to mount
            description="Setup FastAPI server with K8s endpoints and mount FastMCP servers",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Setup FastAPI server."""
        self.logger.debug("Setting up FastAPI server with mounted FastMCP servers...")

        result = PipelineResult(message="FastAPI server setup completed")

        try:
            # Get configuration and discovered servers
            agent_config = context.get("agent_config", {})
            fastmcp_servers = context.get("fastmcp_servers", {})

            # Check if HTTP transport is enabled
            if not self._is_http_enabled():
                result.status = PipelineStatus.SKIPPED
                result.message = "HTTP transport disabled"
                self.logger.info("⚠️ HTTP transport disabled via MCP_MESH_HTTP_ENABLED")
                return result

            # Resolve binding and advertisement configuration
            binding_config = self._resolve_binding_config(agent_config)
            advertisement_config = self._resolve_advertisement_config(agent_config)

            # Create FastAPI application with proper FastMCP lifespan integration
            fastapi_app = self._create_fastapi_app(agent_config, fastmcp_servers)

            # Add K8s health endpoints
            self._add_k8s_endpoints(fastapi_app, agent_config, fastmcp_servers)

            # Mount FastMCP servers
            mounted_servers = {}
            if fastmcp_servers:
                for server_key, server_instance in fastmcp_servers.items():
                    try:
                        mount_path = self._mount_fastmcp_server(
                            fastapi_app, server_key, server_instance
                        )
                        mounted_servers[server_key] = {
                            "mount_path": mount_path,
                            "server_instance": server_instance,
                        }
                        self.logger.info(
                            f"📎 Mounted FastMCP server '{server_key}' at {mount_path}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"❌ Failed to mount FastMCP server '{server_key}': {e}"
                        )
                        result.add_error(f"Failed to mount server '{server_key}': {e}")

            # Start FastAPI server
            server_info = await self._start_fastapi_server(
                fastapi_app, binding_config, advertisement_config
            )

            # Store results in context
            result.add_context("fastapi_app", fastapi_app)
            result.add_context("fastapi_server_info", server_info)
            result.add_context("mounted_fastmcp_servers", mounted_servers)
            result.add_context("fastapi_binding_config", binding_config)
            result.add_context("fastapi_advertisement_config", advertisement_config)

            bind_address = server_info["bind_address"]
            external_endpoint = server_info["external_endpoint"]

            result.message = f"FastAPI server running on {bind_address} (external: {external_endpoint})"
            self.logger.info(
                f"🚀 FastAPI server started on {bind_address} with {len(mounted_servers)} mounted FastMCP servers"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastAPI server setup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastAPI server setup failed: {e}")

        return result

    def _is_http_enabled(self) -> bool:
        """Check if HTTP transport is enabled."""
        import os

        return os.getenv("MCP_MESH_HTTP_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def _resolve_binding_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Resolve local server binding configuration."""
        import os

        # Local binding - always use 0.0.0.0 to bind to all interfaces
        bind_host = "0.0.0.0"

        # Port from agent config or environment
        bind_port = int(os.getenv("MCP_MESH_HTTP_PORT", 0)) or agent_config.get(
            "http_port", 8080
        )

        return {
            "bind_host": bind_host,
            "bind_port": bind_port,
        }

    def _resolve_advertisement_config(
        self, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve external advertisement configuration for registry."""
        import os

        # External hostname - for registry advertisement
        external_host = (
            os.getenv("MCP_MESH_HTTP_HOST")
            or os.getenv("POD_IP")
            or self._auto_detect_external_ip()
        )

        # Full endpoint override
        external_endpoint = os.getenv("MCP_MESH_HTTP_ENDPOINT")

        return {
            "external_host": external_host,
            "external_endpoint": external_endpoint,  # May be None - will build dynamically
        }

    def _auto_detect_external_ip(self) -> str:
        """Auto-detect external IP address for advertisement."""
        try:
            import socket

            # Try to get the IP that would be used to reach external hosts
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                self.logger.debug(f"Auto-detected external IP: {local_ip}")
                return local_ip

        except Exception as e:
            self.logger.warning(
                f"Failed to auto-detect external IP: {e}, using localhost"
            )
            return "localhost"

    def _create_fastapi_app(
        self, agent_config: dict[str, Any], fastmcp_servers: dict[str, Any]
    ) -> Any:
        """Create FastAPI application with FastMCP lifespan integration."""
        try:
            import asyncio
            from contextlib import asynccontextmanager

            from fastapi import FastAPI

            agent_name = agent_config.get("name", "mcp-mesh-agent")
            agent_description = agent_config.get(
                "description", "MCP Mesh Agent with FastAPI integration"
            )

            # Collect lifespans from FastMCP servers
            fastmcp_lifespans = []
            for server_key, server_instance in fastmcp_servers.items():
                if hasattr(server_instance, "http_app") and callable(
                    server_instance.http_app
                ):
                    http_app = server_instance.http_app()
                    if hasattr(http_app, "lifespan"):
                        fastmcp_lifespans.append(http_app.lifespan)
                        self.logger.debug(
                            f"Collected lifespan from FastMCP server '{server_key}'"
                        )

            # Create combined lifespan manager
            @asynccontextmanager
            async def combined_lifespan(app):
                """Combined lifespan manager for FastAPI + FastMCP."""
                # Start all FastMCP lifespans
                lifespan_contexts = []
                for lifespan in fastmcp_lifespans:
                    ctx = lifespan(app)
                    await ctx.__aenter__()
                    lifespan_contexts.append(ctx)

                try:
                    yield
                finally:
                    # Clean up all lifespans in reverse order
                    for ctx in reversed(lifespan_contexts):
                        try:
                            await ctx.__aexit__(None, None, None)
                        except Exception as e:
                            self.logger.warning(f"Error closing FastMCP lifespan: {e}")

            app = FastAPI(
                title=f"MCP Mesh Agent: {agent_name}",
                description=agent_description,
                version=agent_config.get("version", "1.0.0"),
                docs_url="/docs",  # Enable OpenAPI docs
                redoc_url="/redoc",
                lifespan=combined_lifespan if fastmcp_lifespans else None,
            )

            self.logger.debug(
                f"Created FastAPI app for agent '{agent_name}' with {len(fastmcp_lifespans)} FastMCP lifespans"
            )
            return app

        except ImportError as e:
            raise Exception(f"FastAPI not available: {e}")

    def _add_k8s_endpoints(
        self, app: Any, agent_config: dict[str, Any], fastmcp_servers: dict[str, Any]
    ) -> None:
        """Add Kubernetes health and metrics endpoints."""
        agent_name = agent_config.get("name", "mcp-mesh-agent")

        @app.get("/health")
        async def health():
            """Basic health check endpoint for Kubernetes."""
            return {
                "status": "healthy",
                "agent": agent_name,
                "timestamp": self._get_timestamp(),
            }

        @app.get("/ready")
        async def ready():
            """Readiness check for Kubernetes."""
            # Check if we have FastMCP servers with tools
            total_tools = 0
            server_status = {}

            for server_key, server_instance in fastmcp_servers.items():
                tools_count = 0
                if hasattr(server_instance, "_tool_manager") and hasattr(
                    server_instance._tool_manager, "_tools"
                ):
                    tools_count = len(server_instance._tool_manager._tools)

                server_status[server_key] = {
                    "tools_count": tools_count,
                    "has_tools": tools_count > 0,
                }
                total_tools += tools_count

            is_ready = (
                total_tools > 0 or not fastmcp_servers
            )  # Ready if has tools or no servers expected

            return {
                "ready": is_ready,
                "agent": agent_name,
                "total_tools": total_tools,
                "servers": server_status,
                "timestamp": self._get_timestamp(),
            }

        @app.get("/livez")
        async def livez():
            """Liveness check for Kubernetes."""
            return {
                "alive": True,
                "agent": agent_name,
                "timestamp": self._get_timestamp(),
            }

        @app.get("/metrics")
        async def metrics():
            """Basic metrics endpoint for Prometheus."""
            # Simple text format metrics
            total_tools = sum(
                len(getattr(server._tool_manager, "_tools", {}))
                for server in fastmcp_servers.values()
                if hasattr(server, "_tool_manager")
            )

            metrics_text = f"""# HELP mcp_mesh_tools_total Total number of MCP tools
# TYPE mcp_mesh_tools_total gauge
mcp_mesh_tools_total{{agent="{agent_name}"}} {total_tools}

# HELP mcp_mesh_servers_total Total number of FastMCP servers
# TYPE mcp_mesh_servers_total gauge
mcp_mesh_servers_total{{agent="{agent_name}"}} {len(fastmcp_servers)}

# HELP mcp_mesh_up Agent uptime indicator
# TYPE mcp_mesh_up gauge
mcp_mesh_up{{agent="{agent_name}"}} 1
"""
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse(content=metrics_text, media_type="text/plain")

        self.logger.debug(
            "Added K8s health endpoints: /health, /ready, /livez, /metrics"
        )

    def _mount_fastmcp_server(
        self, app: Any, server_key: str, server_instance: Any
    ) -> str:
        """Mount a FastMCP server onto FastAPI."""
        try:
            # Try to get FastMCP's HTTP app
            if hasattr(server_instance, "http_app") and callable(
                server_instance.http_app
            ):
                fastmcp_app = server_instance.http_app()
                # Mount at root since FastMCP's http_app already includes /mcp path
                mount_path = ""
                app.mount(mount_path, fastmcp_app)
                self.logger.debug(
                    f"Mounted FastMCP server '{server_key}' at root (FastMCP handles /mcp internally)"
                )
                return "/mcp"  # Return the actual endpoint users will access
            else:
                raise Exception(
                    f"FastMCP server '{server_key}' does not have http_app() method"
                )

        except Exception as e:
            self.logger.error(f"Failed to mount FastMCP server '{server_key}': {e}")
            raise

    async def _start_fastapi_server(
        self,
        app: Any,
        binding_config: dict[str, Any],
        advertisement_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Start FastAPI server with uvicorn."""
        bind_host = binding_config["bind_host"]
        bind_port = binding_config["bind_port"]
        external_host = advertisement_config["external_host"]
        external_endpoint = advertisement_config["external_endpoint"]

        try:
            import asyncio

            import uvicorn

            # Create uvicorn config
            config = uvicorn.Config(
                app=app,
                host=bind_host,
                port=bind_port,
                log_level="info",
                access_log=False,  # Reduce noise
            )

            # Create and start server
            server = uvicorn.Server(config)

            # Start server as background task
            async def run_server():
                try:
                    await server.serve()
                except Exception as e:
                    self.logger.error(f"FastAPI server stopped with error: {e}")

            server_task = asyncio.create_task(run_server())

            # Give server a moment to start up
            await asyncio.sleep(0.2)

            # Determine actual port (for now, assume it started on requested port)
            actual_port = bind_port if bind_port != 0 else 8080

            # Build external endpoint
            final_external_endpoint = (
                external_endpoint or f"http://{external_host}:{actual_port}"
            )

            return {
                "server": server,
                "server_task": server_task,
                "actual_port": actual_port,
                "bind_address": f"{bind_host}:{actual_port}",
                "external_endpoint": final_external_endpoint,
            }

        except ImportError as e:
            raise Exception(f"uvicorn not available: {e}")
        except Exception as e:
            self.logger.error(f"Failed to start FastAPI server: {e}")
            raise

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()
