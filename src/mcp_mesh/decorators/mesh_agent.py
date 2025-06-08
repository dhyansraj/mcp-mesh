"""
MCP Mesh Agent Decorator

Core decorator implementation for zero-boilerplate mesh integration.
"""

import asyncio
import functools
import inspect
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from mcp_mesh_types import CapabilityMetadata, MeshAgentMetadata
from mcp_mesh_types.method_metadata import MethodMetadata, MethodType, ServiceContract

from ..shared.exceptions import MeshAgentError, RegistryConnectionError
from ..shared.registry_client import RegistryClient
from ..shared.service_discovery import ServiceDiscoveryService
from ..shared.types import HealthStatus

F = TypeVar("F", bound=Callable[..., Any])


class MeshAgentDecorator:
    """Core decorator implementation for mesh agent integration with capability registration."""

    def __init__(
        self,
        capabilities: list[str],
        health_interval: int = 30,
        dependencies: list[str] | None = None,
        registry_url: str | None = None,
        agent_name: str | None = None,
        security_context: str | None = None,
        timeout: int = 30,
        retry_attempts: int = 3,
        enable_caching: bool = True,
        fallback_mode: bool = True,
        # Enhanced capability metadata
        version: str = "1.0.0",
        description: str | None = None,
        endpoint: str | None = None,
        tags: list[str] | None = None,
        performance_profile: dict[str, float] | None = None,
        resource_requirements: dict[str, Any] | None = None,
        **metadata_kwargs: Any,
    ):
        self.capabilities = capabilities
        self.health_interval = health_interval
        self.dependencies = dependencies or []
        self.registry_url = registry_url
        self.agent_name = agent_name or f"agent-{uuid.uuid4().hex[:8]}"
        self.security_context = security_context
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.enable_caching = enable_caching
        self.fallback_mode = fallback_mode

        # Enhanced metadata for capability registration
        self.version = version
        self.description = description
        self.endpoint = endpoint
        self.tags = tags or []
        self.performance_profile = performance_profile or {}
        self.resource_requirements = resource_requirements or {}
        self.metadata_kwargs = metadata_kwargs

        # Internal state
        self._registry_client: RegistryClient | None = None
        self._service_discovery: ServiceDiscoveryService | None = None
        self._health_task: asyncio.Task | None = None
        self._dependency_cache: dict[str, Any] = {}
        self._last_health_check: datetime | None = None
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

        # Method signature extraction state
        self._method_metadata: dict[str, MethodMetadata] = {}
        self._service_contract: ServiceContract | None = None
        self._signature_extraction_time: float = 0.0

        self.logger = logging.getLogger(f"mesh_agent.{self.agent_name}")

    def _extract_method_signatures(self, func_or_class: Any) -> None:
        """
        Extract method signatures from a function or class and create MethodMetadata instances.

        This method handles both single functions and classes with multiple methods,
        automatically extracting type hints, parameters, and creating comprehensive
        metadata for service discovery and contract enforcement.
        """
        start_time = time.perf_counter()

        try:
            # Determine if we're decorating a function or class
            if inspect.isclass(func_or_class):
                self._extract_class_method_signatures(func_or_class)
            else:
                self._extract_function_signature(func_or_class)

            # Create service contract
            self._create_service_contract(func_or_class)

            self._signature_extraction_time = (
                time.perf_counter() - start_time
            ) * 1000  # Convert to ms

            self.logger.debug(
                f"Method signature extraction completed in {self._signature_extraction_time:.2f}ms "
                f"for {len(self._method_metadata)} methods"
            )

        except Exception as e:
            self.logger.error(f"Failed to extract method signatures: {e}")
            # Don't fail the decorator if signature extraction fails

    def _extract_class_method_signatures(self, cls: type) -> None:
        """Extract signatures from all public methods in a class."""
        for method_name in dir(cls):
            # Skip private methods and special methods (except __call__)
            if method_name.startswith("_") and method_name != "__call__":
                continue

            method = getattr(cls, method_name)

            # Only process callable methods
            if not callable(method):
                continue

            # Skip built-in methods
            if hasattr(method, "__module__") and method.__module__ == "builtins":
                continue

            try:
                self._create_method_metadata(method, method_name, cls)
            except Exception as e:
                self.logger.warning(
                    f"Failed to extract signature for method {method_name}: {e}"
                )

    def _extract_function_signature(self, func: Callable) -> None:
        """Extract signature from a single function."""
        method_name = getattr(func, "__name__", "unknown_function")
        try:
            self._create_method_metadata(func, method_name)
        except Exception as e:
            self.logger.warning(
                f"Failed to extract signature for function {method_name}: {e}"
            )

    def _create_method_metadata(
        self, method: Callable, method_name: str, owner_class: type = None
    ) -> None:
        """Create MethodMetadata instance for a specific method."""
        try:
            # Get method signature
            signature = inspect.signature(method)

            # Determine method type
            method_type = self._determine_method_type(method, owner_class)

            # Check if method is async
            is_async = inspect.iscoroutinefunction(method)

            # Get docstring
            docstring = inspect.getdoc(method) or ""

            # Extract type hints
            type_hints = {}
            try:
                type_hints = getattr(method, "__annotations__", {})
            except Exception:
                # Some methods might not have accessible annotations
                pass

            # Create method metadata
            method_metadata = MethodMetadata(
                method_name=method_name,
                signature=signature,
                capabilities=self.capabilities.copy(),  # Associate with decorator capabilities
                return_type=(
                    signature.return_annotation
                    if signature.return_annotation != inspect.Signature.empty
                    else type(None)
                ),
                method_type=method_type,
                is_async=is_async,
                docstring=docstring,
                type_hints=type_hints,
                service_version=self.version,
                annotations=type_hints,
                resource_requirements=self.resource_requirements.copy(),
            )

            self._method_metadata[method_name] = method_metadata

        except Exception as e:
            self.logger.debug(f"Could not create metadata for {method_name}: {e}")

    def _determine_method_type(
        self, method: Callable, owner_class: type = None
    ) -> MethodType:
        """Determine the type of method (instance, class, static, function, etc.)."""
        if owner_class is None:
            return (
                MethodType.ASYNC_FUNCTION
                if inspect.iscoroutinefunction(method)
                else MethodType.FUNCTION
            )

        # Check for class method
        if isinstance(
            inspect.getattr_static(owner_class, method.__name__, None), classmethod
        ):
            return MethodType.CLASS

        # Check for static method
        if isinstance(
            inspect.getattr_static(owner_class, method.__name__, None), staticmethod
        ):
            return MethodType.STATIC

        # Check for async instance method
        if inspect.iscoroutinefunction(method):
            return MethodType.ASYNC_METHOD

        # Default to instance method
        return MethodType.INSTANCE

    def _create_service_contract(self, func_or_class: Any) -> None:
        """Create a service contract containing all extracted method metadata."""
        service_name = self.agent_name

        # Use class name if decorating a class
        if inspect.isclass(func_or_class):
            service_name = f"{self.agent_name}.{func_or_class.__name__}"
        elif hasattr(func_or_class, "__name__"):
            service_name = f"{self.agent_name}.{func_or_class.__name__}"

        self._service_contract = ServiceContract(
            service_name=service_name,
            service_version=self.version,
            capabilities=self.capabilities.copy(),
            description=self.description or f"Service contract for {service_name}",
        )

        # Add all method metadata to the contract
        for method_metadata in self._method_metadata.values():
            self._service_contract.add_method(method_metadata)

    def __call__(self, func_or_class: F) -> F:
        """Apply the decorator to a function or class."""

        # Extract method signatures automatically
        self._extract_method_signatures(func_or_class)

        # Handle class decoration
        if inspect.isclass(func_or_class):
            return self._decorate_class(func_or_class)

        # Handle function decoration
        return self._decorate_function(func_or_class)

    def _decorate_class(self, cls: type) -> type:
        """Apply mesh agent decoration to a class."""

        # Store metadata on the class
        self._store_metadata_on_target(cls)

        # Create enhanced constructor that initializes mesh integration
        original_init = getattr(cls, "__init__", None)

        if original_init:

            @functools.wraps(original_init)
            def enhanced_init(self_instance, *args, **kwargs):
                # Call original constructor
                original_init(self_instance, *args, **kwargs)

                # Store decorator instance on the class instance for runtime access
                self_instance._mesh_decorator = self

                # Initialize mesh integration asynchronously when first method is called
                self_instance._mesh_initialized = False

            cls.__init__ = enhanced_init

        # Enhance all public methods to support mesh integration
        for method_name in dir(cls):
            if method_name.startswith("_") and method_name != "__call__":
                continue

            method = getattr(cls, method_name)
            if not callable(method) or not hasattr(method, "__func__"):
                continue

            # Wrap the method with mesh integration
            if asyncio.iscoroutinefunction(method):
                enhanced_method = self._create_async_method_wrapper(method, method_name)
            else:
                enhanced_method = self._create_sync_method_wrapper(method, method_name)

            setattr(cls, method_name, enhanced_method)

        return cls

    def _decorate_function(self, func: Callable) -> Callable:
        """Apply mesh agent decoration to a function."""

        # Handle both sync and async functions
        if asyncio.iscoroutinefunction(func):
            wrapper = self._create_async_function_wrapper(func)
        else:
            wrapper = self._create_sync_function_wrapper(func)

        # Store metadata on the wrapper function
        self._store_metadata_on_target(wrapper)

        return wrapper

    def _create_async_function_wrapper(self, func: Callable) -> Callable:
        """Create async wrapper for a function."""

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Initialize mesh integration on first call
            if not self._initialized:
                await self._initialize()

            # Inject dependencies into kwargs
            injected_kwargs = await self._inject_dependencies(kwargs)

            # Execute the original function
            try:
                result = await func(*args, **injected_kwargs)
                await self._record_success()
                return result
            except Exception as e:
                await self._record_failure(e)
                raise

        return async_wrapper

    def _create_sync_function_wrapper(self, func: Callable) -> Callable:
        """Create sync wrapper for a function."""

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to handle async initialization
            async def _run():
                if not self._initialized:
                    await self._initialize()

                # Inject dependencies into kwargs
                injected_kwargs = await self._inject_dependencies(kwargs)

                # Execute the original function
                try:
                    result = func(*args, **injected_kwargs)
                    await self._record_success()
                    return result
                except Exception as e:
                    await self._record_failure(e)
                    raise

            # Run the async operations
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(_run())
            except RuntimeError:
                # No event loop running, create one
                return asyncio.run(_run())

        return sync_wrapper

    def _create_async_method_wrapper(
        self, method: Callable, method_name: str
    ) -> Callable:
        """Create async wrapper for a class method."""

        @functools.wraps(method)
        async def async_method_wrapper(self_instance, *args, **kwargs):
            # Initialize mesh integration on first call
            if hasattr(self_instance, "_mesh_decorator") and not getattr(
                self_instance, "_mesh_initialized", False
            ):
                decorator = self_instance._mesh_decorator
                if not decorator._initialized:
                    await decorator._initialize()
                self_instance._mesh_initialized = True

            # Inject dependencies into kwargs
            if hasattr(self_instance, "_mesh_decorator"):
                injected_kwargs = (
                    await self_instance._mesh_decorator._inject_dependencies(kwargs)
                )
            else:
                injected_kwargs = kwargs

            # Execute the original method
            try:
                result = await method(self_instance, *args, **injected_kwargs)
                if hasattr(self_instance, "_mesh_decorator"):
                    await self_instance._mesh_decorator._record_success()
                return result
            except Exception as e:
                if hasattr(self_instance, "_mesh_decorator"):
                    await self_instance._mesh_decorator._record_failure(e)
                raise

        return async_method_wrapper

    def _create_sync_method_wrapper(
        self, method: Callable, method_name: str
    ) -> Callable:
        """Create sync wrapper for a class method."""

        @functools.wraps(method)
        def sync_method_wrapper(self_instance, *args, **kwargs):
            async def _run():
                # Initialize mesh integration on first call
                if hasattr(self_instance, "_mesh_decorator") and not getattr(
                    self_instance, "_mesh_initialized", False
                ):
                    decorator = self_instance._mesh_decorator
                    if not decorator._initialized:
                        await decorator._initialize()
                    self_instance._mesh_initialized = True

                # Inject dependencies into kwargs
                if hasattr(self_instance, "_mesh_decorator"):
                    injected_kwargs = (
                        await self_instance._mesh_decorator._inject_dependencies(kwargs)
                    )
                else:
                    injected_kwargs = kwargs

                # Execute the original method
                try:
                    result = method(self_instance, *args, **injected_kwargs)
                    if hasattr(self_instance, "_mesh_decorator"):
                        await self_instance._mesh_decorator._record_success()
                    return result
                except Exception as e:
                    if hasattr(self_instance, "_mesh_decorator"):
                        await self_instance._mesh_decorator._record_failure(e)
                    raise

            # Run the async operations
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(_run())
            except RuntimeError:
                # No event loop running, create one
                return asyncio.run(_run())

        return sync_method_wrapper

    def _store_metadata_on_target(self, target: Any) -> None:
        """Store comprehensive metadata on the decorated target (function or class)."""

        # Core mesh metadata
        mesh_metadata = {
            "capabilities": self.capabilities.copy(),
            "dependencies": self.dependencies.copy(),
            "decorator_instance": self,
            "agent_name": self.agent_name,
            "version": self.version,
            "description": self.description,
            "endpoint": self.endpoint,
            "tags": self.tags.copy(),
            "performance_profile": self.performance_profile.copy(),
            "resource_requirements": self.resource_requirements.copy(),
            "security_context": self.security_context,
            "health_interval": self.health_interval,
            "timeout": self.timeout,
            "retry_attempts": self.retry_attempts,
            "enable_caching": self.enable_caching,
            "fallback_mode": self.fallback_mode,
        }

        # Method signature metadata
        signature_metadata = {
            "method_metadata": self._method_metadata.copy(),
            "service_contract": self._service_contract,
            "signature_extraction_time": self._signature_extraction_time,
            "extracted_methods": list(self._method_metadata.keys()),
        }

        # Registry integration metadata
        registry_metadata = {
            "registry_url": self.registry_url,
            "metadata_kwargs": self.metadata_kwargs.copy(),
            "is_class_decorated": inspect.isclass(target),
            "target_type": "class" if inspect.isclass(target) else "function",
            "target_name": getattr(target, "__name__", "unknown"),
            "target_module": getattr(target, "__module__", "unknown"),
        }

        # Combined metadata for easy access
        combined_metadata = {
            **mesh_metadata,
            **signature_metadata,
            **registry_metadata,
        }

        # Store metadata with multiple access patterns
        target._mesh_agent_metadata = combined_metadata
        target._mesh_capabilities = self.capabilities.copy()
        target._mesh_dependencies = self.dependencies.copy()
        target._mesh_method_metadata = self._method_metadata.copy()
        target._mesh_service_contract = self._service_contract
        target._mesh_decorator_instance = self

        # Store individual method metadata for easy access
        if self._method_metadata:
            target._mesh_methods = {}
            for method_name, method_meta in self._method_metadata.items():
                target._mesh_methods[method_name] = method_meta

        # Registry-specific metadata for service discovery
        target._mesh_registry_metadata = {
            "service_name": (
                self._service_contract.service_name
                if self._service_contract
                else self.agent_name
            ),
            "service_version": self.version,
            "available_capabilities": self.capabilities.copy(),
            "method_signatures": {
                name: meta.to_dict() for name, meta in self._method_metadata.items()
            },
            "contract_dict": (
                self._service_contract.to_dict() if self._service_contract else None
            ),
        }

    async def _initialize(self) -> None:
        """Initialize mesh integration components."""
        async with self._initialization_lock:
            if self._initialized:
                return

            try:
                # Initialize registry client
                self._registry_client = RegistryClient(
                    url=self.registry_url,
                    timeout=self.timeout,
                    retry_attempts=self.retry_attempts,
                )

                # Initialize service discovery
                self._service_discovery = ServiceDiscoveryService(self._registry_client)

                # Register enhanced capabilities with registry
                await self._register_enhanced_capabilities()

                # Start health monitoring task
                self._health_task = asyncio.create_task(self._health_monitor())

                self._initialized = True
                self.logger.info(
                    f"Mesh agent initialized with capabilities: {self.capabilities}"
                )

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(
                        f"Mesh initialization failed, running in fallback mode: {e}"
                    )
                    self._initialized = True  # Allow function to work without mesh
                else:
                    raise MeshAgentError(f"Failed to initialize mesh agent: {e}") from e

    async def _register_enhanced_capabilities(self) -> None:
        """Register enhanced agent capabilities with the mesh registry."""
        if not self._service_discovery:
            return

        try:
            # Build capability metadata objects with method signature information
            capability_metadata = []
            for cap_name in self.capabilities:
                # Find methods that provide this capability
                methods_for_capability = [
                    method
                    for method in self._method_metadata.values()
                    if cap_name in method.capabilities
                ]

                # Enhanced description including method information
                method_descriptions = []
                if methods_for_capability:
                    method_descriptions = [
                        f"{method.method_name}({', '.join(method.get_required_parameters())})"
                        for method in methods_for_capability
                    ]

                description = f"Capability: {cap_name}"
                if method_descriptions:
                    description += f" - Methods: {', '.join(method_descriptions)}"

                capability_metadata.append(
                    CapabilityMetadata(
                        name=cap_name,
                        version=self.version,
                        description=description,
                        tags=self.tags,
                        performance_metrics=self.performance_profile,
                        resource_requirements=self.resource_requirements,
                        security_level=self.security_context or "standard",
                    )
                )

            # Build enhanced agent metadata with method signature information
            enhanced_metadata = self.metadata_kwargs.copy()

            # Add method signature information to metadata
            if self._service_contract:
                enhanced_metadata.update(
                    {
                        "service_contract": self._service_contract.to_dict(),
                        "method_count": len(self._method_metadata),
                        "signature_extraction_time_ms": self._signature_extraction_time,
                        "available_methods": list(self._method_metadata.keys()),
                    }
                )

            agent_metadata = MeshAgentMetadata(
                name=self.agent_name,
                version=self.version,
                description=self.description,
                capabilities=capability_metadata,
                dependencies=self.dependencies,
                health_interval=self.health_interval,
                security_context=self.security_context,
                endpoint=self.endpoint,
                tags=self.tags,
                performance_profile=self.performance_profile,
                resource_usage=self.resource_requirements,
                metadata=enhanced_metadata,
            )

            # Register with service discovery
            success = await self._service_discovery.register_agent_capabilities(
                agent_id=self.agent_name, metadata=agent_metadata
            )

            if success:
                self.logger.info(
                    f"Registered enhanced capabilities: {self.capabilities}"
                )
            else:
                raise RegistryConnectionError("Failed to register agent capabilities")

        except RegistryConnectionError as e:
            if not self.fallback_mode:
                raise
            self.logger.warning(f"Failed to register enhanced capabilities: {e}")
        except Exception as e:
            if not self.fallback_mode:
                raise RegistryConnectionError(
                    f"Capability registration error: {e}"
                ) from e
            self.logger.warning(f"Failed to register enhanced capabilities: {e}")

    async def _inject_dependencies(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Inject dependency values into function kwargs."""
        if not self.dependencies or not self._registry_client:
            return kwargs

        injected_kwargs = kwargs.copy()

        for dependency in self.dependencies:
            # Skip if dependency already provided
            if dependency in kwargs:
                continue

            # Check cache first
            if self.enable_caching and dependency in self._dependency_cache:
                cache_entry = self._dependency_cache[dependency]
                if not self._is_cache_expired(cache_entry):
                    injected_kwargs[dependency] = cache_entry["value"]
                    continue

            # Fetch from registry
            try:
                dependency_value = await self._registry_client.get_dependency(
                    dependency
                )

                # Cache the result
                if self.enable_caching and dependency_value is not None:
                    self._dependency_cache[dependency] = {
                        "value": dependency_value,
                        "timestamp": datetime.now(),
                        "ttl": timedelta(minutes=5),  # 5-minute cache TTL
                    }

                if dependency_value is not None:
                    injected_kwargs[dependency] = dependency_value

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(
                        f"Failed to inject dependency {dependency}: {e}"
                    )
                    # Don't inject the dependency, let function handle missing parameter
                else:
                    raise MeshAgentError(
                        f"Failed to inject dependency {dependency}: {e}"
                    ) from e

        return injected_kwargs

    async def _health_monitor(self) -> None:
        """Background task for periodic health monitoring."""
        while True:
            try:
                await asyncio.sleep(self.health_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health monitor error: {e}")

    async def _send_heartbeat(self) -> None:
        """Send heartbeat to registry with current health status."""
        if not self._registry_client:
            return

        try:
            health_status = HealthStatus(
                agent_name=self.agent_name,
                status="healthy",
                capabilities=self.capabilities,
                timestamp=datetime.now(),
                metadata={
                    "last_health_check": (
                        self._last_health_check.isoformat()
                        if self._last_health_check
                        else None
                    ),
                    "dependency_cache_size": len(self._dependency_cache),
                },
            )

            await self._registry_client.send_heartbeat(health_status)
            self._last_health_check = datetime.now()

        except Exception as e:
            self.logger.warning(f"Failed to send heartbeat: {e}")

    def _is_cache_expired(self, cache_entry: dict[str, Any]) -> bool:
        """Check if a cache entry has expired."""
        return datetime.now() - cache_entry["timestamp"] > cache_entry["ttl"]

    async def _record_success(self) -> None:
        """Record successful function execution."""
        # Could send metrics to registry or monitoring system
        pass

    async def _record_failure(self, error: Exception) -> None:
        """Record failed function execution."""
        self.logger.error(f"Function execution failed: {error}")
        # Could send error metrics to registry or monitoring system

    async def cleanup(self) -> None:
        """Cleanup resources when decorator is no longer needed."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._registry_client:
            await self._registry_client.close()


# Utility functions for metadata access
def get_mesh_metadata(func_or_class: Any) -> dict[str, Any] | None:
    """
    Retrieve mesh agent metadata from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        Dictionary containing mesh metadata or None if not decorated
    """
    return getattr(func_or_class, "_mesh_agent_metadata", None)


def get_mesh_capabilities(func_or_class: Any) -> list[str] | None:
    """
    Retrieve capabilities from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        List of capabilities or None if not decorated
    """
    return getattr(func_or_class, "_mesh_capabilities", None)


def get_mesh_method_metadata(func_or_class: Any) -> dict[str, MethodMetadata] | None:
    """
    Retrieve method metadata from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        Dictionary mapping method names to MethodMetadata or None if not decorated
    """
    return getattr(func_or_class, "_mesh_method_metadata", None)


def get_mesh_service_contract(func_or_class: Any) -> ServiceContract | None:
    """
    Retrieve service contract from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        ServiceContract instance or None if not decorated
    """
    return getattr(func_or_class, "_mesh_service_contract", None)


def get_mesh_registry_metadata(func_or_class: Any) -> dict[str, Any] | None:
    """
    Retrieve registry-specific metadata from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        Dictionary containing registry metadata or None if not decorated
    """
    return getattr(func_or_class, "_mesh_registry_metadata", None)


def is_mesh_decorated(func_or_class: Any) -> bool:
    """
    Check if a function or class has been decorated with @mesh_agent.

    Args:
        func_or_class: Function or class to check

    Returns:
        True if decorated, False otherwise
    """
    return hasattr(func_or_class, "_mesh_agent_metadata")


def get_mesh_decorator_instance(func_or_class: Any) -> MeshAgentDecorator | None:
    """
    Retrieve the decorator instance from a decorated function or class.

    Args:
        func_or_class: Decorated function or class

    Returns:
        MeshAgentDecorator instance or None if not decorated
    """
    return getattr(func_or_class, "_mesh_decorator_instance", None)


def get_mesh_method_by_name(
    func_or_class: Any, method_name: str
) -> MethodMetadata | None:
    """
    Retrieve specific method metadata by name from a decorated function or class.

    Args:
        func_or_class: Decorated function or class
        method_name: Name of the method to retrieve

    Returns:
        MethodMetadata instance or None if not found
    """
    methods = getattr(func_or_class, "_mesh_methods", None)
    if methods:
        return methods.get(method_name)
    return None


# Public decorator function
def mesh_agent(
    capabilities: list[str],
    health_interval: int = 30,
    dependencies: list[str] | None = None,
    registry_url: str | None = None,
    agent_name: str | None = None,
    security_context: str | None = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True,
    # Enhanced capability metadata
    version: str = "1.0.0",
    description: str | None = None,
    endpoint: str | None = None,
    tags: list[str] | None = None,
    performance_profile: dict[str, float] | None = None,
    resource_requirements: dict[str, Any] | None = None,
    **metadata_kwargs: Any,
) -> Callable[[F], F]:
    """
    Decorator that integrates MCP tools with mesh infrastructure and capability registration.

    This decorator automatically handles:
    - Enhanced registry registration with capability metadata
    - Semantic capability matching and discovery
    - Periodic health monitoring with enhanced metrics
    - Dependency injection
    - Error handling and fallback modes
    - Caching of dependency values

    Args:
        capabilities: List of capabilities this tool provides
        health_interval: Heartbeat interval in seconds (default: 30)
        dependencies: List of service dependencies to inject (default: None)
        registry_url: Registry service URL (default: from env/config)
        agent_name: Agent identifier (default: auto-generated)
        security_context: Security context for authorization (default: None)
        timeout: Network timeout in seconds (default: 30)
        retry_attempts: Number of retry attempts for registry calls (default: 3)
        enable_caching: Enable local caching of dependencies (default: True)
        fallback_mode: Enable graceful degradation mode (default: True)
        version: Agent version for capability versioning (default: "1.0.0")
        description: Agent description for discovery (default: None)
        endpoint: Agent endpoint URL for direct communication (default: None)
        tags: Agent tags for enhanced discovery (default: None)
        performance_profile: Performance characteristics for matching (default: None)
        resource_requirements: Resource requirements specification (default: None)
        **metadata_kwargs: Additional metadata for capability registration
    """
    decorator = MeshAgentDecorator(
        capabilities=capabilities,
        health_interval=health_interval,
        dependencies=dependencies,
        registry_url=registry_url,
        agent_name=agent_name,
        security_context=security_context,
        timeout=timeout,
        retry_attempts=retry_attempts,
        enable_caching=enable_caching,
        fallback_mode=fallback_mode,
        version=version,
        description=description,
        endpoint=endpoint,
        tags=tags,
        performance_profile=performance_profile,
        resource_requirements=resource_requirements,
        **metadata_kwargs,
    )
    return decorator
