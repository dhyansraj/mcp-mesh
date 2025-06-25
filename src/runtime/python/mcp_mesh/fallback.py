"""
Fallback Chain Interfaces for Seamless Remote-to-Local Degradation.

This module provides the core interfaces and types for the fallback chain that enables
interface-optional dependency injection - the critical feature that allows the same
code to work in mesh environment (remote proxies) and standalone (local instances).
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, Union

T = TypeVar("T")


class FallbackMode(Enum):
    """Fallback behavior modes for dependency resolution."""

    REMOTE_ONLY = "remote_only"  # Only try remote proxy, fail if unavailable
    LOCAL_ONLY = "local_only"  # Only try local instantiation
    REMOTE_FIRST = "remote_first"  # Try remote first, fallback to local
    LOCAL_FIRST = "local_first"  # Try local first, fallback to remote
    SMART = "smart"  # Use heuristics to determine best approach


class FallbackReason(Enum):
    """Reasons for falling back from remote to local."""

    REGISTRY_UNAVAILABLE = "registry_unavailable"
    SERVICE_DISCOVERY_FAILED = "service_discovery_failed"
    PROXY_GENERATION_FAILED = "proxy_generation_failed"
    REMOTE_INVOCATION_FAILED = "remote_invocation_failed"
    TIMEOUT_EXCEEDED = "timeout_exceeded"
    PERFORMANCE_THRESHOLD = "performance_threshold"
    EXPLICIT_CONFIG = "explicit_config"


@dataclass
class FallbackMetrics:
    """Performance and behavior metrics for fallback operations."""

    total_attempts: int = 0
    remote_attempts: int = 0
    local_attempts: int = 0
    remote_successes: int = 0
    local_successes: int = 0
    remote_failures: int = 0
    local_failures: int = 0

    # Timing metrics
    total_resolution_time_ms: float = 0.0
    remote_resolution_time_ms: float = 0.0
    local_resolution_time_ms: float = 0.0
    fallback_transition_time_ms: float = 0.0

    # Failure tracking
    fallback_reasons: dict[FallbackReason, int] = field(default_factory=dict)
    last_fallback_reason: FallbackReason | None = None
    last_fallback_timestamp: float | None = None

    def record_attempt(self, is_remote: bool) -> None:
        """Record a dependency resolution attempt."""
        self.total_attempts += 1
        if is_remote:
            self.remote_attempts += 1
        else:
            self.local_attempts += 1

    def record_success(self, is_remote: bool, resolution_time_ms: float) -> None:
        """Record a successful dependency resolution."""
        if is_remote:
            self.remote_successes += 1
            self.remote_resolution_time_ms += resolution_time_ms
        else:
            self.local_successes += 1
            self.local_resolution_time_ms += resolution_time_ms

        self.total_resolution_time_ms += resolution_time_ms

    def record_failure(self, is_remote: bool, reason: FallbackReason) -> None:
        """Record a failed dependency resolution."""
        if is_remote:
            self.remote_failures += 1
        else:
            self.local_failures += 1

        # Track fallback reasons
        if reason not in self.fallback_reasons:
            self.fallback_reasons[reason] = 0
        self.fallback_reasons[reason] += 1

        self.last_fallback_reason = reason
        self.last_fallback_timestamp = time.time()

    def record_fallback_transition(self, transition_time_ms: float) -> None:
        """Record the time taken to transition from remote to local."""
        self.fallback_transition_time_ms += transition_time_ms

    @property
    def remote_success_rate(self) -> float:
        """Calculate remote success rate."""
        if self.remote_attempts == 0:
            return 0.0
        return self.remote_successes / self.remote_attempts

    @property
    def local_success_rate(self) -> float:
        """Calculate local success rate."""
        if self.local_attempts == 0:
            return 0.0
        return self.local_successes / self.local_attempts

    @property
    def average_resolution_time_ms(self) -> float:
        """Calculate average resolution time."""
        if self.total_attempts == 0:
            return 0.0
        return self.total_resolution_time_ms / self.total_attempts

    @property
    def average_fallback_transition_time_ms(self) -> float:
        """Calculate average fallback transition time."""
        fallback_count = sum(self.fallback_reasons.values())
        if fallback_count == 0:
            return 0.0
        return self.fallback_transition_time_ms / fallback_count


@dataclass
class FallbackConfiguration:
    """Configuration for fallback chain behavior."""

    # Core behavior
    mode: FallbackMode = FallbackMode.REMOTE_FIRST
    enabled: bool = True

    # Timeout settings
    remote_timeout_ms: float = 150.0  # Aggressive timeout for 200ms total target
    local_timeout_ms: float = 50.0
    total_timeout_ms: float = 200.0

    # Performance thresholds
    max_remote_latency_ms: float = 100.0
    max_fallback_transition_ms: float = 50.0

    # Retry settings
    remote_retry_attempts: int = 1  # Minimal retries for performance
    local_retry_attempts: int = 0  # Local should not need retries

    # Caching
    cache_successful_resolutions: bool = True
    cache_ttl_seconds: float = 300.0  # 5 minutes

    # Circuit breaker settings
    circuit_breaker_enabled: bool = True
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout_seconds: float = 30.0

    # Monitoring
    enable_detailed_metrics: bool = True
    enable_performance_logging: bool = True


class DependencyResolver(ABC):
    """Abstract interface for dependency resolution strategies."""

    @abstractmethod
    async def resolve(
        self, dependency_type: type[T], context: dict[str, Any]
    ) -> T | None:
        """
        Resolve a dependency to an instance.

        Args:
            dependency_type: The type/class to resolve
            context: Additional context for resolution

        Returns:
            Resolved instance or None if resolution failed
        """
        pass

    @abstractmethod
    def can_resolve(self, dependency_type: type[T]) -> bool:
        """
        Check if this resolver can handle the given dependency type.

        Args:
            dependency_type: The type to check

        Returns:
            True if this resolver can handle the type
        """
        pass

    @property
    @abstractmethod
    def resolver_type(self) -> str:
        """Get the type identifier for this resolver."""
        pass


class RemoteProxyResolver(DependencyResolver):
    """Interface for remote proxy dependency resolution."""

    @abstractmethod
    async def create_proxy(
        self, service_type: type[T], endpoint: str | None = None
    ) -> T | None:
        """
        Create a remote proxy for the given service type.

        Args:
            service_type: The service class to create a proxy for
            endpoint: Optional specific endpoint to use

        Returns:
            Proxy instance or None if creation failed
        """
        pass

    @abstractmethod
    async def discover_service(self, service_type: type[T]) -> str | None:
        """
        Discover the endpoint for a service type.

        Args:
            service_type: The service type to discover

        Returns:
            Service endpoint or None if not found
        """
        pass


class LocalInstanceResolver(DependencyResolver):
    """Interface for local instance dependency resolution."""

    @abstractmethod
    def create_instance(
        self, service_type: type[T], constructor_args: dict[str, Any] | None = None
    ) -> T | None:
        """
        Create a local instance of the given service type.

        Args:
            service_type: The service class to instantiate
            constructor_args: Optional constructor arguments

        Returns:
            Service instance or None if creation failed
        """
        pass

    @abstractmethod
    def get_constructor_args(self, service_type: type[T]) -> dict[str, Any]:
        """
        Get constructor arguments for a service type.

        Args:
            service_type: The service type

        Returns:
            Dictionary of constructor arguments
        """
        pass


class FallbackChainInterface(ABC):
    """
    Core interface for the fallback chain that enables seamless degradation
    from remote to local services.

    This is the CRITICAL interface that enables interface-optional dependency
    injection - allowing the same code to work in mesh environment (remote proxies)
    and standalone (local instances).
    """

    @abstractmethod
    async def resolve_dependency(
        self, dependency_type: type[T], context: dict[str, Any] | None = None
    ) -> T | None:
        """
        Resolve a dependency using the fallback chain.

        This method tries to create a remote proxy first, then falls back to
        local class instantiation if remote fails. The goal is to complete
        the remote→local transition in <200ms.

        Args:
            dependency_type: The type/class to resolve
            context: Optional context information for resolution

        Returns:
            Resolved instance (remote proxy or local instance) or None if both fail
        """
        pass

    @abstractmethod
    def configure_fallback(self, config: FallbackConfiguration) -> None:
        """
        Configure the fallback chain behavior.

        Args:
            config: Fallback configuration
        """
        pass

    @abstractmethod
    def get_metrics(self) -> FallbackMetrics:
        """
        Get performance and behavior metrics for the fallback chain.

        Returns:
            Current metrics
        """
        pass

    @abstractmethod
    def register_resolver(
        self, resolver: DependencyResolver, priority: int = 0
    ) -> None:
        """
        Register a dependency resolver with the chain.

        Args:
            resolver: The resolver to register
            priority: Priority (higher values = higher priority)
        """
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the fallback chain.

        Returns:
            Health status information
        """
        pass


@dataclass
class FallbackResult:
    """Result of a fallback chain resolution attempt."""

    instance: Any | None
    success: bool
    resolution_path: list[str]  # e.g., ["remote_proxy", "local_instance"]
    resolution_time_ms: float
    fallback_reason: FallbackReason | None
    resolver_used: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def used_fallback(self) -> bool:
        """Check if fallback was used (more than one resolution path)."""
        return len(self.resolution_path) > 1

    @property
    def was_successful(self) -> bool:
        """Check if resolution was successful."""
        return self.success and self.instance is not None


class FallbackMonitor(ABC):
    """Interface for monitoring fallback chain operations."""

    @abstractmethod
    def log_resolution_attempt(self, dependency_type: type, resolver_type: str) -> None:
        """Log a dependency resolution attempt."""
        pass

    @abstractmethod
    def log_resolution_success(
        self, dependency_type: type, resolver_type: str, resolution_time_ms: float
    ) -> None:
        """Log a successful dependency resolution."""
        pass

    @abstractmethod
    def log_resolution_failure(
        self,
        dependency_type: type,
        resolver_type: str,
        error: Exception,
        fallback_reason: FallbackReason,
    ) -> None:
        """Log a failed dependency resolution."""
        pass

    @abstractmethod
    def log_fallback_transition(
        self,
        dependency_type: type,
        from_resolver: str,
        to_resolver: str,
        transition_time_ms: float,
        reason: FallbackReason,
    ) -> None:
        """Log a fallback transition from one resolver to another."""
        pass

    @abstractmethod
    def get_performance_summary(self) -> dict[str, Any]:
        """Get a summary of performance metrics."""
        pass


# Utility types for interface-optional dependency injection
DependencyFactory = Callable[[], T]
DependencyInstance = Union[T, DependencyFactory[T]]

# Type aliases for clarity
ServiceType = type[T]
ServiceInstance = T
ServiceEndpoint = str
