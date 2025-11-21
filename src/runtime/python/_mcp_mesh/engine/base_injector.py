"""
Base injector class with shared wrapper creation logic.

Provides common functionality for DependencyInjector and MeshLlmAgentInjector.
"""

import functools
import inspect
import logging
import weakref
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class BaseInjector:
    """
    Base class for injection systems.

    Provides shared functionality for creating and managing function wrappers
    that support dynamic injection with two-phase updates.

    Two-Phase Injection Pattern:
    1. Phase 1 (decorator time): Create wrapper with initial state (None)
    2. Phase 2 (runtime): Update wrapper with actual instances via update method

    Subclasses must implement:
    - Wrapper logic (what to inject and how)
    - Update method signature
    """

    def __init__(self):
        """Initialize base injector with function registry."""
        self._function_registry: weakref.WeakValueDictionary = (
            weakref.WeakValueDictionary()
        )
        logger.debug(f"🔧 {self.__class__.__name__} initialized")

    def _register_wrapper(self, function_id: str, wrapper: Callable) -> None:
        """
        Register a wrapper in the function registry.

        Args:
            function_id: Unique function identifier
            wrapper: Wrapper function to register
        """
        self._function_registry[function_id] = wrapper
        logger.debug(f"🔧 Registered wrapper for {function_id} at {hex(id(wrapper))}")

    def _create_async_wrapper(
        self,
        func: Callable,
        function_id: str,
        injection_logic: Callable[[Callable, tuple, dict], tuple],
        metadata: dict[str, Any],
    ) -> Callable:
        """
        Create async wrapper with injection logic.

        Args:
            func: Original async function to wrap
            function_id: Unique function identifier
            injection_logic: Callable that takes (func, args, kwargs) and returns (args, kwargs)
                            This function should modify kwargs to inject dependencies
            metadata: Additional metadata to store on wrapper

        Returns:
            Async wrapper function
        """

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Apply injection logic to modify kwargs
            args, kwargs = injection_logic(func, args, kwargs)

            # Execute original function
            return await func(*args, **kwargs)

        # Store metadata on wrapper
        async_wrapper._mesh_original_func = func
        async_wrapper._mesh_function_id = function_id

        # Store additional metadata
        for key, value in metadata.items():
            setattr(async_wrapper, key, value)

        return async_wrapper

    def _create_sync_wrapper(
        self,
        func: Callable,
        function_id: str,
        injection_logic: Callable[[Callable, tuple, dict], tuple],
        metadata: dict[str, Any],
    ) -> Callable:
        """
        Create sync wrapper with injection logic.

        Args:
            func: Original sync function to wrap
            function_id: Unique function identifier
            injection_logic: Callable that takes (func, args, kwargs) and returns (args, kwargs)
                            This function should modify kwargs to inject dependencies
            metadata: Additional metadata to store on wrapper

        Returns:
            Sync wrapper function
        """

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Apply injection logic to modify kwargs
            args, kwargs = injection_logic(func, args, kwargs)

            # Execute original function
            return func(*args, **kwargs)

        # Store metadata on wrapper
        sync_wrapper._mesh_original_func = func
        sync_wrapper._mesh_function_id = function_id

        # Store additional metadata
        for key, value in metadata.items():
            setattr(sync_wrapper, key, value)

        return sync_wrapper

    def create_wrapper_with_injection(
        self,
        func: Callable,
        function_id: str,
        injection_logic: Callable[[Callable, tuple, dict], tuple],
        metadata: dict[str, Any],
        register: bool = True,
    ) -> Callable:
        """
        Create wrapper (async or sync) based on function type.

        This is the main entry point for creating wrappers. It automatically
        detects if the function is async or sync and creates the appropriate wrapper.

        Args:
            func: Function to wrap
            function_id: Unique function identifier
            injection_logic: Callable that takes (func, args, kwargs) and returns (args, kwargs)
            metadata: Additional metadata to store on wrapper
            register: Whether to register wrapper in function_registry (default: True)

        Returns:
            Wrapped function with injection capability
        """
        # Detect async vs sync
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            wrapper = self._create_async_wrapper(
                func, function_id, injection_logic, metadata
            )
            logger.debug(f"✅ Created async wrapper for {function_id}")
        else:
            wrapper = self._create_sync_wrapper(
                func, function_id, injection_logic, metadata
            )
            logger.debug(f"✅ Created sync wrapper for {function_id}")

        # Register wrapper if requested
        if register:
            self._register_wrapper(function_id, wrapper)

        return wrapper
