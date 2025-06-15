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


def analyze_injection_strategy(func: Callable, dependencies: list[str]) -> list[int]:
    """
    Analyze function signature and determine injection strategy.

    Rules:
    1. Single parameter: inject regardless of typing (with warning if not McpMeshAgent)
    2. Multiple parameters: only inject into McpMeshAgent typed parameters
    3. Log warnings for mismatches and edge cases

    Args:
        func: Function to analyze
        dependencies: List of dependency names to inject

    Returns:
        List of parameter positions to inject into
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    param_count = len(params)
    mesh_positions = get_mesh_agent_positions(func)
    func_name = f"{func.__module__}.{func.__qualname__}"

    # No parameters at all
    if param_count == 0:
        if dependencies:
            logger.warning(
                f"Function '{func_name}' has no parameters but {len(dependencies)} "
                f"dependencies declared. Skipping injection."
            )
        return []

    # Single parameter rule: inject regardless of typing
    if param_count == 1:
        if not mesh_positions:
            param_name = params[0].name
            logger.warning(
                f"Single parameter '{param_name}' in function '{func_name}' found, "
                f"injecting {dependencies[0] if dependencies else 'dependency'} proxy "
                f"(consider typing as McpMeshAgent for clarity)"
            )
        return [0]  # Inject into the single parameter

    # Multiple parameters rule: only inject into McpMeshAgent typed parameters
    if param_count > 1:
        if not mesh_positions:
            logger.warning(
                f"Function '{func_name}' has {param_count} parameters but none are "
                f"typed as McpMeshAgent. Skipping injection of {len(dependencies)} dependencies. "
                f"Consider typing dependency parameters as McpMeshAgent."
            )
            return []

        # Check for dependency/parameter count mismatches
        if len(dependencies) != len(mesh_positions):
            if len(dependencies) > len(mesh_positions):
                excess_deps = dependencies[len(mesh_positions) :]
                logger.warning(
                    f"Function '{func_name}' has {len(dependencies)} dependencies "
                    f"but only {len(mesh_positions)} McpMeshAgent parameters. "
                    f"Dependencies {excess_deps} will not be injected."
                )
            else:
                excess_params = [
                    params[pos].name for pos in mesh_positions[len(dependencies) :]
                ]
                logger.warning(
                    f"Function '{func_name}' has {len(mesh_positions)} McpMeshAgent parameters "
                    f"but only {len(dependencies)} dependencies declared. "
                    f"Parameters {excess_params} will remain None."
                )

        # Return positions we can actually inject into
        return mesh_positions[: len(dependencies)]

    return mesh_positions


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
        Create a wrapper that handles dynamic dependency injection.

        This wrapper:
        1. Analyzes function signature using smart injection strategy
        2. Injects dependencies positionally based on analysis
        3. Can be updated when topology changes
        4. Handles missing dependencies gracefully
        5. Logs warnings for configuration issues
        """
        func_id = f"{func.__module__}.{func.__qualname__}"

        # Use new smart injection strategy
        mesh_positions = analyze_injection_strategy(func, dependencies)

        # Track which dependencies this function needs
        for dep in dependencies:
            if dep not in self._dependency_mapping:
                self._dependency_mapping[dep] = set()
            self._dependency_mapping[dep].add(func_id)

        # Store current dependency values (can be updated)
        injected_deps = {}

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger.debug(
                f"sync_wrapper called for {func.__name__} with args={args}, kwargs={kwargs}"
            )

            # If no mesh positions to inject into, call function normally
            if not mesh_positions:
                logger.debug(f"No mesh positions for {func.__name__}, calling normally")
                return func(*args, **kwargs)

            # Get function signature
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            logger.debug(f"Function {func.__name__} parameters: {params}")
            logger.debug(f"Mesh positions to inject: {mesh_positions}")
            logger.debug(f"Dependencies to inject: {dependencies}")

            # Create a copy of kwargs to modify
            final_kwargs = kwargs.copy()

            # Inject dependencies into their designated parameter positions
            for dep_index, param_position in enumerate(mesh_positions):
                if dep_index < len(dependencies):
                    dep_name = dependencies[dep_index]
                    param_name = params[param_position]
                    logger.debug(
                        f"Processing dependency {dep_index}: {dep_name} -> {param_name} (position {param_position})"
                    )

                    # Only inject if the parameter wasn't explicitly provided OR if it's None
                    should_inject = (
                        param_name not in final_kwargs
                        or final_kwargs.get(param_name) is None
                    )

                    if should_inject:
                        # Get the dependency to inject
                        if dep_name in injected_deps:
                            dependency = injected_deps[dep_name]
                            logger.debug(
                                f"Using cached dependency {dep_name}: {dependency}"
                            )
                        else:
                            dependency = self.get_dependency(dep_name)
                            logger.debug(
                                f"Retrieved dependency {dep_name}: {dependency}"
                            )

                        # Check if this parameter position has a positional argument
                        if param_position < len(args):
                            # User provided positional arg, don't inject
                            logger.debug(
                                f"Skipping injection for {param_name} - positional arg provided"
                            )
                            continue
                        else:
                            # Inject as keyword argument (replace None or missing)
                            final_kwargs[param_name] = dependency
                            logger.debug(
                                f"Injected {dep_name} as {param_name}: {dependency}"
                            )
                    else:
                        logger.debug(
                            f"Skipping injection for {param_name} - already provided in kwargs with non-None value"
                        )

            logger.debug(
                f"Final call to {func.__name__} with args={args}, kwargs={final_kwargs}"
            )
            return func(*args, **final_kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # If no mesh positions to inject into, call function normally
            if not mesh_positions:
                return await func(*args, **kwargs)

            # Get function signature
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())

            # Create a copy of kwargs to modify
            final_kwargs = kwargs.copy()

            # Inject dependencies into their designated parameter positions
            for dep_index, param_position in enumerate(mesh_positions):
                if dep_index < len(dependencies):
                    dep_name = dependencies[dep_index]
                    param_name = params[param_position]

                    # Only inject if the parameter wasn't explicitly provided
                    if param_name not in final_kwargs:
                        # Get the dependency to inject
                        if dep_name in injected_deps:
                            dependency = injected_deps[dep_name]
                        else:
                            dependency = self.get_dependency(dep_name)

                        # Check if this parameter position has a positional argument
                        if param_position < len(args):
                            # User provided positional arg, don't inject
                            continue
                        else:
                            # Inject as keyword argument
                            final_kwargs[param_name] = dependency

            return await func(*args, **final_kwargs)

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
