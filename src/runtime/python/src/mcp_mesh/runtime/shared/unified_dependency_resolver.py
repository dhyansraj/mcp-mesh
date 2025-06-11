"""
Unified Dependency Resolver Implementation

This module implements the unified dependency resolver that supports all 3 patterns
simultaneously without breaking existing code:

1. String dependencies: "legacy_auth" (existing from Week 1, Day 4)
2. Protocol interfaces: AuthService (traditional interface-based)
3. Concrete classes: OAuth2AuthService (new auto-discovery pattern)
"""

import asyncio
import inspect
import logging
import time
from typing import Any

from mcp_mesh import (
    DependencyPattern,
    DependencyResolutionResult,
    DependencySpecification,
    DependencyValidationError,
    DependencyValidator,
    UnifiedDependencyResolver,
)

from .exceptions import MeshAgentError
from .fallback_chain import MeshFallbackChain
from .registry_client import RegistryClient
from .service_discovery import ServiceDiscoveryService


class BasicDependencyValidator(DependencyValidator):
    """Basic implementation of dependency validation."""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.Validator")

    def validate_specification(
        self, specification: DependencySpecification
    ) -> list[DependencyValidationError]:
        """Validate a single dependency specification."""
        errors = []

        # Basic validation rules
        if specification.pattern == DependencyPattern.STRING:
            if not isinstance(specification.identifier, str):
                errors.append(
                    DependencyValidationError(
                        specification=specification,
                        error_type="invalid_string_identifier",
                        message="String dependency must have string identifier",
                        suggestions=["Ensure dependency is provided as a string"],
                    )
                )
            elif not specification.identifier.strip():
                errors.append(
                    DependencyValidationError(
                        specification=specification,
                        error_type="empty_string_identifier",
                        message="String dependency cannot be empty",
                        suggestions=["Provide a non-empty dependency name"],
                    )
                )

        elif specification.pattern in [
            DependencyPattern.PROTOCOL,
            DependencyPattern.CONCRETE,
        ]:
            if not inspect.isclass(specification.identifier):
                errors.append(
                    DependencyValidationError(
                        specification=specification,
                        error_type="invalid_type_identifier",
                        message=f"{specification.pattern.value} dependency must be a class",
                        suggestions=["Ensure dependency is a class type"],
                    )
                )

            # Check for common issues with concrete classes
            if specification.pattern == DependencyPattern.CONCRETE:
                try:
                    # Check if class can be instantiated
                    signature = inspect.signature(specification.identifier.__init__)
                    required_params = [
                        p
                        for name, p in signature.parameters.items()
                        if name != "self" and p.default == inspect.Parameter.empty
                    ]

                    if required_params:
                        errors.append(
                            DependencyValidationError(
                                specification=specification,
                                error_type="complex_constructor",
                                message=f"Concrete class {specification.identifier.__name__} has required constructor parameters",
                                suggestions=[
                                    "Provide default values for constructor parameters",
                                    "Use a protocol interface instead",
                                    "Register a factory function",
                                ],
                            )
                        )
                except Exception as e:
                    errors.append(
                        DependencyValidationError(
                            specification=specification,
                            error_type="constructor_analysis_failed",
                            message=f"Could not analyze constructor for {specification.identifier.__name__}: {e}",
                            suggestions=["Ensure class has accessible __init__ method"],
                        )
                    )

        return errors

    def validate_specifications(
        self, specifications: list[DependencySpecification]
    ) -> dict[str, list[DependencyValidationError]]:
        """Validate multiple dependency specifications."""
        results = {}

        for spec in specifications:
            errors = self.validate_specification(spec)
            if errors:
                results[spec.display_name] = errors

        # Check for conflicts between specifications
        self._check_for_conflicts(specifications, results)

        return results

    def _check_for_conflicts(
        self,
        specifications: list[DependencySpecification],
        results: dict[str, list[DependencyValidationError]],
    ) -> None:
        """Check for conflicts between multiple specifications."""
        # Check for duplicate parameter names
        param_names = {}
        for spec in specifications:
            if spec.parameter_name:
                if spec.parameter_name in param_names:
                    param_names[spec.parameter_name]
                    error = DependencyValidationError(
                        specification=spec,
                        error_type="duplicate_parameter_name",
                        message=f"Parameter name '{spec.parameter_name}' is used by multiple dependencies",
                        suggestions=[
                            "Use different parameter names",
                            "Combine dependencies into a single specification",
                        ],
                    )

                    if spec.display_name not in results:
                        results[spec.display_name] = []
                    results[spec.display_name].append(error)
                else:
                    param_names[spec.parameter_name] = spec


class MeshUnifiedDependencyResolver(UnifiedDependencyResolver):
    """
    Core implementation of unified dependency resolution.

    This resolver supports all 3 dependency patterns simultaneously:
    1. String dependencies - resolved via registry lookup (legacy compatibility)
    2. Protocol interfaces - resolved via fallback chain with interface matching
    3. Concrete classes - resolved via fallback chain with direct instantiation
    """

    def __init__(
        self,
        registry_client: RegistryClient | None = None,
        service_discovery: ServiceDiscoveryService | None = None,
        fallback_chain: MeshFallbackChain | None = None,
        validator: DependencyValidator | None = None,
        enable_caching: bool = True,
        cache_ttl_seconds: float = 300.0,
    ):
        self.registry_client = registry_client
        self.service_discovery = service_discovery
        self.fallback_chain = fallback_chain
        self.validator = validator or BasicDependencyValidator()
        self.enable_caching = enable_caching
        self.cache_ttl_seconds = cache_ttl_seconds

        # Resolution cache
        self._resolution_cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, float] = {}

        # Legacy string dependency cache (for backward compatibility)
        self._legacy_cache: dict[str, Any] = {}

        self.logger = logging.getLogger(f"{__name__}.UnifiedResolver")

    @property
    def resolver_name(self) -> str:
        return "unified_dependency_resolver"

    async def resolve_dependency(
        self,
        specification: DependencySpecification,
        context: dict[str, Any] | None = None,
    ) -> DependencyResolutionResult:
        """
        Resolve a dependency based on its specification.

        This method supports all 3 patterns:
        1. STRING: Legacy registry-based lookup
        2. PROTOCOL: Fallback chain with interface matching
        3. CONCRETE: Fallback chain with direct instantiation
        """
        context = context or {}
        start_time = time.perf_counter()

        # Check cache first
        if self.enable_caching:
            cached_result = self._get_cached_result(specification)
            if cached_result:
                return cached_result

        # Validate specification
        validation_errors = self.validator.validate_specification(specification)
        if validation_errors:
            error_messages = [err.message for err in validation_errors]
            error = MeshAgentError(
                f"Dependency validation failed: {'; '.join(error_messages)}"
            )

            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="validation_failed",
                resolution_time_ms=(time.perf_counter() - start_time) * 1000,
                error=error,
            )

        # Route to appropriate resolution method based on pattern
        try:
            if specification.pattern == DependencyPattern.STRING:
                result = await self._resolve_string_dependency(specification, context)
            elif specification.pattern == DependencyPattern.PROTOCOL:
                result = await self._resolve_protocol_dependency(specification, context)
            elif specification.pattern == DependencyPattern.CONCRETE:
                result = await self._resolve_concrete_dependency(specification, context)
            else:
                raise MeshAgentError(
                    f"Unsupported dependency pattern: {specification.pattern}"
                )

            # Update timing
            result.resolution_time_ms = (time.perf_counter() - start_time) * 1000

            # Cache successful results
            if result.success and self.enable_caching:
                self._cache_result(specification, result)

            return result

        except Exception as e:
            self.logger.error(
                f"Failed to resolve dependency {specification.display_name}: {e}"
            )

            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="error",
                resolution_time_ms=(time.perf_counter() - start_time) * 1000,
                error=e,
            )

    async def _resolve_string_dependency(
        self, specification: DependencySpecification, context: dict[str, Any]
    ) -> DependencyResolutionResult:
        """Resolve string dependency using legacy registry lookup."""
        dependency_name = str(specification.identifier)

        # Check legacy cache
        if dependency_name in self._legacy_cache:
            return DependencyResolutionResult(
                specification=specification,
                instance=self._legacy_cache[dependency_name],
                success=True,
                resolution_method="legacy_cache",
                resolution_time_ms=0.0,
            )

        # Try registry-based resolution
        if self.registry_client:
            try:
                instance = await self.registry_client.get_dependency(dependency_name)
                if instance is not None:
                    self._legacy_cache[dependency_name] = instance
                    return DependencyResolutionResult(
                        specification=specification,
                        instance=instance,
                        success=True,
                        resolution_method="registry_lookup",
                        resolution_time_ms=0.0,
                    )
            except Exception as e:
                self.logger.debug(f"Registry lookup failed for {dependency_name}: {e}")

        # If we have a type hint, try to resolve as type-based dependency
        if specification.type_hint and inspect.isclass(specification.type_hint):
            self.logger.debug(
                f"Attempting type-based resolution for string dependency {dependency_name}"
            )

            if self.fallback_chain:
                try:
                    instance = await self.fallback_chain.resolve_dependency(
                        dependency_type=specification.type_hint, context=context
                    )

                    if instance is not None:
                        return DependencyResolutionResult(
                            specification=specification,
                            instance=instance,
                            success=True,
                            resolution_method="fallback_chain_type_hint",
                            resolution_time_ms=0.0,
                            fallback_used=True,
                        )
                except Exception as e:
                    self.logger.debug(
                        f"Fallback chain resolution failed for {dependency_name}: {e}"
                    )

        # Resolution failed
        return DependencyResolutionResult(
            specification=specification,
            instance=None,
            success=False,
            resolution_method="failed",
            resolution_time_ms=0.0,
            error=MeshAgentError(
                f"Could not resolve string dependency: {dependency_name}"
            ),
        )

    async def _resolve_protocol_dependency(
        self, specification: DependencySpecification, context: dict[str, Any]
    ) -> DependencyResolutionResult:
        """Resolve protocol dependency using fallback chain."""
        protocol_type = specification.identifier

        if not self.fallback_chain:
            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="no_fallback_chain",
                resolution_time_ms=0.0,
                error=MeshAgentError(
                    "Fallback chain not available for protocol resolution"
                ),
            )

        try:
            instance = await self.fallback_chain.resolve_dependency(
                dependency_type=protocol_type, context=context
            )

            if instance is not None:
                return DependencyResolutionResult(
                    specification=specification,
                    instance=instance,
                    success=True,
                    resolution_method="fallback_chain_protocol",
                    resolution_time_ms=0.0,
                )
            else:
                return DependencyResolutionResult(
                    specification=specification,
                    instance=None,
                    success=False,
                    resolution_method="fallback_chain_failed",
                    resolution_time_ms=0.0,
                    error=MeshAgentError(
                        f"Fallback chain could not resolve protocol: {protocol_type.__name__}"
                    ),
                )

        except Exception as e:
            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="fallback_chain_error",
                resolution_time_ms=0.0,
                error=e,
            )

    async def _resolve_concrete_dependency(
        self, specification: DependencySpecification, context: dict[str, Any]
    ) -> DependencyResolutionResult:
        """Resolve concrete class dependency using fallback chain."""
        concrete_type = specification.identifier

        if not self.fallback_chain:
            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="no_fallback_chain",
                resolution_time_ms=0.0,
                error=MeshAgentError(
                    "Fallback chain not available for concrete class resolution"
                ),
            )

        try:
            instance = await self.fallback_chain.resolve_dependency(
                dependency_type=concrete_type, context=context
            )

            if instance is not None:
                return DependencyResolutionResult(
                    specification=specification,
                    instance=instance,
                    success=True,
                    resolution_method="fallback_chain_concrete",
                    resolution_time_ms=0.0,
                )
            else:
                return DependencyResolutionResult(
                    specification=specification,
                    instance=None,
                    success=False,
                    resolution_method="fallback_chain_failed",
                    resolution_time_ms=0.0,
                    error=MeshAgentError(
                        f"Fallback chain could not resolve concrete class: {concrete_type.__name__}"
                    ),
                )

        except Exception as e:
            return DependencyResolutionResult(
                specification=specification,
                instance=None,
                success=False,
                resolution_method="fallback_chain_error",
                resolution_time_ms=0.0,
                error=e,
            )

    def can_resolve(self, specification: DependencySpecification) -> bool:
        """Check if this resolver can handle the given dependency specification."""
        try:
            if specification.pattern == DependencyPattern.STRING:
                # Can always attempt string resolution
                return True
            elif specification.pattern == DependencyPattern.PROTOCOL:
                # Can resolve protocols if fallback chain is available
                return self.fallback_chain is not None
            elif specification.pattern == DependencyPattern.CONCRETE:
                # Can resolve concrete classes if fallback chain is available
                return self.fallback_chain is not None
            else:
                return False
        except Exception:
            return False

    async def resolve_multiple(
        self,
        specifications: list[DependencySpecification],
        context: dict[str, Any] | None = None,
    ) -> list[DependencyResolutionResult]:
        """Resolve multiple dependencies efficiently."""
        context = context or {}

        # Validate all specifications first
        validation_results = self.validator.validate_specifications(specifications)
        if validation_results:
            self.logger.warning(f"Validation issues found: {validation_results}")

        # Resolve all dependencies concurrently
        tasks = []
        for spec in specifications:
            task = self.resolve_dependency(spec, context)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions from concurrent resolution
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    DependencyResolutionResult(
                        specification=specifications[i],
                        instance=None,
                        success=False,
                        resolution_method="concurrent_error",
                        resolution_time_ms=0.0,
                        error=result,
                    )
                )
            else:
                final_results.append(result)

        return final_results

    def _get_cache_key(self, specification: DependencySpecification) -> str:
        """Generate cache key for a dependency specification."""
        if specification.pattern == DependencyPattern.STRING:
            return f"str:{specification.identifier}"
        else:
            type_name = getattr(
                specification.identifier, "__name__", str(specification.identifier)
            )
            return f"{specification.pattern.value}:{type_name}"

    def _get_cached_result(
        self, specification: DependencySpecification
    ) -> DependencyResolutionResult | None:
        """Get cached resolution result if available and not expired."""
        cache_key = self._get_cache_key(specification)

        if cache_key not in self._resolution_cache:
            return None

        timestamp = self._cache_timestamps.get(cache_key, 0)
        if time.time() - timestamp > self.cache_ttl_seconds:
            # Cache expired
            del self._resolution_cache[cache_key]
            del self._cache_timestamps[cache_key]
            return None

        cached_result = self._resolution_cache[cache_key]
        # Create a new result object to avoid modifying cached data
        return DependencyResolutionResult(
            specification=specification,
            instance=cached_result.instance,
            success=cached_result.success,
            resolution_method=f"cached_{cached_result.resolution_method}",
            resolution_time_ms=0.0,  # Cache hit is essentially instant
            error=cached_result.error,
            fallback_used=cached_result.fallback_used,
        )

    def _cache_result(
        self, specification: DependencySpecification, result: DependencyResolutionResult
    ) -> None:
        """Cache a successful resolution result."""
        if not result.success:
            return

        cache_key = self._get_cache_key(specification)
        self._resolution_cache[cache_key] = result
        self._cache_timestamps[cache_key] = time.time()

    def clear_cache(self) -> None:
        """Clear all cached results."""
        self._resolution_cache.clear()
        self._cache_timestamps.clear()
        self._legacy_cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "cached_results": len(self._resolution_cache),
            "legacy_cached_results": len(self._legacy_cache),
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "caching_enabled": self.enable_caching,
        }
