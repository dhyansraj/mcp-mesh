"""Service proxy interfaces and types for MCP Mesh dynamic proxy generation."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol

from .method_metadata import MethodMetadata, ServiceContract


class ServiceProxyProtocol(Protocol):
    """Protocol defining the interface for service proxies."""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """Dynamically provide access to proxied methods."""
        ...


class MeshServiceProxyInterface(ABC):
    """Abstract base interface for MCP Mesh service proxies.

    This interface defines the contract that all service proxies must implement
    for dynamic method generation and remote service communication.
    """

    @abstractmethod
    def __init__(
        self, service_class: type, registry_client: Any, endpoint: str
    ) -> None:
        """Initialize the service proxy.

        Args:
            service_class: The class type to create a proxy for
            registry_client: Client for communicating with the registry
            endpoint: Service endpoint for remote communication
        """
        ...

    @abstractmethod
    def _generate_proxy_methods(self) -> None:
        """Generate proxy methods based on service contract from registry.

        This method should:
        1. Retrieve the service contract from the registry
        2. Generate proxy methods for each method in the contract
        3. Ensure 100% signature compatibility with the original class
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_service_contract(self) -> ServiceContract | None:
        """Get the service contract for this proxy.

        Returns:
            ServiceContract if available, None otherwise
        """
        ...


class ProxyGenerationError(Exception):
    """Exception raised when proxy generation fails."""

    pass


class RemoteInvocationError(Exception):
    """Exception raised when remote method invocation fails."""

    pass


class ServiceContractError(Exception):
    """Exception raised when service contract is invalid or missing."""

    pass
