"""
MCP Mesh Agent Decorator

Core decorator implementation for zero-boilerplate mesh integration.
"""

import asyncio
import functools
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from mcp_mesh_types import CapabilityMetadata, MeshAgentMetadata

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

        self.logger = logging.getLogger(f"mesh_agent.{self.agent_name}")

    def __call__(self, func: F) -> F:
        """Apply the decorator to a function."""

        # Handle both sync and async functions
        if asyncio.iscoroutinefunction(func):

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

            # Store metadata on the wrapper function
            async_wrapper._mesh_agent_metadata = {
                "capabilities": self.capabilities,
                "dependencies": self.dependencies,
                "decorator_instance": self,
            }

            return async_wrapper

        else:

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

            # Store metadata on the wrapper function
            sync_wrapper._mesh_agent_metadata = {
                "capabilities": self.capabilities,
                "dependencies": self.dependencies,
                "decorator_instance": self,
            }

            return sync_wrapper

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
                    raise MeshAgentError(f"Failed to initialize mesh agent: {e}")

    async def _register_enhanced_capabilities(self) -> None:
        """Register enhanced agent capabilities with the mesh registry."""
        if not self._service_discovery:
            return

        try:
            # Build capability metadata objects
            capability_metadata = []
            for cap_name in self.capabilities:
                capability_metadata.append(
                    CapabilityMetadata(
                        name=cap_name,
                        version=self.version,
                        description=f"Capability: {cap_name}",
                        tags=self.tags,
                        performance_metrics=self.performance_profile,
                        resource_requirements=self.resource_requirements,
                        security_level=self.security_context or "standard",
                    )
                )

            # Build enhanced agent metadata
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
                metadata=self.metadata_kwargs,
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
                raise RegistryConnectionError(f"Capability registration error: {e}")
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
                    )

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
