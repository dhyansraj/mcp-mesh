"""
Dynamic dependency injection system for MCP Mesh.

Handles both initial injection and runtime updates when topology changes.
"""

import asyncio
import functools
import logging
import weakref
from collections.abc import Callable
from typing import Any

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
            logger.info(f"Registering dependency: {name}")
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
            logger.info(f"Unregistering dependency: {name}")
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
        1. Injects current dependencies at call time
        2. Can be updated when topology changes
        3. Handles missing dependencies gracefully
        """
        func_id = f"{func.__module__}.{func.__qualname__}"

        # Track which dependencies this function needs
        for dep in dependencies:
            if dep not in self._dependency_mapping:
                self._dependency_mapping[dep] = set()
            self._dependency_mapping[dep].add(func_id)

        # Store current dependency values (can be updated)
        injected_deps = {}

        @functools.wraps(func)
        def sync_wrapper(**kwargs):
            # Inject current dependencies
            for dep_name in dependencies:
                if dep_name not in kwargs or kwargs[dep_name] is None:
                    # Use stored value or get current value
                    if dep_name in injected_deps:
                        kwargs[dep_name] = injected_deps[dep_name]
                    else:
                        kwargs[dep_name] = self.get_dependency(dep_name)

            return func(**kwargs)

        @functools.wraps(func)
        async def async_wrapper(**kwargs):
            # Inject current dependencies
            for dep_name in dependencies:
                if dep_name not in kwargs or kwargs[dep_name] is None:
                    # Use stored value or get current value
                    if dep_name in injected_deps:
                        kwargs[dep_name] = injected_deps[dep_name]
                    else:
                        kwargs[dep_name] = self.get_dependency(dep_name)

            return await func(**kwargs)

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
