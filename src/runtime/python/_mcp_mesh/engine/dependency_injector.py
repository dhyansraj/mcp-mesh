"""
Dynamic dependency injection system for MCP Mesh.

Handles both initial injection and runtime updates when topology changes.
Focused purely on dependency injection - telemetry/tracing is handled at
the HTTP middleware layer for unified approach across MCP agents and FastAPI apps.
"""

import asyncio
import functools
import inspect
import logging
import weakref
from collections.abc import Callable
from typing import Any

from .signature_analyzer import get_mesh_agent_positions, has_llm_agent_parameter

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
                f"⚠️ Function '{func_name}' has {param_count} parameters but none are "
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
    1. Maintains a registry of available dependencies (McpMeshAgent)
    2. Coordinates with MeshLlmAgentInjector for LLM agent injection
    3. Tracks which functions depend on which services
    4. Updates function bindings when topology changes
    5. Handles graceful degradation when dependencies unavailable
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

        # LLM agent injector for MeshLlmAgent parameters
        from .mesh_llm_agent_injector import get_global_llm_injector

        self._llm_injector = get_global_llm_injector()
        logger.debug("🤖 DependencyInjector initialized with MeshLlmAgentInjector")

    async def register_dependency(self, name: str, instance: Any) -> None:
        """Register a new dependency or update existing one.

        Args:
            name: Composite key in format "function_id:dep_N" or legacy capability name
            instance: Proxy instance to register
        """
        async with self._lock:
            logger.debug(f"📦 Registering dependency: {name}")
            self._dependencies[name] = instance

            # Notify all functions that depend on this (using composite keys)
            if name in self._dependency_mapping:
                for func_id in self._dependency_mapping[name]:
                    if func_id in self._function_registry:
                        func = self._function_registry[func_id]
                        logger.debug(
                            f"🔄 UPDATING dependency '{name}' for {func_id} -> {func} at {hex(id(func))}"
                        )
                        if hasattr(func, "_mesh_update_dependency"):
                            # Extract dep_index from composite key (format: "function_id:dep_N")
                            if ":dep_" in name:
                                dep_index_str = name.split(":dep_")[-1]
                                try:
                                    dep_index = int(dep_index_str)
                                    func._mesh_update_dependency(dep_index, instance)
                                except ValueError:
                                    logger.warning(
                                        f"⚠️ Invalid dep_index in key '{name}', skipping update"
                                    )
                            else:
                                # Legacy format (shouldn't happen with new code)
                                logger.warning(
                                    f"⚠️ Legacy dependency key format '{name}' not supported in array-based injection"
                                )

    async def unregister_dependency(self, name: str) -> None:
        """Remove a dependency (e.g., service went down).

        Args:
            name: Composite key in format "function_id:dep_N" or legacy capability name
        """
        async with self._lock:
            logger.info(f"🗑️ INJECTOR: Unregistering dependency: {name}")
            if name in self._dependencies:
                del self._dependencies[name]
                logger.info(f"🗑️ INJECTOR: Removed {name} from dependencies registry")

                # Notify all functions that depend on this
                if name in self._dependency_mapping:
                    affected_functions = self._dependency_mapping[name]
                    logger.info(
                        f"🗑️ INJECTOR: Updating {len(affected_functions)} functions affected by {name} removal"
                    )

                    for func_id in affected_functions:
                        if func_id in self._function_registry:
                            func = self._function_registry[func_id]
                            if hasattr(func, "_mesh_update_dependency"):
                                logger.info(
                                    f"🗑️ INJECTOR: Removing {name} from function {func_id}"
                                )
                                # Extract dep_index from composite key
                                if ":dep_" in name:
                                    dep_index_str = name.split(":dep_")[-1]
                                    try:
                                        dep_index = int(dep_index_str)
                                        func._mesh_update_dependency(dep_index, None)
                                    except ValueError:
                                        logger.warning(
                                            f"⚠️ Invalid dep_index in key '{name}', skipping removal"
                                        )
                                else:
                                    # Legacy format
                                    logger.warning(
                                        f"⚠️ Legacy dependency key format '{name}' not supported in array-based injection"
                                    )
                            else:
                                logger.warning(
                                    f"🗑️ INJECTOR: Function {func_id} has no _mesh_update_dependency method"
                                )
                        else:
                            logger.warning(
                                f"🗑️ INJECTOR: Function {func_id} not found in registry"
                            )
                else:
                    logger.info(f"🗑️ INJECTOR: No functions mapped to dependency {name}")
            else:
                logger.info(f"🗑️ INJECTOR: Dependency {name} was not registered (no-op)")

    def get_dependency(self, name: str) -> Any | None:
        """Get current instance of a dependency."""
        return self._dependencies.get(name)

    def find_original_function(self, function_name: str) -> Any | None:
        """Find the original function by name from wrapper registry or decorator registry.

        This is used for self-dependency proxy creation to get the cached
        original function reference for direct calls.

        Args:
            function_name: Name of the function to find

        Returns:
            Original function if found, None otherwise
        """
        logger.debug(f"🔍 Searching for original function: '{function_name}'")

        # First, search through wrapper registry (functions with dependencies)
        for func_id, wrapper_func in self._function_registry.items():
            if hasattr(wrapper_func, "_mesh_original_func"):
                original = wrapper_func._mesh_original_func

                # Match by function name
                if hasattr(original, "__name__") and original.__name__ == function_name:
                    logger.debug(
                        f"✅ Found original function '{function_name}' in wrapper registry: {func_id}"
                    )
                    return original

        # If not found in wrapper registry, search in decorator registry (all functions)
        try:
            from .decorator_registry import DecoratorRegistry

            # Search through mesh tools (functions decorated with @mesh.tool)
            mesh_tools = DecoratorRegistry.get_mesh_tools()
            for tool_name, decorated_func in mesh_tools.items():
                original_func = decorated_func.function  # Get the original function
                if (
                    hasattr(original_func, "__name__")
                    and original_func.__name__ == function_name
                ):
                    logger.debug(
                        f"✅ Found original function '{function_name}' in decorator registry: {tool_name}"
                    )
                    return original_func

        except Exception as e:
            logger.warning(f"⚠️ Error searching decorator registry: {e}")

        # List available functions for debugging
        available_functions = []
        for wrapper_func in self._function_registry.values():
            if hasattr(wrapper_func, "_mesh_original_func"):
                original = wrapper_func._mesh_original_func
                if hasattr(original, "__name__"):
                    available_functions.append(original.__name__)

        # Also list functions from decorator registry
        try:
            from .decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            for tool_name, decorated_func in mesh_tools.items():
                if hasattr(decorated_func.function, "__name__"):
                    available_functions.append(decorated_func.function.__name__)
        except:
            pass

        logger.warning(
            f"❌ Original function '{function_name}' not found. "
            f"Available functions: {list(set(available_functions))}"
        )
        return None

    def process_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Process llm_tools from registry response and delegate to MeshLlmAgentInjector.

        Args:
            llm_tools: Dict mapping function_id -> list of tool metadata
                      Format: {"function_id": [{"function_name": "...", "endpoint": {...}, ...}]}
        """
        logger.info(
            f"🤖 DependencyInjector processing llm_tools for {len(llm_tools)} functions"
        )
        self._llm_injector.process_llm_tools(llm_tools)

    def process_llm_providers(self, llm_providers: dict[str, dict[str, Any]]) -> None:
        """
        Process llm_providers from registry response and delegate to MeshLlmAgentInjector (v0.6.1).

        Args:
            llm_providers: Dict mapping function_name -> ResolvedLLMProvider
                          Format: {"function_name": {"agent_id": "...", "endpoint": "...", ...}}
        """
        logger.info(
            f"🔌 DependencyInjector processing llm_providers for {len(llm_providers)} functions"
        )
        self._llm_injector.process_llm_providers(llm_providers)

    def update_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Update llm_tools when topology changes (heartbeat updates).

        Args:
            llm_tools: Updated llm_tools dict from registry
        """
        logger.info(
            f"🔄 DependencyInjector updating llm_tools for {len(llm_tools)} functions"
        )
        self._llm_injector.update_llm_tools(llm_tools)

    def create_llm_injection_wrapper(
        self, func: Callable, function_id: str
    ) -> Callable:
        """
        Create wrapper for function with MeshLlmAgent parameter.

        Delegates to MeshLlmAgentInjector.

        Args:
            func: Function to wrap
            function_id: Unique function ID from @mesh.llm decorator

        Returns:
            Wrapped function with MeshLlmAgent injection
        """
        logger.debug(f"🤖 Creating LLM injection wrapper for {function_id}")
        return self._llm_injector.create_injection_wrapper(func, function_id)

    def create_injection_wrapper(
        self, func: Callable, dependencies: list[str]
    ) -> Callable:
        """
        Create in-place dependency injection by modifying the original function.

        This approach:
        1. Preserves the original function pointer for FastMCP
        2. Adds dynamic dependency injection capability
        3. Can be updated when topology changes
        4. Handles missing dependencies gracefully
        5. Logs warnings for configuration issues
        """
        func_id = f"{func.__module__}.{func.__qualname__}"

        # Use new smart injection strategy
        mesh_positions = analyze_injection_strategy(func, dependencies)

        # Track which dependencies this function needs (using composite keys)
        for dep_index, dep in enumerate(dependencies):
            dep_key = f"{func_id}:dep_{dep_index}"
            if dep_key not in self._dependency_mapping:
                self._dependency_mapping[dep_key] = set()
            self._dependency_mapping[dep_key].add(func_id)

        # Store current dependency values as array (indexed by position)
        if not hasattr(func, "_mesh_injected_deps"):
            func._mesh_injected_deps = [None] * len(dependencies)

        # Store original implementation if not already stored
        if not hasattr(func, "_mesh_original_func"):
            func._mesh_original_func = func

        # Create a wrapper function that handles dependency injection
        # Capture logger in local scope to avoid NameError
        wrapper_logger = logger

        # If no mesh positions to inject, create minimal wrapper for tracking
        if not mesh_positions:
            logger.debug(
                f"🔧 No injection positions for {func.__name__}, creating minimal wrapper for tracking"
            )

            # Check if we need async wrapper for minimal case
            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def minimal_wrapper(*args, **kwargs):
                    # Use ExecutionTracer for functions without dependencies (v0.4.0 style)
                    from ..tracing.execution_tracer import ExecutionTracer

                    wrapper_logger.debug(
                        f"🔧 DI: Executing async function {func.__name__} (no dependencies)"
                    )

                    # For async functions without dependencies, use the async tracer
                    return await ExecutionTracer.trace_function_execution_async(
                        func, args, kwargs, [], [], 0, wrapper_logger
                    )

            else:

                @functools.wraps(func)
                def minimal_wrapper(*args, **kwargs):
                    # Use ExecutionTracer for functions without dependencies (v0.4.0 style)
                    from ..tracing.execution_tracer import ExecutionTracer

                    wrapper_logger.debug(
                        f"🔧 DI: Executing sync function {func.__name__} (no dependencies)"
                    )

                    # Use original function tracer for functions without dependencies
                    return ExecutionTracer.trace_original_function(
                        func, args, kwargs, wrapper_logger
                    )

            # Add minimal metadata for compatibility (use array for consistency)
            minimal_wrapper._mesh_injected_deps = [None] * len(dependencies)
            minimal_wrapper._mesh_dependencies = dependencies
            minimal_wrapper._mesh_positions = mesh_positions
            minimal_wrapper._mesh_original_func = func

            def update_dependency(dep_index: int, instance: Any | None) -> None:
                """No-op update for functions without injection positions."""
                pass

            minimal_wrapper._mesh_update_dependency = update_dependency

            # Register this wrapper for dependency updates (even though it won't use them)
            logger.debug(
                f"🔧 REGISTERING minimal wrapper: {func_id} -> {minimal_wrapper} at {hex(id(minimal_wrapper))}"
            )
            self._function_registry[func_id] = minimal_wrapper

            return minimal_wrapper

        # Determine if we need async wrapper
        need_async_wrapper = inspect.iscoroutinefunction(func)

        if need_async_wrapper:

            @functools.wraps(func)
            async def dependency_wrapper(*args, **kwargs):
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: Function {func.__name__} called"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: args={args}, kwargs={kwargs}"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: mesh_positions={mesh_positions}"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: dependencies={dependencies}"
                )

                # We know mesh_positions is not empty since we checked above

                # Get function signature
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                final_kwargs = kwargs.copy()

                wrapper_logger.debug(f"🔧 DEPENDENCY_WRAPPER: params={params}")
                wrapper_logger.debug(f"🔧 DEPENDENCY_WRAPPER: original kwargs={kwargs}")

                # Inject dependencies as kwargs (using array-based lookup)
                injected_count = 0
                for dep_index, param_position in enumerate(mesh_positions):
                    if dep_index < len(dependencies):
                        dep_name = dependencies[dep_index]
                        param_name = params[param_position]

                        wrapper_logger.debug(
                            f"🔧 DEPENDENCY_WRAPPER: Processing dep {dep_index}: {dep_name} -> {param_name}"
                        )

                        # Only inject if the parameter wasn't explicitly provided
                        if (
                            param_name not in final_kwargs
                            or final_kwargs.get(param_name) is None
                        ):
                            # Get the dependency from wrapper's array storage (by index)
                            dependency = None
                            if dep_index < len(dependency_wrapper._mesh_injected_deps):
                                dependency = dependency_wrapper._mesh_injected_deps[
                                    dep_index
                                ]
                            wrapper_logger.debug(
                                f"🔧 DEPENDENCY_WRAPPER: From wrapper storage[{dep_index}]: {dependency}"
                            )

                            if dependency is None:
                                # Fallback to global storage with composite key
                                dep_key = f"{func.__module__}.{func.__qualname__}:dep_{dep_index}"
                                dependency = self.get_dependency(dep_key)
                                wrapper_logger.debug(
                                    f"🔧 DEPENDENCY_WRAPPER: From global storage[{dep_key}]: {dependency}"
                                )

                            final_kwargs[param_name] = dependency
                            injected_count += 1
                            wrapper_logger.debug(
                                f"🔧 DEPENDENCY_WRAPPER: Injected {dep_name} from index {dep_index} as {param_name}"
                            )
                        else:
                            wrapper_logger.debug(
                                f"🔧 DEPENDENCY_WRAPPER: Skipping {param_name} - already provided"
                            )

                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: Injected {injected_count} dependencies"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: final_kwargs={final_kwargs}"
                )

                # ===== INJECT LLM AGENT IF PRESENT (Option A) =====
                # Check if this function has @mesh.llm metadata attached (on the original function)
                if hasattr(func, "_mesh_llm_param_name"):
                    llm_param = func._mesh_llm_param_name
                    # Only inject if not already provided
                    if (
                        llm_param not in final_kwargs
                        or final_kwargs.get(llm_param) is None
                    ):
                        llm_agent = getattr(func, "_mesh_llm_agent", None)
                        final_kwargs[llm_param] = llm_agent
                        wrapper_logger.debug(
                            f"🤖 LLM_INJECTION: Injected {llm_param}={llm_agent}"
                        )

                # ===== EXECUTE WITH DEPENDENCY INJECTION AND TRACING =====
                # Use ExecutionTracer for comprehensive execution logging (v0.4.0 style)
                from ..tracing.execution_tracer import ExecutionTracer

                original_func = func._mesh_original_func

                wrapper_logger.debug(
                    f"🔧 DI: Executing async function {original_func.__name__} with {injected_count} injected dependencies"
                )

                # Use ExecutionTracer's async method for clean tracing
                result = await ExecutionTracer.trace_function_execution_async(
                    original_func,
                    args,
                    final_kwargs,
                    dependencies,
                    mesh_positions,
                    injected_count,
                    wrapper_logger,
                )

                wrapper_logger.debug(
                    f"🔧 DI: Function {original_func.__name__} returned: {type(result)}"
                )
                return result

        else:
            # Create sync wrapper for sync functions without dependencies
            @functools.wraps(func)
            def dependency_wrapper(*args, **kwargs):
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: Function {func.__name__} called"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: args={args}, kwargs={kwargs}"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: mesh_positions={mesh_positions}"
                )
                wrapper_logger.debug(
                    f"🔧 DEPENDENCY_WRAPPER: dependencies={dependencies}"
                )

                # We know mesh_positions is not empty since we checked above

                # Handle dependency injection for sync functions
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                final_kwargs = kwargs.copy()

                # Inject dependencies as kwargs (using array-based lookup)
                injected_count = 0
                for dep_index, param_position in enumerate(mesh_positions):
                    if dep_index < len(dependencies):
                        dep_name = dependencies[dep_index]
                        param_name = params[param_position]

                        # Only inject if the parameter wasn't explicitly provided
                        if (
                            param_name not in final_kwargs
                            or final_kwargs.get(param_name) is None
                        ):
                            # Get the dependency from wrapper's array storage (by index)
                            dependency = None
                            if dep_index < len(dependency_wrapper._mesh_injected_deps):
                                dependency = dependency_wrapper._mesh_injected_deps[
                                    dep_index
                                ]

                            if dependency is None:
                                # Fallback to global storage with composite key
                                dep_key = f"{func.__module__}.{func.__qualname__}:dep_{dep_index}"
                                dependency = self.get_dependency(dep_key)

                            final_kwargs[param_name] = dependency
                            injected_count += 1

                # ===== INJECT LLM AGENT IF PRESENT (Option A) =====
                # Check if this function has @mesh.llm metadata attached (on the original function)
                if hasattr(func, "_mesh_llm_param_name"):
                    llm_param = func._mesh_llm_param_name
                    # Only inject if not already provided
                    if (
                        llm_param not in final_kwargs
                        or final_kwargs.get(llm_param) is None
                    ):
                        llm_agent = getattr(func, "_mesh_llm_agent", None)
                        final_kwargs[llm_param] = llm_agent
                        wrapper_logger.debug(
                            f"🤖 LLM_INJECTION: Injected {llm_param}={llm_agent}"
                        )

                # ===== EXECUTE WITH DEPENDENCY INJECTION AND TRACING =====
                # Use ExecutionTracer for comprehensive execution logging (v0.4.0 style)
                from ..tracing.execution_tracer import ExecutionTracer

                wrapper_logger.debug(
                    f"🔧 DI: Executing sync function {func._mesh_original_func.__name__} with {injected_count} injected dependencies"
                )

                # Use ExecutionTracer for clean execution tracing
                return ExecutionTracer.trace_function_execution(
                    func._mesh_original_func,
                    args,
                    final_kwargs,
                    dependencies,
                    mesh_positions,
                    injected_count,
                    wrapper_logger,
                )

        # Store dependency state on wrapper as array (indexed by position)
        dependency_wrapper._mesh_injected_deps = [None] * len(dependencies)

        # Add update method to wrapper (now uses index-based updates)
        def update_dependency(dep_index: int, instance: Any | None) -> None:
            """Called when a dependency changes (index-based for duplicate capability support)."""
            if dep_index < len(dependency_wrapper._mesh_injected_deps):
                dependency_wrapper._mesh_injected_deps[dep_index] = instance
                if instance is None:
                    wrapper_logger.debug(
                        f"Removed dependency at index {dep_index} from {func_id}"
                    )
                else:
                    wrapper_logger.debug(
                        f"Updated dependency at index {dep_index} for {func_id}"
                    )
                    wrapper_logger.debug(
                        f"🔗 Wrapper pointer receiving dependency: {dependency_wrapper} at {hex(id(dependency_wrapper))}"
                    )
            else:
                wrapper_logger.warning(
                    f"⚠️ Attempted to update dependency at index {dep_index} but wrapper only has {len(dependency_wrapper._mesh_injected_deps)} dependencies"
                )

        # Store update method on wrapper
        dependency_wrapper._mesh_update_dependency = update_dependency
        dependency_wrapper._mesh_dependencies = dependencies
        dependency_wrapper._mesh_positions = mesh_positions
        dependency_wrapper._mesh_original_func = func

        # Register this wrapper for dependency updates
        logger.debug(
            f"🔧 REGISTERING in function_registry: {func_id} -> {dependency_wrapper} at {hex(id(dependency_wrapper))}"
        )
        self._function_registry[func_id] = dependency_wrapper

        # Return the wrapper (which FastMCP will register)
        return dependency_wrapper


# Global injector instance
_global_injector = DependencyInjector()


def get_global_injector() -> DependencyInjector:
    """Get the global dependency injector instance."""
    return _global_injector
