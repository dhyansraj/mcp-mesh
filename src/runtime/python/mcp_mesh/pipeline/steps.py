"""
Pipeline step implementations for MCP Mesh processing.

Provides concrete implementations of common processing steps like
decorator collection, configuration resolution, and heartbeat preparation.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Optional

from ..decorator_registry import DecoratorRegistry
from ..engine.logging_config import configure_logging
from ..shared.registry_client_wrapper import RegistryClientWrapper
from ..shared.support_types import HealthStatus, HealthStatusType

# Ensure logging is configured
configure_logging()
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
                agent_id, agent_config, tools_list, context
            )

            # Build health status for heartbeat
            health_status = self._build_health_status(
                agent_id, agent_config, tools_list, context
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
        context: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """Build agent registration payload."""
        # Get external endpoint information from FastAPI advertisement config
        advertisement_config = {}
        if context:
            advertisement_config = context.get("fastapi_advertisement_config", {})

        # Use external host/port for registry advertisement (not binding address)
        external_host = advertisement_config.get("external_host") or agent_config.get(
            "http_host", "localhost"
        )
        external_endpoint = advertisement_config.get("external_endpoint")

        # Parse external endpoint if provided, otherwise use external_host + port
        if external_endpoint:
            from urllib.parse import urlparse

            parsed = urlparse(external_endpoint)
            http_host = parsed.hostname or external_host
            http_port = parsed.port or agent_config.get("http_port", 8080)
        else:
            http_host = external_host
            http_port = agent_config.get("http_port", 8080)

        # Don't send 0.0.0.0 as it's a binding address, not an external address
        if http_host == "0.0.0.0":
            http_host = "localhost"

        return {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "version": agent_config.get("version", "1.0.0"),
            "http_host": http_host,
            "http_port": http_port,
            "timestamp": datetime.now(UTC),
            "namespace": agent_config.get("namespace", "default"),
            "tools": tools_list,
        }

    def _build_health_status(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
        context: dict[str, Any] = None,
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

        # Build metadata with external endpoint information
        metadata = dict(agent_config)  # Copy agent config

        # Add external endpoint information from FastAPI advertisement config
        if context:
            advertisement_config = context.get("fastapi_advertisement_config", {})
            external_host = advertisement_config.get("external_host")
            external_endpoint = advertisement_config.get("external_endpoint")

            if external_host:
                metadata["external_host"] = external_host
            if external_endpoint:
                metadata["external_endpoint"] = external_endpoint
                # Parse endpoint for individual components
                from urllib.parse import urlparse

                parsed = urlparse(external_endpoint)
                if parsed.hostname:
                    metadata["external_host"] = parsed.hostname
                if parsed.port:
                    metadata["external_port"] = parsed.port

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=capabilities,
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=metadata,
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
            # Only log if we find FastMCP instances to reduce noise

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
            description="Prepare FastAPI app with K8s endpoints and mount FastMCP servers",
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

            # Get heartbeat config for lifespan integration
            heartbeat_config = context.get("heartbeat_config")

            # Create FastAPI application with proper FastMCP lifespan integration
            fastapi_app = self._create_fastapi_app(
                agent_config, fastmcp_servers, heartbeat_config
            )

            # Add K8s health endpoints
            self._add_k8s_endpoints(fastapi_app, agent_config, {})

            # Create HTTP wrappers for FastMCP servers (instead of direct mounting)
            mcp_wrappers = {}
            if fastmcp_servers:
                for server_key, server_instance in fastmcp_servers.items():
                    try:
                        # Create HttpMcpWrapper for proper MCP protocol handling
                        from ..engine.http_wrapper import HttpConfig, HttpMcpWrapper

                        # Use wrapper config - it will create its own FastAPI app
                        http_config = HttpConfig(
                            host=binding_config["bind_host"],
                            port=binding_config["bind_port"],
                        )

                        mcp_wrapper = HttpMcpWrapper(server_instance, http_config)
                        await mcp_wrapper.setup()

                        # Add MCP endpoints to our main FastAPI app
                        self._integrate_mcp_wrapper(
                            fastapi_app, mcp_wrapper, server_key
                        )

                        mcp_wrappers[server_key] = {
                            "wrapper": mcp_wrapper,
                            "server_instance": server_instance,
                        }
                        self.logger.info(
                            f"🔌 Integrated MCP wrapper for FastMCP server '{server_key}'"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"❌ Failed to create MCP wrapper for server '{server_key}': {e}"
                        )
                        result.add_error(f"Failed to wrap server '{server_key}': {e}")

            # Store results in context (app prepared, but server not started yet)
            result.add_context("fastapi_app", fastapi_app)
            result.add_context("mcp_wrappers", mcp_wrappers)
            result.add_context("fastapi_binding_config", binding_config)
            result.add_context("fastapi_advertisement_config", advertisement_config)

            bind_host = binding_config["bind_host"]
            bind_port = binding_config["bind_port"]
            external_host = advertisement_config["external_host"]
            external_endpoint = (
                advertisement_config.get("external_endpoint")
                or f"http://{external_host}:{bind_port}"
            )

            result.message = f"FastAPI app prepared for {bind_host}:{bind_port} (external: {external_endpoint})"
            self.logger.info(
                f"📦 FastAPI app prepared with {len(mcp_wrappers)} MCP wrappers (ready for uvicorn.run)"
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
        self,
        agent_config: dict[str, Any],
        fastmcp_servers: dict[str, Any],
        heartbeat_config: dict[str, Any] = None,
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
                """Combined lifespan manager for FastAPI + FastMCP + Heartbeat."""
                # Start all FastMCP lifespans
                lifespan_contexts = []
                for lifespan in fastmcp_lifespans:
                    ctx = lifespan(app)
                    await ctx.__aenter__()
                    lifespan_contexts.append(ctx)

                # Start heartbeat task if configured
                heartbeat_task = None
                if heartbeat_config:
                    import asyncio

                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_lifespan_task(heartbeat_config)
                    )
                    self.logger.info(
                        f"💓 Started heartbeat task in FastAPI lifespan with {heartbeat_config['interval']}s interval"
                    )

                try:
                    yield
                finally:
                    # Clean up heartbeat task
                    if heartbeat_task:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            self.logger.info(
                                "🛑 Heartbeat task cancelled during shutdown"
                            )

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
                lifespan=(
                    combined_lifespan
                    if (fastmcp_lifespans or heartbeat_config)
                    else None
                ),
            )

            self.logger.debug(
                f"Created FastAPI app for agent '{agent_name}' with {len(fastmcp_lifespans)} FastMCP lifespans"
            )
            return app

        except ImportError as e:
            raise Exception(f"FastAPI not available: {e}")

    def _add_k8s_endpoints(
        self, app: Any, agent_config: dict[str, Any], mcp_wrappers: dict[str, Any]
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
            # Simple readiness check - always ready for now
            # TODO: Update this to check MCP wrapper status
            return {
                "ready": True,
                "agent": agent_name,
                "mcp_wrappers": len(mcp_wrappers),
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
            # TODO: Update to get tools count from MCP wrappers

            metrics_text = f"""# HELP mcp_mesh_wrappers_total Total number of MCP wrappers
# TYPE mcp_mesh_wrappers_total gauge
mcp_mesh_wrappers_total{{agent="{agent_name}"}} {len(mcp_wrappers)}

# HELP mcp_mesh_up Agent uptime indicator
# TYPE mcp_mesh_up gauge
mcp_mesh_up{{agent="{agent_name}"}} 1
"""
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse(content=metrics_text, media_type="text/plain")

        self.logger.debug(
            "Added K8s health endpoints: /health, /ready, /livez, /metrics"
        )

    def _integrate_mcp_wrapper(
        self, app: Any, mcp_wrapper: Any, server_key: str
    ) -> None:
        """Integrate HttpMcpWrapper MCP endpoints into the main FastAPI app."""
        try:
            # The HttpMcpWrapper creates its own FastAPI app with MCP endpoints
            # We need to extract the MCP endpoint handlers and add them to our main app

            # Get the MCP route handlers from the wrapper's app
            wrapper_app = mcp_wrapper.app

            # Find the /mcp route and copy it to our main app
            for route in wrapper_app.routes:
                if hasattr(route, "path") and route.path == "/mcp":
                    # Add the MCP endpoint to our main app
                    app.add_route("/mcp", route.endpoint, methods=["POST"])
                    self.logger.debug(
                        f"Added /mcp endpoint from wrapper '{server_key}'"
                    )
                    break
            else:
                self.logger.warning(f"No /mcp route found in wrapper '{server_key}'")

        except Exception as e:
            self.logger.error(f"Failed to integrate MCP wrapper '{server_key}': {e}")
            raise

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
                # Mount at /mcp path for MCP protocol access
                mount_path = "/mcp"
                app.mount(mount_path, fastmcp_app)
                self.logger.debug(
                    f"Mounted FastMCP server '{server_key}' at {mount_path}"
                )
                return mount_path  # Return the actual endpoint users will access
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

    async def _heartbeat_lifespan_task(self, heartbeat_config: dict[str, Any]) -> None:
        """Heartbeat task that runs in FastAPI lifespan."""
        registry_wrapper = heartbeat_config["registry_wrapper"]
        agent_id = heartbeat_config["agent_id"]
        interval = heartbeat_config["interval"]
        context = heartbeat_config["context"]

        self.logger.info(f"💓 Starting heartbeat lifespan task for agent '{agent_id}'")

        heartbeat_count = 0
        try:
            while True:
                heartbeat_count += 1

                try:
                    # Build health status from context (reuse existing logic)
                    health_status = self._build_health_status_from_context(context)

                    # Debug: Log heartbeat request details
                    import json

                    # Convert health status to dict for logging
                    if hasattr(health_status, "__dict__"):
                        health_dict = {
                            "agent_name": getattr(
                                health_status, "agent_name", agent_id
                            ),
                            "status": (
                                getattr(health_status, "status", "healthy").value
                                if hasattr(
                                    getattr(health_status, "status", "healthy"), "value"
                                )
                                else str(getattr(health_status, "status", "healthy"))
                            ),
                            "capabilities": getattr(health_status, "capabilities", []),
                            "timestamp": (
                                getattr(health_status, "timestamp", "").isoformat()
                                if hasattr(
                                    getattr(health_status, "timestamp", ""), "isoformat"
                                )
                                else str(getattr(health_status, "timestamp", ""))
                            ),
                            "version": getattr(health_status, "version", "1.0.0"),
                            "metadata": getattr(health_status, "metadata", {}),
                        }
                    else:
                        health_dict = health_status

                    request_json = json.dumps(health_dict, indent=2, default=str)
                    self.logger.debug(
                        f"🔍 Heartbeat request #{heartbeat_count}:\n{request_json}"
                    )

                    # Send heartbeat first
                    response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
                        health_status
                    )

                    # Debug: Log heartbeat response details
                    if response:
                        response_json = json.dumps(response, indent=2, default=str)
                        self.logger.debug(
                            f"🔍 Heartbeat response #{heartbeat_count}:\n{response_json}"
                        )
                    else:
                        self.logger.debug(
                            f"🔍 Heartbeat response #{heartbeat_count}: None (no response)"
                        )

                    # Log success
                    if response:
                        self.logger.info(
                            f"💚 Heartbeat #{heartbeat_count} sent successfully for agent '{agent_id}'"
                        )
                    else:
                        self.logger.warning(
                            f"💔 Heartbeat #{heartbeat_count} failed for agent '{agent_id}' - no response"
                        )

                    # Log every 10th heartbeat for visibility
                    if heartbeat_count % 10 == 0:
                        elapsed_time = heartbeat_count * interval
                        self.logger.info(
                            f"💓 Heartbeat #{heartbeat_count} for agent '{agent_id}' - "
                            f"running for {elapsed_time} seconds"
                        )

                except Exception as e:
                    self.logger.error(
                        f"❌ Heartbeat #{heartbeat_count} error for agent '{agent_id}': {e}"
                    )
                    # Continue to next cycle

                # Wait for next heartbeat interval
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            self.logger.info(
                f"🛑 Heartbeat lifespan task cancelled for agent '{agent_id}'"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"💥 Heartbeat lifespan task failed for agent '{agent_id}': {e}"
            )

    def _build_health_status_from_context(self, context: dict[str, Any]) -> Any:
        """Build health status object from pipeline context."""
        # Get existing health status from context or build from current state
        existing_health_status = context.get("health_status")

        if existing_health_status:
            # Update timestamp to current time for fresh heartbeat
            if hasattr(existing_health_status, "timestamp"):
                from datetime import UTC, datetime

                existing_health_status.timestamp = datetime.now(UTC)
            return existing_health_status

        # Build minimal health status from context if none exists
        agent_id = context.get("agent_id", "unknown-agent")
        agent_config = context.get("agent_config", {})

        # Import here to avoid circular imports
        from datetime import UTC, datetime

        from ..shared.support_types import HealthStatus, HealthStatusType

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=agent_config.get("capabilities", []),
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
        )

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()


class HeartbeatLoopStep(PipelineStep):
    """
    Starts background heartbeat loop for continuous registry communication.

    This step starts an asyncio background task that sends periodic heartbeats
    to the mesh registry using the existing registry client wrapper. The task
    runs independently and doesn't block pipeline progression.
    """

    def __init__(self):
        super().__init__(
            name="heartbeat-loop",
            required=False,  # Optional - agent can run standalone without registry
            description="Start background heartbeat loop for registry communication",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Start background heartbeat task."""
        self.logger.debug("Starting background heartbeat loop...")

        result = PipelineResult(message="Heartbeat loop started")

        try:
            # Get configuration
            agent_config = context.get("agent_config", {})
            registry_wrapper = context.get("registry_wrapper")

            # Check if registry is available
            if not registry_wrapper:
                result.status = PipelineStatus.SKIPPED
                result.message = (
                    "No registry connection - agent running in standalone mode"
                )
                self.logger.info("⚠️ No registry connection, skipping heartbeat loop")
                return result

            # Get agent ID and heartbeat interval configuration
            agent_id = context.get("agent_id", "unknown-agent")
            heartbeat_interval = self._get_heartbeat_interval(agent_config)

            # Store heartbeat config for FastAPI lifespan (don't start task in this event loop)
            result.add_context(
                "heartbeat_config",
                {
                    "registry_wrapper": registry_wrapper,
                    "agent_id": agent_id,
                    "interval": heartbeat_interval,
                    "context": context,  # Pass full context for health status building
                },
            )

            result.message = (
                f"Heartbeat config prepared (interval: {heartbeat_interval}s)"
            )
            self.logger.info(
                f"💓 Heartbeat config prepared for FastAPI lifespan with {heartbeat_interval}s interval"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to start heartbeat loop: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Failed to start heartbeat loop: {e}")

        return result

    def _get_heartbeat_interval(self, agent_config: dict[str, Any]) -> int:
        """Get heartbeat interval from configuration sources."""
        import os

        # Priority order: ENV > agent_config > default
        env_interval = os.getenv("MCP_MESH_HEARTBEAT_INTERVAL")
        if env_interval:
            try:
                return int(env_interval)
            except ValueError:
                self.logger.warning(
                    f"Invalid MCP_MESH_HEARTBEAT_INTERVAL: {env_interval}"
                )

        # Check agent config
        health_interval = agent_config.get("health_interval")
        if health_interval:
            return int(health_interval)

        # Default to 30 seconds
        return 30


class AtexitLoopStep(PipelineStep):
    """
    Starts a keep-alive service to prevent script exit.

    This step ensures the agent process stays alive by starting
    a non-daemon thread with a keep-alive loop and signal handling.
    """

    def __init__(self):
        super().__init__(
            name="keep-alive-service",
            required=False,
            description="Start keep-alive service to prevent script exit",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Start keep-alive service to prevent script exit."""
        self.logger.debug("Starting keep-alive service to prevent script exit...")

        result = PipelineResult(message="Keep-alive service started")

        try:
            # Check if auto-run is enabled
            auto_run_enabled = self._check_auto_run_enabled(context)
            if not auto_run_enabled:
                result.status = PipelineStatus.SUCCESS
                result.message = "Auto-run disabled, keep-alive service not needed"
                self.logger.info("ℹ️ Auto-run disabled, keep-alive service not needed")
                return result

            # Get agent configuration
            agent_config = context.get("agent_config", {})
            agent_id = context.get("agent_id", "unknown-agent")

            # Register atexit handler
            import atexit
            import signal
            import threading
            import time

            self.logger.info(f"🚀 Starting keep-alive service for agent '{agent_id}'")

            # Configure keep-alive settings from environment or agent config
            keep_alive_interval = self._get_keep_alive_interval(agent_config)

            # Create keep-alive state
            keep_alive_state = {
                "running": True,
                "agent_id": agent_id,
                "interval": keep_alive_interval,
                "heartbeat_count": 0,
            }

            def keep_alive_loop():
                """Keep-alive loop that runs to prevent script exit."""
                self.logger.info(
                    f"💓 Starting keep-alive service for agent '{agent_id}' "
                    f"with {keep_alive_interval}s interval"
                )
                self.logger.info("🛑 Press Ctrl+C to stop the service")

                # Set up signal handlers for graceful shutdown
                def signal_handler(signum, frame):
                    self.logger.info(
                        f"🔴 Received shutdown signal {signum} for agent '{agent_id}'"
                    )
                    keep_alive_state["running"] = False

                try:
                    signal.signal(signal.SIGINT, signal_handler)
                    signal.signal(signal.SIGTERM, signal_handler)
                except ValueError:
                    # Not in main thread - can't register signal handlers
                    self.logger.debug(
                        "Cannot register signal handlers from background thread"
                    )

                try:
                    while keep_alive_state["running"]:
                        time.sleep(keep_alive_interval)
                        keep_alive_state["heartbeat_count"] += 1

                        # Log periodic status
                        if (
                            keep_alive_state["heartbeat_count"] % 10 == 0
                        ):  # Every 10 intervals
                            elapsed_time = (
                                keep_alive_state["heartbeat_count"]
                                * keep_alive_interval
                            )
                            self.logger.info(
                                f"💓 Keep-alive heartbeat #{keep_alive_state['heartbeat_count']} "
                                f"for agent '{agent_id}' - running for {elapsed_time} seconds"
                            )

                except KeyboardInterrupt:
                    self.logger.info(
                        f"🔴 Received KeyboardInterrupt for agent '{agent_id}'"
                    )
                except Exception as e:
                    self.logger.error(
                        f"💥 Keep-alive loop error for agent '{agent_id}': {e}"
                    )
                finally:
                    self.logger.info(
                        f"🛑 Keep-alive service for agent '{agent_id}' shutting down"
                    )
                    keep_alive_state["running"] = False

            # Schedule the keep-alive loop as an asyncio task in the current event loop
            # This prevents the main event loop from ending
            try:
                import asyncio

                loop = asyncio.get_running_loop()

                async def async_keep_alive_loop():
                    """Async version of keep-alive loop that runs in main event loop."""
                    self.logger.info(
                        f"💓 Starting async keep-alive service for agent '{agent_id}' "
                        f"with {keep_alive_interval}s interval"
                    )
                    self.logger.info("🛑 Press Ctrl+C to stop the service")

                    try:
                        while keep_alive_state["running"]:
                            await asyncio.sleep(keep_alive_interval)
                            keep_alive_state["heartbeat_count"] += 1

                            # Log periodic status
                            if (
                                keep_alive_state["heartbeat_count"] % 10 == 0
                            ):  # Every 10 intervals
                                elapsed_time = (
                                    keep_alive_state["heartbeat_count"]
                                    * keep_alive_interval
                                )
                                self.logger.info(
                                    f"💓 Keep-alive heartbeat #{keep_alive_state['heartbeat_count']} "
                                    f"for agent '{agent_id}' - running for {elapsed_time} seconds"
                                )
                    except asyncio.CancelledError:
                        self.logger.info(
                            f"🔴 Keep-alive service cancelled for agent '{agent_id}'"
                        )
                        raise
                    except Exception as e:
                        self.logger.error(
                            f"💥 Keep-alive loop error for agent '{agent_id}': {e}"
                        )
                    finally:
                        self.logger.info(
                            f"🛑 Keep-alive service for agent '{agent_id}' shutting down"
                        )
                        keep_alive_state["running"] = False

                # Create the keep-alive task
                keep_alive_task = loop.create_task(async_keep_alive_loop())

                # Store keep-alive state in context for monitoring
                result.add_context("keep_alive_registered", True)
                result.add_context("keep_alive_interval", keep_alive_interval)
                result.add_context("keep_alive_state", keep_alive_state)
                result.add_context("keep_alive_task", keep_alive_task)

                self.logger.info(
                    f"✅ Async keep-alive service started for agent '{agent_id}' "
                    f"with {keep_alive_interval}s interval"
                )

            except RuntimeError:
                # No event loop running - fall back to thread approach
                self.logger.debug(
                    "No event loop running, falling back to thread approach"
                )
                keep_alive_thread = threading.Thread(
                    target=keep_alive_loop, daemon=False
                )
                keep_alive_thread.start()

                result.add_context("keep_alive_registered", True)
                result.add_context("keep_alive_interval", keep_alive_interval)
                result.add_context("keep_alive_state", keep_alive_state)
                result.add_context("keep_alive_thread", keep_alive_thread)

                self.logger.info(
                    f"✅ Thread-based keep-alive service started for agent '{agent_id}' "
                    f"with {keep_alive_interval}s interval"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Keep-alive service startup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Keep-alive service startup failed: {e}")

        return result

    def _check_auto_run_enabled(self, context: dict[str, Any]) -> bool:
        """Check if auto-run is enabled from context or environment."""
        # Check environment variable first (takes precedence)
        env_auto_run = os.environ.get("MCP_MESH_AUTO_RUN", "").lower()
        if env_auto_run in ("true", "1", "yes"):
            self.logger.debug(
                "🌐 Auto-run enabled via MCP_MESH_AUTO_RUN environment variable"
            )
            return True
        elif env_auto_run in ("false", "0", "no"):
            self.logger.debug(
                "🌐 Auto-run disabled via MCP_MESH_AUTO_RUN environment variable"
            )
            return False

        # Check agent configuration from context
        agent_config = context.get("agent_config", {})
        if agent_config.get("auto_run", False):
            self.logger.debug("🎯 Auto-run enabled via agent configuration")
            return True

        # Check mesh agents metadata
        mesh_agents = context.get("mesh_agents", {})
        for func_name, decorated_func in mesh_agents.items():
            metadata = getattr(decorated_func, "metadata", {})
            if metadata.get("auto_run", False):
                self.logger.debug(
                    f"🎯 Auto-run enabled via @mesh.agent(auto_run=True) on {func_name}"
                )
                return True

        return False

    def _get_keep_alive_interval(self, agent_config: dict[str, Any]) -> int:
        """Get keep-alive interval from environment or agent config."""
        # Check environment variable first
        env_interval = os.environ.get("MCP_MESH_AUTO_RUN_INTERVAL")
        if env_interval:
            try:
                interval = int(env_interval)
                self.logger.debug(
                    f"🌐 Keep-alive interval from environment: {interval}s"
                )
                return interval
            except ValueError:
                self.logger.warning(
                    f"Invalid MCP_MESH_AUTO_RUN_INTERVAL: {env_interval}, using default"
                )

        # Check agent configuration
        interval = agent_config.get("auto_run_interval", 10)  # Default 10 seconds
        self.logger.debug(f"🎯 Keep-alive interval from config: {interval}s")
        return interval
