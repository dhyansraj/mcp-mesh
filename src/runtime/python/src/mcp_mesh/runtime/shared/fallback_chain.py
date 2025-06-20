"""
Fallback Chain Implementation for Seamless Remote-to-Local Degradation.

This module implements the core fallback chain that enables interface-optional
dependency injection - the critical feature that allows the same code to work
in mesh environment (remote proxies) and standalone (local instances).
"""

import asyncio
import inspect
import logging
import time
from typing import Any, TypeVar

from mcp_mesh import (
    DependencyResolver,
    FallbackChainInterface,
    FallbackConfiguration,
    FallbackMetrics,
    FallbackMode,
    FallbackMonitor,
    FallbackReason,
    FallbackResult,
    LocalInstanceResolver,
    RemoteProxyResolver,
)

from .registry_client import RegistryClient
from .service_discovery import ServiceDiscoveryService
from .service_proxy import MeshServiceProxy

T = TypeVar("T")


class MeshRemoteProxyResolver(RemoteProxyResolver):
    """Remote proxy resolver using MCP mesh infrastructure."""

    def __init__(
        self,
        registry_client: RegistryClient,
        service_discovery: ServiceDiscoveryService,
        timeout_ms: float = 150.0,
    ):
        self.registry_client = registry_client
        self.service_discovery = service_discovery
        self.timeout_ms = timeout_ms
        self.logger = logging.getLogger(f"{__name__}.RemoteProxyResolver")

    async def resolve(
        self, dependency_type: type[T], context: dict[str, Any]
    ) -> T | None:
        """Resolve dependency via remote proxy."""
        try:
            # Discover service endpoint
            endpoint = await self.discover_service(dependency_type)
            if not endpoint:
                return None

            # Create proxy
            proxy = await self.create_proxy(dependency_type, endpoint)
            return proxy

        except Exception as e:
            self.logger.debug(
                f"Remote proxy resolution failed for {dependency_type}: {e}"
            )
            return None

    def can_resolve(self, dependency_type: type[T]) -> bool:
        """Check if we can create a remote proxy for this type."""
        # We can attempt to create proxies for any class type
        return inspect.isclass(dependency_type)

    @property
    def resolver_type(self) -> str:
        return "remote_proxy"

    async def create_proxy(
        self, service_type: type[T], endpoint: str | None = None
    ) -> T | None:
        """Create a remote proxy for the given service type."""
        try:
            if not endpoint:
                endpoint = await self.discover_service(service_type)
                if not endpoint:
                    return None

            # Create the mesh service proxy
            proxy = MeshServiceProxy(
                service_class=service_type,
                registry_client=self.registry_client,
                endpoint=endpoint,
            )

            # Return the proxy - it implements the same interface as service_type
            return proxy

        except Exception as e:
            self.logger.debug(f"Failed to create proxy for {service_type}: {e}")
            return None

    async def discover_service(self, service_type: type[T]) -> str | None:
        """Discover the endpoint for a service type."""
        try:
            # Use service discovery to find agents providing this capability
            capability_name = getattr(service_type, "__name__", str(service_type))

            agents = await asyncio.wait_for(
                self.service_discovery.find_agents_by_capability(capability_name),
                timeout=self.timeout_ms / 1000.0,
            )

            if not agents:
                return None

            # Use the first available agent
            agent = agents[0]
            return agent.endpoint

        except TimeoutError:
            self.logger.debug(f"Service discovery timeout for {service_type}")
            return None
        except Exception as e:
            self.logger.debug(f"Service discovery failed for {service_type}: {e}")
            return None


class MeshLocalInstanceResolver(LocalInstanceResolver):
    """Local instance resolver for fallback to local class instantiation."""

    def __init__(self, timeout_ms: float = 50.0):
        self.timeout_ms = timeout_ms
        self.logger = logging.getLogger(f"{__name__}.LocalInstanceResolver")
        self._constructor_cache: dict[type, dict[str, Any]] = {}

    async def resolve(
        self, dependency_type: type[T], context: dict[str, Any]
    ) -> T | None:
        """Resolve dependency via local instantiation."""
        try:
            # Get constructor arguments
            constructor_args = self.get_constructor_args(dependency_type)

            # Create local instance
            instance = self.create_instance(dependency_type, constructor_args)
            return instance

        except Exception as e:
            self.logger.debug(
                f"Local instance resolution failed for {dependency_type}: {e}"
            )
            return None

    def can_resolve(self, dependency_type: type[T]) -> bool:
        """Check if we can instantiate this type locally."""
        try:
            # Check if it's a class with a callable constructor
            if not inspect.isclass(dependency_type):
                return False

            # Check if constructor is accessible
            inspect.signature(dependency_type.__init__)
            return True

        except Exception:
            return False

    @property
    def resolver_type(self) -> str:
        return "local_instance"

    def create_instance(
        self, service_type: type[T], constructor_args: dict[str, Any] | None = None
    ) -> T | None:
        """Create a local instance of the given service type."""
        try:
            if constructor_args is None:
                constructor_args = self.get_constructor_args(service_type)

            # Instantiate the class
            instance = service_type(**constructor_args)
            return instance

        except Exception as e:
            self.logger.debug(f"Failed to create local instance of {service_type}: {e}")
            return None

    def get_constructor_args(self, service_type: type[T]) -> dict[str, Any]:
        """Get constructor arguments for a service type."""
        # Cache constructor arguments for performance
        if service_type in self._constructor_cache:
            return self._constructor_cache[service_type].copy()

        try:
            signature = inspect.signature(service_type.__init__)
            args = {}

            for param_name, param in signature.parameters.items():
                if param_name == "self":
                    continue

                # Use default value if available
                if param.default is not inspect.Parameter.empty:
                    args[param_name] = param.default
                # For required parameters, try to infer sensible defaults
                elif param.annotation:
                    default_value = self._get_default_for_type(param.annotation)
                    if default_value is not None:
                        args[param_name] = default_value

            self._constructor_cache[service_type] = args.copy()
            return args

        except Exception as e:
            self.logger.debug(
                f"Failed to extract constructor args for {service_type}: {e}"
            )
            return {}

    def _get_default_for_type(self, type_annotation: type) -> Any:
        """Get a sensible default value for a type annotation."""
        # Basic type mappings
        type_defaults = {
            str: "",
            int: 0,
            float: 0.0,
            bool: False,
            list: lambda: [],
            dict: lambda: {},
            set: lambda: set(),
        }

        # Handle callable defaults
        default = type_defaults.get(type_annotation)
        if callable(default):
            return default()
        return default


class SimpleFallbackMonitor(FallbackMonitor):
    """Simple implementation of fallback monitoring."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(f"{__name__}.FallbackMonitor")
        self._performance_data: list[dict[str, Any]] = []

    def log_resolution_attempt(self, dependency_type: type, resolver_type: str) -> None:
        """Log a dependency resolution attempt."""
        self.logger.debug(
            f"Attempting {resolver_type} resolution for {dependency_type.__name__}"
        )

    def log_resolution_success(
        self, dependency_type: type, resolver_type: str, resolution_time_ms: float
    ) -> None:
        """Log a successful dependency resolution."""
        self.logger.debug(
            f"Successfully resolved {dependency_type.__name__} via {resolver_type} "
            f"in {resolution_time_ms:.2f}ms"
        )

        self._performance_data.append(
            {
                "dependency_type": dependency_type.__name__,
                "resolver_type": resolver_type,
                "resolution_time_ms": resolution_time_ms,
                "success": True,
                "timestamp": time.time(),
            }
        )

    def log_resolution_failure(
        self,
        dependency_type: type,
        resolver_type: str,
        error: Exception,
        fallback_reason: FallbackReason,
    ) -> None:
        """Log a failed dependency resolution."""
        self.logger.debug(
            f"Failed to resolve {dependency_type.__name__} via {resolver_type}: "
            f"{error} (reason: {fallback_reason.value})"
        )

    def log_fallback_transition(
        self,
        dependency_type: type,
        from_resolver: str,
        to_resolver: str,
        transition_time_ms: float,
        reason: FallbackReason,
    ) -> None:
        """Log a fallback transition from one resolver to another."""
        self.logger.info(
            f"Fallback transition for {dependency_type.__name__}: "
            f"{from_resolver} -> {to_resolver} in {transition_time_ms:.2f}ms "
            f"(reason: {reason.value})"
        )

    def get_performance_summary(self) -> dict[str, Any]:
        """Get a summary of performance metrics."""
        if not self._performance_data:
            return {"total_resolutions": 0}

        successful_resolutions = [d for d in self._performance_data if d["success"]]

        return {
            "total_resolutions": len(self._performance_data),
            "successful_resolutions": len(successful_resolutions),
            "average_resolution_time_ms": (
                sum(d["resolution_time_ms"] for d in successful_resolutions)
                / len(successful_resolutions)
                if successful_resolutions
                else 0
            ),
            "resolver_usage": self._get_resolver_usage_stats(),
        }

    def _get_resolver_usage_stats(self) -> dict[str, int]:
        """Get statistics on resolver usage."""
        stats = {}
        for data in self._performance_data:
            resolver = data["resolver_type"]
            stats[resolver] = stats.get(resolver, 0) + 1
        return stats


class MeshFallbackChain(FallbackChainInterface):
    """
    Core implementation of the fallback chain for seamless remote-to-local degradation.

    This is the CRITICAL implementation that enables interface-optional dependency
    injection - allowing the same code to work in mesh environment (remote proxies)
    and standalone (local instances).
    """

    def __init__(
        self,
        registry_client: RegistryClient | None = None,
        service_discovery: ServiceDiscoveryService | None = None,
        config: FallbackConfiguration | None = None,
        monitor: FallbackMonitor | None = None,
    ):
        self.config = config or FallbackConfiguration()
        self.metrics = FallbackMetrics()
        self.monitor = monitor or SimpleFallbackMonitor()
        self.logger = logging.getLogger(f"{__name__}.FallbackChain")

        # Resolver registry (priority-ordered)
        self._resolvers: list[tuple[DependencyResolver, int]] = []

        # Circuit breaker state
        self._circuit_breaker_state: dict[str, dict[str, Any]] = {}

        # Resolution cache
        self._resolution_cache: dict[type, Any] = {}
        self._cache_timestamps: dict[type, float] = {}

        # Initialize default resolvers
        self._initialize_default_resolvers(registry_client, service_discovery)

    def _initialize_default_resolvers(
        self,
        registry_client: RegistryClient | None,
        service_discovery: ServiceDiscoveryService | None,
    ) -> None:
        """Initialize default resolvers based on configuration."""
        # Remote proxy resolver (if registry available)
        if registry_client and service_discovery:
            remote_resolver = MeshRemoteProxyResolver(
                registry_client=registry_client,
                service_discovery=service_discovery,
                timeout_ms=self.config.remote_timeout_ms,
            )

            # Priority based on fallback mode
            if self.config.mode == FallbackMode.REMOTE_FIRST:
                self.register_resolver(remote_resolver, priority=100)
            elif self.config.mode == FallbackMode.LOCAL_FIRST:
                self.register_resolver(remote_resolver, priority=0)
            else:
                self.register_resolver(remote_resolver, priority=50)

        # Local instance resolver
        local_resolver = MeshLocalInstanceResolver(
            timeout_ms=self.config.local_timeout_ms
        )

        if self.config.mode == FallbackMode.LOCAL_FIRST:
            self.register_resolver(local_resolver, priority=100)
        elif self.config.mode == FallbackMode.REMOTE_FIRST:
            self.register_resolver(local_resolver, priority=0)
        else:
            self.register_resolver(local_resolver, priority=50)

    async def resolve_dependency(
        self, dependency_type: type[T], context: dict[str, Any] | None = None
    ) -> T | None:
        """
        Resolve a dependency using the fallback chain.

        This method tries to create a remote proxy first, then falls back to
        local class instantiation if remote fails. The goal is to complete
        the remote→local transition in <200ms.
        """
        if not self.config.enabled:
            return None

        context = context or {}
        start_time = time.perf_counter()

        # Check cache first
        if self.config.cache_successful_resolutions:
            cached_instance = self._get_cached_instance(dependency_type)
            if cached_instance is not None:
                return cached_instance

        # Apply timeout to entire resolution process
        try:
            result = await asyncio.wait_for(
                self._resolve_with_fallback(dependency_type, context),
                timeout=self.config.total_timeout_ms / 1000.0,
            )

            total_time_ms = (time.perf_counter() - start_time) * 1000

            # Cache successful resolutions
            if result and result.success and self.config.cache_successful_resolutions:
                self._cache_instance(dependency_type, result.instance)

            # Update metrics
            self.metrics.record_success(
                is_remote=(
                    "remote" in result.resolution_path[0]
                    if result.resolution_path
                    else False
                ),
                resolution_time_ms=total_time_ms,
            )

            # Log performance warning if we exceeded target
            if total_time_ms > self.config.total_timeout_ms:
                self.logger.warning(
                    f"Dependency resolution for {dependency_type.__name__} took "
                    f"{total_time_ms:.2f}ms (target: {self.config.total_timeout_ms}ms)"
                )

            return result.instance if result else None

        except TimeoutError:
            total_time_ms = (time.perf_counter() - start_time) * 1000
            self.logger.warning(
                f"Dependency resolution timeout for {dependency_type.__name__} "
                f"after {total_time_ms:.2f}ms"
            )

            self.metrics.record_failure(False, FallbackReason.TIMEOUT_EXCEEDED)
            return None

    async def _resolve_with_fallback(
        self, dependency_type: type[T], context: dict[str, Any]
    ) -> FallbackResult | None:
        """Perform dependency resolution with fallback logic."""
        resolution_path = []
        errors = []
        last_resolver_type = None

        # Sort resolvers by priority (descending)
        sorted_resolvers = sorted(self._resolvers, key=lambda x: x[1], reverse=True)

        for resolver, _priority in sorted_resolvers:
            if not resolver.can_resolve(dependency_type):
                continue

            # Check circuit breaker
            if self._is_circuit_breaker_open(resolver.resolver_type):
                self.logger.debug(
                    f"Circuit breaker open for {resolver.resolver_type}, skipping"
                )
                continue

            # Skip based on mode restrictions
            if not self._should_try_resolver(resolver):
                continue

            resolver_start_time = time.perf_counter()

            try:
                self.monitor.log_resolution_attempt(
                    dependency_type, resolver.resolver_type
                )
                self.metrics.record_attempt(
                    is_remote=("remote" in resolver.resolver_type)
                )

                # Attempt resolution
                instance = await resolver.resolve(dependency_type, context)

                if instance is not None:
                    resolution_time_ms = (
                        time.perf_counter() - resolver_start_time
                    ) * 1000

                    self.monitor.log_resolution_success(
                        dependency_type, resolver.resolver_type, resolution_time_ms
                    )

                    resolution_path.append(resolver.resolver_type)

                    # Log fallback transition if this wasn't the first resolver tried
                    if (
                        last_resolver_type
                        and last_resolver_type != resolver.resolver_type
                    ):
                        transition_time_ms = resolution_time_ms  # Approximate
                        self.monitor.log_fallback_transition(
                            dependency_type,
                            last_resolver_type,
                            resolver.resolver_type,
                            transition_time_ms,
                            FallbackReason.SERVICE_DISCOVERY_FAILED,  # Generic reason
                        )

                        self.metrics.record_fallback_transition(transition_time_ms)

                    return FallbackResult(
                        instance=instance,
                        success=True,
                        resolution_path=resolution_path,
                        resolution_time_ms=resolution_time_ms,
                        fallback_reason=None,
                        resolver_used=resolver.resolver_type,
                        errors=errors,
                    )
                else:
                    # Resolution returned None
                    reason = self._determine_fallback_reason(resolver, None)
                    self.monitor.log_resolution_failure(
                        dependency_type,
                        resolver.resolver_type,
                        Exception("Resolution returned None"),
                        reason,
                    )
                    errors.append(f"{resolver.resolver_type}: returned None")
                    self._update_circuit_breaker(resolver.resolver_type, False)

            except Exception as e:
                resolution_time_ms = (time.perf_counter() - resolver_start_time) * 1000
                reason = self._determine_fallback_reason(resolver, e)

                self.monitor.log_resolution_failure(
                    dependency_type, resolver.resolver_type, e, reason
                )

                errors.append(f"{resolver.resolver_type}: {str(e)}")
                self._update_circuit_breaker(resolver.resolver_type, False)

                # If this was a timeout, don't try more resolvers
                if isinstance(e, asyncio.TimeoutError):
                    break

            resolution_path.append(resolver.resolver_type)
            last_resolver_type = resolver.resolver_type

        # All resolvers failed
        return FallbackResult(
            instance=None,
            success=False,
            resolution_path=resolution_path,
            resolution_time_ms=0.0,
            fallback_reason=FallbackReason.SERVICE_DISCOVERY_FAILED,
            resolver_used=None,
            errors=errors,
        )

    def _should_try_resolver(self, resolver: DependencyResolver) -> bool:
        """Check if we should try this resolver based on configuration."""
        if self.config.mode == FallbackMode.REMOTE_ONLY:
            return "remote" in resolver.resolver_type
        elif self.config.mode == FallbackMode.LOCAL_ONLY:
            return "local" in resolver.resolver_type

        # For other modes, try all resolvers in priority order
        return True

    def _determine_fallback_reason(
        self, resolver: DependencyResolver, error: Exception | None
    ) -> FallbackReason:
        """Determine the reason for fallback based on resolver type and error."""
        if isinstance(error, asyncio.TimeoutError):
            return FallbackReason.TIMEOUT_EXCEEDED

        if "remote" in resolver.resolver_type:
            if error and "registry" in str(error).lower():
                return FallbackReason.REGISTRY_UNAVAILABLE
            elif error and "discovery" in str(error).lower():
                return FallbackReason.SERVICE_DISCOVERY_FAILED
            elif error and "proxy" in str(error).lower():
                return FallbackReason.PROXY_GENERATION_FAILED
            else:
                return FallbackReason.REMOTE_INVOCATION_FAILED

        return FallbackReason.SERVICE_DISCOVERY_FAILED

    def _get_cached_instance(self, dependency_type: type[T]) -> T | None:
        """Get cached instance if available and not expired."""
        if dependency_type not in self._resolution_cache:
            return None

        timestamp = self._cache_timestamps.get(dependency_type, 0)
        if time.time() - timestamp > self.config.cache_ttl_seconds:
            # Cache expired
            del self._resolution_cache[dependency_type]
            del self._cache_timestamps[dependency_type]
            return None

        return self._resolution_cache[dependency_type]

    def _cache_instance(self, dependency_type: type[T], instance: T) -> None:
        """Cache a successful resolution."""
        self._resolution_cache[dependency_type] = instance
        self._cache_timestamps[dependency_type] = time.time()

    def _is_circuit_breaker_open(self, resolver_type: str) -> bool:
        """Check if circuit breaker is open for a resolver type."""
        if not self.config.circuit_breaker_enabled:
            return False

        state = self._circuit_breaker_state.get(resolver_type, {})
        failure_count = state.get("failure_count", 0)
        last_failure = state.get("last_failure_time", 0)

        if failure_count >= self.config.circuit_breaker_failure_threshold:
            # Check if recovery timeout has passed
            if (
                time.time() - last_failure
                < self.config.circuit_breaker_recovery_timeout_seconds
            ):
                return True
            else:
                # Reset circuit breaker
                self._circuit_breaker_state[resolver_type] = {"failure_count": 0}

        return False

    def _update_circuit_breaker(self, resolver_type: str, success: bool) -> None:
        """Update circuit breaker state."""
        if not self.config.circuit_breaker_enabled:
            return

        if resolver_type not in self._circuit_breaker_state:
            self._circuit_breaker_state[resolver_type] = {"failure_count": 0}

        if success:
            self._circuit_breaker_state[resolver_type]["failure_count"] = 0
        else:
            state = self._circuit_breaker_state[resolver_type]
            state["failure_count"] = state.get("failure_count", 0) + 1
            state["last_failure_time"] = time.time()

    def configure_fallback(self, config: FallbackConfiguration) -> None:
        """Configure the fallback chain behavior."""
        self.config = config
        self.logger.info(f"Fallback chain configured with mode: {config.mode.value}")

    def get_metrics(self) -> FallbackMetrics:
        """Get performance and behavior metrics for the fallback chain."""
        return self.metrics

    def register_resolver(
        self, resolver: DependencyResolver, priority: int = 0
    ) -> None:
        """Register a dependency resolver with the chain."""
        self._resolvers.append((resolver, priority))
        self.logger.debug(
            f"Registered {resolver.resolver_type} resolver with priority {priority}"
        )

    async def health_check(self) -> dict[str, Any]:
        """Perform a health check on the fallback chain."""
        healthy_resolvers = []
        unhealthy_resolvers = []

        for resolver, _priority in self._resolvers:
            try:
                # Basic health check - see if resolver can handle a simple type
                can_resolve = resolver.can_resolve(str)
                if can_resolve:
                    healthy_resolvers.append(resolver.resolver_type)
                else:
                    unhealthy_resolvers.append(resolver.resolver_type)
            except Exception as e:
                unhealthy_resolvers.append(f"{resolver.resolver_type} (error: {e})")

        return {
            "fallback_chain_enabled": self.config.enabled,
            "fallback_mode": self.config.mode.value,
            "healthy_resolvers": healthy_resolvers,
            "unhealthy_resolvers": unhealthy_resolvers,
            "total_resolvers": len(self._resolvers),
            "metrics": {
                "total_attempts": self.metrics.total_attempts,
                "remote_success_rate": self.metrics.remote_success_rate,
                "local_success_rate": self.metrics.local_success_rate,
                "average_resolution_time_ms": self.metrics.average_resolution_time_ms,
            },
            "circuit_breaker_state": self._circuit_breaker_state,
            "cache_size": len(self._resolution_cache),
        }
