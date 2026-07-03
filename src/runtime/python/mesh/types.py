"""
MCP Mesh type definitions for dependency injection.
"""

import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, Optional, Protocol, TypeAlias, TypeVar

_StreamT = TypeVar("_StreamT")
Stream: TypeAlias = AsyncIterator[_StreamT]
"""Return-annotation marker for tools that stream their output.

Tool authors opt in to token-by-token streaming by annotating the return type:

    @mesh.tool
    async def chat(prompt: str) -> mesh.Stream[str]:
        async for chunk in llm_stream():
            yield chunk

When the framework detects ``mesh.Stream[str]`` (or the equivalent
``AsyncIterator[str]`` / ``AsyncGenerator[str, None]``), it forwards each
yielded chunk via FastMCP ``Context.report_progress(message=chunk)`` and
sends the joined text as the final ``CallToolResult`` so non-streaming
consumers degrade gracefully.

v1 supports ``Stream[str]`` only.
"""

try:
    from pydantic_core import core_schema

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


@dataclass(frozen=True)
class _MediaParamInfo:
    """Metadata marker for media-typed tool parameters."""

    media_type: str = "*/*"


def MediaParam(media_type: str = "*/*"):
    """Create a type annotation for tool parameters that accept media URIs.

    When used as a type hint on a @mesh.tool parameter, the framework adds
    'x-media-type' to the JSON schema, enabling LLMs to pass media URIs
    through multi-agent call chains.

    Usage:
        @mesh.tool(capability="analyzer")
        async def analyze(
            question: str,
            image: mesh.MediaParam("image/*") = None,
            llm: mesh.MeshLlmAgent = None,
        ) -> str:
            if image:
                return await llm(question, media=[image])
            return await llm(question)

    Args:
        media_type: MIME type pattern (e.g., "image/*", "application/pdf", "*/*")

    Returns:
        Annotated type that Pydantic treats as Optional[str] with media metadata.
    """
    return Annotated[Optional[str], _MediaParamInfo(media_type)]


class McpMeshTool(Protocol):
    """
    MCP Mesh tool proxy for dependency injection.

    This protocol defines the interface for injected tool dependencies. When you declare
    a dependency on a remote tool, MCP Mesh injects a proxy that implements this interface.

    Features:
    - Simple callable interface for tool invocation
    - Full MCP protocol methods (tools, resources, prompts)
    - Streaming support with FastMCP's StreamableHttpTransport
    - Session management with notifications
    - Automatic redirect handling
    - CallToolResult objects with structured content parsing

    Usage Examples:
        @mesh.tool(dependencies=["date-service"])
        def greet(name: str, date_service: McpMeshTool) -> str:
            # Simple call - proxy knows which remote function to invoke
            current_date = date_service()

            # With arguments
            current_date = date_service({"format": "ISO"})

            return f"Hello {name}, today is {current_date}"

        @mesh.tool(dependencies=["file-service"])
        async def process_files(file_service: McpMeshTool) -> str:
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

    The proxy provides all MCP protocol features while maintaining a simple callable interface.
    """

    def __call__(
        self,
        arguments: Optional[dict[str, Any]] = None,
        *,
        headers: Optional[dict[str, str]] = None
    ) -> Any:
        """
        Call the bound remote function.

        Args:
            arguments: Arguments to pass to the remote function (optional)
            headers: Per-call headers to inject into the downstream request (optional).
                     Filtered by the MCP_MESH_PROPAGATE_HEADERS allowlist
                     (exact match by default; trailing "*" for prefix match —
                     e.g., "x-audit-*" permits "x-audit-id").
                     Merges with session-level propagated headers (per-call wins).

        Returns:
            Result from the remote function call (CallToolResult object)
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
            Custom Pydantic core schema for McpMeshTool.

            This makes McpMeshTool parameters appear as optional/nullable in MCP schemas,
            preventing serialization errors while maintaining type safety for dependency injection.

            The dependency injection system will replace None values with actual proxy objects
            at runtime, so MCP callers never need to provide these parameters.
            """
            # Treat McpMeshTool as an optional Any type for MCP serialization
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


class MeshJob(Protocol):
    """
    MCP Mesh job injectable for long-running task support (Phase 1, MeshJob substrate).

    Used as a type annotation on a ``@mesh.tool`` parameter to receive either
    a producer-side ``JobController`` (when the tool is decorated with
    ``@mesh.tool(task=True)`` and invoked as a job — i.e. via the inbound
    job-dispatch path or a claim worker) or a consumer-side ``JobProxy``
    (when the tool depends on a remote ``task=True`` capability and submits
    work via ``mesh.MeshJob.submit(...)``).

    On the producer side the injected object exposes:
        - ``await job.update_progress(progress, message=None)`` — coalesced delta.
        - ``await job.request_input(prompt=None)`` *(since v2.6)* —
          transition the job to ``input_required``, signalling the consumer
          that the handler is blocked awaiting an external answer. STATUS-ONLY:
          posts the transition (``prompt`` rides the ``progress_message``
          field), flushes immediately, and returns — it does NOT await the
          answer. Compose with ``recv_event`` for request-and-await:
          ``await job.request_input(prompt)`` then
          ``await job.recv_event(types=["answer"])``; an external party answers
          via ``proxy.send_event("answer", ...)``. Non-terminal — the handler
          keeps running; ``complete`` / ``fail`` exit ``input_required``.
        - ``await job.complete(result)`` — terminal success.
        - ``await job.fail(error)`` — terminal failure.
        - ``job.claim_epoch`` *(since v2.8)* — the claim generation this
          attempt executes under (``int``), or ``None`` for a push-mode
          inbound job / an old registry. Read-only; useful to stamp on side
          effects so a superseded re-execution's writes are distinguishable
          downstream. Supersession itself surfaces through the existing
          cancellation path (``CancelledError`` in the handler) — no polling
          of this value is required.
        - ``await job.recv_event(types=None, timeout_secs=None)`` *(since v2.2)* —
          wait for the next event posted into this job's event channel.
          Returns the event dict ``{job_id, seq, type, payload, trace_context,
          posted_by, created_at}`` or ``None`` on timeout. Used by
          handlers that need to receive external inputs (extend-deadline
          signals, user-supplied input on ``input_required`` pauses,
          arbitrary user-defined events) without blocking the registry.

    On the consumer side the injected object exposes:
        - ``await job.wait(timeout_secs=None)`` — poll until terminal.
        - ``await job.status()`` — single registry read.
        - ``await job.cancel(reason=None)`` — request cancellation.
        - ``await job.send_event(event_type, payload=None)`` *(since v2.2)* —
          post an event into the job's event channel. Returns a receipt
          dict ``{job_id, seq, created_at}``. The running handler sees
          the event on its next ``recv_event`` call (or wakes
          immediately if already long-polling). Raises
          :class:`mesh.JobTerminalError` if the job has reached a
          terminal state.

    A ``MeshJob`` parameter is **orthogonal** to the positional indexing
    used by ``McpMeshTool``: the DDDI resolver records its signature
    position separately so the function can declare the job param wherever
    it reads naturally without disturbing tool-dependency slot numbering.
    See ``MESHJOB_DDDI_CONTRACT.md`` for the full classification rules.

    A function with a ``MeshJob`` parameter MAY still be invoked as a
    regular synchronous tool call — in that case the runtime passes
    ``None`` for the slot. User functions should treat ``None`` as the
    "fast path" (no progress reporting, no cancellation checks).

    Usage Examples:
        Producer (long-running task):

            @mesh.tool(capability="plan_trip", task=True)
            async def plan_trip(
                user_id: str,
                weather: McpMeshTool = None,
                job: MeshJob = None,
            ) -> dict:
                if job is not None:
                    await job.update_progress(0.1, "checking weather")
                w = await weather({"city": "PDX"})
                if job is not None:
                    await job.update_progress(0.9, "done")
                return {"itinerary": w}

        Consumer (await a remote job):

            @mesh.tool(capability="orchestrate", dependencies=["plan_trip"])
            async def orchestrate(
                user_id: str,
                plan_trip: MeshJob = None,
            ) -> dict:
                proxy = await plan_trip.submit(user_id=user_id, max_duration=600)
                return await proxy.wait(timeout_secs=600)
    """

    if PYDANTIC_AVAILABLE:

        @classmethod
        def __get_pydantic_core_schema__(
            cls,
            source_type: Any,
            handler: Any,
        ) -> core_schema.CoreSchema:
            """
            Custom Pydantic core schema for MeshJob.

            Mirrors :class:`McpMeshTool` / :class:`MeshLlmAgent`: the parameter
            appears as optional/nullable in the MCP tool input schema so MCP
            callers don't have to (and can't) supply it. The runtime fills
            it in — JobController on the producer side when invoked as a job,
            JobProxy on the consumer side, or ``None`` on a regular call.
            """
            return core_schema.with_default_schema(
                core_schema.nullable_schema(core_schema.any_schema()),
                default=None,
            )

    else:

        @classmethod
        def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> dict:
            return {
                "type": "default",
                "schema": {"type": "nullable", "schema": {"type": "any"}},
                "default": None,
            }


def _create_deprecated_mcpmeshagent():
    """Create McpMeshAgent as a deprecated alias for McpMeshTool."""

    class McpMeshAgent(McpMeshTool, Protocol):
        """
        Deprecated: Use McpMeshTool instead.

        This is a backwards-compatible alias that will be removed in a future version.
        """

        def __init_subclass__(cls, **kwargs):
            warnings.warn(
                "McpMeshAgent is deprecated, use McpMeshTool instead. "
                "McpMeshAgent will be removed in a future version.",
                DeprecationWarning,
                stacklevel=2,
            )
            super().__init_subclass__(**kwargs)

    return McpMeshAgent


# Deprecated alias for backwards compatibility
McpMeshAgent = _create_deprecated_mcpmeshagent()


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
        - Provider always comes from the decorator's ``provider={...}`` filter
        - Environment variables override other decorator settings:
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
class LlmMeta:
    """
    Metadata from LLM response for cost tracking and debugging.

    This is attached to results from @mesh.llm calls as `_mesh_meta` attribute,
    providing access to token counts, latency, and model information.

    Attributes:
        provider: LLM provider name (e.g., "anthropic", "openai")
        model: Full model identifier (e.g., "anthropic/claude-3-5-haiku-20241022")
        input_tokens: Number of tokens in the prompt
        output_tokens: Number of tokens in the response
        total_tokens: Total tokens used (input + output)
        latency_ms: Request latency in milliseconds

    Usage:
        @mesh.llm(provider="anthropic/claude-3-5-haiku-20241022")
        async def ask(question: str, llm: MeshLlmAgent) -> Answer:
            result = await llm(question)

            # Access result normally
            print(result.answer)

            # Access metadata
            print(result._mesh_meta.model)          # "anthropic/claude-3-5-haiku-20241022"
            print(result._mesh_meta.output_tokens)  # 85
            print(result._mesh_meta.latency_ms)     # 125.5

            return result

    Note:
        For primitive return types (str, int, etc.) and frozen Pydantic models,
        _mesh_meta cannot be attached. This is a Python limitation.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float


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

    Note:
        ``media=`` is *not* a field on this dataclass. It is a kwarg on
        ``MeshLlmAgent.__call__()`` (e.g. ``await llm("describe", media=["s3://..."])``)
        that the consumer pre-resolves into provider-native content blocks
        before constructing the request — the resolved blocks land inside
        ``messages[*].content``. See ``meshctl man multimodal`` for details.
    """

    messages: list[dict[str, Any]]  # Changed from Dict[str, str] to allow tool_calls
    tools: Optional[list[dict]] = None
    model_params: Optional[dict] = None
    context: Optional[dict] = None
    request_id: Optional[str] = None
    caller_agent: Optional[str] = None
