"""
DecoratorRegistry - Central storage for all MCP Mesh decorator metadata.

This is NOT the mesh registry service! This is just local storage for decorator
metadata that gets processed later by DecoratorProcessor in mcp_mesh_runtime.

The DecoratorRegistry stores metadata from decorators like @mesh_agent without
making any network calls or requiring any runtime infrastructure.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class DecoratedFunction:
    """Metadata for a function decorated with an MCP Mesh decorator."""

    decorator_type: str  # "mesh_agent", "mesh_tool", etc.
    function: Callable
    metadata: dict[str, Any]
    registered_at: datetime

    def __post_init__(self):
        """Add function name to metadata for convenience."""
        if "function_name" not in self.metadata:
            self.metadata["function_name"] = self.function.__name__


@dataclass
class LLMAgentMetadata:
    """Metadata for a function decorated with @mesh.llm."""

    function: Callable
    config: dict[str, Any]  # LLM configuration (provider, model, filter, etc.)
    output_type: type | None  # Pydantic model type from return annotation
    param_name: str  # Name of MeshLlmAgent parameter
    function_id: str  # Unique function ID for registry
    registered_at: datetime


class DecoratorRegistry:
    """
    Central registry for ALL MCP Mesh decorators.

    This class provides local storage for decorator metadata without requiring
    any network infrastructure. It's designed to be extensible for future
    decorator types.

    Example decorator types:
    - mesh_agent: Agent registration and capability declaration
    - mesh_tool: Enhanced tool registration (future)
    - mesh_resource: Resource management (future)
    - mesh_workflow: Multi-agent workflows (future)
    """

    # Separate storage by decorator type for better organization
    _mesh_agents: dict[str, DecoratedFunction] = {}
    _mesh_tools: dict[str, DecoratedFunction] = {}  # Future use
    _mesh_resources: dict[str, DecoratedFunction] = {}  # Future use
    _mesh_workflows: dict[str, DecoratedFunction] = {}  # Future use
    _mesh_llm_agents: dict[str, "LLMAgentMetadata"] = {}  # LLM agents with agentic loop

    # Registry for new decorator types (extensibility)
    _custom_decorators: dict[str, dict[str, DecoratedFunction]] = {}

    # Immediate uvicorn server storage (for preventing shutdown state)
    _immediate_uvicorn_server: dict[str, Any] | None = None

    # FastMCP lifespan storage (for proper integration with FastAPI)
    _fastmcp_lifespan: Any | None = None

    # FastMCP HTTP app storage (the same app instance whose lifespan was extracted)
    _fastmcp_http_app: Any | None = None

    # FastMCP server info storage (for schema extraction during heartbeat)
    _fastmcp_server_info: dict[str, Any] | None = None

    # Route-to-wrapper mapping for @mesh.route dependency injection
    # Key: "METHOD:path" (e.g., "GET:/api/v1/benchmark-services")
    # Value: {"wrapper": Callable, "dependencies": list[str]}
    _route_wrapper_registry: dict[str, dict[str, Any]] = {}

    @classmethod
    def register_route_wrapper(
        cls, method: str, path: str, wrapper: Callable, dependencies: list[str]
    ) -> None:
        """
        Register a route's wrapper function for dependency injection.

        Args:
            method: HTTP method (e.g., "GET", "POST")
            path: Route path (e.g., "/api/v1/benchmark-services")
            wrapper: The injection wrapper function
            dependencies: List of dependency capability names
        """
        route_id = f"{method}:{path}"
        cls._route_wrapper_registry[route_id] = {
            "wrapper": wrapper,
            "dependencies": dependencies,
            "method": method,
            "path": path,
        }
        logger.debug(
            f"📝 Registered route wrapper: {route_id} with {len(dependencies)} dependencies"
        )

    @classmethod
    def get_route_wrapper(cls, route_id: str) -> dict[str, Any] | None:
        """Get route wrapper info by route ID (METHOD:path)."""
        return cls._route_wrapper_registry.get(route_id)

    @classmethod
    def get_all_route_wrappers(cls) -> dict[str, dict[str, Any]]:
        """Get all registered route wrappers."""
        return cls._route_wrapper_registry.copy()

    @classmethod
    def register_mesh_agent(cls, func: Callable, metadata: dict[str, Any]) -> None:
        """
        Register a @mesh_agent decorated function.

        Args:
            func: The decorated function
            metadata: Decorator metadata (capabilities, dependencies, etc.)
        """
        decorated_func = DecoratedFunction(
            decorator_type="mesh_agent",
            function=func,
            metadata=metadata.copy(),
            registered_at=datetime.now(),
        )

        cls._mesh_agents[func.__name__] = decorated_func

    @classmethod
    def register_mesh_tool(cls, func: Callable, metadata: dict[str, Any]) -> None:
        """Register a @mesh_tool decorated function (future use)."""
        decorated_func = DecoratedFunction(
            decorator_type="mesh_tool",
            function=func,
            metadata=metadata.copy(),
            registered_at=datetime.now(),
        )

        cls._mesh_tools[func.__name__] = decorated_func

    @classmethod
    def update_mesh_tool_function(cls, func_name: str, new_func: Callable) -> None:
        """Update the function reference for a registered mesh tool."""
        if func_name in cls._mesh_tools:
            old_func = cls._mesh_tools[func_name].function
            cls._mesh_tools[func_name].function = new_func
            logger.debug(
                f"🔄 DecoratorRegistry: Updated '{func_name}' from {hex(id(old_func))} to {hex(id(new_func))}"
            )
        else:
            logger.debug(
                f"⚠️ DecoratorRegistry: Function '{func_name}' not found for update"
            )

    @classmethod
    def register_mesh_resource(cls, func: Callable, metadata: dict[str, Any]) -> None:
        """Register a @mesh_resource decorated function (future use)."""
        decorated_func = DecoratedFunction(
            decorator_type="mesh_resource",
            function=func,
            metadata=metadata.copy(),
            registered_at=datetime.now(),
        )

        cls._mesh_resources[func.__name__] = decorated_func

    @classmethod
    def register_mesh_workflow(cls, func: Callable, metadata: dict[str, Any]) -> None:
        """Register a @mesh_workflow decorated function (future use)."""
        decorated_func = DecoratedFunction(
            decorator_type="mesh_workflow",
            function=func,
            metadata=metadata.copy(),
            registered_at=datetime.now(),
        )

        cls._mesh_workflows[func.__name__] = decorated_func

    @classmethod
    def register_mesh_llm(
        cls,
        func: Callable,
        config: dict[str, Any],
        output_type: type | None,
        param_name: str,
        function_id: str,
    ) -> None:
        """
        Register a @mesh.llm decorated function.

        Args:
            func: The decorated function
            config: LLM configuration (provider, model, filter, etc.)
            output_type: Pydantic model type from return annotation
            param_name: Name of MeshLlmAgent parameter
            function_id: Unique function ID for registry
        """
        llm_metadata = LLMAgentMetadata(
            function=func,
            config=config.copy(),
            output_type=output_type,
            param_name=param_name,
            function_id=function_id,
            registered_at=datetime.now(),
        )

        cls._mesh_llm_agents[function_id] = llm_metadata
        logger.info(
            f"🤖 Registered LLM agent: {func.__name__} (function_id={function_id}, param={param_name}, filter={config.get('filter')}, provider={config.get('provider')})"
        )

    @classmethod
    def update_mesh_llm_function(cls, function_id: str, new_func: Callable) -> None:
        """Update the function reference for a registered LLM agent (used for wrapper injection)."""
        if function_id in cls._mesh_llm_agents:
            old_func = cls._mesh_llm_agents[function_id].function
            cls._mesh_llm_agents[function_id].function = new_func
            logger.info(
                f"🔄 DecoratorRegistry: Updated LLM function '{function_id}' from {hex(id(old_func))} to {hex(id(new_func))}"
            )
        else:
            logger.warning(
                f"⚠️ DecoratorRegistry: LLM function '{function_id}' not found for update"
            )

    @classmethod
    def register_custom_decorator(
        cls, decorator_type: str, func: Callable, metadata: dict[str, Any]
    ) -> None:
        """
        Register a custom decorator type (extensibility).

        Args:
            decorator_type: Name of the custom decorator type
            func: The decorated function
            metadata: Decorator metadata
        """
        if decorator_type not in cls._custom_decorators:
            cls._custom_decorators[decorator_type] = {}

        decorated_func = DecoratedFunction(
            decorator_type=decorator_type,
            function=func,
            metadata=metadata.copy(),
            registered_at=datetime.now(),
        )

        cls._custom_decorators[decorator_type][func.__name__] = decorated_func

    @classmethod
    def get_mesh_agents(cls) -> dict[str, DecoratedFunction]:
        """Get all @mesh_agent decorated functions."""
        return cls._mesh_agents.copy()

    @classmethod
    def get_mesh_tools(cls) -> dict[str, DecoratedFunction]:
        """Get all @mesh_tool decorated functions."""
        return cls._mesh_tools.copy()

    @classmethod
    def get_mesh_resources(cls) -> dict[str, DecoratedFunction]:
        """Get all @mesh_resource decorated functions."""
        return cls._mesh_resources.copy()

    @classmethod
    def get_mesh_workflows(cls) -> dict[str, DecoratedFunction]:
        """Get all @mesh_workflow decorated functions."""
        return cls._mesh_workflows.copy()

    @classmethod
    def get_mesh_llm_agents(cls) -> dict[str, LLMAgentMetadata]:
        """Get all @mesh.llm decorated functions."""
        return cls._mesh_llm_agents.copy()

    @classmethod
    def get_all_by_type(cls, decorator_type: str) -> dict[str, DecoratedFunction]:
        """
        Get all decorated functions of a specific type.

        Args:
            decorator_type: Type of decorator ("mesh_agent", "mesh_tool", etc.)

        Returns:
            Dictionary of function_name -> DecoratedFunction
        """
        storage_map = {
            "mesh_agent": cls._mesh_agents,
            "mesh_tool": cls._mesh_tools,
            "mesh_resource": cls._mesh_resources,
            "mesh_workflow": cls._mesh_workflows,
        }

        if decorator_type in storage_map:
            return storage_map[decorator_type].copy()
        elif decorator_type in cls._custom_decorators:
            return cls._custom_decorators[decorator_type].copy()
        else:
            return {}

    @classmethod
    def get_all_decorators(cls) -> dict[str, DecoratedFunction]:
        """
        Get ALL decorated functions across all decorator types.

        Returns:
            Dictionary of function_name -> DecoratedFunction
        """
        all_decorators = {}

        # Add built-in decorator types
        all_decorators.update(cls._mesh_agents)
        all_decorators.update(cls._mesh_tools)
        all_decorators.update(cls._mesh_resources)
        all_decorators.update(cls._mesh_workflows)

        # Add custom decorator types
        for _custom_type, custom_functions in cls._custom_decorators.items():
            all_decorators.update(custom_functions)

        return all_decorators

    @classmethod
    def get_decorator_types(cls) -> list[str]:
        """Get list of all registered decorator types."""
        types = ["mesh_agent", "mesh_tool", "mesh_resource", "mesh_workflow"]
        types.extend(cls._custom_decorators.keys())
        return types

    @classmethod
    def get_function_decorators(cls, func_name: str) -> list[DecoratedFunction]:
        """
        Get all decorators applied to a specific function.

        This is useful for functions that have multiple decorators applied.

        Args:
            func_name: Name of the function to search for

        Returns:
            List of DecoratedFunction objects for the given function
        """
        all_decorators = cls.get_all_decorators()
        return [
            decorated_func
            for decorated_func in all_decorators.values()
            if decorated_func.function.__name__ == func_name
        ]

    @classmethod
    def clear_all(cls) -> None:
        """Clear all registered decorators (useful for testing)."""
        cls._mesh_agents.clear()
        cls._mesh_tools.clear()
        cls._mesh_resources.clear()
        cls._mesh_workflows.clear()
        cls._mesh_llm_agents.clear()
        cls._custom_decorators.clear()

        # Also clear the shared agent ID from mesh.decorators
        try:
            from mesh.decorators import _clear_shared_agent_id

            _clear_shared_agent_id()
        except ImportError:
            # Graceful fallback if mesh.decorators not available
            pass

    @classmethod
    def get_stats(cls) -> dict[str, int]:
        """Get statistics about registered decorators."""
        stats = {
            "mesh_agent": len(cls._mesh_agents),
            "mesh_tool": len(cls._mesh_tools),
            "mesh_resource": len(cls._mesh_resources),
            "mesh_workflow": len(cls._mesh_workflows),
        }

        for custom_type, custom_functions in cls._custom_decorators.items():
            stats[custom_type] = len(custom_functions)

        stats["total"] = sum(stats.values())
        return stats

    # Cache for resolved agent configuration to avoid repeated work
    _cached_agent_config: dict[str, Any] | None = None

    @classmethod
    def update_agent_config(cls, updates: dict[str, Any]) -> None:
        """
        Update the cached agent configuration with new values.

        This is useful for API services that generate their agent ID
        during pipeline execution and need to store it for telemetry.

        Args:
            updates: Dictionary of config values to update
        """
        if cls._cached_agent_config is None:
            # Initialize with current resolved config if not cached yet
            cls._cached_agent_config = cls.get_resolved_agent_config().copy()

        # Update with new values
        cls._cached_agent_config.update(updates)

        logger.debug(f"🔧 Updated cached agent configuration with: {updates}")

    @classmethod
    def get_resolved_agent_config(cls) -> dict[str, Any]:
        """
        Get resolved agent configuration from stored decorator metadata.

        Returns the configuration that was already resolved by @mesh.agent decorator,
        including the generated agent_id. No re-resolution is performed.

        Returns:
            dict: Pre-resolved configuration with consistent agent_id
        """
        # Step 1: Check if cached configuration already has agent_id (from API pipeline)
        if cls._cached_agent_config is not None and cls._cached_agent_config.get(
            "agent_id"
        ):
            logger.debug(
                f"🔧 Using cached agent configuration: agent_id='{cls._cached_agent_config.get('agent_id')}'"
            )
            return cls._cached_agent_config

        # Step 2: If we have explicit @mesh.agent configuration, use it
        if cls._mesh_agents:
            for agent_name, decorated_func in cls._mesh_agents.items():
                # Return the already-resolved configuration from decorator
                resolved_config = decorated_func.metadata.copy()

                # Cache the configuration for future calls
                cls._cached_agent_config = resolved_config

                logger.debug(
                    f"🔧 Retrieved resolved agent configuration: agent_id='{resolved_config.get('agent_id')}'"
                )
                return resolved_config

        # Step 3: Fallback to synthetic defaults when no @mesh.agent decorator exists
        # This happens when only @mesh.tool decorators are used and no cached agent_id
        from ..shared.config_resolver import ValidationRule, get_config_value
        from ..shared.defaults import MeshDefaults

        # Check if we're in an API context (have mesh_route decorators)
        mesh_routes = cls.get_all_by_type("mesh_route")
        is_api_context = len(mesh_routes) > 0

        if is_api_context:
            # Use API service ID generation logic for consistency
            agent_id = cls._generate_api_service_id_fallback()
        else:
            # Use standard MCP agent ID generation
            from mesh.decorators import _get_or_create_agent_id

            agent_id = _get_or_create_agent_id()

        fallback_config = {
            "name": None,
            "version": get_config_value(
                "MCP_MESH_VERSION",
                default=MeshDefaults.VERSION,
                rule=ValidationRule.STRING_RULE,
            ),
            "description": None,
            "http_host": get_config_value(
                "MCP_MESH_HTTP_HOST",
                default=MeshDefaults.HTTP_HOST,
                rule=ValidationRule.STRING_RULE,
            ),
            "http_port": get_config_value(
                "MCP_MESH_HTTP_PORT",
                default=MeshDefaults.HTTP_PORT,
                rule=ValidationRule.PORT_RULE,
            ),
            "enable_http": get_config_value(
                "MCP_MESH_HTTP_ENABLED",
                default=MeshDefaults.HTTP_ENABLED,
                rule=ValidationRule.TRUTHY_RULE,
            ),
            "namespace": get_config_value(
                "MCP_MESH_NAMESPACE",
                default=MeshDefaults.NAMESPACE,
                rule=ValidationRule.STRING_RULE,
            ),
            "health_interval": get_config_value(
                "MCP_MESH_HEALTH_INTERVAL",
                default=MeshDefaults.HEALTH_INTERVAL,
                rule=ValidationRule.NONZERO_RULE,
            ),
            "auto_run": get_config_value(
                "MCP_MESH_AUTO_RUN",
                default=MeshDefaults.AUTO_RUN,
                rule=ValidationRule.TRUTHY_RULE,
            ),
            "auto_run_interval": get_config_value(
                "MCP_MESH_AUTO_RUN_INTERVAL",
                default=MeshDefaults.AUTO_RUN_INTERVAL,
                rule=ValidationRule.NONZERO_RULE,
            ),
            "agent_id": agent_id,
        }

        # Cache the fallback configuration
        cls._cached_agent_config = fallback_config

        logger.debug(
            f"🔧 Generated synthetic agent configuration: agent_id='{agent_id}'"
        )
        return fallback_config

    @classmethod
    def _generate_api_service_id_fallback(cls) -> str:
        """
        Generate API service ID as fallback using same priority logic as API pipeline.

        Priority order:
        1. MCP_MESH_API_NAME environment variable
        2. MCP_MESH_AGENT_NAME environment variable (fallback)
        3. Default to "api-{uuid8}"

        Returns:
            Generated service ID with UUID suffix matching API service format
        """
        import uuid

        from ..shared.config_resolver import ValidationRule, get_config_value

        # Check for API-specific environment variable first (same as API pipeline)
        api_name = get_config_value(
            "MCP_MESH_API_NAME",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )

        # Fallback to general agent name env var
        if not api_name:
            api_name = get_config_value(
                "MCP_MESH_AGENT_NAME",
                default=None,
                rule=ValidationRule.STRING_RULE,
            )

        # Clean the service name if provided
        if api_name:
            cleaned_name = api_name.lower().replace(" ", "-").replace("_", "-")
            cleaned_name = "-".join(part for part in cleaned_name.split("-") if part)
        else:
            cleaned_name = ""

        # Generate UUID suffix
        uuid_suffix = str(uuid.uuid4())[:8]

        # Apply same naming logic as API pipeline
        if not cleaned_name:
            # No name provided: default to "api-{uuid8}"
            service_id = f"api-{uuid_suffix}"
        elif "api" in cleaned_name.lower():
            # Name already contains "api": use "{name}-{uuid8}"
            service_id = f"{cleaned_name}-{uuid_suffix}"
        else:
            # Name doesn't contain "api": use "{name}-api-{uuid8}"
            service_id = f"{cleaned_name}-api-{uuid_suffix}"

        logger.debug(
            f"Generated fallback API service ID: '{service_id}' from env name: '{api_name}'"
        )
        return service_id

    @classmethod
    def get_all_agents(cls) -> list[tuple[Any, dict[str, Any]]]:
        """
        Get all registered agents in a format compatible with tests.

        Returns:
            List of (agent_object, metadata) tuples
        """
        agents = []
        for decorated_func in cls._mesh_agents.values():
            agents.append((decorated_func.function, decorated_func.metadata))
        return agents

    @classmethod
    def build_registry_metadata(cls, agent_class: Any) -> dict[str, Any]:
        """
        Build registry metadata for a specific agent class.

        This method formats the decorator metadata for registry registration.

        Args:
            agent_class: The decorated agent class

        Returns:
            Metadata dictionary formatted for registry registration
        """
        # Find the agent in our registry
        for decorated_func in cls._mesh_agents.values():
            if decorated_func.function == agent_class:
                metadata = decorated_func.metadata.copy()

                # Format for registry
                registry_metadata = {
                    "name": metadata.get("agent_name"),
                    "tools": metadata.get("tools", []),
                    "enable_http": metadata.get("enable_http"),
                    "http_host": metadata.get("http_host", "localhost"),
                    "http_port": metadata.get("http_port", 0),
                }

                # Build endpoint from HTTP config if enabled
                if metadata.get("enable_http"):
                    registry_metadata["endpoint"] = (
                        f"http://{metadata.get('http_host', 'localhost')}:{metadata.get('http_port', 8080)}"
                    )

                return registry_metadata

        return {}

    @classmethod
    def store_immediate_uvicorn_server(cls, server_info: dict[str, Any]) -> None:
        """
        Store reference to immediate uvicorn server started in decorator.

        Args:
            server_info: Dictionary containing server information:
                - 'app': FastAPI app instance
                - 'host': Server host
                - 'port': Server port
                - 'thread': Thread object
                - Any other relevant server metadata
        """
        cls._immediate_uvicorn_server = server_info
        logger.debug(
            f"🔄 REGISTRY: Stored immediate uvicorn server reference: {server_info.get('host')}:{server_info.get('port')}"
        )

    @classmethod
    def get_immediate_uvicorn_server(cls) -> dict[str, Any] | None:
        """
        Get stored immediate uvicorn server reference.

        Returns:
            Server info dict if available, None otherwise
        """
        return cls._immediate_uvicorn_server

    @classmethod
    def clear_immediate_uvicorn_server(cls) -> None:
        """Clear stored immediate uvicorn server reference."""
        cls._immediate_uvicorn_server = None
        logger.debug("🔄 REGISTRY: Cleared immediate uvicorn server reference")

    # Health check result storage
    _health_check_result: dict | None = None

    @classmethod
    def store_health_check_result(cls, result: dict) -> None:
        """Store health check result for /health endpoint."""
        cls._health_check_result = result
        logger.debug(
            f"💾 REGISTRY: Stored health check result: {result.get('status', 'unknown')}"
        )

    @classmethod
    def get_health_check_result(cls) -> dict | None:
        """Get stored health check result."""
        return cls._health_check_result

    @classmethod
    def clear_health_check_result(cls) -> None:
        """Clear stored health check result."""
        cls._health_check_result = None
        logger.debug("🗑️ REGISTRY: Cleared health check result")

    @classmethod
    def store_fastmcp_lifespan(cls, lifespan: Any) -> None:
        """
        Store FastMCP lifespan for integration with FastAPI.

        Args:
            lifespan: FastMCP lifespan function
        """
        cls._fastmcp_lifespan = lifespan
        logger.debug("🔄 REGISTRY: Stored FastMCP lifespan for FastAPI integration")

    @classmethod
    def get_fastmcp_lifespan(cls) -> Any | None:
        """
        Get stored FastMCP lifespan.

        Returns:
            FastMCP lifespan if available, None otherwise
        """
        return cls._fastmcp_lifespan

    @classmethod
    def clear_fastmcp_lifespan(cls) -> None:
        """Clear stored FastMCP lifespan reference."""
        cls._fastmcp_lifespan = None
        logger.debug("🔄 REGISTRY: Cleared FastMCP lifespan reference")

    @classmethod
    def store_fastmcp_http_app(cls, http_app: Any) -> None:
        """
        Store FastMCP HTTP app (the same instance whose lifespan was extracted).

        Args:
            http_app: FastMCP HTTP app instance
        """
        cls._fastmcp_http_app = http_app
        logger.debug("🔄 REGISTRY: Stored FastMCP HTTP app for mounting")

    @classmethod
    def get_fastmcp_http_app(cls) -> Any | None:
        """
        Get stored FastMCP HTTP app.

        Returns:
            FastMCP HTTP app if available, None otherwise
        """
        return cls._fastmcp_http_app

    @classmethod
    def clear_fastmcp_http_app(cls) -> None:
        """Clear stored FastMCP HTTP app reference."""
        cls._fastmcp_http_app = None
        logger.debug("🔄 REGISTRY: Cleared FastMCP HTTP app reference")

    @classmethod
    def store_fastmcp_server_info(cls, server_info: dict[str, Any]) -> None:
        """
        Store FastMCP server info for schema extraction during heartbeat.

        Args:
            server_info: Dictionary of server_name -> server metadata (including tools)
        """
        cls._fastmcp_server_info = server_info
        logger.debug(
            f"🔄 REGISTRY: Stored FastMCP server info for {len(server_info)} servers"
        )

    @classmethod
    def get_fastmcp_server_info(cls) -> dict[str, Any] | None:
        """
        Get stored FastMCP server info.

        Returns:
            FastMCP server info if available, None otherwise
        """
        return cls._fastmcp_server_info

    @classmethod
    def clear_fastmcp_server_info(cls) -> None:
        """Clear stored FastMCP server info reference."""
        cls._fastmcp_server_info = None
        logger.debug("🔄 REGISTRY: Cleared FastMCP server info reference")


# Convenience functions for external access
def get_all_mesh_agents() -> dict[str, DecoratedFunction]:
    """Convenience function to get all mesh agents."""
    return DecoratorRegistry.get_mesh_agents()


def get_decorator_stats() -> dict[str, int]:
    """Convenience function to get decorator statistics."""
    return DecoratorRegistry.get_stats()


def clear_decorator_registry() -> None:
    """Convenience function to clear the registry (testing only)."""
    DecoratorRegistry.clear_all()
