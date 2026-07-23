"""
Mesh Decorators - New dual decorator architecture for MCP Mesh.

Provides two levels of decoration:
- @mesh.tool: Function-level tool registration and capabilities
- @mesh.agent: Agent-level configuration and metadata

Usage:
    import mesh

    @mesh.agent(name="my-agent", version="1.0.0")
    class MyAgent:
        @mesh.tool(capability="greeting")
        def say_hello(self):
            return "Hello!"

Note: Direct imports like 'from mesh import tool' are discouraged.
Use 'import mesh' and then '@mesh.tool()' for consistency with MCP patterns.
"""

from . import decorators, jobs
from .jobs import JobNotFoundError, JobTerminalError
from .types import (
    LlmMeta,
    McpMeshAgent,
    McpMeshTool,
    MeshContextModel,
    MeshJob,
    MeshLlmAgent,
    MeshLlmRequest,
    Stream,
)

# Note: helpers.llm_provider is imported lazily in __getattr__ to avoid
# initialization timing issues with @mesh.agent auto_run in tests

__version__ = "3.3.0"


# Helper function to create FastMCP server with proper naming
def create_server(name: str | None = None) -> "FastMCP":
    """
    Create a FastMCP server with proper naming for MCP Mesh integration.

    If a @mesh.agent decorator has been applied to a class in the current module,
    this function will use the agent name for the server. Otherwise, it uses the
    provided name or a default.

    Args:
        name: Optional server name. If not provided, will try to use @mesh.agent name

    Returns:
        FastMCP server instance with proper name

    Example:
        @mesh.agent(name="my-service")
        class MyAgent:
            pass

        server = mesh.create_server()  # Uses "my-service" as server name

        @mesh.tool(capability="greeting")
        @server.tool()
        def hello():
            return "Hello!"
    """
    from fastmcp import FastMCP

    # Try to get agent name from existing @mesh.agent decorators
    if name is None:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        agents = DecoratorRegistry.get_mesh_agents()

        if agents:
            # Use the first agent's name found
            agent_data = next(iter(agents.values()))
            agent_metadata = agent_data.metadata
            agent_name = agent_metadata.get("name")
            if agent_name:
                name = agent_name

    # Fallback to default name
    if name is None:
        name = "mcp-mesh-server"

    return FastMCP(name=name)


# Make decorators available as mesh.tool, mesh.agent, mesh.route, mesh.llm, and mesh.llm_provider
def __getattr__(name):
    import warnings

    if name == "tool":
        return decorators.tool
    elif name == "agent":
        return decorators.agent
    elif name == "route":
        return decorators.route
    elif name == "a2a":
        return decorators.a2a
    elif name == "a2a_consumer":
        return decorators.a2a_consumer
    elif name == "A2AClient":
        from ._a2a_consumer import A2AClient

        return A2AClient
    elif name == "A2ABearer":
        from ._a2a_consumer import A2ABearer

        return A2ABearer
    elif name == "A2AResponse":
        from ._a2a_consumer import A2AResponse

        return A2AResponse
    elif name == "A2AJob":
        from ._a2a_consumer import A2AJob

        return A2AJob
    elif name == "A2AStream":
        from ._a2a_consumer import A2AStream

        return A2AStream
    elif name == "A2AEvent":
        from ._a2a_consumer import A2AEvent

        return A2AEvent
    elif name == "A2AJobError":
        from ._a2a_consumer import A2AJobError

        return A2AJobError
    elif name == "A2AJobFailed":
        from ._a2a_consumer import A2AJobFailed

        return A2AJobFailed
    elif name == "A2AJobCanceled":
        from ._a2a_consumer import A2AJobCanceled

        return A2AJobCanceled
    elif name == "service":
        from ._service import service

        return service
    elif name == "selector":
        from ._service import selector

        return selector
    elif name == "MeshServiceUnavailableError":
        from ._service import MeshServiceUnavailableError

        return MeshServiceUnavailableError
    elif name == "llm":
        return decorators.llm
    elif name == "llm_provider":
        # Lazy import to avoid initialization timing issues
        from .helpers import llm_provider

        return llm_provider
    elif name == "McpMeshTool":
        return McpMeshTool
    elif name == "McpMeshAgent":
        warnings.warn(
            "McpMeshAgent is deprecated, use McpMeshTool instead. "
            "McpMeshAgent will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return McpMeshAgent
    elif name == "MeshContextModel":
        return MeshContextModel
    elif name == "MeshJob":
        return MeshJob
    elif name == "jobs":
        return jobs
    elif name == "JobNotFoundError":
        return JobNotFoundError
    elif name == "JobTerminalError":
        return JobTerminalError
    elif name == "MeshLlmAgent":
        return MeshLlmAgent
    elif name == "MeshLlmRequest":
        return MeshLlmRequest
    elif name == "LlmMeta":
        return LlmMeta
    elif name == "Stream":
        return Stream
    elif name == "create_server":
        return create_server
    elif name == "MediaParam":
        from .types import MediaParam

        return MediaParam
    elif name == "upload_media":
        from .media import upload_media

        return upload_media
    elif name == "download_media":
        from .media import download_media

        return download_media
    elif name == "media_result":
        from .media import media_result

        return media_result
    elif name == "MediaResult":
        from .media import MediaResult

        return MediaResult
    elif name == "save_upload":
        from .web import save_upload

        return save_upload
    elif name == "save_upload_result":
        from .web import save_upload_result

        return save_upload_result
    elif name == "MediaUpload":
        from .web import MediaUpload

        return MediaUpload
    elif name == "TraceContext":
        from _mcp_mesh.tracing.context import TraceContext

        return TraceContext
    elif name == "calling_job":
        # Issue #1263: provider-side accessor for the calling job's identity.
        from _mcp_mesh.engine.job_context import calling_job

        return calling_job
    elif name == "CallingJob":
        from _mcp_mesh.engine.job_context import CallingJob

        return CallingJob
    elif name == "SupersededError":
        # Issue #1278: typed supersession signal. A provider raises this to
        # reject a call from a superseded executor; the calling side's injected
        # proxy re-raises it on recognizing the reserved envelope.
        from _mcp_mesh.engine.superseded import SupersededError

        return SupersededError
    elif name == "MaxIterationsError":
        # Issue #1355: typed signal raised by the delegating @mesh.llm consumer
        # when the provider-managed loop exhausts max_iterations.
        from _mcp_mesh.engine.llm_errors import MaxIterationsError

        return MaxIterationsError
    elif name == "ToolExecutionError":
        # Raised when a tool invoked inside the agentic loop fails.
        from _mcp_mesh.engine.llm_errors import ToolExecutionError

        return ToolExecutionError
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Note: In Python, we can't completely prevent 'from mesh import tool'
# but we strongly discourage it for API consistency with MCP patterns
__all__ = []
