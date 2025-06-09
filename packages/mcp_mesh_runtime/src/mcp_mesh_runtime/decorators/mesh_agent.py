"""
MCP Mesh Agent Decorator

Core decorator implementation for zero-boilerplate mesh integration.
"""

import asyncio
import functools
import inspect
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from mcp_mesh import (
    CapabilityMetadata,
    DependencyAnalyzer,
    DependencyList,
    DependencySpecification,
    FallbackConfiguration,
    FallbackMode,
    MeshAgentMetadata,
    MethodMetadata,
    MethodType,
    ServiceContract,
)

from ..shared.exceptions import MeshAgentError, RegistryConnectionError
from ..shared.fallback_chain import MeshFallbackChain
from ..shared.registry_client import RegistryClient
from ..shared.service_discovery import ServiceDiscoveryService
from ..shared.types import HealthStatus
from ..shared.unified_dependency_resolver import MeshUnifiedDependencyResolver

F = TypeVar("F", bound=Callable[..., Any])


class MeshAgentDecorator:
    """Core decorator implementation for mesh agent integration with capability registration."""

    def __init__(
        self,
        capabilities: list[str],
        health_interval: int = 30,
        dependencies: DependencyList | None = None,
        registry_url: str | None = None,
        agent_name: str | None = None,
        security_context: str | None = None,
        timeout: int = 30,
        retry_attempts: int = 3,
        enable_caching: bool = True,
        fallback_mode: bool = True,
        fallback_config: FallbackConfiguration | None = None,
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

        # Configure fallback chain
        self.fallback_config = fallback_config or FallbackConfiguration(
            enabled=fallback_mode,
            mode=FallbackMode.REMOTE_FIRST,
            remote_timeout_ms=timeout * 1000 * 0.75,  # 75% of total timeout for remote
            local_timeout_ms=timeout * 1000 * 0.25,  # 25% of total timeout for local
            total_timeout_ms=timeout * 1000,
        )

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
        self._fallback_chain: MeshFallbackChain | None = None
        self._unified_resolver: MeshUnifiedDependencyResolver | None = None
        self._health_task: asyncio.Task | None = None
        self._dependency_cache: dict[str, Any] = {}
        self._last_health_check: datetime | None = None
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

        # Dependency specifications
        self._dependency_specifications: list[DependencySpecification] = []

        # Method signature extraction state
        self._method_metadata: dict[str, MethodMetadata] = {}
        self._service_contract: ServiceContract | None = None
        self._signature_extraction_time: float = 0.0

        self.logger = logging.getLogger(f"mesh_agent.{self.agent_name}")

        # Set up debug logging if DEBUG environment variable is set
        if os.getenv("MCP_MESH_DEBUG", "").lower() in ("true", "1", "yes"):
            self.logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self.logger.addHandler(handler)

        self.logger.debug(
            f"🔧 Initializing MeshAgentDecorator for agent '{self.agent_name}'"
        )
        self.logger.debug(f"📋 Capabilities: {self.capabilities}")
        self.logger.debug(f"🔗 Dependencies: {self.dependencies}")
        self.logger.debug(
            f"⚙️ Configuration: registry_url={self.registry_url}, "
            f"health_interval={self.health_interval}, fallback_mode={self.fallback_mode}"
        )

        # Pre-analyze dependencies for unified resolution
        self._analyze_dependencies()

        # Validate dependency specifications
        self._validate_dependencies()

    def _analyze_dependencies(self) -> None:
        """
        Analyze dependencies to create unified dependency specifications.

        This method converts the mixed dependency list (strings, protocols, concrete classes)
        into standardized DependencySpecification objects for unified resolution.
        """
        if not self.dependencies:
            return

        try:
            self.logger.debug(
                f"🔍 Starting dependency analysis for {len(self.dependencies)} dependencies"
            )

            # Analyze dependencies without function signature initially
            # We'll update with function signature info when decorating
            self._dependency_specifications = (
                DependencyAnalyzer.analyze_dependencies_list(
                    dependencies=self.dependencies,
                    function_signature=None,  # Will be updated in __call__
                )
            )

            self.logger.debug(
                f"✅ Analyzed {len(self._dependency_specifications)} dependency specifications: "
                f"{[spec.display_name for spec in self._dependency_specifications]}"
            )

        except Exception as e:
            self.logger.warning(f"❌ Failed to analyze dependencies: {e}")
            self.logger.debug(
                "🔄 Falling back to string-based dependency specifications"
            )
            # Fallback to treating all as string dependencies for backward compatibility
            self._dependency_specifications = [
                DependencySpecification.from_string(str(dep))
                for dep in self.dependencies
            ]
            self.logger.debug(
                f"📝 Created {len(self._dependency_specifications)} fallback dependency specs"
            )

    def _update_dependency_specifications_with_signature(
        self, function_signature: inspect.Signature
    ) -> None:
        """Update dependency specifications with function signature information."""
        try:
            self.logger.debug(
                "🔧 Updating dependency specifications with function signature"
            )
            self.logger.debug(f"📋 Function signature: {function_signature}")

            # Re-analyze with function signature for better parameter mapping
            updated_specs = DependencyAnalyzer.analyze_dependencies_list(
                dependencies=self.dependencies, function_signature=function_signature
            )

            self._dependency_specifications = updated_specs

            self.logger.debug(
                f"✅ Updated dependency specifications with signature info: "
                f"{[spec.display_name for spec in self._dependency_specifications]}"
            )

        except Exception as e:
            self.logger.warning(
                f"Failed to update dependency specifications with signature: {e}"
            )

    def _validate_dependencies(self) -> None:
        """Validate dependency specifications and log warnings for issues."""
        if not self._dependency_specifications:
            return

        try:
            from ..shared.unified_dependency_resolver import BasicDependencyValidator

            validator = BasicDependencyValidator()

            self.logger.debug(
                f"🔍 Validating {len(self._dependency_specifications)} dependency specifications"
            )

            validation_results = validator.validate_specifications(
                self._dependency_specifications
            )

            if validation_results:
                self.logger.warning("⚠️ Dependency validation issues found:")
                for dep_name, errors in validation_results.items():
                    for error in errors:
                        self.logger.warning(f"  ❌ {dep_name}: {error.message}")
                        if error.suggestions:
                            for suggestion in error.suggestions:
                                self.logger.info(f"    💡 Suggestion: {suggestion}")
            else:
                self.logger.debug(
                    "✅ All dependency specifications validated successfully"
                )

        except Exception as e:
            self.logger.warning(f"Failed to validate dependencies: {e}")

    def _extract_method_signatures(self, func_or_class: Any) -> None:
        """
        Extract method signatures from a function or class and create MethodMetadata instances.

        This method handles both single functions and classes with multiple methods,
        automatically extracting type hints, parameters, and creating comprehensive
        metadata for service discovery and contract enforcement.
        """
        start_time = time.perf_counter()

        self.logger.debug(
            f"🔍 Starting method signature extraction for {type(func_or_class).__name__}"
        )

        try:
            # Determine if we're decorating a function or class
            if inspect.isclass(func_or_class):
                self.logger.debug(
                    f"📋 Extracting signatures from class: {func_or_class.__name__}"
                )
                self._extract_class_method_signatures(func_or_class)
            else:
                func_name = getattr(func_or_class, "__name__", "unknown_function")
                self.logger.debug(f"📋 Extracting signature from function: {func_name}")
                self._extract_function_signature(func_or_class)

            # Create service contract
            self.logger.debug("📄 Creating service contract")
            self._create_service_contract(func_or_class)

            self._signature_extraction_time = (
                time.perf_counter() - start_time
            ) * 1000  # Convert to ms

            self.logger.debug(
                f"✅ Method signature extraction completed in {self._signature_extraction_time:.2f}ms "
                f"for {len(self._method_metadata)} methods: {list(self._method_metadata.keys())}"
            )

        except Exception as e:
            self.logger.error(f"❌ Failed to extract method signatures: {e}")
            self.logger.debug(
                "🔄 Continuing decorator initialization despite signature extraction failure"
            )
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

        target_name = getattr(func_or_class, "__name__", "unknown")
        self.logger.debug(f"🎯 Applying mesh agent decorator to: {target_name}")

        # Extract method signatures automatically
        self.logger.debug("📝 Extracting method signatures")
        self._extract_method_signatures(func_or_class)

        # Update dependency specifications with function signature if decorating a function
        if not inspect.isclass(func_or_class) and self.dependencies:
            try:
                self.logger.debug(
                    "🔧 Updating dependency specs with function signature"
                )
                function_signature = inspect.signature(func_or_class)
                self._update_dependency_specifications_with_signature(
                    function_signature
                )
            except Exception as e:
                self.logger.debug(
                    f"⚠️ Could not extract signature for dependency analysis: {e}"
                )

        # Handle class decoration
        if inspect.isclass(func_or_class):
            self.logger.debug(f"🏗️ Decorating class: {func_or_class.__name__}")
            decorated_class = self._decorate_class(func_or_class)
        else:
            # Handle function decoration
            self.logger.debug(f"⚡ Decorating function: {target_name}")
            decorated_class = self._decorate_function(func_or_class)

        # 🚀 CRITICAL FIX: Start mesh lifecycle immediately after decoration
        self.logger.debug(f"🚀 Starting mesh lifecycle immediately for: {target_name}")
        self._schedule_immediate_initialization()

        return decorated_class

    def _schedule_immediate_initialization(self) -> None:
        """Schedule immediate mesh lifecycle initialization in a background thread."""

        def run_async_init():
            """Run async initialization in a new event loop."""
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run the initialization
                loop.run_until_complete(self._initialize())

                self.logger.debug(
                    f"✅ Mesh lifecycle started successfully for agent '{self.agent_name}'"
                )

            except Exception as e:
                self.logger.debug(f"❌ Failed to start mesh lifecycle: {e}")
                # Don't fail the decorator application - graceful degradation
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        # Start initialization in a daemon thread so it doesn't block decorator application
        import threading

        init_thread = threading.Thread(
            target=run_async_init, name=f"MeshInit-{self.agent_name}", daemon=True
        )
        init_thread.start()

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
            # Inject dependencies into kwargs (initialization already completed in background)
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
            # For sync functions, we need to handle async dependency injection
            async def _run():
                # Inject dependencies into kwargs (initialization already completed in background)
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
            # Inject dependencies into kwargs (initialization already completed in background)
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
                # Inject dependencies into kwargs (initialization already completed in background)
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
                self.logger.debug("🔄 Mesh agent already initialized, skipping")
                return

            self.logger.debug("🚀 Starting mesh agent initialization")

            try:
                # Initialize registry client
                self.logger.debug(
                    f"🌐 Initializing registry client: {self.registry_url}"
                )
                self._registry_client = RegistryClient(
                    url=self.registry_url,
                    timeout=self.timeout,
                    retry_attempts=self.retry_attempts,
                )

                # Initialize service discovery
                self.logger.debug("🔍 Initializing service discovery")
                self._service_discovery = ServiceDiscoveryService(self._registry_client)

                # Initialize fallback chain
                self.logger.debug(
                    f"🔗 Initializing fallback chain with config: {self.fallback_config}"
                )
                self._fallback_chain = MeshFallbackChain(
                    registry_client=self._registry_client,
                    service_discovery=self._service_discovery,
                    config=self.fallback_config,
                )

                # Initialize unified dependency resolver
                self.logger.debug(
                    f"🧩 Initializing unified dependency resolver (caching: {self.enable_caching})"
                )
                self._unified_resolver = MeshUnifiedDependencyResolver(
                    registry_client=self._registry_client,
                    service_discovery=self._service_discovery,
                    fallback_chain=self._fallback_chain,
                    enable_caching=self.enable_caching,
                )

                # Register enhanced capabilities with registry
                self.logger.debug("📋 Registering enhanced capabilities")
                await self._register_enhanced_capabilities()

                # Start health monitoring task
                self.logger.debug(
                    f"💓 Starting health monitoring (interval: {self.health_interval}s)"
                )
                self._health_task = asyncio.create_task(self._health_monitor())

                self._initialized = True
                self.logger.info(
                    f"🎉 Mesh agent '{self.agent_name}' initialized successfully with capabilities: {self.capabilities}"
                )

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(
                        f"⚠️ Mesh initialization failed, running in fallback mode: {e}"
                    )
                    self.logger.debug(
                        "🔄 Continuing in standalone mode without mesh features"
                    )
                    self._initialized = True  # Allow function to work without mesh
                else:
                    self.logger.error(f"❌ Mesh agent initialization failed: {e}")
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
                    f"✅ Successfully registered enhanced capabilities: {self.capabilities}"
                )
                self.logger.debug(
                    f"📊 Service contract: {self._service_contract.service_name if self._service_contract else 'None'}"
                )
            else:
                self.logger.error("❌ Failed to register agent capabilities")
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
        """Inject dependency values into function kwargs using the unified resolver."""
        if not self._dependency_specifications:
            return kwargs

        injected_kwargs = kwargs.copy()

        # Use unified resolver to resolve all dependencies
        if self._unified_resolver:
            try:
                resolution_results = await self._unified_resolver.resolve_multiple(
                    specifications=self._dependency_specifications,
                    context={
                        "agent_name": self.agent_name,
                        "capabilities": self.capabilities,
                        "existing_kwargs": kwargs,
                    },
                )

                self.logger.debug(
                    f"🧩 Processing {len(resolution_results)} dependency resolution results"
                )

                # Process resolution results
                for result in resolution_results:
                    spec = result.specification

                    # Determine parameter name to use
                    param_name = spec.parameter_name or spec.display_name

                    # Skip if already provided in kwargs
                    if param_name in kwargs:
                        self.logger.debug(
                            f"⏭️ Skipping '{param_name}' - already provided in kwargs"
                        )
                        continue

                    if result.success and result.instance is not None:
                        injected_kwargs[param_name] = result.instance
                        self.logger.debug(
                            f"✅ Injected {spec.pattern.value} dependency '{param_name}' "
                            f"via {result.resolution_method} (type: {type(result.instance).__name__})"
                        )
                    else:
                        if not spec.is_optional:
                            if self.fallback_mode:
                                self.logger.warning(
                                    f"⚠️ Failed to resolve required dependency '{param_name}': "
                                    f"{result.error}"
                                )
                            else:
                                self.logger.error(
                                    f"❌ Failed to resolve required dependency '{param_name}': "
                                    f"{result.error}"
                                )
                                raise MeshAgentError(
                                    f"Failed to resolve required dependency '{param_name}': "
                                    f"{result.error}"
                                )
                        else:
                            self.logger.debug(
                                f"🔘 Optional dependency '{param_name}' not resolved: {result.error}"
                            )

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(f"⚠️ Unified dependency resolution failed: {e}")
                    self.logger.debug("🔄 Falling back to legacy dependency resolution")
                else:
                    self.logger.error(f"❌ Unified dependency resolution failed: {e}")
                    raise MeshAgentError(
                        f"Unified dependency resolution failed: {e}"
                    ) from e
        else:
            # Fallback to legacy resolution if unified resolver not available
            injected_kwargs = await self._inject_dependencies_legacy(kwargs)

        return injected_kwargs

    async def _inject_dependencies_legacy(
        self, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Legacy dependency injection for backward compatibility."""
        if not self.dependencies:
            return kwargs

        injected_kwargs = kwargs.copy()

        for dependency in self.dependencies:
            # Convert to string for legacy handling
            dependency_str = str(dependency)

            # Skip if dependency already provided
            if dependency_str in kwargs:
                continue

            # Check cache first
            if self.enable_caching and dependency_str in self._dependency_cache:
                cache_entry = self._dependency_cache[dependency_str]
                if not self._is_cache_expired(cache_entry):
                    injected_kwargs[dependency_str] = cache_entry["value"]
                    continue

            # Resolve dependency using legacy approach
            try:
                dependency_value = await self._resolve_dependency_via_fallback(
                    dependency_str
                )

                # Cache the result
                if self.enable_caching and dependency_value is not None:
                    self._dependency_cache[dependency_str] = {
                        "value": dependency_value,
                        "timestamp": datetime.now(),
                        "ttl": timedelta(minutes=5),  # 5-minute cache TTL
                    }

                if dependency_value is not None:
                    injected_kwargs[dependency_str] = dependency_value

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(
                        f"Failed to inject dependency {dependency_str}: {e}"
                    )
                    # Don't inject the dependency, let function handle missing parameter
                else:
                    raise MeshAgentError(
                        f"Failed to inject dependency {dependency_str}: {e}"
                    ) from e

        return injected_kwargs

    async def _resolve_dependency_via_fallback(self, dependency: str) -> Any:
        """
        Resolve a dependency using the fallback chain.

        This is the core method that enables interface-optional dependency injection:
        1. Try to resolve as a remote proxy via registry discovery
        2. Fall back to local class instantiation if remote fails
        3. Provide graceful error handling if both fail
        """
        if not self._fallback_chain:
            # Fallback to legacy registry-based dependency resolution
            if self._registry_client:
                return await self._registry_client.get_dependency(dependency)
            return None

        # Try to resolve dependency as a type
        dependency_type = self._resolve_dependency_type(dependency)
        if not dependency_type:
            # If we can't resolve the type, try legacy approach
            if self._registry_client:
                return await self._registry_client.get_dependency(dependency)
            return None

        # Use fallback chain to resolve the dependency
        instance = await self._fallback_chain.resolve_dependency(
            dependency_type=dependency_type,
            context={
                "agent_name": self.agent_name,
                "capabilities": self.capabilities,
                "dependency_name": dependency,
            },
        )

        return instance

    def _resolve_dependency_type(self, dependency: str) -> type | None:
        """
        Resolve a dependency string to a type/class.

        This method tries to convert dependency strings like:
        - "OAuth2AuthService" -> OAuth2AuthService class
        - "auth_service" -> AuthService class (via naming conventions)
        - "my_module.MyClass" -> MyClass from my_module
        """
        # Try direct name lookup in globals
        try:
            # Check if it's already a type
            if isinstance(dependency, type):
                return dependency

            # Try to import if it looks like a module path
            if "." in dependency:
                module_path, class_name = dependency.rsplit(".", 1)
                try:
                    import importlib

                    module = importlib.import_module(module_path)
                    return getattr(module, class_name)
                except (ImportError, AttributeError):
                    pass

            # Try to find in current module's globals
            import sys

            current_frame = sys._getframe(1)
            while current_frame:
                if dependency in current_frame.f_globals:
                    candidate = current_frame.f_globals[dependency]
                    if inspect.isclass(candidate):
                        return candidate
                current_frame = current_frame.f_back

            # Try common naming convention transformations
            # e.g., "auth_service" -> "AuthService"
            class_name_candidates = [
                dependency,  # As-is
                dependency.title().replace("_", ""),  # auth_service -> AuthService
                dependency.replace(
                    "_", ""
                ).title(),  # auth_service -> AuthService (alternative)
                f"{dependency.title().replace('_', '')}Service",  # auth -> AuthService
                f"{dependency.title().replace('_', '')}Client",  # auth -> AuthClient
            ]

            for candidate_name in class_name_candidates:
                # Check in all loaded modules
                for module_name, module in sys.modules.items():
                    if module and hasattr(module, candidate_name):
                        candidate = getattr(module, candidate_name)
                        if inspect.isclass(candidate):
                            return candidate

        except Exception as e:
            self.logger.debug(
                f"Failed to resolve dependency type for '{dependency}': {e}"
            )

        return None

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
            self.logger.debug(f"💓 Sending heartbeat for agent '{self.agent_name}'")

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
            self.logger.debug("✅ Heartbeat sent successfully")

        except Exception as e:
            self.logger.warning(f"❌ Failed to send heartbeat: {e}")

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


# INTERNAL decorator function - DO NOT USE DIRECTLY
# Use mcp_mesh.mesh_agent instead for auto-enhanced version
def _internal_mesh_agent(
    capabilities: list[str],
    health_interval: int = 30,
    dependencies: DependencyList | None = None,
    registry_url: str | None = None,
    agent_name: str | None = None,
    security_context: str | None = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True,
    fallback_config: FallbackConfiguration | None = None,
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
    - Interface-optional dependency injection with fallback chain
    - Error handling and graceful degradation modes
    - Caching of dependency values
    - Performance optimization for <200ms fallback transitions

    CRITICAL FEATURE: Interface-Optional Dependency Injection
    ========================================================
    This decorator enables the same code to work in mesh environment (remote proxies)
    and standalone (local instances) without any Protocol definitions or interface changes.

    The fallback chain:
    1. Try remote proxy via registry discovery
    2. Fall back to local class instantiation if remote fails
    3. Provide graceful error handling if both fail
    4. Complete remote→local transition in <200ms

    Example:
        @mesh_agent(
            capabilities=["auth", "file_operations"],
            dependencies=[
                "legacy_auth",           # String (existing)
                AuthService,             # Protocol interface
                OAuth2AuthService,       # Concrete class (new)
            ]
        )
        async def flexible_function(
            legacy_auth: str,
            auth_service: AuthService,
            oauth2_auth: OAuth2AuthService
        ):
            # All three patterns work simultaneously!
            return await auth_service.authenticate(oauth2_auth.get_token())

    Args:
        capabilities: List of capabilities this tool provides
        health_interval: Heartbeat interval in seconds (default: 30)
        dependencies: List of service dependencies to inject - supports:
            - String dependencies: "legacy_auth" (existing Week 1, Day 4 format)
            - Protocol interfaces: AuthService (traditional interface-based)
            - Concrete classes: OAuth2AuthService (new auto-discovery pattern)
            (default: None)
        registry_url: Registry service URL (default: from env/config)
        agent_name: Agent identifier (default: auto-generated)
        security_context: Security context for authorization (default: None)
        timeout: Network timeout in seconds (default: 30)
        retry_attempts: Number of retry attempts for registry calls (default: 3)
        enable_caching: Enable local caching of dependencies (default: True)
        fallback_mode: Enable graceful degradation mode (default: True)
        fallback_config: Advanced fallback chain configuration (default: auto-configured)
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
        fallback_config=fallback_config,
        version=version,
        description=description,
        endpoint=endpoint,
        tags=tags,
        performance_profile=performance_profile,
        resource_requirements=resource_requirements,
        **metadata_kwargs,
    )
    return decorator


# DEPRECATED: Use mcp_mesh.mesh_agent instead
def mesh_agent(*args, **kwargs):
    """
    DEPRECATED: This function is deprecated and will be removed.

    Use mcp_mesh.mesh_agent instead, which automatically provides
    enhanced mesh capabilities when mcp_mesh is imported.

    This import pattern breaks portability and violates the single import source principle.
    """
    import warnings

    warnings.warn(
        "Importing mesh_agent from mcp_mesh.decorators.mesh_agent is deprecated. "
        "Use 'from mcp_mesh import mesh_agent' instead for auto-enhanced capabilities.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _internal_mesh_agent(*args, **kwargs)
