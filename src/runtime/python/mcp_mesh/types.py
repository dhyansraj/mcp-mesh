"""
MCP Mesh type definitions for dependency injection.
"""

from typing import Any, Protocol

try:
    from pydantic_core import core_schema

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


class McpMeshAgent(Protocol):
    """
    Protocol for MCP Mesh agent proxies used in dependency injection.

    Each proxy is bound to a specific remote function and knows exactly what to call.
    The registry handles function-to-function mapping, so users don't need to specify function names.

    Usage Examples:
        @mesh.tool(dependencies=[{"capability": "get_current_date"}])  # Function name as capability
        def greet(name: str, date_getter: McpMeshAgent) -> str:
            # Simple call - proxy knows which remote function to invoke
            current_date = date_getter()

            # With arguments
            current_date = date_getter({"format": "ISO"})

            # Explicit invoke (same as call)
            current_date = date_getter.invoke({"format": "ISO"})

            return f"Hello {name}, today is {current_date}"

    The proxy is bound to one specific remote function, eliminating the need to specify function names.
    """

    def __call__(self, arguments: dict[str, Any] = None) -> Any:
        """
        Call the bound remote function.

        Args:
            arguments: Arguments to pass to the remote function (optional)

        Returns:
            Result from the remote function call
        """
        ...

    def invoke(self, arguments: dict[str, Any] = None) -> Any:
        """
        Explicitly invoke the bound remote function.

        This method provides the same functionality as __call__ but with
        an explicit method name for those who prefer it.

        Args:
            arguments: Arguments to pass to the remote function (optional)

        Returns:
            Result from the remote function call

        Example:
            result = date_getter.invoke({"format": "ISO"})
            # Same as: result = date_getter({"format": "ISO"})
        """
        ...

    if PYDANTIC_AVAILABLE:

        @classmethod
        def __get_pydantic_core_schema__(
            cls,
            source_type: Any,
            handler: Any,
        ) -> core_schema.CoreSchema:
            """
            Custom Pydantic core schema for McpMeshAgent.

            This makes McpMeshAgent parameters appear as optional/nullable in MCP schemas,
            preventing serialization errors while maintaining type safety for dependency injection.

            The dependency injection system will replace None values with actual proxy objects
            at runtime, so MCP callers never need to provide these parameters.
            """
            # Treat McpMeshAgent as an optional Any type for MCP serialization
            return core_schema.with_default_schema(
                core_schema.nullable_schema(core_schema.any_schema()),
                default=None,
            )

    else:
        # Fallback for when pydantic-core is not available
        @classmethod
        def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> dict:
            return {
                "type": "default",
                "schema": {"type": "nullable", "schema": {"type": "any"}},
                "default": None,
            }
