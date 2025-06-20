"""MCP Mesh Service Proxy Implementation.

Provides dynamic proxy generation for remote service method calls through MCP protocol.
"""

import asyncio
import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp_mesh import (
    MeshServiceProxyInterface,
    MethodMetadata,
    ProxyGenerationError,
    RemoteInvocationError,
    ServiceContract,
    ServiceContractError,
)

from .exceptions import RegistryConnectionError
from .registry_client import RegistryClient


class MeshServiceProxy(MeshServiceProxyInterface):
    """Dynamic proxy for remote service method calls via MCP protocol.

    This class generates proxy methods that maintain 100% signature compatibility
    with the original service class while routing calls through the MCP protocol.
    """

    def __init__(
        self, service_class: type, registry_client: RegistryClient, endpoint: str
    ) -> None:
        """Initialize the service proxy.

        Args:
            service_class: The class type to create a proxy for
            registry_client: Client for communicating with the registry
            endpoint: Service endpoint for remote communication
        """
        self._service_class = service_class
        self._registry_client = registry_client
        self._endpoint = endpoint
        self._service_contract: ServiceContract | None = None
        self._logger = logging.getLogger(f"mesh_proxy.{service_class.__name__}")

        # Performance tracking
        self._call_count = 0
        self._error_count = 0
        self._total_latency = 0.0

        # Initialize the proxy
        self._initialize_proxy()

    def _initialize_proxy(self) -> None:
        """Initialize the proxy by loading service contract and generating methods."""
        try:
            # Load service contract from registry
            asyncio.create_task(self._load_service_contract())

            # Generate proxy methods
            self._generate_proxy_methods()

            self._logger.info(
                f"Initialized service proxy for {self._service_class.__name__} "
                f"with endpoint {self._endpoint}"
            )

        except Exception as e:
            raise ProxyGenerationError(
                f"Failed to initialize proxy for {self._service_class.__name__}: {str(e)}"
            ) from e

    async def _load_service_contract(self) -> None:
        """Load service contract from the registry."""
        try:
            # For now, just extract contract from the class directly
            # In future, this could load from registry via registry_client
            self._service_contract = await self._extract_contract_from_class()

        except Exception as e:
            self._logger.error(f"Failed to load service contract: {str(e)}")
            raise ServiceContractError(
                f"Unable to load service contract: {str(e)}"
            ) from e

    async def _extract_contract_from_class(self) -> ServiceContract:
        """Extract service contract directly from the class definition."""
        contract = ServiceContract(
            service_name=self._service_class.__name__.lower(),
            description=f"Auto-generated contract for {self._service_class.__name__}",
        )

        # Extract methods from the class
        for name, method in inspect.getmembers(self._service_class, inspect.isfunction):
            if not name.startswith("_"):  # Skip private methods
                try:
                    metadata = self._extract_method_metadata(name, method)
                    contract.add_method(metadata)
                except Exception as e:
                    self._logger.warning(
                        f"Failed to extract metadata for {name}: {str(e)}"
                    )

        return contract

    def _extract_method_metadata(
        self, method_name: str, method: Callable
    ) -> MethodMetadata:
        """Extract method metadata from a callable."""
        signature = inspect.signature(method)

        # Create method metadata
        metadata = MethodMetadata(
            method_name=method_name,
            signature=signature,
            docstring=inspect.getdoc(method) or "",
            is_async=asyncio.iscoroutinefunction(method),
        )

        return metadata

    def _generate_proxy_methods(self) -> None:
        """Generate proxy methods based on service contract from registry."""
        if not self._service_contract:
            self._logger.warning(
                "No service contract available, cannot generate proxy methods"
            )
            return

        methods_generated = 0

        for method_name, metadata in self._service_contract.methods.items():
            try:
                proxy_method = self._create_proxy_method(method_name, metadata)
                setattr(self, method_name, proxy_method)
                methods_generated += 1

                self._logger.debug(f"Generated proxy method: {method_name}")

            except Exception as e:
                self._logger.error(
                    f"Failed to generate proxy method {method_name}: {str(e)}"
                )
                raise ProxyGenerationError(
                    f"Failed to generate method {method_name}: {str(e)}"
                ) from e

        self._logger.info(f"Generated {methods_generated} proxy methods")

    def _create_proxy_method(
        self, method_name: str, metadata: MethodMetadata
    ) -> Callable:
        """Create a single proxy method from method metadata.

        Args:
            method_name: Name of the method to create
            metadata: Method metadata containing signature and type information

        Returns:
            Callable proxy method that matches the original signature
        """
        # Extract signature information
        signature = metadata.signature
        is_async = metadata.is_async

        if is_async:
            # Create async proxy method
            @wraps(self._async_method_template)
            async def async_proxy_method(*args, **kwargs):
                return await self._invoke_remote_method(
                    method_name, args, kwargs, metadata
                )

            # Set the correct signature
            async_proxy_method.__signature__ = signature
            async_proxy_method.__name__ = method_name
            async_proxy_method.__doc__ = metadata.docstring

            return async_proxy_method
        else:
            # Create sync proxy method
            @wraps(self._sync_method_template)
            def sync_proxy_method(*args, **kwargs):
                # For sync methods, we need to handle the async call
                return asyncio.run(
                    self._invoke_remote_method(method_name, args, kwargs, metadata)
                )

            # Set the correct signature
            sync_proxy_method.__signature__ = signature
            sync_proxy_method.__name__ = method_name
            sync_proxy_method.__doc__ = metadata.docstring

            return sync_proxy_method

    async def _async_method_template(self, *args, **kwargs):
        """Template for async proxy methods."""
        pass

    def _sync_method_template(self, *args, **kwargs):
        """Template for sync proxy methods."""
        pass

    async def _invoke_remote_method(
        self, method_name: str, args: tuple, kwargs: dict, metadata: MethodMetadata
    ) -> Any:
        """Invoke a method on the remote service via MCP protocol.

        Args:
            method_name: Name of the method to invoke
            args: Positional arguments
            kwargs: Keyword arguments
            metadata: Method metadata for validation and type conversion

        Returns:
            Result from the remote method invocation
        """
        start_time = asyncio.get_event_loop().time()

        try:
            self._call_count += 1

            # Validate arguments against method signature
            self._validate_arguments(method_name, args, kwargs, metadata)

            # Prepare the MCP protocol call
            call_data = self._prepare_mcp_call(method_name, args, kwargs, metadata)

            # Make the remote call with retry logic
            result = await self._make_remote_call_with_retry(call_data)

            # Process and validate the result
            processed_result = self._process_result(result, metadata)

            # Update performance metrics
            latency = asyncio.get_event_loop().time() - start_time
            self._total_latency += latency

            self._logger.debug(
                f"Remote call to {method_name} completed in {latency:.3f}s"
            )

            return processed_result

        except Exception as e:
            self._error_count += 1
            latency = asyncio.get_event_loop().time() - start_time

            self._logger.error(
                f"Remote call to {method_name} failed after {latency:.3f}s: {str(e)}"
            )

            raise RemoteInvocationError(
                f"Failed to invoke {method_name} on remote service: {str(e)}"
            ) from e

    def _validate_arguments(
        self, method_name: str, args: tuple, kwargs: dict, metadata: MethodMetadata
    ) -> None:
        """Validate arguments against method signature."""
        try:
            # Use the signature to bind arguments
            bound_args = metadata.signature.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Additional validation could be added here
            # e.g., type checking, range validation, etc.

        except TypeError as e:
            raise RemoteInvocationError(
                f"Invalid arguments for {method_name}: {str(e)}"
            ) from e

    def _prepare_mcp_call(
        self, method_name: str, args: tuple, kwargs: dict, metadata: MethodMetadata
    ) -> dict[str, Any]:
        """Prepare MCP protocol call data."""
        return {
            "method": method_name,
            "args": args,
            "kwargs": kwargs,
            "service_class": self._service_class.__name__,
            "endpoint": self._endpoint,
            "metadata": metadata.to_dict(),
            "timeout": metadata.timeout_hint,
        }

    async def _make_remote_call_with_retry(
        self, call_data: dict[str, Any], max_retries: int = 3
    ) -> Any:
        """Make remote call with retry logic."""
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                # In a real implementation, this would use actual MCP protocol
                # For now, simulate the remote call
                result = await self._simulate_mcp_call(call_data)
                return result

            except (TimeoutError, RegistryConnectionError) as e:
                last_exception = e
                if attempt < max_retries:
                    # Exponential backoff
                    delay = 2**attempt
                    self._logger.warning(
                        f"Remote call failed (attempt {attempt + 1}), retrying in {delay}s: {str(e)}"
                    )
                    await asyncio.sleep(delay)
                else:
                    break
            except Exception as e:
                # Non-retryable errors
                raise e

        raise RemoteInvocationError(
            f"Remote call failed after {max_retries + 1} attempts: {str(last_exception)}"
        )

    async def _simulate_mcp_call(self, call_data: dict[str, Any]) -> Any:
        """Simulate MCP protocol call - placeholder implementation."""
        # In real implementation, this would:
        # 1. Establish MCP connection to the endpoint
        # 2. Send the method call request
        # 3. Wait for and process the response
        # 4. Handle MCP protocol errors

        # For now, simulate a successful call
        await asyncio.sleep(0.01)  # Simulate network latency

        # Mock response based on method name
        method_name = call_data["method"]
        if method_name == "get_status":
            return {"status": "ok", "timestamp": "2024-01-01T00:00:00Z"}
        elif method_name == "process_data":
            return {"result": "processed", "items": len(call_data.get("args", []))}
        else:
            return {"success": True, "method": method_name}

    def _process_result(self, result: Any, metadata: MethodMetadata) -> Any:
        """Process and validate the result from remote call."""
        # Type validation and conversion could be added here
        # based on the method's return type annotation

        if metadata.return_type and metadata.return_type is not type(None):
            # In a real implementation, we could validate the return type
            pass

        return result

    def get_service_contract(self) -> ServiceContract | None:
        """Get the service contract for this proxy."""
        return self._service_contract

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get performance metrics for this proxy."""
        avg_latency = self._total_latency / max(self._call_count, 1)
        error_rate = self._error_count / max(self._call_count, 1)

        return {
            "service_class": self._service_class.__name__,
            "endpoint": self._endpoint,
            "total_calls": self._call_count,
            "total_errors": self._error_count,
            "error_rate": error_rate,
            "average_latency_seconds": avg_latency,
            "total_latency_seconds": self._total_latency,
        }

    async def close(self) -> None:
        """Clean up proxy resources."""
        if self._contract_tools:
            # Clean up contract tools resources if needed
            pass

        self._logger.info(f"Closed service proxy for {self._service_class.__name__}")


class MockContractTools:
    """Mock contract tools for graceful degradation when database is unavailable."""

    async def get_service_contract(self, class_type: type) -> ServiceContract | None:
        """Mock implementation that returns None."""
        return None
