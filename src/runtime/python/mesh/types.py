"""
MCP Mesh type definitions for dependency injection.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

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


class MeshLlmAgent(Protocol):
    """
    LLM agent proxy with automatic agentic loop.

    This protocol defines the interface for LLM agents that are automatically injected
    by the @mesh.llm decorator. The proxy handles the entire agentic loop internally:
    - Tool formatting for provider (Claude, OpenAI, etc.)
    - LLM API calls
    - Tool execution via MCP proxies
    - Response parsing to Pydantic models

    The MeshLlmAgent is injected by the mesh framework and configured via the
    @mesh.llm decorator. Users only need to call the proxy with their message.

    Usage Example:
        from pydantic import BaseModel
        import mesh

        class ChatResponse(BaseModel):
            answer: str
            confidence: float

        @mesh.llm(
            filter={"capability": "document", "tags": ["pdf"]},
            provider="claude",
            model="claude-3-5-sonnet-20241022"
        )
        @mesh.tool(capability="chat")
        def chat(message: str, llm: MeshLlmAgent = None) -> ChatResponse:
            # Optional: Override system prompt
            llm.set_system_prompt("You are a helpful document assistant.")

            # Execute automatic agentic loop
            return llm(message)

    Configuration Hierarchy:
        - Decorator parameters provide defaults
        - Environment variables override decorator settings:
          * MESH_LLM_PROVIDER: Override provider
          * MESH_LLM_MODEL: Override model
          * ANTHROPIC_API_KEY: Claude API key
          * OPENAI_API_KEY: OpenAI API key
          * MESH_LLM_MAX_ITERATIONS: Override max iterations

    The proxy is automatically injected with:
        - Filtered tools from registry (based on @mesh.llm filter)
        - Provider configuration (provider, model, api_key)
        - Output type (inferred from function return annotation)
        - System prompt (from decorator or file)
    """

    def set_system_prompt(self, prompt: str) -> None:
        """
        Override the system prompt at runtime.

        Args:
            prompt: System prompt to use for LLM calls

        Example:
            llm.set_system_prompt("You are an expert document analyst.")
        """
        ...

    def __call__(self, message: str | list[dict[str, Any]], **kwargs) -> Any:
        """
        Execute automatic agentic loop and return typed response.

        This method handles the complete agentic loop:
        1. Format tools for provider (via LiteLLM)
        2. Call LLM API with tools
        3. If tool_use: execute via MCP proxies, loop back to LLM
        4. If final response: parse into output type (Pydantic model)
        5. Return typed response

        Args:
            message: Either:
                - str: Single user message (will be wrapped in messages array)
                - list[dict]: Full conversation history with messages in format
                  [{"role": "user|assistant|system", "content": "..."}]
            **kwargs: Additional context passed to LLM (provider-specific)

        Returns:
            Pydantic model instance (type inferred from function return annotation)

        Raises:
            MaxIterationsError: If max_iterations exceeded without final response
            ValidationError: If LLM response doesn't match output type schema
            ToolExecutionError: If tool execution fails during agentic loop

        Example (single-turn):
            response = llm("Analyze this document: /path/to/file.pdf")
            # Returns ChatResponse(answer="...", confidence=0.95)

        Example (multi-turn):
            messages = [
                {"role": "user", "content": "Hello, I need help with Python."},
                {"role": "assistant", "content": "I'd be happy to help! What do you need?"},
                {"role": "user", "content": "How do I read a file?"}
            ]
            response = llm(messages)
            # Returns ChatResponse with contextual answer
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
            Custom Pydantic core schema for MeshLlmAgent.

            This makes MeshLlmAgent parameters appear as optional/nullable in MCP schemas,
            preventing serialization errors while maintaining type safety for dependency injection.

            The MeshLlmAgentInjector will replace None values with actual proxy objects
            at runtime, so MCP callers never need to provide these parameters.
            """
            # Treat MeshLlmAgent as an optional Any type for MCP serialization
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


# Import BaseModel for MeshContextModel
try:
    from pydantic import BaseModel

    class MeshContextModel(BaseModel):
        """
        Base model for LLM prompt template contexts.

        Use this to create type-safe, validated context models for
        Jinja2 prompt templates in @mesh.llm decorated functions.

        The MeshContextModel provides:
        - Type safety via Pydantic validation
        - Field descriptions for LLM schema generation
        - Strict mode (extra fields forbidden)
        - Automatic .model_dump() for template rendering

        Example:
            from mesh import MeshContextModel
            from pydantic import Field

            class ChatContext(MeshContextModel):
                user_name: str = Field(description="Name of the user")
                domain: str = Field(description="Chat domain: support, sales, etc.")
                expertise_level: str = Field(
                    default="beginner",
                    description="User expertise: beginner, intermediate, expert"
                )

            @mesh.llm(
                system_prompt="file://prompts/chat.jinja2",
                context_param="ctx"
            )
            @mesh.tool(capability="chat")
            def chat(message: str, ctx: ChatContext, llm: MeshLlmAgent = None):
                return llm(message)  # Template auto-rendered with ctx!

        Field Descriptions in LLM Chains:
            When a specialist LLM agent has MeshContextModel parameters, the Field
            descriptions are extracted and included in the tool schema sent to
            calling LLM agents. This helps orchestrator LLMs construct context
            objects correctly.

            Without descriptions:
                {"domain": "string"}  # LLM doesn't know what this means

            With descriptions:
                {"domain": {"type": "string", "description": "Chat domain: support, sales"}}
                # LLM understands what to provide!

        Template Rendering:
            When used with @mesh.llm(system_prompt="file://..."), the context is
            automatically converted to a dict via .model_dump() and passed to the
            Jinja2 template renderer.
        """

        class Config:
            extra = "forbid"  # Strict mode - reject unexpected fields

except ImportError:
    # Fallback if Pydantic not available (should not happen in practice)
    class MeshContextModel:  # type: ignore
        """Placeholder when Pydantic unavailable."""

        pass


@dataclass
class MeshLlmRequest:
    """
    Standard LLM request format for mesh-delegated LLM calls.

    This dataclass is used when delegating LLM calls to mesh-registered LLM provider
    agents via @mesh.llm_provider. It standardizes the request format across the mesh.

    Usage:
        Provider side (automatic with @mesh.llm_provider):
            @mesh.llm_provider(model="anthropic/claude-sonnet-4-5", capability="llm")
            def claude_provider():
                pass  # Automatically handles MeshLlmRequest

        Consumer side (future with provider=dict):
            @mesh.llm(provider={"capability": "llm", "tags": ["claude"]})
            def chat(message: str, llm: MeshLlmAgent = None):
                return llm(message)  # Converts to MeshLlmRequest internally

    Attributes:
        messages: List of message dicts with "role" and "content" keys (and optionally "tool_calls")
        tools: Optional list of tool definitions (MCP format)
        model_params: Optional parameters to pass to the model (temperature, max_tokens, etc.)
        context: Optional arbitrary context data for debugging/tracing
        request_id: Optional request ID for tracking
        caller_agent: Optional agent name that initiated the request
    """

    messages: List[Dict[str, Any]]  # Changed from Dict[str, str] to allow tool_calls
    tools: Optional[List[Dict]] = None
    model_params: Optional[Dict] = None
    context: Optional[Dict] = None
    request_id: Optional[str] = None
    caller_agent: Optional[str] = None
