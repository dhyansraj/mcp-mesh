"""Unified MCP Proxy using FastMCP's built-in client.

This replaces both MCPClientProxy and FullMCPProxy with a single implementation
that uses FastMCP's superior client capabilities.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UnifiedMCPProxy:
    """Unified MCP proxy using FastMCP's built-in client.

    This provides the implementation for McpMeshAgent type parameters,
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

    def _create_fastmcp_client(self, endpoint: str):
        """Create FastMCP client with DNS detection for threading conflict avoidance.

        This method detects DNS names vs IP addresses and forces HTTP fallback for DNS names
        to avoid FastMCP client threading conflicts in containerized environments.

        Args:
            endpoint: MCP endpoint URL

        Returns:
            FastMCP Client instance with or without trace headers
        """
        try:
            # Extract hostname from endpoint URL for DNS detection
            from urllib.parse import urlparse

            parsed = urlparse(endpoint)
            hostname = parsed.hostname or parsed.netloc.split(":")[0]

            # DNS resolution works perfectly with FastMCP - no need to force HTTP fallback
            self.logger.debug(f"✅ Using FastMCP client for endpoint: {hostname}")

            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport

            # Try to get current trace context for header injection
            trace_headers = self._get_trace_headers()

            # Use stream_timeout for read timeout (default 300s for LLM calls)
            # Note: sse_read_timeout is deprecated, use httpx_client_factory instead
            import httpx

            def create_httpx_client(**kwargs):
                # Override timeout to use stream_timeout for long-running LLM calls
                kwargs["timeout"] = httpx.Timeout(
                    timeout=self.stream_timeout,
                    connect=30.0,  # 30s for connection
                    read=self.stream_timeout,  # Long read timeout for SSE streams
                    write=30.0,  # 30s for writes
                    pool=30.0,  # 30s for pool
                )
                return httpx.AsyncClient(**kwargs)

            if trace_headers:
                # Create client with trace headers for distributed tracing
                transport = StreamableHttpTransport(
                    url=endpoint,
                    headers=trace_headers,
                    httpx_client_factory=create_httpx_client,
                )
                return Client(transport)
            else:
                # Create standard client when no trace context available
                transport = StreamableHttpTransport(
                    url=endpoint,
                    httpx_client_factory=create_httpx_client,
                )
                return Client(transport)

        except ImportError as e:
            # DNS names or FastMCP not available - this will trigger HTTP fallback
            self.logger.debug(f"🔄 FastMCP client unavailable: {e}")
            raise  # Re-raise to trigger _fallback_http_call
        except Exception as e:
            # Any other error - this will trigger HTTP fallback
            self.logger.debug(f"🔄 FastMCP client error: {e}")
            raise ImportError(
                f"FastMCP client failed: {e}"
            )  # Convert to ImportError to trigger fallback

    def _get_trace_headers(self) -> dict[str, str]:
        """Extract trace headers from current context for distributed tracing.

        Returns:
            Dict of trace headers or empty dict if no trace context available
        """
        try:
            from ..tracing.context import TraceContext

            current_trace = TraceContext.get_current()
            if current_trace:
                headers = {
                    "X-Trace-ID": current_trace.trace_id,
                    "X-Parent-Span": current_trace.span_id,  # Current span becomes parent for downstream
                }
                self.logger.info(
                    f"🔗 TRACE_PROPAGATION: Injecting headers trace_id={current_trace.trace_id[:8]}... "
                    f"parent_span={current_trace.span_id[:8]}..."
                )
                return headers
            else:
                self.logger.warning("🔗 TRACE_PROPAGATION: No trace context available")
                return {}

        except Exception as e:
            # Never fail MCP calls due to tracing issues
            self.logger.warning(
                f"🔗 TRACE_PROPAGATION: Exception getting trace context: {e}"
            )
            return {}

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
        self.include_telemetry_in_response = self.kwargs_config.get(
            "include_telemetry_response", True
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

    # Note: We use context managers for each call instead of persistent client
    # This is cleaner and follows FastMCP patterns

    # Main tool call method - clean async interface following FastMCP patterns
    async def __call__(self, *args, **kwargs) -> Any:
        """Call the remote tool using natural async patterns."""
        return await self.call_tool_with_tracing(self.function_name, kwargs)

    async def call_tool_with_tracing(self, name: str, arguments: dict = None) -> Any:
        """Call a tool with clean ExecutionTracer integration (v0.4.0 style)."""
        # Check if telemetry is enabled - use same check as ExecutionTracer for consistency
        from ..tracing.execution_tracer import ExecutionTracer
        from ..tracing.utils import is_tracing_enabled

        if not self.telemetry_enabled or not is_tracing_enabled():
            return await self.call_tool(name, arguments)

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
                        "proxy_type": "fastmcp_with_fallback",
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

            return await self.call_tool(name, arguments)

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

    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        """Call a tool using FastMCP client with HTTP transport.

        Returns CallToolResult object with structured content parsing.
        """
        import time

        start_time = time.time()

        try:
            # Use correct FastMCP client endpoint - agents expose MCP on /mcp
            mcp_endpoint = f"{self.endpoint}/mcp"
            self.logger.debug(f"🔄 Trying FastMCP client with endpoint: {mcp_endpoint}")

            # Create client with automatic trace header injection
            client_instance = self._create_fastmcp_client(mcp_endpoint)

            async with client_instance as client:

                # Use FastMCP's call_tool which returns CallToolResult object
                result = await client.call_tool(name, arguments or {})

                # Calculate performance metrics
                end_time = time.time()
                duration_ms = round((end_time - start_time) * 1000, 2)

                # FastMCP client automatically handles:
                # - CallToolResult object creation
                # - Structured content parsing
                # - Error handling

                # Convert CallToolResult to native Python structures for client simplicity
                converted_result = self._convert_mcp_result_to_python(result)

                # Add telemetry metadata to converted result if enabled
                if self.include_telemetry_in_response and isinstance(
                    converted_result, dict
                ):
                    converted_result["_telemetry"] = {
                        "method": "fastmcp_client",
                        "duration_ms": duration_ms,
                        "endpoint": mcp_endpoint,
                        "tool_name": name,
                        "telemetry_enabled": self.telemetry_enabled,
                        "distributed_tracing": self.distributed_tracing_enabled,
                    }

                self.logger.info(
                    f"✅ FastMCP tool call successful: {name} in {duration_ms}ms"
                )
                return converted_result

        except ImportError as e:
            self.logger.warning(
                f"FastMCP Client not available: {e}, falling back to HTTP"
            )
            return await self._fallback_http_call(name, arguments)
        except Exception as e:
            self.logger.warning(f"FastMCP Client failed: {e}, falling back to HTTP")
            # Try HTTP fallback
            try:
                result = await self._fallback_http_call(name, arguments)
                return result
            except Exception as fallback_error:
                raise RuntimeError(
                    f"Tool call to '{name}' failed: {e}, fallback also failed: {fallback_error}"
                )

    def _convert_mcp_result_to_python(self, mcp_result: Any) -> Any:
        """Convert MCP protocol objects (CallToolResult, etc.) to native Python structures.

        This provides a clean interface for client agents without exposing FastMCP internals.
        Handles complex responses, structured content, and maintains compatibility.
        """
        try:
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

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to convert MCP result, returning as-is: {e}")
            return mcp_result

    def _convert_content_item_to_python(self, content_item: Any) -> Any:
        """Convert individual content items to Python structures."""
        try:
            # Handle TextContent objects
            if hasattr(content_item, "text"):
                text_content = content_item.text

                # Try to parse as JSON first (for structured responses)
                try:
                    import json

                    parsed = json.loads(text_content)
                    self.logger.debug(f"📊 Parsed JSON content: {type(parsed)}")
                    return parsed
                except (json.JSONDecodeError, TypeError):
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

    async def _fallback_http_call(self, name: str, arguments: dict = None) -> Any:
        """Enhanced fallback HTTP call using httpx directly with performance tracking."""
        import time

        start_time = time.time()

        try:
            import json

            import httpx

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }

            url = f"{self.endpoint}/mcp"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            # Add trace headers
            headers = self._inject_trace_headers(headers)

            # Enhanced timeout for large content processing
            enhanced_timeout = max(
                self.timeout, 300
            )  # At least 5 minutes for large files

            self.logger.info(
                f"🔄 HTTP fallback call to {url} with {len(str(payload))} byte payload, timeout: {enhanced_timeout}s"
            )

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(enhanced_timeout, read=enhanced_timeout),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                response = await client.post(url, json=payload, headers=headers)

                self.logger.debug(
                    f"📥 Response status: {response.status_code}, headers: {dict(response.headers)}"
                )

                response.raise_for_status()

                response_text = response.text.strip()

                if not response_text:
                    self.logger.error("❌ Empty response from server")
                    raise RuntimeError("Empty response from server")

                self.logger.debug(
                    f"📄 Response length: {len(response_text)} chars, starts with: {response_text[:100]}"
                )

                data = None

                # Handle SSE format
                if response_text.startswith("event:") or "data:" in response_text:
                    self.logger.debug("🔄 Parsing SSE format response")
                    # Parse SSE format - handle multiple events
                    for line in response_text.split("\n"):
                        line = line.strip()
                        if line.startswith("data:"):
                            json_str = line[5:].strip()
                            if json_str and json_str != "":
                                try:
                                    data = json.loads(json_str)
                                    self.logger.debug(
                                        f"✅ Successfully parsed SSE data: {type(data)}"
                                    )
                                    break
                                except json.JSONDecodeError as e:
                                    self.logger.warning(
                                        f"⚠️ Failed to parse SSE line: {json_str[:100]}, error: {e}"
                                    )
                                    continue
                else:
                    # Plain JSON response
                    self.logger.debug("🔄 Parsing plain JSON response")
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        self.logger.error(
                            f"❌ Failed to parse JSON response: {e}, content: {response_text[:200]}"
                        )
                        raise RuntimeError(f"Invalid JSON response: {e}")

                if data is None:
                    raise RuntimeError("No valid data found in response")

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

                # Calculate performance metrics
                end_time = time.time()
                duration_ms = round((end_time - start_time) * 1000, 2)

                # Log performance metrics
                self.logger.info(
                    f"📊 HTTP fallback performance: {duration_ms}ms for tool '{name}'"
                )

                if isinstance(result, dict) and "content" in result:
                    self.logger.info(
                        f"✅ Successfully parsed result with content in {duration_ms}ms"
                    )
                    # Add performance metadata to result if enabled
                    if self.include_telemetry_in_response and isinstance(result, dict):
                        result["_telemetry"] = {
                            "method": "http_fallback",
                            "duration_ms": duration_ms,
                            "endpoint": self.endpoint,
                            "tool_name": name,
                            "telemetry_enabled": self.telemetry_enabled,
                            "fallback_reason": "fastmcp_unavailable",
                        }
                    return result
                else:
                    # Wrap in CallToolResult-like structure with performance data
                    self.logger.info(
                        f"🔄 Wrapping result in CallToolResult structure ({duration_ms}ms)"
                    )
                    wrapped_result = {
                        "content": [{"type": "text", "text": str(result)}]
                    }
                    if self.include_telemetry_in_response:
                        wrapped_result["_telemetry"] = {
                            "method": "http_fallback",
                            "duration_ms": duration_ms,
                            "endpoint": self.endpoint,
                            "tool_name": name,
                            "telemetry_enabled": self.telemetry_enabled,
                            "fallback_reason": "fastmcp_unavailable",
                        }
                    return wrapped_result

        except ImportError:
            raise RuntimeError("httpx not available for HTTP fallback")
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
            self.logger.error(f"❌ HTTP fallback failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"HTTP fallback failed: {e}")

    async def call_tool_streaming(
        self, name: str, arguments: dict = None, progress_handler=None
    ) -> AsyncIterator[Any]:
        """Call a tool with streaming response using FastMCP's streaming support.

        Args:
            name: Tool name to call
            arguments: Tool arguments
            progress_handler: Optional progress handler for streaming

        Yields:
            Streaming response chunks
        """
        if not self.streaming_capable:
            raise ValueError(f"Tool {name} not configured for streaming")

        client = await self._get_client()

        try:
            # Use FastMCP's streaming capabilities
            # Note: FastMCP client may have different streaming API
            # For now, fall back to regular call_tool and yield result
            self.logger.debug(f"🌊 Streaming call to tool '{name}'")

            result = await client.call_tool(name, arguments or {})
            yield result

        except Exception as e:
            self.logger.error(f"❌ Streaming call to '{name}' failed: {e}")
            raise RuntimeError(f"Streaming call to '{name}' failed: {e}")

    # MCP Protocol Methods - using FastMCP client's superior implementation
    async def list_tools(self) -> list:
        """List available tools from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Create client with automatic trace header injection
        client_instance = self._create_fastmcp_client(mcp_endpoint)
        async with client_instance as client:
            result = await client.list_tools()
            return result.tools if hasattr(result, "tools") else result

    async def list_resources(self) -> list:
        """List available resources from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Create client with automatic trace header injection
        client_instance = self._create_fastmcp_client(mcp_endpoint)
        async with client_instance as client:
            result = await client.list_resources()
            return result.resources if hasattr(result, "resources") else result

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Create client with automatic trace header injection
        client_instance = self._create_fastmcp_client(mcp_endpoint)
        async with client_instance as client:
            result = await client.read_resource(uri)
            return result.contents if hasattr(result, "contents") else result

    async def list_prompts(self) -> list:
        """List available prompts from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Create client with automatic trace header injection
        client_instance = self._create_fastmcp_client(mcp_endpoint)
        async with client_instance as client:
            result = await client.list_prompts()
            return result.prompts if hasattr(result, "prompts") else result

    async def get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Get prompt template from remote agent."""
        mcp_endpoint = f"{self.endpoint}/mcp"

        # Create client with automatic trace header injection
        client_instance = self._create_fastmcp_client(mcp_endpoint)
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

    def call_tool_auto(self, name: str, arguments: dict = None) -> Any:
        """Automatically choose streaming vs non-streaming based on configuration."""
        if self.streaming_capable:
            return self.call_tool_streaming(name, arguments)
        else:
            return self.call_tool_enhanced(name, arguments)
