"""
MCP Mesh type definitions for dependency injection.
"""

from collections.abc import AsyncIterator
from typing import Any, Optional, Protocol

try:
    from pydantic_core import core_schema

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


class McpMeshAgent(Protocol):
    """
    Unified MCP Mesh agent proxy using FastMCP's built-in client.

    This protocol now provides all MCP protocol features using FastMCP's superior client
    implementation, replacing both the old basic and advanced proxy types.

    Features:
    - All MCP protocol methods (tools, resources, prompts)
    - Streaming support with FastMCP's StreamableHttpTransport
    - Session management with notifications
    - Automatic redirect handling (fixes /mcp/ → /mcp issue)
    - CallToolResult objects with structured content parsing
    - Enhanced proxy configuration via kwargs

    Usage Examples:
        @mesh.tool(dependencies=["date-service"])
        def greet(name: str, date_service: McpMeshAgent) -> str:
            # Simple call - proxy knows which remote function to invoke
            current_date = date_service()

            # With arguments
            current_date = date_service({"format": "ISO"})

            # Explicit invoke (same as call)
            current_date = date_service.invoke({"format": "ISO"})

            return f"Hello {name}, today is {current_date}"

        @mesh.tool(dependencies=["file-service"])
        async def process_files(file_service: McpMeshAgent) -> str:
            # Full MCP Protocol usage
            tools = await file_service.list_tools()
            resources = await file_service.list_resources()
            prompts = await file_service.list_prompts()

            # Read a specific resource
            config = await file_service.read_resource("file://config.json")

            # Get a prompt template
            prompt = await file_service.get_prompt("analysis_prompt", {"topic": "data"})

            # Streaming tool call
            async for chunk in file_service.call_tool_streaming("process_large_file", {"file": "big.txt"}):
                print(chunk)

            return "Processing complete"

    The unified proxy provides all MCP protocol features while maintaining simple callable interface.
    """

    def __call__(self, arguments: Optional[dict[str, Any]] = None) -> Any:
        """
        Call the bound remote function.

        Args:
            arguments: Arguments to pass to the remote function (optional)

        Returns:
            Result from the remote function call (CallToolResult object)
        """
        ...

    def invoke(self, arguments: Optional[dict[str, Any]] = None) -> Any:
        """
        Explicitly invoke the bound remote function.

        This method provides the same functionality as __call__ but with
        an explicit method name for those who prefer it.

        Args:
            arguments: Arguments to pass to the remote function (optional)

        Returns:
            Result from the remote function call (CallToolResult object)

        Example:
            result = date_service.invoke({"format": "ISO"})
            # Same as: result = date_service({"format": "ISO"})
        """
        ...

    # Full MCP Protocol Methods - now available on all McpMeshAgent proxies
    async def list_tools(self) -> list:
        """List available tools from remote agent."""
        ...

    async def list_resources(self) -> list:
        """List available resources from remote agent."""
        ...

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent."""
        ...

    async def list_prompts(self) -> list:
        """List available prompts from remote agent."""
        ...

    async def get_prompt(self, name: str, arguments: Optional[dict] = None) -> Any:
        """Get prompt template from remote agent."""
        ...

    # Streaming Support using FastMCP's superior streaming capabilities
    async def call_tool_streaming(
        self, name: str, arguments: dict = None, progress_handler=None
    ) -> AsyncIterator[Any]:
        """
        Call a tool with streaming response using FastMCP's streaming support.

        Args:
            name: Tool name to call
            arguments: Tool arguments
            progress_handler: Optional progress handler for streaming

        Yields:
            Streaming response chunks
        """
        ...

    # Session Management using FastMCP's built-in session support
    async def create_session(self) -> str:
        """Create a new session and return session ID."""
        ...

    async def call_with_session(self, session_id: str, **kwargs) -> Any:
        """Call tool with explicit session ID for stateful operations."""
        ...

    async def close_session(self, session_id: str) -> bool:
        """Close session and cleanup session state."""
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
    DEPRECATED: Use McpMeshAgent instead.

    This type has been unified with McpMeshAgent. All features previously exclusive
    to McpAgent are now available in McpMeshAgent using FastMCP's superior client.

    Migration:
        # Old way (deprecated)
        def process_files(file_service: McpAgent) -> str:
            pass

        # New way (recommended)
        def process_files(file_service: McpMeshAgent) -> str:
            pass

    McpMeshAgent now provides all MCP protocol features including streaming,
    session management, and CallToolResult objects via FastMCP client.
    """

    # Basic compatibility with McpMeshAgent
    def __call__(self, arguments: Optional[dict[str, Any]] = None) -> Any:
        """Call the bound remote function (McpMeshAgent compatibility)."""
        ...

    def invoke(self, arguments: Optional[dict[str, Any]] = None) -> Any:
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

    async def get_prompt(self, name: str, arguments: Optional[dict] = None) -> Any:
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
