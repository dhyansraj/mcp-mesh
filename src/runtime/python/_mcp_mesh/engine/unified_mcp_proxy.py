"""Unified MCP Proxy using FastMCP's built-in client.

This is the primary MCP client proxy for cross-service communication,
using FastMCP's superior client capabilities with async support.
"""

import asyncio
import contextvars
import json
import logging
import os
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

from ..shared.json_fast import dumps_bytes as json_dumps_bytes
from ..shared.json_fast import loads as json_loads
from ..shared.logging_config import (
    format_log_value,
    format_result_summary,
    get_trace_prefix,
)
from ..shared.sse_parser import SSEParser
from ..tracing.context import TraceContext
from ..tracing.utils import generate_span_id

logger = logging.getLogger(__name__)


def _create_ssl_context_for_endpoint(endpoint: str):
    """Create SSL context for HTTPS endpoints, or None for HTTP.

    Centralises mTLS / SPIRE configuration so that every transport
    (FastMCP httpx factory, HTTP direct call, etc.) behaves identically.

    Returns:
        ssl.SSLContext configured for mTLS, or *None* when the endpoint
        is plain HTTP or TLS is not enabled.

    Raises:
        RuntimeError: When HTTPS is requested but cert/key env vars are missing.
    """
    if not endpoint.startswith("https://"):
        return None

    from ..shared.tls_config import get_tls_config

    tls = get_tls_config()
    if not tls["enabled"]:
        return None

    if not tls.get("cert_path") or not tls.get("key_path"):
        raise RuntimeError(
            "HTTPS endpoint requires MCP_MESH_TLS_CERT and MCP_MESH_TLS_KEY"
        )

    import ssl

    ssl_ctx = ssl.create_default_context()
    if tls.get("ca_path"):
        ssl_ctx.load_verify_locations(tls["ca_path"])
    ssl_ctx.load_cert_chain(tls["cert_path"], tls["key_path"])
    # SPIFFE/SPIRE certs use URI SANs, not DNS/IP SANs.
    # Disable hostname check but keep cert chain validation
    # (create_default_context sets verify_mode=CERT_REQUIRED).
    if tls.get("provider") == "spire":
        ssl_ctx.check_hostname = False
    return ssl_ctx


# ContextVar for passing merged outbound headers into httpx event_hooks closure
_outbound_headers_var: contextvars.ContextVar[dict[str, str] | None] = (
    contextvars.ContextVar("_outbound_headers", default=None)
)

# Module-level connection pools for reuse across tool calls.
#
# IMPORTANT: httpx.AsyncClient and FastMCP.Client both create internal asyncio
# resources (Locks/Events via anyio) that are bound to the event loop on which
# they are first used. Since mesh tool isolation dispatches @mesh.tool async
# bodies onto a pool of dedicated worker event loops (see
# ``_mcp_mesh.shared.tool_executor``), a client created on worker loop A cannot
# safely be used from worker loop B — doing so raises:
#     RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop
#
# To stay loop-safe, we cache one client per (loop, endpoint). The pool size
# stays small in practice: N worker loops + 1 main loop, times the number of
# distinct cross-agent endpoints. The pool dict is guarded by a plain
# ``threading.Lock`` (NOT ``asyncio.Lock``) so it is itself loop-agnostic and
# can be acquired safely from any worker thread.
#
# FastMCP Client supports reentrant context managers (ref-counted sessions),
# so concurrent `async with` blocks on the same pooled client share one session.
_fastmcp_client_pool: dict[tuple[int, str], Any] = {}
_httpx_pool: dict[tuple[int, str], Any] = {}
_pool_lock = threading.Lock()


def _current_loop_key() -> int:
    """Return id() of the running event loop (used as part of the pool key)."""
    return id(asyncio.get_running_loop())


def _get_httpx_client_sync(base_endpoint: str) -> "httpx.AsyncClient":
    """Get or create a pooled httpx client bound to the CURRENT event loop.

    Synchronous lookup guarded by a threading.Lock — safe to call from any
    worker thread. The returned client is loop-affine: only use it from the
    same event loop that created it.
    """
    import httpx

    key = (_current_loop_key(), base_endpoint)
    with _pool_lock:
        client = _httpx_pool.get(key)
        if client is not None and not client.is_closed:
            return client
        ssl_ctx = _create_ssl_context_for_endpoint(base_endpoint)
        tls_kwargs = {"verify": ssl_ctx} if ssl_ctx is not None else {}
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, read=300.0),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
            **tls_kwargs,
        )
        _httpx_pool[key] = client
        logger.debug(
            f"Created pooled httpx client for loop={key[0]} endpoint={base_endpoint}"
        )
        return client


async def close_connection_pools() -> None:
    """Close ALL pooled HTTP/FastMCP clients across every owning event loop.

    Each cached client is bound to the loop that created it (see module-level
    docstring). Closing a client from a different loop would raise the same
    cross-loop error we are trying to avoid. So for clients owned by a
    DIFFERENT loop than the caller's, we schedule the close coroutine on the
    owning loop via ``asyncio.run_coroutine_threadsafe`` and await the
    resulting future on the current loop via ``asyncio.wrap_future`` — that
    avoids the deadlock pitfall of calling ``.result()`` from the same loop
    a future is bound to.

    Typical caller is uvicorn's main loop during graceful shutdown. Worker
    loop clients (the majority, since N workers ≥ 1) used to leak silently
    until daemon threads died at process termination; this routine now
    actively closes them.
    """
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — nothing we can safely close from here.
        return

    # Build {loop_id: loop} map from the current loop + worker loops so we can
    # find the owning loop for each pooled client by its (loop_id, endpoint) key.
    from ..shared.tool_executor import get_worker_loops

    loop_by_id: dict[int, asyncio.AbstractEventLoop] = {id(current_loop): current_loop}
    for loop in get_worker_loops():
        loop_by_id[id(loop)] = loop

    with _pool_lock:
        fastmcp_to_close = list(_fastmcp_client_pool.items())
        httpx_to_close = list(_httpx_pool.items())
        _fastmcp_client_pool.clear()
        _httpx_pool.clear()

    async def _close_one(client, owning_loop, *, is_fastmcp: bool, label: str) -> None:
        kind = "FastMCP" if is_fastmcp else "httpx"
        if owning_loop is current_loop:
            # Same loop — just await directly.
            if is_fastmcp:
                await client.__aexit__(None, None, None)
            else:
                await client.aclose()
            return

        # Different (worker) loop — schedule on its loop, await the resulting
        # future on the current loop. Using wrap_future (NOT future.result())
        # avoids deadlocking when this happens to be invoked on the same loop
        # as the future's bound loop.
        if is_fastmcp:
            coro = client.__aexit__(None, None, None)
        else:
            coro = client.aclose()
        fut = asyncio.run_coroutine_threadsafe(coro, owning_loop)
        try:
            await asyncio.wait_for(asyncio.wrap_future(fut), timeout=5)
        except asyncio.TimeoutError:
            logger.warning(f"Timed out closing {kind} client for: {label}")

    for key, client in fastmcp_to_close:
        owning_loop = loop_by_id.get(key[0])
        if owning_loop is None or owning_loop.is_closed():
            logger.debug(
                f"Skipping FastMCP client for {key[1]}: owning loop closed/missing"
            )
            continue
        try:
            await _close_one(client, owning_loop, is_fastmcp=True, label=key[1])
            logger.debug(f"Closed pooled FastMCP client for: {key[1]}")
        except Exception as e:
            logger.warning(f"Error closing FastMCP client for {key[1]}: {e}")

    for key, client in httpx_to_close:
        owning_loop = loop_by_id.get(key[0])
        if owning_loop is None or owning_loop.is_closed():
            logger.debug(
                f"Skipping httpx client for {key[1]}: owning loop closed/missing"
            )
            continue
        try:
            await _close_one(client, owning_loop, is_fastmcp=False, label=key[1])
            logger.debug(f"Closed pooled httpx client for: {key[1]}")
        except Exception as e:
            logger.warning(f"Error closing httpx client for {key[1]}: {e}")


class UnifiedMCPProxy:
    """Unified MCP proxy using FastMCP's built-in client.

    This provides the implementation for McpMeshTool type parameters,
    offering all MCP protocol features using FastMCP's superior client.

    Features:
    - All MCP protocol methods (tools, resources, prompts)
    - Streaming support with progress handler
    - Session management with notifications
    - Automatic redirect handling (fixes /mcp/ → /mcp issue)
    - CallToolResult objects with structured content
    - Enhanced proxy configuration via kwargs
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: dict | None = None
    ):
        """Initialize Unified MCP Proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call (for __call__ compatibility)
            kwargs_config: Optional kwargs configuration from @mesh.tool decorator
        """
        self.endpoint = endpoint.rstrip("/")
        self.function_name = function_name
        self.kwargs_config = kwargs_config or {}
        self.logger = logger.getChild(f"unified_proxy.{function_name}")

        # Configure from kwargs
        self._configure_from_kwargs()

        # Configure telemetry settings
        self._configure_telemetry()

        # Log configuration
        if self.kwargs_config:
            self.logger.debug(
                f"🔧 UnifiedMCPProxy initialized with kwargs: {self.kwargs_config}"
            )

    def _is_ip_address(self, hostname: str) -> bool:
        """Check if hostname is an IP address vs DNS name.

        Args:
            hostname: Hostname to check

        Returns:
            True if IP address, False if DNS name
        """
        import ipaddress

        try:
            ipaddress.ip_address(hostname)
            return True
        except ValueError:
            return False

    @staticmethod
    def _build_fastmcp_client(
        mcp_endpoint: str, base_endpoint: str, stream_timeout: float = 300.0
    ):
        """Build a FastMCP client with dynamic trace header injection.

        Uses httpx event_hooks to inject trace headers at REQUEST TIME rather than
        at transport construction time. This ensures the current trace context is
        captured when the HTTP request is actually made, fixing the trace hierarchy bug.

        Args:
            mcp_endpoint: MCP endpoint URL (e.g. http://host/mcp)
            base_endpoint: Base endpoint URL (for SSL context)
            stream_timeout: Read timeout for long-running LLM calls

        Returns:
            FastMCP Client instance with dynamic trace header injection
        """
        try:
            # Extract hostname from endpoint URL for DNS detection
            from urllib.parse import urlparse

            parsed = urlparse(mcp_endpoint)
            hostname = parsed.hostname or parsed.netloc.split(":")[0]

            # DNS resolution works perfectly with FastMCP
            logger.debug(f"✅ Using FastMCP client for endpoint: {hostname}")

            # Use stream_timeout for read timeout (default 300s for LLM calls)
            import httpx
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport

            def create_httpx_client(**kwargs):
                """Create httpx client with dynamic trace header injection via event hooks."""

                async def inject_trace_headers_hook(request: httpx.Request) -> None:
                    """Inject trace headers at REQUEST TIME for correct context propagation.

                    This hook runs just before each HTTP request is sent, capturing the
                    current trace context at that moment. This fixes the trace hierarchy
                    bug where headers were captured at client creation time instead.
                    """
                    try:
                        from ..tracing.context import TraceContext

                        # Inject trace headers when trace context exists (always propagate)
                        trace_context = TraceContext.get_current()
                        if trace_context:
                            request.headers["X-Trace-ID"] = trace_context.trace_id
                            request.headers["X-Parent-Span"] = trace_context.span_id
                            logger.debug(
                                f"🔗 TRACE_HOOK: Injecting at request time - "
                                f"trace_id={trace_context.trace_id[:8]}... "
                                f"parent_span={trace_context.span_id[:8]}..."
                            )

                        # Inject merged outbound headers from ContextVar
                        # (session propagated + custom + per-call, merged in call_tool)
                        outbound = _outbound_headers_var.get()
                        if outbound:
                            for key, value in outbound.items():
                                request.headers[key] = value
                    except Exception as e:
                        # Never fail HTTP requests due to tracing issues
                        logger.debug(f"🔗 TRACE_HOOK: Failed to inject headers: {e}")

                # Override timeout to use stream_timeout for long-running LLM calls
                kwargs["timeout"] = httpx.Timeout(
                    timeout=stream_timeout,
                    connect=30.0,  # 30s for connection
                    read=stream_timeout,  # Long read timeout for SSE streams
                    write=30.0,  # 30s for writes
                    pool=30.0,  # 30s for pool
                )

                # Add event hook for dynamic trace header injection
                existing_hooks = kwargs.get("event_hooks", {})
                request_hooks = existing_hooks.get("request", [])
                request_hooks.append(inject_trace_headers_hook)
                existing_hooks["request"] = request_hooks
                kwargs["event_hooks"] = existing_hooks

                # Apply mTLS config for https endpoints
                ssl_ctx = _create_ssl_context_for_endpoint(base_endpoint)
                if ssl_ctx is not None:
                    kwargs["verify"] = ssl_ctx

                return httpx.AsyncClient(**kwargs)

            # Create client WITHOUT static headers - headers injected via hook at request time
            transport = StreamableHttpTransport(
                url=mcp_endpoint,
                httpx_client_factory=create_httpx_client,
            )
            return Client(transport)

        except ImportError as e:
            # DNS names or FastMCP not available
            logger.debug(f"🔄 FastMCP client unavailable: {e}")
            raise  # Re-raise ImportError
        except Exception as e:
            # Any other error building client
            logger.debug(f"🔄 FastMCP client error: {e}")
            raise ImportError(f"FastMCP client failed: {e}")

    @classmethod
    async def _get_or_create_fastmcp_client(
        cls, mcp_endpoint: str, base_endpoint: str, stream_timeout: float = 300.0
    ):
        """Get a pooled FastMCP client bound to the CURRENT event loop.

        See module-level pool docstring: FastMCP Client owns asyncio resources
        that are loop-affine, so we key the pool by ``(loop_id, endpoint)``.

        Health-check rationale (no proactive probe of the cached client):

        FastMCP's ``Client._connect()`` already self-heals at session level —
        on each ``async with``, it inspects ``session_task`` and restarts the
        background session task if it is ``None`` or ``done()`` (which is
        precisely what happens when the previous session errored or was torn
        down). The two attribute-level signals available are:

          * ``client.is_connected()`` — only True while a session is live
            (i.e. inside an ``async with`` block). Between calls it is
            always False; it does NOT indicate "broken", just "idle".
          * ``client._session_state.session_task.done()`` — touches private
            internals; redundant with the check ``_connect()`` already does.

        FastMCP exposes no `ping_no_session()` or transport-health probe
        cheap enough to run on every cache hit (``ping()`` requires a live
        session and a network round-trip). So we rely on FastMCP's built-in
        reconnect on the next ``async with``. In the worst case (transport
        permanently broken at the underlying httpx level) the next call
        raises and the existing HTTP-fallback path in ``call_tool`` covers
        it. Note also that the proxy's primary path is the pooled httpx
        client (see ``_http_call``); FastMCP is fallback + listing methods.
        """
        key = (_current_loop_key(), mcp_endpoint)
        with _pool_lock:
            client = _fastmcp_client_pool.get(key)
            if client is not None:
                return client
            client = cls._build_fastmcp_client(
                mcp_endpoint, base_endpoint, stream_timeout
            )
            _fastmcp_client_pool[key] = client
            logger.debug(
                f"Created pooled FastMCP client for loop={key[0]} endpoint={mcp_endpoint}"
            )
            return client

    def _configure_from_kwargs(self):
        """Auto-configure proxy settings from kwargs."""
        # Basic configuration
        self.timeout = self.kwargs_config.get("timeout", 30)
        self.retry_count = self.kwargs_config.get("retry_count", 1)
        self.custom_headers = self.kwargs_config.get("custom_headers", {})

        # Streaming configuration
        self.streaming_capable = self.kwargs_config.get("streaming", False)
        self.stream_timeout = self.kwargs_config.get("stream_timeout", 300)

        # Session configuration
        self.session_required = self.kwargs_config.get("session_required", False)
        self.auto_session_management = self.kwargs_config.get(
            "auto_session_management", True
        )

        # Content handling
        self.max_response_size = self.kwargs_config.get(
            "max_response_size", 10 * 1024 * 1024
        )

        self.logger.info(
            f"🔧 Unified MCP proxy configured - timeout: {self.timeout}s, "
            f"streaming: {self.streaming_capable}, session_required: {self.session_required}"
        )

    def _configure_telemetry(self):
        """Configure telemetry and tracing settings."""
        import os

        # Telemetry configuration
        self.telemetry_enabled = self.kwargs_config.get(
            "telemetry_enabled",
            os.getenv("MCP_MESH_TELEMETRY_ENABLED", "true").lower()
            in ("true", "1", "yes", "on"),
        )

        self.distributed_tracing_enabled = self.kwargs_config.get(
            "distributed_tracing_enabled",
            os.getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false").lower()
            in ("true", "1", "yes", "on"),
        )

        self.redis_trace_publishing = self.kwargs_config.get(
            "redis_trace_publishing",
            os.getenv("MCP_MESH_REDIS_TRACE_PUBLISHING", "true").lower()
            in ("true", "1", "yes", "on"),
        )

        # Performance metrics configuration
        self.collect_performance_metrics = self.kwargs_config.get(
            "performance_metrics", True
        )

        # Agent context collection
        self.collect_agent_context = self.kwargs_config.get(
            "agent_context_collection", True
        )

        self.logger.debug(
            f"📊 Telemetry configuration - enabled: {self.telemetry_enabled}, "
            f"distributed_tracing: {self.distributed_tracing_enabled}, "
            f"redis_publishing: {self.redis_trace_publishing}, "
            f"performance_metrics: {self.collect_performance_metrics}"
        )

    def _inject_trace_headers(self, headers: dict) -> dict:
        """Inject trace context headers for distributed tracing."""
        from ..tracing.trace_context_helper import TraceContextHelper

        TraceContextHelper.inject_trace_headers_to_request(
            headers, self.endpoint, self.logger
        )
        return headers

    def _collect_agent_context_metadata(
        self, tool_name: str, arguments: dict = None
    ) -> dict:
        """Collect comprehensive agent context metadata for distributed tracing."""
        import hashlib
        import os
        import socket
        from datetime import datetime

        try:
            # Get system information
            hostname = socket.gethostname()

            # Try to get IP address
            try:
                # Connect to a remote address to get local IP
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
            except Exception:
                local_ip = "127.0.0.1"

            # Create proxy instance identifier
            proxy_id = hashlib.md5(
                f"{self.endpoint}:{self.function_name}:{id(self)}".encode()
            ).hexdigest()[:12]

            # Get process information
            process_id = os.getpid()

            # Calculate argument fingerprint for request correlation
            arg_fingerprint = None
            if arguments:
                arg_str = (
                    str(sorted(arguments.items()))
                    if isinstance(arguments, dict)
                    else str(arguments)
                )
                arg_fingerprint = hashlib.md5(arg_str.encode()).hexdigest()[:8]

            return {
                "proxy_instance_id": proxy_id,
                "client_hostname": hostname,
                "client_ip": local_ip,
                "client_process_id": process_id,
                "target_agent_endpoint": self.endpoint,
                "target_tool_name": tool_name,
                "request_fingerprint": arg_fingerprint,
                "proxy_config": {
                    "timeout": self.timeout,
                    "retry_count": self.retry_count,
                    "streaming_capable": self.streaming_capable,
                    "session_required": self.session_required,
                },
                "call_timestamp": datetime.now().isoformat(),
                "call_context": "mcp_mesh_dependency_injection",
            }

        except Exception as e:
            self.logger.warning(f"Failed to collect full agent context: {e}")
            # Return minimal context
            return {
                "proxy_instance_id": f"proxy_{id(self)}",
                "target_agent_endpoint": self.endpoint,
                "target_tool_name": tool_name,
                "call_timestamp": datetime.now().isoformat(),
                "call_context": "mcp_mesh_dependency_injection",
            }

    # Note: We use module-level pooled clients with reentrant context managers.
    # FastMCP Client ref-counts sessions, so concurrent `async with` blocks share one session.

    # Main tool call method - clean async interface following FastMCP patterns
    async def __call__(self, *args, **kwargs) -> Any:
        """Call the remote tool using natural async patterns."""
        per_call_headers = kwargs.pop("headers", None)
        return await self.call_tool_with_tracing(
            self.function_name, kwargs, per_call_headers=per_call_headers
        )

    async def call_tool_with_tracing(
        self,
        name: str,
        arguments: dict = None,
        *,
        per_call_headers: dict[str, str] | None = None,
    ) -> Any:
        """Call a tool with clean ExecutionTracer integration (v0.4.0 style)."""
        # Check if telemetry is enabled - use same check as ExecutionTracer for consistency
        from ..tracing.execution_tracer import ExecutionTracer
        from ..tracing.utils import is_tracing_enabled

        if not self.telemetry_enabled or not is_tracing_enabled():
            return await self.call_tool(
                name, arguments, per_call_headers=per_call_headers
            )

        # Create wrapper function for ExecutionTracer compatibility
        async def proxy_call_wrapper(*args, **kwargs):
            # Add proxy-specific metadata to execution context if tracer is available
            try:
                from ..tracing.context import TraceContext

                current_trace = TraceContext.get_current()
                if current_trace and hasattr(current_trace, "execution_metadata"):
                    # Add proxy metadata to current trace
                    proxy_metadata = {
                        "call_type": "unified_mcp_proxy",
                        "endpoint": self.endpoint,
                        "proxy_type": "http_with_fastmcp_fallback",
                        "streaming_capable": self.streaming_capable,
                        "timeout": self.timeout,
                        "retry_count": self.retry_count,
                    }

                    # Add enhanced agent context if enabled
                    if self.collect_agent_context:
                        try:
                            agent_context = self._collect_agent_context_metadata(
                                name, arguments
                            )
                            proxy_metadata.update(agent_context)
                        except Exception as e:
                            self.logger.debug(
                                f"Failed to collect agent context metadata: {e}"
                            )

                    # Update current execution metadata
                    if hasattr(current_trace, "execution_metadata"):
                        current_trace.execution_metadata.update(proxy_metadata)

            except Exception as e:
                self.logger.debug(f"Failed to add proxy metadata: {e}")

            return await self.call_tool(
                name, arguments, per_call_headers=per_call_headers
            )

        # Use ExecutionTracer's static async method for clean integration
        return await ExecutionTracer.trace_function_execution_async(
            proxy_call_wrapper,
            args=(),
            kwargs={},  # arguments are handled inside the wrapper
            dependencies=[self.endpoint],
            mesh_positions=[],
            injected_count=1,
            logger_instance=self.logger,
        )

    def _inject_trace_into_args(
        self,
        arguments: dict | None,
        per_call_headers: dict[str, str] | None,
    ) -> tuple[dict, dict[str, str]]:
        """Build (args_with_trace, merged_headers) for an outbound tool call.

        Shared by ``call_tool`` (buffered) and ``stream`` so that both transport
        paths inject trace context and propagate headers identically. The two
        return values are:

        * ``args_with_trace`` — the original arguments (or empty dict) augmented
          with ``_trace_id`` / ``_parent_span`` / ``_mesh_headers`` when
          applicable. Delegates to the Rust core for cross-runtime parity and
          falls back to a Python implementation if the core is unavailable.
        * ``merged_headers`` — the resolved set of outbound HTTP headers
          (session-propagated + ``custom_headers`` + per-call), filtered by the
          propagate allowlist. Caller is responsible for setting
          ``_outbound_headers_var`` so the httpx event hook picks them up.
        """
        from ..tracing.context import matches_propagate_header

        current_trace = TraceContext.get_current()
        merged_headers: dict[str, str] = dict(TraceContext.get_propagated_headers())

        if self.custom_headers:
            for k, v in self.custom_headers.items():
                if matches_propagate_header(k):
                    merged_headers[k.lower()] = v

        if per_call_headers:
            for k, v in per_call_headers.items():
                if matches_propagate_header(k):
                    merged_headers[k.lower()] = v

        if current_trace:
            try:
                import mcp_mesh_core

                args_json = json.dumps(arguments or {})
                headers_json = json.dumps(merged_headers) if merged_headers else None
                injected_json = mcp_mesh_core.inject_trace_context_py(
                    args_json,
                    current_trace.trace_id,
                    current_trace.span_id,
                    headers_json,
                )
                args_with_trace = json.loads(injected_json)
                tp = get_trace_prefix()
                self.logger.debug(
                    f"{tp}🔗 Injecting trace context via Rust core: trace_id={current_trace.trace_id[:8]}..., parent_span={current_trace.span_id[:8]}..."
                )
            except Exception as e:
                tp = get_trace_prefix()
                self.logger.debug(
                    f"{tp}Rust inject_trace_context failed, using fallback: {e}"
                )
                args_with_trace = dict(arguments) if arguments else {}
                args_with_trace["_trace_id"] = current_trace.trace_id
                args_with_trace["_parent_span"] = current_trace.span_id
                if merged_headers:
                    args_with_trace["_mesh_headers"] = merged_headers
        else:
            args_with_trace = dict(arguments) if arguments else {}
            if merged_headers:
                args_with_trace["_mesh_headers"] = merged_headers

        return args_with_trace, merged_headers

    async def call_tool(
        self,
        name: str,
        arguments: dict = None,
        *,
        per_call_headers: dict[str, str] | None = None,
    ) -> Any:
        """Call a tool using direct HTTP with FastMCP fallback.

        Returns CallToolResult object with structured content parsing.
        """
        import time

        start_time = time.time()

        # Get trace prefix if available
        tp = get_trace_prefix()

        args_with_trace, merged_headers = self._inject_trace_into_args(
            arguments, per_call_headers
        )

        # Log cross-agent call - summary line
        arg_keys = list(arguments.keys()) if arguments else []
        self.logger.debug(
            f"{tp}🔄 Cross-agent call: {self.endpoint}/{name} (timeout: {self.timeout}s, args={arg_keys})"
        )
        # Log full args (will be TRACE later)
        self.logger.debug(
            f"{tp}🔄 Cross-agent call args: {format_log_value(arguments)}"
        )

        try:
            # Set merged outbound headers ContextVar for httpx hook to read
            _outbound_headers_var.set(merged_headers if merged_headers else None)

            try:
                # HTTP direct path (PRIMARY) — pooled httpx client, no MCP session overhead
                result = await self._http_call(name, args_with_trace)
                return result
            except Exception as e:
                error_msg = str(e)
                # Don't fallback on application-level errors — the remote tool responded
                if "Tool call error" in error_msg or "JSON-RPC error" in error_msg:
                    raise
                self.logger.warning(
                    f"HTTP transport failed: {e}, falling back to FastMCP client"
                )
                try:
                    # FastMCP client path (FALLBACK)
                    mcp_endpoint = f"{self.endpoint}/mcp"
                    client_instance = await self._get_or_create_fastmcp_client(
                        mcp_endpoint, self.endpoint, self.stream_timeout
                    )
                    async with client_instance as client:
                        from ..tracing.context import set_payload_sizes

                        set_payload_sizes(request_bytes=0, response_bytes=0)
                        result = await client.call_tool(name, args_with_trace)
                        converted_result = self._convert_mcp_result_to_python(result)
                        end_time = time.time()
                        duration_ms = round((end_time - start_time) * 1000, 2)
                        self.logger.info(
                            f"{tp}✅ FastMCP fallback successful: {name} in {duration_ms}ms → {format_result_summary(converted_result)}"
                        )
                        return converted_result
                except Exception as fallback_error:
                    raise RuntimeError(
                        f"Tool call to '{name}' failed: HTTP={e}, FastMCP={fallback_error}"
                    )
        finally:
            _outbound_headers_var.set(None)

    def _convert_mcp_result_to_python(self, mcp_result: Any) -> Any:
        """Convert MCP protocol objects (CallToolResult, etc.) to native Python structures.

        This provides a clean interface for client agents without exposing FastMCP internals.
        Handles complex responses, structured content, and maintains compatibility.
        """
        try:
            # Check for MCP error responses FIRST
            if hasattr(mcp_result, "isError") and mcp_result.isError:
                error_text = ""
                if mcp_result.content:
                    for item in mcp_result.content:
                        if hasattr(item, "text"):
                            error_text = item.text
                            break
                self.logger.error(f"Remote tool returned error: {error_text}")
                raise RuntimeError(f"Remote tool call failed: {error_text}")

            # Handle CallToolResult objects
            if hasattr(mcp_result, "content"):
                self.logger.debug("🔄 Converting CallToolResult to Python dict")

                # Extract content from MCP result
                if not mcp_result.content:
                    return None

                # Handle single content item (most common)
                if len(mcp_result.content) == 1:
                    content_item = mcp_result.content[0]
                    return self._convert_content_item_to_python(content_item)

                # Handle multiple content items
                else:
                    converted_items = []
                    for item in mcp_result.content:
                        converted_items.append(
                            self._convert_content_item_to_python(item)
                        )
                    return {"content": converted_items, "type": "multi_content"}

            # Handle structured content objects
            elif hasattr(mcp_result, "structured_content"):
                self.logger.debug("🔄 Converting structured content to Python dict")
                return self._convert_structured_content(mcp_result.structured_content)

            # Handle already converted/plain objects
            elif isinstance(
                mcp_result, (dict, list, str, int, float, bool, type(None))
            ):
                self.logger.debug("✅ Result already in Python format")
                return mcp_result

            # Handle other object types by attempting dict conversion
            else:
                self.logger.debug(f"🔄 Converting {type(mcp_result).__name__} to dict")
                if hasattr(mcp_result, "__dict__"):
                    return mcp_result.__dict__
                else:
                    return str(mcp_result)

        except RuntimeError:
            raise
        except Exception as e:
            self.logger.warning(
                f"⚠️ Failed to convert MCP result, returning as-is: {e}"
            )
            return mcp_result

    def _convert_content_item_to_python(self, content_item: Any) -> Any:
        """Convert individual content items to Python structures."""
        try:
            # Handle ResourceLink content (resource_link type)
            if getattr(content_item, "type", None) == "resource_link":
                resource_data = {
                    "type": "resource_link",
                    "resource": {
                        "uri": str(getattr(content_item, "uri", "")),
                        "name": getattr(content_item, "name", ""),
                    },
                }
                if getattr(content_item, "mimeType", None) is not None:
                    resource_data["resource"]["mimeType"] = content_item.mimeType
                if getattr(content_item, "description", None) is not None:
                    resource_data["resource"]["description"] = content_item.description
                if getattr(content_item, "size", None) is not None:
                    resource_data["resource"]["size"] = content_item.size
                if getattr(content_item, "annotations", None) is not None:
                    annotations = content_item.annotations
                    if hasattr(annotations, "model_dump"):
                        resource_data["resource"]["annotations"] = (
                            annotations.model_dump(exclude_none=True)
                        )
                    else:
                        resource_data["resource"]["annotations"] = annotations
                self.logger.debug(
                    "🔗 Converted resource_link content: %s",
                    resource_data["resource"].get("name"),
                )
                return resource_data

            # Handle TextContent objects
            elif hasattr(content_item, "text"):
                text_content = content_item.text

                # Try to parse as JSON first (for structured responses)
                try:
                    parsed = json_loads(text_content)
                    self.logger.debug(f"📊 Parsed JSON content: {type(parsed)}")
                    return parsed
                except (ValueError, TypeError):
                    # Return as plain text if not JSON
                    self.logger.debug("📝 Returning text content as-is")
                    return text_content

            # Handle ImageContent, ResourceContent, etc.
            elif hasattr(content_item, "type"):
                return {
                    "type": content_item.type,
                    "data": getattr(content_item, "data", str(content_item)),
                }

            # Handle dict-like objects
            elif isinstance(content_item, dict):
                return content_item

            # Fallback to string representation
            else:
                return str(content_item)

        except Exception as e:
            self.logger.warning(f"⚠️ Content conversion failed: {e}")
            return str(content_item)

    def _convert_structured_content(self, structured_content: Any) -> Any:
        """Convert structured content to Python dict."""
        if isinstance(structured_content, dict):
            return structured_content
        elif hasattr(structured_content, "__dict__"):
            return structured_content.__dict__
        else:
            return {"data": str(structured_content)}

    def _normalize_resource_link(self, item: dict) -> dict:
        """Normalize a resource_link content item to the nested format consumers expect.

        MCP wire format has fields flat on the object, but the FastMCP client path
        returns them nested under a "resource" sub-dict. This ensures consistency
        regardless of transport.
        """
        # Support both flat (wire format) and already-nested formats
        nested = item.get("resource", {}) or {}
        resource_data = {
            "type": "resource_link",
            "resource": {
                "uri": str(item.get("uri", nested.get("uri", ""))),
                "name": item.get("name", nested.get("name", "")),
            },
        }
        for field in ("mimeType", "description", "size"):
            val = item.get(field) if field in item else nested.get(field)
            if val is not None:
                resource_data["resource"][field] = val
        annotations = item.get("annotations") if "annotations" in item else nested.get("annotations")
        if annotations is not None:
            resource_data["resource"]["annotations"] = annotations
        return resource_data

    def _normalize_http_result(self, result: Any) -> Any:
        """Normalize HTTP result to match FastMCP format.

        Extracts structured content from MCP envelope so callers get consistent
        response format regardless of transport method (HTTP direct vs FastMCP).
        """
        if not isinstance(result, dict):
            return result

        # If result has "content" array (MCP envelope format), extract the data
        if "content" in result and isinstance(result["content"], list):
            content_list = result["content"]

            if not content_list:
                return None

            # Single content item - extract and parse
            if len(content_list) == 1:
                content_item = content_list[0]
                # Normalize resource_link to nested format matching FastMCP path
                if (
                    isinstance(content_item, dict)
                    and content_item.get("type") == "resource_link"
                ):
                    return self._normalize_resource_link(content_item)
                # Preserve other non-text content types (image, etc.) as-is
                if isinstance(content_item, dict) and content_item.get("type") not in (
                    None,
                    "text",
                ):
                    return content_item
                if isinstance(content_item, dict) and "text" in content_item:
                    text_value = content_item["text"]
                    if isinstance(text_value, (dict, list)):
                        return text_value
                    try:
                        return json_loads(text_value)
                    except (ValueError, TypeError):
                        return text_value
                return content_item

            # Multiple content items - convert each
            converted_items = []
            for item in content_list:
                # Normalize resource_link to nested format matching FastMCP path
                if isinstance(item, dict) and item.get("type") == "resource_link":
                    converted_items.append(self._normalize_resource_link(item))
                # Preserve other non-text content types as-is
                elif isinstance(item, dict) and item.get("type") not in (None, "text"):
                    converted_items.append(item)
                elif isinstance(item, dict) and "text" in item:
                    text_value = item["text"]
                    if isinstance(text_value, (dict, list)):
                        converted_items.append(text_value)
                    else:
                        try:
                            converted_items.append(json_loads(text_value))
                        except (ValueError, TypeError):
                            converted_items.append(text_value)
                else:
                    converted_items.append(item)
            return {"content": converted_items, "type": "multi_content"}

        # Result is already in clean format
        return result

    def _sanitize_arguments(self, arguments: dict) -> dict:
        """Convert non-JSON-serializable argument values to plain dicts.

        Handles Pydantic models, dataclasses, and objects with __dict__.
        """
        if not arguments:
            return {}
        return {k: self._sanitize_value(v) for k, v in arguments.items()}

    def _sanitize_value(self, value):
        """Recursively convert a value to JSON-serializable form."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {k: self._sanitize_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize_value(v) for v in value]
        # Pydantic v2 model
        if hasattr(value, "model_dump"):
            return value.model_dump()
        # Pydantic v1 model
        if hasattr(value, "dict") and not isinstance(value, type):
            return value.dict()
        # Dataclass
        import dataclasses

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.asdict(value)
        # Fallback: try __dict__, then str
        if hasattr(value, "__dict__"):
            return value.__dict__
        return str(value)

    async def _http_call(self, name: str, arguments: dict = None) -> Any:
        """Direct HTTP call using pooled httpx client with performance tracking."""
        import time

        start_time = time.time()

        try:
            import httpx

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": self._sanitize_arguments(arguments)},
            }

            # Serialize payload as bytes — avoids extra str→bytes encode
            request_body = json_dumps_bytes(payload)
            request_bytes = len(request_body)

            url = f"{self.endpoint}/mcp"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            # Add trace headers
            headers = self._inject_trace_headers(headers)

            # Inject merged outbound headers (session propagated + custom + per-call)
            outbound = _outbound_headers_var.get()
            if outbound:
                for key, value in outbound.items():
                    headers[key] = value

            # Enhanced timeout for large content processing
            enhanced_timeout = max(
                self.timeout, 300
            )  # At least 5 minutes for large files

            # Set X-Mesh-Timeout for registry proxy (#769). If already
            # propagated from an incoming request, keep that value;
            # otherwise use env/default. Also use it for client timeout.
            if "X-Mesh-Timeout" not in headers and "x-mesh-timeout" not in headers:
                call_timeout = os.environ.get(
                    "MCP_MESH_CALL_TIMEOUT", str(int(enhanced_timeout))
                )
                headers["X-Mesh-Timeout"] = call_timeout

            # Use X-Mesh-Timeout to set client-side timeout (authoritative override)
            mesh_timeout_val = headers.get("X-Mesh-Timeout") or headers.get("x-mesh-timeout")
            if mesh_timeout_val:
                try:
                    mesh_timeout_secs = int(mesh_timeout_val)
                    if mesh_timeout_secs > 0:
                        enhanced_timeout = mesh_timeout_secs  # override, not max
                except (ValueError, TypeError):
                    pass

            self.logger.debug(
                f"🔄 HTTP call to {url} with {request_bytes} byte payload, timeout: {enhanced_timeout}s"
            )

            client = _get_httpx_client_sync(self.endpoint)
            response = await client.post(
                url,
                content=request_body,
                headers=headers,
                timeout=httpx.Timeout(enhanced_timeout, read=enhanced_timeout),
            )

            self.logger.debug(
                f"📥 Response status: {response.status_code}, headers: {dict(response.headers)}"
            )

            response.raise_for_status()

            response_text = response.text.strip()
            response_bytes = len(response_text.encode("utf-8"))

            # Set payload sizes for ExecutionTracer to pick up
            from ..tracing.context import set_payload_sizes

            set_payload_sizes(
                request_bytes=request_bytes,
                response_bytes=response_bytes,
            )

            if not response_text:
                self.logger.error("❌ Empty response from server")
                raise RuntimeError("Empty response from server")

            self.logger.debug(
                f"📄 Response length: {len(response_text)} chars, starts with: {response_text[:100]}"
            )

            # Use shared SSE parser for both SSE and plain JSON responses
            data = SSEParser.parse_sse_response(
                response_text, f"UnifiedMCPProxy.{name}"
            )

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                error_code = error.get("code", -1)
                self.logger.error(f"❌ JSON-RPC error {error_code}: {error_msg}")
                raise RuntimeError(f"Tool call error [{error_code}]: {error_msg}")

            # Return the result (compatible with CallToolResult)
            result = data.get("result")
            if result is None:
                self.logger.warning("⚠️ No result field in response")
                return {"content": [{"type": "text", "text": "No result returned"}]}

            # Check for CallToolResult.isError (matches FastMCP error handling)
            if isinstance(result, dict) and result.get("isError"):
                error_text = ""
                for item in result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        error_text = item["text"]
                        break
                self.logger.error(f"❌ Remote tool error: {error_text}")
                raise RuntimeError(f"Tool call error: {error_text}")

            # Calculate performance metrics
            end_time = time.time()
            duration_ms = round((end_time - start_time) * 1000, 2)

            # Normalize HTTP response to match FastMCP format
            normalized_result = self._normalize_http_result(result)
            self.logger.debug(f"✅ HTTP call: {name} in {duration_ms}ms")
            return normalized_result

        except ImportError:
            raise RuntimeError("httpx not available for HTTP call")
        except httpx.TimeoutException as e:
            self.logger.error(f"⏰ HTTP request timeout after {enhanced_timeout}s: {e}")
            raise RuntimeError(f"HTTP request timeout: {e}")
        except httpx.HTTPStatusError as e:
            self.logger.error(
                f"❌ HTTP error {e.response.status_code}: {e.response.text[:200]}"
            )
            raise RuntimeError(
                f"HTTP error {e.response.status_code}: {e.response.text[:200]}"
            )
        except Exception as e:
            self.logger.error(f"❌ HTTP call failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"HTTP call failed: {e}")

    async def stream(
        self,
        name: str | None = None,
        *,
        per_call_headers: dict[str, str] | None = None,
        **arguments,
    ) -> AsyncIterator[str]:
        """Stream text chunks from a remote ``Stream[str]`` tool.

        Returns an async iterator that yields each chunk as the producer emits
        it via MCP ``notifications/progress``. The final result (joined
        accumulated text) is NOT returned separately — callers iterate to get
        the whole stream.

        If the remote producer does NOT advertise ``stream_type == "text"`` in
        its kwargs config, no progress notifications will arrive; in that case
        we degrade gracefully by yielding the buffered final-result text as a
        single chunk so ``async for`` callers always observe at least one item
        when the call succeeds.

        Why this method always uses the FastMCP client path: streaming relies
        on intermediate ``notifications/progress`` messages delivered out-of-
        band on the same MCP session. The proxy's ``_http_call`` path is a
        one-shot JSON-RPC POST which structurally cannot surface those mid-
        stream notifications — only FastMCP's ``Client.call_tool`` exposes a
        ``progress_handler`` callback.

        Cross-loop safety (#818): the queue, the call_task, and the FastMCP
        client must all live on the SAME event loop as this coroutine. We
        construct the queue here (not at the call site) and spawn the call
        task with ``asyncio.create_task`` so the current ``contextvars.Context``
        — including ``_outbound_headers_var`` and the trace context — is
        inherited by the child task automatically.
        """
        target_name = name or self.function_name

        producer_stream_type = self.kwargs_config.get("stream_type")
        if producer_stream_type != "text":
            self.logger.warning(
                f"⚠️ stream(): producer for '{target_name}' does not advertise "
                f"streaming (stream_type={producer_stream_type!r}); the call will "
                "succeed but chunks will arrive as a single buffered final message."
            )

        args_with_trace, merged_headers = self._inject_trace_into_args(
            arguments, per_call_headers
        )

        tp = get_trace_prefix()
        self.logger.info(
            f"{tp}🌊 stream() start: {self.endpoint}/{target_name} "
            f"(args={list(arguments.keys())})"
        )

        SENTINEL: object = object()
        queue: asyncio.Queue = asyncio.Queue()

        async def progress_handler(
            progress: float, total: float | None, message: str | None
        ) -> None:
            if message is not None:
                self.logger.debug(
                    f"{tp}📥 stream() chunk #{int(progress)}: {format_log_value(message)}"
                )
                await queue.put(message)

        mcp_endpoint = f"{self.endpoint}/mcp"
        token = _outbound_headers_var.set(merged_headers if merged_headers else None)
        try:
            client_instance = await self._get_or_create_fastmcp_client(
                mcp_endpoint, self.endpoint, self.stream_timeout
            )
            async with client_instance as client:
                # ``asyncio.create_task`` inherits the current contextvars.Context
                # by default — so trace-context and ``_outbound_headers_var`` set
                # above flow into the task without explicit propagation.
                call_task: asyncio.Task = asyncio.create_task(
                    client.call_tool(
                        target_name,
                        args_with_trace,
                        progress_handler=progress_handler,
                    )
                )
                call_task.add_done_callback(lambda _t: queue.put_nowait(SENTINEL))

                yielded_any = False
                consumer_broke = False
                try:
                    while True:
                        item = await queue.get()
                        if item is SENTINEL:
                            break
                        yielded_any = True
                        yield item
                except (GeneratorExit, asyncio.CancelledError):
                    consumer_broke = True
                    if not call_task.done():
                        call_task.cancel()
                    # Best-effort drain so the underlying coroutine can run its
                    # finally blocks; never mask the GeneratorExit/CancelledError
                    # with the resulting CancelledError from our own cancel().
                    try:
                        await call_task
                    except BaseException:
                        pass
                    raise

                # Normal completion path: drain the task to surface its exception
                # (timeout, connection error, RaiseToolError, etc.) so the
                # consumer's ``async for`` sees the original error class.
                if not call_task.done():
                    call_task.cancel()
                    try:
                        await call_task
                    except asyncio.CancelledError:
                        pass
                    final_result = None
                else:
                    final_result = await call_task

                # If the producer was non-streaming and no progress chunks
                # arrived, extract text from the final CallToolResult and yield
                # it as one chunk (graceful degradation).
                if not yielded_any and final_result is not None:
                    fallback_text = self._extract_text_from_result(final_result)
                    if fallback_text:
                        self.logger.info(
                            f"{tp}🌊 stream() degraded to buffered single-chunk for "
                            f"'{target_name}' ({len(fallback_text)} chars)"
                        )
                        yield fallback_text
        finally:
            _outbound_headers_var.reset(token)
            self.logger.info(f"{tp}🌊 stream() end: {self.endpoint}/{target_name}")

    async def call_tool_streaming(
        self,
        name: str,
        arguments: dict = None,
    ) -> AsyncIterator[Any]:
        """Backwards-compatible alias for :meth:`stream`.

        Older callers passed ``arguments`` as a positional dict. ``stream``
        accepts kwargs to mirror the user-facing ``proxy.stream(prompt=...)``
        idiom, so we splat the dict here.
        """
        async for chunk in self.stream(name, **(arguments or {})):
            yield chunk

    @staticmethod
    def _extract_text_from_result(result: Any) -> str | None:
        """Pull joined text from a FastMCP CallToolResult, if any.

        Returns None when the result has no text-bearing content (e.g. binary
        image content, empty result). Used by ``stream()`` to provide a single
        buffered chunk when the producer didn't emit progress notifications.
        """
        content = getattr(result, "content", None)
        if not content:
            return None
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts) if parts else None

    # MCP Protocol Methods - using FastMCP client's superior implementation
    async def list_tools(self) -> list:
        """List available tools from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Get pooled client with automatic trace header injection
        client_instance = await self._get_or_create_fastmcp_client(
            mcp_endpoint, self.endpoint, self.stream_timeout
        )
        async with client_instance as client:
            result = await client.list_tools()
            return result.tools if hasattr(result, "tools") else result

    async def list_resources(self) -> list:
        """List available resources from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Get pooled client with automatic trace header injection
        client_instance = await self._get_or_create_fastmcp_client(
            mcp_endpoint, self.endpoint, self.stream_timeout
        )
        async with client_instance as client:
            result = await client.list_resources()
            return result.resources if hasattr(result, "resources") else result

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Get pooled client with automatic trace header injection
        client_instance = await self._get_or_create_fastmcp_client(
            mcp_endpoint, self.endpoint, self.stream_timeout
        )
        async with client_instance as client:
            result = await client.read_resource(uri)
            return result.contents if hasattr(result, "contents") else result

    async def list_prompts(self) -> list:
        """List available prompts from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Get pooled client with automatic trace header injection
        client_instance = await self._get_or_create_fastmcp_client(
            mcp_endpoint, self.endpoint, self.stream_timeout
        )
        async with client_instance as client:
            result = await client.list_prompts()
            return result.prompts if hasattr(result, "prompts") else result

    async def get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Get prompt template from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Get pooled client with automatic trace header injection
        client_instance = await self._get_or_create_fastmcp_client(
            mcp_endpoint, self.endpoint, self.stream_timeout
        )
        async with client_instance as client:
            result = await client.get_prompt(name, arguments or {})
            return result

    # Session Management - leveraging FastMCP's built-in session support
    async def create_session(self) -> str:
        """Create a new session and return session ID.

        FastMCP client handles session management internally.
        """

        # Generate session ID for compatibility
        session_id = f"session:{uuid.uuid4().hex[:16]}"
        self.logger.debug(f"📝 Created session ID: {session_id}")
        return session_id

    async def call_with_session(self, session_id: str, **kwargs) -> Any:
        """Call tool with explicit session ID for stateful operations.

        FastMCP client handles session routing automatically.
        """
        # For now, delegate to regular call_tool
        # FastMCP client may handle sessions differently
        function_args = kwargs.copy()
        function_args["session_id"] = session_id

        return await self.call_tool(self.function_name, function_args)

    async def close_session(self, session_id: str) -> bool:
        """Close session and cleanup session state."""
        self.logger.debug(f"🗑️ Session close requested for: {session_id}")
        # FastMCP client handles session cleanup internally
        return True

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"UnifiedMCPProxy(endpoint='{self.endpoint}', "
            f"function='{self.function_name}', fastmcp_client=True)"
        )


# Compatibility aliases for gradual migration
class FastMCPProxy(UnifiedMCPProxy):
    """Alias for UnifiedMCPProxy - more descriptive name."""

    pass


class EnhancedUnifiedMCPProxy(UnifiedMCPProxy):
    """Enhanced version with additional auto-configuration capabilities.

    This is the main proxy class that should be used for all MCP agent types.
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: dict | None = None
    ):
        """Initialize Enhanced Unified MCP Proxy."""
        super().__init__(endpoint, function_name, kwargs_config)

        # Additional enhanced configuration
        self._configure_enhanced_features()

    def _configure_enhanced_features(self):
        """Configure enhanced features from kwargs."""
        # Retry configuration
        self.retry_delay = self.kwargs_config.get("retry_delay", 1.0)
        self.retry_backoff = self.kwargs_config.get("retry_backoff", 2.0)

        # Authentication
        self.auth_required = self.kwargs_config.get("auth_required", False)

        # Content type handling
        self.accepted_content_types = self.kwargs_config.get(
            "accepts", ["application/json"]
        )
        self.default_content_type = self.kwargs_config.get(
            "content_type", "application/json"
        )

        self.logger.info(
            f"🚀 Enhanced Unified MCP proxy - retries: {self.retry_count}, "
            f"auth_required: {self.auth_required}"
        )

    async def call_tool_enhanced(self, name: str, arguments: dict = None) -> Any:
        """Enhanced tool call with retry logic and custom configuration."""
        last_exception = None

        for attempt in range(self.retry_count + 1):
            try:
                return await self.call_tool(name, arguments)

            except Exception as e:
                last_exception = e

                if attempt < self.retry_count:
                    # Calculate retry delay with backoff
                    delay = self.retry_delay * (self.retry_backoff**attempt)

                    self.logger.warning(
                        f"🔄 Request failed (attempt {attempt + 1}/{self.retry_count + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )

                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ All {self.retry_count + 1} attempts failed for {name}"
                    )

        raise last_exception
