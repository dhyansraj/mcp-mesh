"""
Dependency Injection Tools

Tools for manual dependency resolution and injection, complementing the automatic
dependency injection provided by the @mesh_agent decorator.
"""

import inspect
import logging
from collections.abc import Callable
from typing import Any

from mcp_mesh import (
    DependencySpecification,
    DependencyValidationError,
    ValidationResult,
)

from ..shared.exceptions import MeshAgentError
from ..shared.registry_client import RegistryClient
from ..shared.service_discovery import ServiceDiscoveryService
from ..shared.unified_dependency_resolver import (
    MeshUnifiedDependencyResolver,
)

logger = logging.getLogger(__name__)


def resolve_dependency(
    dependency_spec: str | type,
    registry_client: RegistryClient = None,
    service_discovery: ServiceDiscoveryService = None,
    context: dict = None,
) -> Any:
    """
    Manually resolve a single dependency specification.

    This function provides direct access to the dependency resolution system
    used by @mesh_agent decorator for cases where manual control is needed.

    Args:
        dependency_spec: Dependency to resolve - can be:
            - String: "service_name" (registry lookup)
            - Type: ServiceInterface (interface-based resolution)
            - Concrete class: ConcreteService (direct instantiation)
        registry_client: Optional registry client for resolution
        service_discovery: Optional service discovery for enhanced resolution
        context: Optional context for resolution

    Returns:
        Resolved dependency instance

    Raises:
        MeshAgentError: If dependency cannot be resolved

    Example:
        # String dependency
        auth_service = resolve_dependency("auth_service")

        # Type dependency
        storage = resolve_dependency(StorageInterface)

        # Concrete class dependency
        oauth = resolve_dependency(OAuth2AuthService)
    """
    try:
        # Convert to dependency specification
        spec = _create_dependency_specification(dependency_spec)

        # Create resolver if we have registry components
        if registry_client or service_discovery:
            resolver = MeshUnifiedDependencyResolver(
                registry_client=registry_client,
                service_discovery=service_discovery,
                enable_caching=True,
            )

            # Resolve using unified resolver
            import asyncio

            try:
                # Try to get current event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create a task and run it
                    loop.create_task(resolver.resolve_dependency(spec, context))
                    # Note: This is a limitation - we can't await in sync function
                    # For now, return None and log warning
                    logger.warning(
                        "resolve_dependency called from async context - use async version"
                    )
                    return None
                else:
                    result = loop.run_until_complete(
                        resolver.resolve_dependency(spec, context)
                    )
            except RuntimeError:
                # No event loop, create one
                result = asyncio.run(resolver.resolve_dependency(spec, context))

            if result.success:
                return result.instance
            else:
                raise MeshAgentError(f"Failed to resolve dependency: {result.error}")
        else:
            # Simple resolution without registry
            return _simple_dependency_resolution(dependency_spec)

    except Exception as e:
        logger.error(f"Dependency resolution failed for {dependency_spec}: {e}")
        raise MeshAgentError(
            f"Could not resolve dependency {dependency_spec}: {e}"
        ) from e


async def resolve_dependency_async(
    dependency_spec: str | type,
    registry_client: RegistryClient = None,
    service_discovery: ServiceDiscoveryService = None,
    context: dict = None,
) -> Any:
    """
    Async version of resolve_dependency for use in async contexts.

    Args:
        dependency_spec: Dependency to resolve
        registry_client: Optional registry client for resolution
        service_discovery: Optional service discovery for enhanced resolution
        context: Optional context for resolution

    Returns:
        Resolved dependency instance

    Raises:
        MeshAgentError: If dependency cannot be resolved
    """
    try:
        # Convert to dependency specification
        spec = _create_dependency_specification(dependency_spec)

        # Create resolver if we have registry components
        if registry_client or service_discovery:
            resolver = MeshUnifiedDependencyResolver(
                registry_client=registry_client,
                service_discovery=service_discovery,
                enable_caching=True,
            )

            result = await resolver.resolve_dependency(spec, context)

            if result.success:
                return result.instance
            else:
                raise MeshAgentError(f"Failed to resolve dependency: {result.error}")
        else:
            # Simple resolution without registry
            return _simple_dependency_resolution(dependency_spec)

    except Exception as e:
        logger.error(f"Dependency resolution failed for {dependency_spec}: {e}")
        raise MeshAgentError(
            f"Could not resolve dependency {dependency_spec}: {e}"
        ) from e


def inject_dependencies(
    func: Callable,
    dependencies: list[Any],
    dependency_names: list[str] = None,
) -> Callable:
    """
    Create a wrapper function that injects the provided dependencies.

    This function allows manual dependency injection by wrapping a function
    and providing specific dependency instances to inject.

    Args:
        func: Function to wrap with dependency injection
        dependencies: List of dependency instances to inject
        dependency_names: Optional list of parameter names to map dependencies to.
                         If not provided, will use function signature inspection.

    Returns:
        Wrapped function with dependencies injected

    Example:
        # Original function
        def process_data(data_processor: DataProcessor, auth: AuthService):
            return data_processor.process(auth.get_user())

        # Create instances
        processor = DataProcessor()
        auth = AuthService()

        # Inject dependencies
        enhanced_func = inject_dependencies(
            process_data,
            [processor, auth],
            ["data_processor", "auth"]
        )

        # Call without providing dependencies
        result = enhanced_func()
    """
    try:
        # Get function signature
        signature = inspect.signature(func)
        parameters = list(signature.parameters.keys())

        # Determine dependency mapping
        if dependency_names:
            if len(dependency_names) != len(dependencies):
                raise MeshAgentError(
                    f"Dependency names count ({len(dependency_names)}) "
                    f"must match dependencies count ({len(dependencies)})"
                )
            dep_mapping = dict(zip(dependency_names, dependencies, strict=False))
        else:
            # Map dependencies to parameters in order
            if len(dependencies) > len(parameters):
                raise MeshAgentError(
                    f"Too many dependencies ({len(dependencies)}) "
                    f"for function parameters ({len(parameters)})"
                )
            dep_mapping = dict(
                zip(parameters[: len(dependencies)], dependencies, strict=False)
            )

        # Create wrapper function
        if inspect.iscoroutinefunction(func):

            async def async_wrapper(*args, **kwargs):
                # Inject dependencies that aren't already provided
                injected_kwargs = kwargs.copy()
                for param_name, dependency in dep_mapping.items():
                    if param_name not in injected_kwargs:
                        injected_kwargs[param_name] = dependency

                return await func(*args, **injected_kwargs)

            return async_wrapper
        else:

            def sync_wrapper(*args, **kwargs):
                # Inject dependencies that aren't already provided
                injected_kwargs = kwargs.copy()
                for param_name, dependency in dep_mapping.items():
                    if param_name not in injected_kwargs:
                        injected_kwargs[param_name] = dependency

                return func(*args, **injected_kwargs)

            return sync_wrapper

    except Exception as e:
        logger.error(f"Failed to inject dependencies into {func.__name__}: {e}")
        raise MeshAgentError(f"Dependency injection failed: {e}") from e


def validate_dependency_types(dependencies: list[Any]) -> ValidationResult:
    """
    Validate a list of dependency instances for compatibility and correctness.

    This function performs comprehensive validation of dependency instances,
    checking for common issues and compatibility problems.

    Args:
        dependencies: List of dependency instances to validate

    Returns:
        ValidationResult with success status and any validation errors

    Example:
        dependencies = [auth_service, data_processor, file_handler]
        result = validate_dependency_types(dependencies)

        if not result.is_valid:
            for error in result.errors:
                print(f"Validation error: {error.message}")
        else:
            print("All dependencies are valid")
    """
    try:
        errors = []

        # Validate each dependency
        for i, dependency in enumerate(dependencies):
            try:
                # Check if dependency is None
                if dependency is None:
                    errors.append(
                        DependencyValidationError(
                            specification=None,
                            error_type="null_dependency",
                            message=f"Dependency at index {i} is None",
                            suggestions=["Ensure dependency is properly instantiated"],
                        )
                    )
                    continue

                # Check if dependency is callable (has methods)
                if not hasattr(dependency, "__class__"):
                    errors.append(
                        DependencyValidationError(
                            specification=None,
                            error_type="invalid_type",
                            message=f"Dependency at index {i} is not a proper object",
                            suggestions=["Ensure dependency is a class instance"],
                        )
                    )
                    continue

                # Check for common interface compliance
                dependency_type = type(dependency)

                # Validate that it's not a built-in type (unless it's a wrapper)
                if dependency_type.__module__ == "builtins" and not isinstance(
                    dependency, str | int | float | bool
                ):
                    errors.append(
                        DependencyValidationError(
                            specification=None,
                            error_type="builtin_type",
                            message=f"Dependency at index {i} is a built-in type: {dependency_type.__name__}",
                            suggestions=[
                                "Use proper service classes instead of built-in types"
                            ],
                        )
                    )

                # Check for basic callable methods
                public_methods = [
                    method
                    for method in dir(dependency)
                    if not method.startswith("_")
                    and callable(getattr(dependency, method))
                ]

                if not public_methods:
                    errors.append(
                        DependencyValidationError(
                            specification=None,
                            error_type="no_public_methods",
                            message=f"Dependency at index {i} ({dependency_type.__name__}) has no public methods",
                            suggestions=[
                                "Ensure dependency class implements required methods"
                            ],
                        )
                    )

            except Exception as e:
                errors.append(
                    DependencyValidationError(
                        specification=None,
                        error_type="validation_error",
                        message=f"Failed to validate dependency at index {i}: {e}",
                        suggestions=["Check dependency instantiation and type"],
                    )
                )

        # Check for duplicate instances (by type)
        type_counts = {}
        for i, dependency in enumerate(dependencies):
            if dependency is not None:
                dep_type = type(dependency)
                if dep_type in type_counts:
                    errors.append(
                        DependencyValidationError(
                            specification=None,
                            error_type="duplicate_type",
                            message=f"Multiple instances of {dep_type.__name__} found at indices {type_counts[dep_type]} and {i}",
                            suggestions=[
                                "Ensure each dependency type is only provided once"
                            ],
                        )
                    )
                else:
                    type_counts[dep_type] = i

        # Create validation result
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            validated_count=len(dependencies),
            error_count=len(errors),
        )

    except Exception as e:
        logger.error(f"Dependency validation failed: {e}")
        return ValidationResult(
            is_valid=False,
            errors=[
                DependencyValidationError(
                    specification=None,
                    error_type="validation_system_error",
                    message=f"Validation system error: {e}",
                    suggestions=["Check validation inputs and system state"],
                )
            ],
            validated_count=len(dependencies) if dependencies else 0,
            error_count=1,
        )


def _create_dependency_specification(
    dependency_spec: str | type,
) -> DependencySpecification:
    """Convert a dependency specification to a DependencySpecification object."""
    if isinstance(dependency_spec, str):
        return DependencySpecification.from_string(dependency_spec)
    elif inspect.isclass(dependency_spec):
        # Determine if it's a protocol or concrete class
        if hasattr(dependency_spec, "_is_protocol"):
            return DependencySpecification.from_protocol(dependency_spec)
        else:
            return DependencySpecification.from_concrete_class(dependency_spec)
    else:
        raise MeshAgentError(
            f"Unsupported dependency specification type: {type(dependency_spec)}"
        )


def _simple_dependency_resolution(dependency_spec: str | type) -> Any:
    """Simple dependency resolution without registry components."""
    if isinstance(dependency_spec, str):
        # String dependencies require registry - return None
        logger.warning(
            f"Cannot resolve string dependency '{dependency_spec}' without registry"
        )
        return None
    elif inspect.isclass(dependency_spec):
        # Try to instantiate the class
        try:
            # Check if it requires parameters
            signature = inspect.signature(dependency_spec.__init__)
            required_params = [
                p
                for name, p in signature.parameters.items()
                if name != "self" and p.default == inspect.Parameter.empty
            ]

            if required_params:
                logger.warning(
                    f"Cannot instantiate {dependency_spec.__name__} - requires parameters: "
                    f"{[p.name for p in required_params]}"
                )
                return None

            # Instantiate without parameters
            return dependency_spec()

        except Exception as e:
            logger.warning(f"Failed to instantiate {dependency_spec.__name__}: {e}")
            return None
    else:
        logger.warning(f"Cannot resolve dependency of type {type(dependency_spec)}")
        return None
