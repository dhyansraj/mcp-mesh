"""
MCP Mesh Registry Client

Compatibility wrapper that automatically chooses between generated and manual clients.

🤖 AI BEHAVIOR GUIDANCE:
This module provides backward compatibility while transitioning to generated clients.

PRIORITY ORDER:
1. Use GeneratedRegistryClient (from OpenAPI spec)
2. Fallback to manual implementation if generated not available

MIGRATION PLAN:
- Phase 1: Both clients available, generated preferred
- Phase 2: Only generated client (remove manual fallback)
- Phase 3: Direct import of generated client everywhere

TO COMPLETE MIGRATION:
1. Ensure all code uses this module (not direct imports)
2. Run 'make generate' to ensure generated client is available
3. Update imports to use GeneratedRegistryClient directly
4. Remove this compatibility wrapper
"""

from typing import Any

# Try to import generated client first
try:
    from .registry_client_generated import (
        GENERATED_CLIENT_AVAILABLE,
        GeneratedRegistryClient,
    )
except ImportError:
    GENERATED_CLIENT_AVAILABLE = False
    GeneratedRegistryClient = None

# Import manual client as fallback
try:
    from .registry_client_manual_deprecated import (
        RegistryClient as ManualRegistryClient,
    )

    MANUAL_CLIENT_AVAILABLE = True
except ImportError:
    MANUAL_CLIENT_AVAILABLE = False
    ManualRegistryClient = None

from .exceptions import RegistryConnectionError
from .types import HealthStatus


class RegistryClient:
    """
    Compatibility wrapper for registry clients.

    Automatically uses the best available client implementation:
    1. Generated OpenAPI client (preferred)
    2. Manual implementation (fallback)
    """

    def __init__(self, url: str = None, timeout: int = 30, **kwargs):
        self.url = url
        self.timeout = timeout
        self.kwargs = kwargs

        # Choose implementation
        if GENERATED_CLIENT_AVAILABLE:
            print("🤖 Using generated OpenAPI registry client")
            self._client = GeneratedRegistryClient(url, timeout, **kwargs)
            self._client_type = "generated"
        elif MANUAL_CLIENT_AVAILABLE:
            print("⚠️  Using deprecated manual registry client")
            print("   Run 'make generate' to use the OpenAPI-generated client")
            self._client = ManualRegistryClient(url, timeout, **kwargs)
            self._client_type = "manual"
        else:
            raise RegistryConnectionError(
                "No registry client implementation available. "
                "Run 'make generate' to create generated client."
            )

    def get_client_type(self) -> str:
        """Get the type of client being used."""
        return self._client_type

    def is_using_generated_client(self) -> bool:
        """Check if using the generated OpenAPI client."""
        return self._client_type == "generated"

    # Delegate all methods to the underlying client
    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str | None = None,
    ) -> bool:
        """Register agent with the registry."""
        return await self._client.register_agent(
            agent_name, capabilities, dependencies, security_context
        )

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send heartbeat to registry."""
        return await self._client.send_heartbeat(health_status)

    async def send_heartbeat_with_response(
        self, health_status: HealthStatus
    ) -> dict[str, Any] | None:
        """Send heartbeat and return full response."""
        return await self._client.send_heartbeat_with_response(health_status)

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Get all registered agents."""
        return await self._client.get_all_agents()

    async def close(self) -> None:
        """Close the client."""
        if hasattr(self._client, "close"):
            await self._client.close()

    # Additional methods that might exist in manual client
    def __getattr__(self, name):
        """Delegate any other methods to the underlying client."""
        return getattr(self._client, name)


# Factory function for convenience
def create_registry_client(url: str = None, **kwargs) -> RegistryClient:
    """
    Create a registry client with automatic implementation selection.

    Args:
        url: Registry URL
        **kwargs: Additional client configuration

    Returns:
        RegistryClient instance using best available implementation
    """
    return RegistryClient(url, **kwargs)


# Aliases for compatibility
def create_generated_registry_client(url: str = None, **kwargs) -> RegistryClient:
    """
    DEPRECATED: Use create_registry_client() instead.

    This function now returns the same auto-selecting client.
    """
    return create_registry_client(url, **kwargs)


# Export the main class
__all__ = [
    "RegistryClient",
    "create_registry_client",
    "create_generated_registry_client",
    "GENERATED_CLIENT_AVAILABLE",
    "MANUAL_CLIENT_AVAILABLE",
]
