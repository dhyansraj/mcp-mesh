"""
MCP Mesh type definitions for dependency injection.
"""

from collections.abc import AsyncIterator
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


class McpAgent(Protocol):
    """
    Protocol for Full MCP Agent proxies with complete MCP protocol support.

    This agent type provides access to the complete MCP protocol including:
    - Tools (call, list)
    - Resources (read, list)
    - Prompts (get, list)
    - Streaming tool calls

    Usage Examples:
        @mesh.tool(dependencies=[{"capability": "file_service"}])
        async def process_files(file_service: McpAgent) -> str:
            # Vanilla MCP Protocol usage (100% compatible)
            tools = await file_service.list_tools()
            resources = await file_service.list_resources()
            prompts = await file_service.list_prompts()

            # Read a specific resource
            config = await file_service.read_resource("file://config.json")

            # Get a prompt template
            prompt = await file_service.get_prompt("analysis_prompt", {"topic": "data"})

            # Basic tool call (McpMeshAgent compatibility)
            result = file_service({"action": "process"})

            # Streaming tool call (breakthrough feature)
            async for chunk in file_service.call_tool_streaming("process_large_file", {"file": "big.txt"}):
                print(chunk)

            return "Processing complete"

    This proxy provides full MCP protocol access while maintaining backward compatibility
    with the basic __call__ interface from McpMeshAgent.
    """

    # Basic compatibility with McpMeshAgent
    def __call__(self, arguments: dict[str, Any] | None = None) -> Any:
        """Call the bound remote function (McpMeshAgent compatibility)."""
        ...

    def invoke(self, arguments: dict[str, Any] | None = None) -> Any:
        """Explicitly invoke the bound remote function (McpMeshAgent compatibility)."""
        ...

    # Vanilla MCP Protocol Methods (100% compatibility)
    async def list_tools(self) -> list:
        """List available tools from remote agent (vanilla MCP method)."""
        ...

    async def list_resources(self) -> list:
        """List available resources from remote agent (vanilla MCP method)."""
        ...

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent (vanilla MCP method)."""
        ...

    async def list_prompts(self) -> list:
        """List available prompts from remote agent (vanilla MCP method)."""
        ...

    async def get_prompt(self, name: str, arguments: dict | None = None) -> Any:
        """Get prompt template from remote agent (vanilla MCP method)."""
        ...

    # Streaming Support - THE BREAKTHROUGH METHOD!
    async def call_tool_streaming(
        self, name: str, arguments: dict | None = None
    ) -> AsyncIterator[dict]:
        """
        Call a tool with streaming response using FastMCP's text/event-stream.

        This enables multihop streaming (A→B→C chains) by leveraging FastMCP's
        built-in streaming support with Accept: text/event-stream header.

        Args:
            name: Tool name to call
            arguments: Tool arguments

        Yields:
            Streaming response chunks as dictionaries
        """
        ...

    # Phase 6: Explicit Session Management
    async def create_session(self) -> str:
        """
        Create a new session and return session ID.

        For Phase 6 explicit session management. In Phase 8, this will be
        automated based on @mesh.tool(session_required=True) annotations.

        Returns:
            New session ID string
        """
        ...

    async def call_with_session(self, session_id: str, **kwargs) -> Any:
        """
        Call tool with explicit session ID for stateful operations.

        This ensures all calls with the same session_id route to the same
        agent instance for session affinity.

        Args:
            session_id: Session ID to include in request headers
            **kwargs: Tool arguments to pass

        Returns:
            Tool response
        """
        ...

    async def close_session(self, session_id: str) -> bool:
        """
        Close session and cleanup session state.

        Args:
            session_id: Session ID to close

        Returns:
            True if session was closed successfully
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
            Custom Pydantic core schema for McpAgent.

            Similar to McpMeshAgent, this makes McpAgent parameters appear as
            optional/nullable in MCP schemas, preventing serialization errors
            while maintaining type safety for dependency injection.
            """
            # Treat McpAgent as an optional Any type for MCP serialization
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
