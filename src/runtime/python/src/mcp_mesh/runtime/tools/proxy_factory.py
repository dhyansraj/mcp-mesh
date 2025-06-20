"""Service Proxy Factory and Utilities.

Provides factory functions and utilities for creating and managing service proxies
with dynamic class generation, type preservation, and runtime validation.
"""

import asyncio
import inspect
import logging
import types
from typing import Any, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from mcp_mesh import (
    MethodMetadata,
    ProxyGenerationError,
    ServiceContract,
    ServiceContractError,
)

from ..shared.registry_client import RegistryClient
from ..shared.service_proxy import MeshServiceProxy
from ..shared.types import EndpointInfo

T = TypeVar("T")

logger = logging.getLogger(__name__)


class TypeValidator:
    """Runtime type validation for proxy methods."""

    @staticmethod
    def validate_type(
        value: Any, expected_type: type, param_name: str = "parameter"
    ) -> bool:
        """Validate a value against an expected type.

        Args:
            value: Value to validate
            expected_type: Expected type
            param_name: Parameter name for error messages

        Returns:
            True if validation passes

        Raises:
            TypeError: If validation fails
        """
        try:
            # Handle None values for Optional types
            if value is None:
                origin = get_origin(expected_type)
                if origin is Union:
                    args = get_args(expected_type)
                    if type(None) in args:
                        return True
                return expected_type is type(None)

            # Handle Union types (including Optional)
            origin = get_origin(expected_type)
            if origin is Union:
                args = get_args(expected_type)
                for arg_type in args:
                    if arg_type is type(None):
                        continue
                    try:
                        if TypeValidator.validate_type(value, arg_type, param_name):
                            return True
                    except TypeError:
                        continue
                raise TypeError(f"{param_name} does not match any type in Union")

            # Handle generic types
            if origin is not None:
                if origin is list:
                    if not isinstance(value, list):
                        raise TypeError(f"{param_name} must be a list")
                    args = get_args(expected_type)
                    if args:
                        for item in value:
                            TypeValidator.validate_type(
                                item, args[0], f"{param_name} item"
                            )
                    return True

                elif origin is dict:
                    if not isinstance(value, dict):
                        raise TypeError(f"{param_name} must be a dict")
                    args = get_args(expected_type)
                    if len(args) == 2:
                        key_type, value_type = args
                        for k, v in value.items():
                            TypeValidator.validate_type(
                                k, key_type, f"{param_name} key"
                            )
                            TypeValidator.validate_type(
                                v, value_type, f"{param_name} value"
                            )
                    return True

            # Handle basic types
            if expected_type is Any:
                return True

            if not isinstance(value, expected_type):
                raise TypeError(
                    f"{param_name} must be of type {expected_type.__name__}, got {type(value).__name__}"
                )

            return True

        except Exception as e:
            if isinstance(e, TypeError):
                raise
            raise TypeError(f"Type validation failed for {param_name}: {str(e)}")

    @staticmethod
    def validate_method_args(
        args: tuple, kwargs: dict, metadata: MethodMetadata, method_name: str
    ) -> None:
        """Validate method arguments against method metadata.

        Args:
            args: Positional arguments
            kwargs: Keyword arguments
            metadata: Method metadata with type information
            method_name: Method name for error messages

        Raises:
            TypeError: If validation fails
        """
        try:
            # Bind arguments to signature
            bound_args = metadata.signature.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Validate each argument type
            for param_name, value in bound_args.arguments.items():
                if param_name in metadata.type_hints:
                    expected_type = metadata.type_hints[param_name]
                    TypeValidator.validate_type(
                        value, expected_type, f"{method_name}.{param_name}"
                    )

        except Exception as e:
            raise TypeError(f"Argument validation failed for {method_name}: {str(e)}")

    @staticmethod
    def validate_return_value(
        value: Any, metadata: MethodMetadata, method_name: str
    ) -> Any:
        """Validate return value against method metadata.

        Args:
            value: Return value to validate
            metadata: Method metadata with return type information
            method_name: Method name for error messages

        Returns:
            The validated return value

        Raises:
            TypeError: If validation fails
        """
        if metadata.return_type and metadata.return_type != type(None):
            TypeValidator.validate_type(
                value, metadata.return_type, f"{method_name} return value"
            )
        return value


class DynamicProxyGenerator:
    """Generates dynamic proxy classes with full type preservation."""

    def __init__(self, registry_client: RegistryClient):
        self.registry_client = registry_client
        self._class_cache: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.DynamicProxyGenerator")

    def generate_proxy_class(
        self,
        service_class: type[T],
        service_contract: ServiceContract,
        base_proxy: MeshServiceProxy,
    ) -> type[T]:
        """Generate a dynamic proxy class that matches the service class interface.

        Args:
            service_class: The original service class
            service_contract: Service contract with method metadata
            base_proxy: Base proxy instance for method delegation

        Returns:
            Generated proxy class with preserved type annotations
        """
        class_name = f"{service_class.__name__}Proxy"
        cache_key = f"{class_name}_{id(service_contract)}"

        # Check cache first
        if cache_key in self._class_cache:
            return self._class_cache[cache_key]

        # Get type hints from original class
        try:
            type_hints = get_type_hints(service_class)
        except (NameError, AttributeError):
            type_hints = {}
            self._logger.warning(
                f"Could not get type hints for {service_class.__name__}"
            )

        # Create class dictionary with all proxy methods
        class_dict = {
            "__module__": service_class.__module__,
            "__doc__": f"Dynamic proxy for {service_class.__name__}",
            "__annotations__": type_hints,
            "_service_class": service_class,
            "_service_contract": service_contract,
            "_base_proxy": base_proxy,
        }

        # Generate proxy methods for each method in the contract
        for method_name, metadata in service_contract.methods.items():
            proxy_method = self._create_proxy_method(method_name, metadata, base_proxy)
            class_dict[method_name] = proxy_method

        # Add any class methods or static methods from original class
        for name, method in inspect.getmembers(service_class):
            if name.startswith("_"):
                continue

            if isinstance(method, classmethod | staticmethod):
                class_dict[name] = method
            elif hasattr(method, "__func__") and isinstance(
                method.__func__, types.FunctionType
            ):
                # Handle bound methods
                if name not in class_dict:
                    # Create a fallback proxy method
                    fallback_metadata = self._extract_method_metadata(name, method)
                    fallback_proxy = self._create_proxy_method(
                        name, fallback_metadata, base_proxy
                    )
                    class_dict[name] = fallback_proxy

        # Create the dynamic class
        proxy_class = type(class_name, (object,), class_dict)

        # Preserve original class attributes for type checking
        proxy_class.__qualname__ = service_class.__qualname__
        if hasattr(service_class, "__type_params__"):
            proxy_class.__type_params__ = service_class.__type_params__

        # Cache the generated class
        self._class_cache[cache_key] = proxy_class

        self._logger.info(
            f"Generated dynamic proxy class {class_name} with {len(service_contract.methods)} methods"
        )

        return cast(type[T], proxy_class)

    def _create_proxy_method(
        self, method_name: str, metadata: MethodMetadata, base_proxy: MeshServiceProxy
    ) -> callable:
        """Create a single proxy method with full signature preservation.

        Args:
            method_name: Name of the method
            metadata: Method metadata with signature information
            base_proxy: Base proxy for method delegation

        Returns:
            Proxy method with preserved signature and type checking
        """
        # Get the original signature
        signature = metadata.signature
        is_async = metadata.is_async

        if is_async:
            # Create async proxy method
            async def async_proxy_method(*args, **kwargs):
                # Validate arguments
                TypeValidator.validate_method_args(args, kwargs, metadata, method_name)

                # Invoke the base proxy method
                result = await base_proxy._invoke_remote_method(
                    method_name, args, kwargs, metadata
                )

                # Validate return value
                return TypeValidator.validate_return_value(
                    result, metadata, method_name
                )

            # Preserve signature and metadata
            async_proxy_method.__signature__ = signature
            async_proxy_method.__name__ = method_name
            async_proxy_method.__doc__ = metadata.docstring
            async_proxy_method.__annotations__ = metadata.type_hints

            return async_proxy_method
        else:
            # Create sync proxy method
            def sync_proxy_method(*args, **kwargs):
                # Validate arguments
                TypeValidator.validate_method_args(args, kwargs, metadata, method_name)

                # Invoke the base proxy method (handle async in sync context)
                if asyncio.iscoroutinefunction(base_proxy._invoke_remote_method):
                    # Run in event loop
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Create a task for concurrent execution
                            loop.create_task(
                                base_proxy._invoke_remote_method(
                                    method_name, args, kwargs, metadata
                                )
                            )
                            # This is a limitation - sync methods called from async context
                            # In practice, this should be avoided
                            raise RuntimeError(
                                f"Cannot call sync proxy method {method_name} from async context. "
                                f"Use the async version instead."
                            )
                        else:
                            result = loop.run_until_complete(
                                base_proxy._invoke_remote_method(
                                    method_name, args, kwargs, metadata
                                )
                            )
                    except RuntimeError:
                        # No event loop running, create one
                        result = asyncio.run(
                            base_proxy._invoke_remote_method(
                                method_name, args, kwargs, metadata
                            )
                        )
                else:
                    result = base_proxy._invoke_remote_method(
                        method_name, args, kwargs, metadata
                    )

                # Validate return value
                return TypeValidator.validate_return_value(
                    result, metadata, method_name
                )

            # Preserve signature and metadata
            sync_proxy_method.__signature__ = signature
            sync_proxy_method.__name__ = method_name
            sync_proxy_method.__doc__ = metadata.docstring
            sync_proxy_method.__annotations__ = metadata.type_hints

            return sync_proxy_method

    def _extract_method_metadata(
        self, method_name: str, method: callable
    ) -> MethodMetadata:
        """Extract metadata from a method for fallback proxy creation."""
        signature = inspect.signature(method)

        return MethodMetadata(
            method_name=method_name,
            signature=signature,
            is_async=asyncio.iscoroutinefunction(method),
            docstring=inspect.getdoc(method) or "",
        )


class EnhancedProxyFactory:
    """Enhanced factory for creating service proxies with full type preservation."""

    def __init__(self, registry_client: RegistryClient | None = None):
        """Initialize the enhanced proxy factory.

        Args:
            registry_client: Optional registry client. If None, will create default.
        """
        self._registry_client = (
            registry_client or self._create_default_registry_client()
        )
        self._proxy_cache: dict[str, Any] = {}
        self._class_cache: dict[str, type] = {}
        self._logger = logging.getLogger("enhanced_proxy_factory")
        self._proxy_generator = DynamicProxyGenerator(self._registry_client)

    def create_service_proxy(self, service_class: type[T]) -> T:
        """Create a service proxy for the given class.

        Args:
            service_class: The class to create a proxy for

        Returns:
            Proxy instance with the same interface as service_class

        Raises:
            ProxyGenerationError: If proxy creation fails
        """
        try:
            # Resolve service endpoint
            endpoint_info = self.resolve_service_endpoint(service_class)

            # Generate cache key
            cache_key = f"{service_class.__name__}:{endpoint_info.url}"

            # Check cache first
            if cache_key in self._proxy_cache:
                self._logger.debug(f"Returning cached proxy for {cache_key}")
                return self._proxy_cache[cache_key]

            # Create base proxy
            base_proxy = MeshServiceProxy(
                service_class=service_class,
                registry_client=self._registry_client,
                endpoint=endpoint_info.url,
            )

            # Get service contract
            service_contract = base_proxy.get_service_contract()
            if not service_contract:
                raise ServiceContractError(
                    f"No service contract found for {service_class.__name__}"
                )

            # Generate dynamic proxy class
            proxy_class = self._proxy_generator.generate_proxy_class(
                service_class, service_contract, base_proxy
            )

            # Create proxy instance
            proxy_instance = proxy_class()

            # Cache the proxy
            self._proxy_cache[cache_key] = proxy_instance

            self._logger.info(f"Created enhanced proxy for {service_class.__name__}")

            return proxy_instance

        except Exception as e:
            raise ProxyGenerationError(
                f"Failed to create service proxy for {service_class.__name__}: {str(e)}"
            )

    def resolve_service_endpoint(self, service_class: type) -> EndpointInfo:
        """Resolve service endpoint information for a service class.

        Args:
            service_class: The service class to resolve endpoint for

        Returns:
            EndpointInfo with resolved endpoint details

        Raises:
            ServiceContractError: If endpoint cannot be resolved
        """
        try:
            # In a real implementation, this would query the registry
            # For now, create a mock endpoint info
            service_name = service_class.__name__.lower()

            # Check for explicit endpoint configuration
            if hasattr(service_class, "_proxy_endpoint"):
                url = service_class._proxy_endpoint
            else:
                # Default endpoint resolution
                url = f"mcp://localhost:8080/{service_name}"

            return EndpointInfo(
                url=url,
                service_name=service_name,
                service_version="1.0.0",
                protocol="mcp",
            )

        except Exception as e:
            raise ServiceContractError(
                f"Failed to resolve endpoint for {service_class.__name__}: {str(e)}"
            )

    def validate_proxy_compatibility(
        self, proxy: Any, contract: ServiceContract
    ) -> bool:
        """Validate that a proxy is compatible with a service contract.

        Args:
            proxy: The proxy instance to validate
            contract: The service contract to validate against

        Returns:
            True if proxy is compatible, False otherwise
        """
        try:
            # Check if proxy has the required methods
            for method_name, metadata in contract.methods.items():
                if not hasattr(proxy, method_name):
                    self._logger.warning(f"Proxy missing method: {method_name}")
                    return False

                # Check method signature compatibility
                proxy_method = getattr(proxy, method_name)
                proxy_signature = inspect.signature(proxy_method)

                # Compare signatures
                if not self._signatures_compatible(proxy_signature, metadata.signature):
                    self._logger.warning(f"Method signature mismatch for {method_name}")
                    return False

            # Verify type hints preservation
            if hasattr(proxy, "__annotations__"):
                pass
                # Additional type hint validation could be added here

            return True

        except Exception as e:
            self._logger.error(f"Proxy compatibility validation failed: {str(e)}")
            return False

    def _signatures_compatible(
        self, proxy_sig: inspect.Signature, contract_sig: inspect.Signature
    ) -> bool:
        """Check if two signatures are compatible."""
        try:
            # Compare parameter names and types
            proxy_params = proxy_sig.parameters
            contract_params = contract_sig.parameters

            if len(proxy_params) != len(contract_params):
                return False

            for name, contract_param in contract_params.items():
                if name not in proxy_params:
                    return False

                proxy_param = proxy_params[name]

                # Check parameter kinds match
                if proxy_param.kind != contract_param.kind:
                    return False

                # Check annotations match (if available)
                if (
                    proxy_param.annotation != inspect.Parameter.empty
                    and contract_param.annotation != inspect.Parameter.empty
                ) and proxy_param.annotation != contract_param.annotation:
                    return False

            # Check return annotations
            return not (
                (
                    proxy_sig.return_annotation != inspect.Signature.empty
                    and contract_sig.return_annotation != inspect.Signature.empty
                )
                and proxy_sig.return_annotation != contract_sig.return_annotation
            )

        except Exception:
            return False

    def _create_default_registry_client(self) -> RegistryClient:
        """Create a default registry client."""
        try:
            return RegistryClient()
        except Exception as e:
            self._logger.warning(f"Failed to create registry client: {str(e)}")
            return RegistryClient(url="http://localhost:8080")


# Global factory instance
_default_factory: EnhancedProxyFactory | None = None


def get_proxy_factory() -> EnhancedProxyFactory:
    """Get the global enhanced proxy factory instance.

    Returns:
        Global EnhancedProxyFactory instance
    """
    global _default_factory
    if _default_factory is None:
        _default_factory = EnhancedProxyFactory()
    return _default_factory


def create_service_proxy(service_class: type[T]) -> T:
    """Create a service proxy with full type preservation and validation.

    Args:
        service_class: The class to create a proxy for

    Returns:
        Proxy instance with the same interface as service_class

    Example:
        >>> class MyService:
        ...     def process_data(self, data: str) -> dict:
        ...         pass
        >>>
        >>> proxy = create_service_proxy(MyService)
        >>> result = proxy.process_data("test")  # Full type checking and autocomplete
    """
    factory = get_proxy_factory()
    return factory.create_service_proxy(service_class)


def resolve_service_endpoint(service_class: type) -> EndpointInfo:
    """Resolve service endpoint information for a service class.

    Args:
        service_class: The service class to resolve endpoint for

    Returns:
        EndpointInfo with resolved endpoint details
    """
    factory = get_proxy_factory()
    return factory.resolve_service_endpoint(service_class)


def validate_proxy_compatibility(proxy: Any, contract: ServiceContract) -> bool:
    """Validate that a proxy is compatible with a service contract.

    Args:
        proxy: The proxy instance to validate
        contract: The service contract to validate against

    Returns:
        True if proxy is compatible, False otherwise
    """
    factory = get_proxy_factory()
    return factory.validate_proxy_compatibility(proxy, contract)


def round_trip_type_test(service_class: type[T]) -> bool:
    """Test that type hints are preserved through proxy generation.

    This function creates a proxy and verifies that all type information
    is preserved exactly as in the original class.

    Args:
        service_class: The service class to test

    Returns:
        True if 100% type hint preservation is verified
    """
    try:
        # Create proxy
        proxy = create_service_proxy(service_class)

        # Get original type hints
        try:
            original_hints = get_type_hints(service_class)
        except (NameError, AttributeError):
            original_hints = getattr(service_class, "__annotations__", {})

        # Get proxy type hints
        try:
            proxy_hints = get_type_hints(type(proxy))
        except (NameError, AttributeError):
            proxy_hints = getattr(type(proxy), "__annotations__", {})

        # Compare type hints
        if original_hints != proxy_hints:
            logger.warning(f"Type hint mismatch for {service_class.__name__}")
            logger.debug(f"Original: {original_hints}")
            logger.debug(f"Proxy: {proxy_hints}")
            return False

        # Test method signatures
        for method_name in dir(service_class):
            if method_name.startswith("_"):
                continue

            original_method = getattr(service_class, method_name, None)
            proxy_method = getattr(proxy, method_name, None)

            if callable(original_method) and callable(proxy_method):
                original_sig = inspect.signature(original_method)
                proxy_sig = inspect.signature(proxy_method)

                if original_sig != proxy_sig:
                    logger.warning(f"Signature mismatch for {method_name}")
                    logger.debug(f"Original: {original_sig}")
                    logger.debug(f"Proxy: {proxy_sig}")
                    return False

        logger.info(f"Round-trip type test passed for {service_class.__name__}")
        return True

    except Exception as e:
        logger.error(
            f"Round-trip type test failed for {service_class.__name__}: {str(e)}"
        )
        return False


# Legacy compatibility functions
def create_typed_proxy(service_class: type[T], endpoint: str) -> T:
    """Create a strongly-typed service proxy (legacy compatibility).

    Args:
        service_class: The class to create a proxy for
        endpoint: Service endpoint (ignored in new implementation)

    Returns:
        Proxy instance typed as service_class
    """
    return create_service_proxy(service_class)


# Legacy ProxyFactory for backward compatibility
class ProxyFactory:
    """Legacy proxy factory for backward compatibility."""

    def __init__(self, registry_client: RegistryClient | None = None):
        self._enhanced_factory = EnhancedProxyFactory(registry_client)

    def create_proxy(
        self, service_class: type[T], endpoint: str, cache_key: str | None = None
    ) -> T:
        """Create a proxy (legacy interface)."""
        # Set custom endpoint if provided
        if endpoint:
            service_class._proxy_endpoint = endpoint

        try:
            return self._enhanced_factory.create_service_proxy(service_class)
        finally:
            # Clean up custom endpoint
            if hasattr(service_class, "_proxy_endpoint"):
                delattr(service_class, "_proxy_endpoint")

    def get_cached_proxy(self, cache_key: str):
        """Get cached proxy (legacy interface)."""
        return self._enhanced_factory._proxy_cache.get(cache_key)

    def remove_cached_proxy(self, cache_key: str) -> bool:
        """Remove cached proxy (legacy interface)."""
        if cache_key in self._enhanced_factory._proxy_cache:
            del self._enhanced_factory._proxy_cache[cache_key]
            return True
        return False

    def clear_cache(self) -> None:
        """Clear cache (legacy interface)."""
        self._enhanced_factory._proxy_cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache stats (legacy interface)."""
        return {
            "cached_proxies": len(self._enhanced_factory._proxy_cache),
            "cache_keys": list(self._enhanced_factory._proxy_cache.keys()),
        }

    async def validate_proxy(self, proxy) -> bool:
        """Validate proxy (legacy interface)."""
        # Try to get service contract
        if hasattr(proxy, "_base_proxy"):
            base_proxy = proxy._base_proxy
            contract = base_proxy.get_service_contract()
            if contract:
                return self._enhanced_factory.validate_proxy_compatibility(
                    proxy, contract
                )
        return False


async def validate_proxy_health(proxy) -> dict[str, Any]:
    """Validate proxy health (legacy compatibility)."""
    try:
        factory = get_proxy_factory()
        if hasattr(proxy, "_base_proxy"):
            base_proxy = proxy._base_proxy
            metrics = base_proxy.get_performance_metrics()
            contract = base_proxy.get_service_contract()

            is_valid = (
                await factory._enhanced_factory.validate_proxy_compatibility(
                    proxy, contract
                )
                if contract
                else False
            )

            return {
                "is_healthy": is_valid,
                "performance_metrics": metrics,
                "has_contract": contract is not None,
                "method_count": len(contract.methods) if contract else 0,
                "capabilities": contract.capabilities if contract else [],
            }
        else:
            return {
                "is_healthy": False,
                "error": "Proxy does not have base proxy",
                "performance_metrics": {},
                "has_contract": False,
                "method_count": 0,
                "capabilities": [],
            }
    except Exception as e:
        return {
            "is_healthy": False,
            "error": str(e),
            "performance_metrics": {},
            "has_contract": False,
            "method_count": 0,
            "capabilities": [],
        }


# Type-safe proxy creation decorators
def proxy_for(endpoint: str):
    """Decorator to mark a class for proxy creation.

    Args:
        endpoint: Service endpoint for remote communication

    Example:
        >>> @proxy_for("mcp://remote-service:8080")
        ... class MyServiceProxy:
        ...     pass  # This will become a proxy for MyService
    """

    def decorator(cls: type[T]) -> type[T]:
        cls._proxy_endpoint = endpoint
        cls._is_proxy_class = True
        return cls

    return decorator
