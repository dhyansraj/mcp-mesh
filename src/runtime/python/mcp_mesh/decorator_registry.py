"""
DecoratorRegistry - Central storage for all MCP Mesh decorator metadata.

This is NOT the mesh registry service! This is just local storage for decorator
metadata that gets processed later by DecoratorProcessor in mcp_mesh_runtime.

The DecoratorRegistry stores metadata from decorators like @mesh_agent without
making any network calls or requiring any runtime infrastructure.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


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

    # Registry for new decorator types (extensibility)
    _custom_decorators: dict[str, dict[str, DecoratedFunction]] = {}

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
            cls._mesh_tools[func_name].function = new_func

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
                    "http_host": metadata.get("http_host", "0.0.0.0"),
                    "http_port": metadata.get("http_port", 0),
                }

                # Build endpoint from HTTP config if enabled
                if metadata.get("enable_http"):
                    registry_metadata["endpoint"] = (
                        f"http://{metadata.get('http_host', '0.0.0.0')}:{metadata.get('http_port', 8080)}"
                    )

                return registry_metadata

        return {}


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
