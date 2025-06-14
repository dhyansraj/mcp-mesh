"""
Dynamic dependency injection system for MCP Mesh.

Handles both initial injection and runtime updates when topology changes.
"""

import asyncio
import functools
import inspect
import logging
import weakref
from collections.abc import Callable
from typing import Any

from .signature_analyzer import get_mesh_agent_positions

logger = logging.getLogger(__name__)


class DependencyInjector:
    """
    Manages dynamic dependency injection for mesh agents.

    This class:
    1. Maintains a registry of available dependencies
    2. Tracks which functions depend on which services
    3. Updates function bindings when topology changes
    4. Handles graceful degradation when dependencies unavailable
    """

    def __init__(self):
        self._dependencies: dict[str, Any] = {}
        self._function_registry: weakref.WeakValueDictionary = (
            weakref.WeakValueDictionary()
        )
        self._dependency_mapping: dict[str, set[str]] = (
            {}
        )  # dep_name -> set of function_ids
        self._lock = asyncio.Lock()

    async def register_dependency(self, name: str, instance: Any) -> None:
        """Register a new dependency or update existing one."""
        async with self._lock:
            logger.info(f"📦 Registering dependency: {name}")
            self._dependencies[name] = instance

            # Notify all functions that depend on this
            if name in self._dependency_mapping:
                for func_id in self._dependency_mapping[name]:
                    if func_id in self._function_registry:
                        func_wrapper = self._function_registry[func_id]
                        if hasattr(func_wrapper, "_update_dependency"):
                            func_wrapper._update_dependency(name, instance)

    async def unregister_dependency(self, name: str) -> None:
        """Remove a dependency (e.g., service went down)."""
        async with self._lock:
            logger.info(f"📤 Unregistering dependency: {name}")
            if name in self._dependencies:
                del self._dependencies[name]

                # Notify all functions that depend on this
                if name in self._dependency_mapping:
                    for func_id in self._dependency_mapping[name]:
                        if func_id in self._function_registry:
                            func_wrapper = self._function_registry[func_id]
                            if hasattr(func_wrapper, "_update_dependency"):
                                func_wrapper._update_dependency(name, None)

    def get_dependency(self, name: str) -> Any | None:
        """Get current instance of a dependency."""
        return self._dependencies.get(name)

    def create_injection_wrapper(
        self, func: Callable, dependencies: list[str]
    ) -> Callable:
        """
        Create a wrapper that handles dynamic dependency injection using McpMeshAgent types.

        This wrapper:
        1. Analyzes function signature for McpMeshAgent parameters
        2. Injects dependencies positionally based on declaration order
        3. Can be updated when topology changes
        4. Handles missing dependencies gracefully
        """
        func_id = f"{func.__module__}.{func.__qualname__}"

        # Get positions of McpMeshAgent parameters
        mesh_positions = get_mesh_agent_positions(func)

        # Track which dependencies this function needs
        for dep in dependencies:
            if dep not in self._dependency_mapping:
                self._dependency_mapping[dep] = set()
            self._dependency_mapping[dep].add(func_id)

        # Store current dependency values (can be updated)
        injected_deps = {}

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Build the final args list by inserting dependencies at their positions
            # and adjusting user-provided args accordingly

            # Get function signature to determine total expected parameters

            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            param_count = len(params)

            # Initialize final args list
            final_args = []

            # Place user-provided args, skipping McpMeshAgent positions
            user_arg_index = 0
            for param_index in range(param_count):
                param = params[param_index]

                if param_index in mesh_positions:
                    # This position is for a dependency, inject it
                    dep_index = mesh_positions.index(param_index)
                    if dep_index < len(dependencies):
                        dep_name = dependencies[dep_index]

                        # Get the dependency to inject
                        if dep_name in injected_deps:
                            dependency = injected_deps[dep_name]
                        else:
                            dependency = self.get_dependency(dep_name)

                        final_args.append(dependency)
                    else:
                        final_args.append(None)
                else:
                    # This position is for a user-provided arg
                    if user_arg_index < len(args):
                        final_args.append(args[user_arg_index])
                        user_arg_index += 1
                    elif param.default != inspect.Parameter.empty:
                        # Parameter has a default value, stop adding positional args
                        # Let the function use its default values
                        break
                    else:
                        # Required parameter but no value provided
                        final_args.append(None)

            return func(*final_args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Build the final args list by inserting dependencies at their positions
            # and adjusting user-provided args accordingly

            # Get function signature to determine total expected parameters

            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            param_count = len(params)

            # Initialize final args list
            final_args = []

            # Place user-provided args, skipping McpMeshAgent positions
            user_arg_index = 0
            for param_index in range(param_count):
                param = params[param_index]

                if param_index in mesh_positions:
                    # This position is for a dependency, inject it
                    dep_index = mesh_positions.index(param_index)
                    if dep_index < len(dependencies):
                        dep_name = dependencies[dep_index]

                        # Get the dependency to inject
                        if dep_name in injected_deps:
                            dependency = injected_deps[dep_name]
                        else:
                            dependency = self.get_dependency(dep_name)

                        final_args.append(dependency)
                    else:
                        final_args.append(None)
                else:
                    # This position is for a user-provided arg
                    if user_arg_index < len(args):
                        final_args.append(args[user_arg_index])
                        user_arg_index += 1
                    elif param.default != inspect.Parameter.empty:
                        # Parameter has a default value, stop adding positional args
                        # Let the function use its default values
                        break
                    else:
                        # Required parameter but no value provided
                        final_args.append(None)

            return await func(*final_args, **kwargs)

        # Choose appropriate wrapper
        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

        # Add update method to wrapper
        def update_dependency(name: str, instance: Any | None) -> None:
            """Called when a dependency changes."""
            if instance is None:
                injected_deps.pop(name, None)
                logger.debug(f"Removed {name} from {func_id}")
            else:
                injected_deps[name] = instance
                logger.debug(f"Updated {name} for {func_id}")

        wrapper._update_dependency = update_dependency
        wrapper._injected_deps = injected_deps
        wrapper._original_func = func
        wrapper._dependencies = dependencies

        # Register this wrapper
        self._function_registry[func_id] = wrapper

        return wrapper


# Global injector instance
_global_injector = DependencyInjector()


def get_global_injector() -> DependencyInjector:
    """Get the global dependency injector instance."""
    return _global_injector
