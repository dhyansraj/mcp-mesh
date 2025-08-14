"""Full MCP Protocol Proxy with streaming support and enhanced auto-configuration."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

from ..shared.sse_parser import SSEStreamProcessor
from .async_mcp_client import AsyncMCPClient
from .mcp_client_proxy import MCPClientProxy

logger = logging.getLogger(__name__)


class FullMCPProxy(MCPClientProxy):
    """Full MCP Protocol Proxy with streaming support and complete MCP method access.

    This proxy extends MCPClientProxy to provide:
    1. Full MCP protocol support (tools, resources, prompts)
    2. Streaming tool calls using FastMCP's text/event-stream
    3. Direct method access for developers (not just __call__)
    4. Multihop streaming capabilities (A→B→C chains)

    Designed to replace the prototype McpMeshAgent with proper dependency injection.
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: Optional[dict] = None
    ):
        """Initialize Full MCP Proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call (for __call__ compatibility)
            kwargs_config: Optional kwargs configuration from @mesh.tool decorator
        """
        super().__init__(endpoint, function_name, kwargs_config)
        self.logger = logger.getChild(f"full_proxy.{function_name}")

        # Log kwargs configuration if provided
        if self.kwargs_config:
            self.logger.debug(
                f"🔧 FullMCPProxy initialized with kwargs: {self.kwargs_config}"
            )

    def _inject_trace_headers(self, headers: dict) -> dict:
        """Inject trace context headers for distributed tracing."""
        from ..tracing.trace_context_helper import TraceContextHelper

        TraceContextHelper.inject_trace_headers_to_request(
            headers, self.endpoint, self.logger
        )
        return headers

    # Phase 6: Streaming Support - THE BREAKTHROUGH METHOD!
    async def call_tool_streaming(
        self, name: str, arguments: dict = None
    ) -> AsyncIterator[dict]:
        """Call a tool with streaming response using FastMCP's text/event-stream.

        This is the breakthrough method that enables multihop streaming (A→B→C chains)
        by leveraging FastMCP's built-in streaming support.

        Args:
            name: Tool name to call
            arguments: Tool arguments

        Yields:
            Streaming response chunks as dictionaries
        """
        self.logger.debug(f"🌊 Streaming call to tool '{name}' with args: {arguments}")

        try:
            # Prepare JSON-RPC payload
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }

            # Use httpx for streaming support
            try:
                import httpx

                url = f"{self.endpoint}/mcp"

                # Build headers with trace context
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",  # THIS IS THE KEY!
                }
                headers = self._inject_trace_headers(headers)

                async with httpx.AsyncClient(timeout=30.0) as client:
                    async with client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code >= 400:
                            raise RuntimeError(f"HTTP error {response.status_code}")

                        # Use shared SSE stream processor
                        sse_processor = SSEStreamProcessor(f"FullMCPProxy.{name}")

                        async for chunk_bytes in response.aiter_bytes(8192):
                            chunks = sse_processor.process_chunk(chunk_bytes)
                            for chunk in chunks:
                                yield chunk

                        # Process any remaining data
                        final_chunks = sse_processor.finalize()
                        for chunk in final_chunks:
                            yield chunk

            except ImportError:
                # Fallback: if httpx not available, use sync call
                self.logger.warning(
                    "httpx not available for streaming, falling back to sync call"
                )
                result = await self._async_call_tool(name, arguments)
                yield result

        except Exception as e:
            self.logger.error(f"❌ Streaming call to '{name}' failed: {e}")
            raise RuntimeError(f"Streaming call to '{name}' failed: {e}")

    async def _async_call_tool(self, name: str, arguments: dict = None) -> dict:
        """Async version of tool call (non-streaming fallback)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            result = await client.call_tool(name, arguments or {})
            return result
        finally:
            await client.close()

    # Vanilla MCP Protocol Methods (100% compatibility)
    async def list_tools(self) -> list:
        """List available tools from remote agent (vanilla MCP method)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_tools()
        finally:
            await client.close()

    async def list_resources(self) -> list:
        """List available resources from remote agent (vanilla MCP method)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_resources()
        finally:
            await client.close()

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent (vanilla MCP method)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.read_resource(uri)
        finally:
            await client.close()

    async def list_prompts(self) -> list:
        """List available prompts from remote agent (vanilla MCP method)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_prompts()
        finally:
            await client.close()

    async def get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Get prompt template from remote agent (vanilla MCP method)."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.get_prompt(name, arguments)
        finally:
            await client.close()

    # Phase 6: Explicit Session Management
    async def create_session(self) -> str:
        """
        Create a new session and return session ID.

        For Phase 6 explicit session management. In Phase 8, this will be
        automated based on @mesh.tool(session_required=True) annotations.

        Returns:
            New session ID string
        """
        # Generate unique session ID
        session_id = f"session:{uuid.uuid4().hex[:16]}"

        # For Phase 6, we just return the ID. The session routing middleware
        # will handle the actual session assignment when calls are made with
        # the session ID in headers.
        self.logger.debug(f"Created session ID: {session_id}")
        return session_id

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
        try:
            import httpx

            # Build MCP tool call request
            # Add session_id to function arguments if the function expects it
            function_args = kwargs.copy()
            function_args["session_id"] = (
                session_id  # Pass session_id as function parameter
            )

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": self.function_name,
                    "arguments": function_args,
                },
            }

            # URL for MCP protocol endpoint
            url = f"{self.endpoint.rstrip('/')}/mcp"

            # Add session ID to headers for session routing
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",  # Required by FastMCP
                "X-Session-ID": session_id,  # Key header for session routing
            }
            headers = self._inject_trace_headers(headers)

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 404:
                    raise RuntimeError(f"MCP endpoint not found at {url}")
                elif response.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP error {response.status_code}: {response.reason_phrase}"
                    )

                response_text = response.text

                # Handle Server-Sent Events format from FastMCP
                if response_text.startswith("event:"):
                    # Parse SSE format: extract JSON from "data:" lines
                    json_data = None
                    for line in response_text.split("\n"):
                        if line.startswith("data:"):
                            json_str = line[5:].strip()  # Remove 'data:' prefix
                            try:
                                json_data = json.loads(json_str)
                                break
                            except json.JSONDecodeError:
                                continue

                    if json_data is None:
                        raise RuntimeError("Could not parse SSE response from FastMCP")
                    data = json_data
                else:
                    # Plain JSON response
                    data = response.json()

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Return the result
            if "result" in data:
                return data["result"]
            return data

        except httpx.RequestError as e:
            raise RuntimeError(f"Connection error to {url}: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response: {e}")
        except ImportError:
            # Fallback error - session calls require httpx for header support
            raise RuntimeError("Session calls require httpx library for header support")

    async def close_session(self, session_id: str) -> bool:
        """
        Close session and cleanup session state.

        Args:
            session_id: Session ID to close

        Returns:
            True if session was closed successfully
        """
        # For Phase 6, session cleanup is handled by the session routing middleware
        # and Redis TTL. In Phase 8, this might send explicit cleanup requests.
        self.logger.debug(f"Session close requested for: {session_id}")

        # Always return True for Phase 6 - cleanup is automatic
        return True

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"FullMCPProxy(endpoint='{self.endpoint}', function='{self.function_name}')"
        )


class EnhancedFullMCPProxy(FullMCPProxy):
    """Enhanced Full MCP proxy with streaming auto-configuration and advanced features.

    Auto-configures based on kwargs from @mesh.tool decorator:
    - streaming: Enable/disable streaming responses
    - stream_timeout: Timeout for streaming requests
    - buffer_size: Streaming buffer size
    - Plus all EnhancedMCPClientProxy features (timeout, retries, headers, auth)
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: Optional[dict] = None
    ):
        """Initialize Enhanced Full MCP Proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call
            kwargs_config: Optional kwargs configuration from @mesh.tool decorator
        """
        super().__init__(endpoint, function_name, kwargs_config)
        self.kwargs_config = kwargs_config or {}

        # Configure streaming from kwargs
        self._configure_from_kwargs()

        self.logger = logger.getChild(f"enhanced_full_proxy.{function_name}")

    def _configure_from_kwargs(self):
        """Auto-configure proxy settings from kwargs."""
        # Basic configuration (inherited from EnhancedMCPClientProxy concepts)
        self.timeout = self.kwargs_config.get("timeout", 30)
        self.retry_count = self.kwargs_config.get("retry_count", 1)
        self.retry_delay = self.kwargs_config.get("retry_delay", 1.0)
        self.retry_backoff = self.kwargs_config.get("retry_backoff", 2.0)
        self.custom_headers = self.kwargs_config.get("custom_headers", {})
        self.auth_required = self.kwargs_config.get("auth_required", False)

        # Streaming-specific configuration
        self.streaming_capable = self.kwargs_config.get("streaming", False)
        self.stream_timeout = self.kwargs_config.get("stream_timeout", 300)  # 5 minutes
        self.buffer_size = self.kwargs_config.get("buffer_size", 4096)

        # Session management configuration
        self.session_required = self.kwargs_config.get("session_required", False)
        self.stateful = self.kwargs_config.get("stateful", False)
        self.auto_session_management = self.kwargs_config.get(
            "auto_session_management", True
        )  # Enable by default
        self._current_session_id = None  # Track current session for auto-management

        # Content handling
        self.accepted_content_types = self.kwargs_config.get(
            "accepts", ["application/json"]
        )
        self.default_content_type = self.kwargs_config.get(
            "content_type", "application/json"
        )
        self.max_response_size = self.kwargs_config.get(
            "max_response_size", 10 * 1024 * 1024
        )  # 10MB

        self.logger.info(
            f"🔧 Enhanced Full MCP proxy configured - timeout: {self.timeout}s, "
            f"retries: {self.retry_count}, streaming: {self.streaming_capable}, "
            f"stream_timeout: {self.stream_timeout}s, session_required: {self.session_required}, "
            f"auto_session_management: {self.auto_session_management}"
        )

    def call_tool_auto(self, name: str, arguments: dict = None) -> Any:
        """Automatically choose streaming vs non-streaming and handle sessions based on configuration."""
        # Handle automatic session management if required
        if self.session_required and self.auto_session_management:
            return self._call_with_auto_session(name, arguments)

        # Regular non-session calls
        if self.streaming_capable:
            # Return async generator for streaming
            return self.call_tool_streaming_enhanced(name, arguments)
        else:
            # Return coroutine for regular async call
            return self.call_tool_enhanced(name, arguments)

    async def _call_with_auto_session(self, name: str, arguments: dict = None) -> Any:
        """Automatically manage session creation and cleanup for session-required calls."""
        # Create session if we don't have one
        if not self._current_session_id:
            self._current_session_id = await self.create_session()
            self.logger.info(f"🎯 Auto-created session: {self._current_session_id}")

        try:
            # Make the call with session
            if self.streaming_capable:
                # For streaming calls, we need to handle session in headers
                # Note: call_with_session doesn't support streaming yet, so fall back to enhanced call
                self.logger.debug(
                    "🌊 Session-required streaming call - using enhanced streaming with session headers"
                )
                return self.call_tool_streaming_enhanced(
                    name, arguments, session_id=self._current_session_id
                )
            else:
                # Use the existing session-aware method
                # call_with_session expects function arguments as kwargs, not the function name
                function_args = arguments or {}
                result = await self.call_with_session(
                    session_id=self._current_session_id, **function_args
                )
                return result

        except Exception as e:
            self.logger.error(f"❌ Auto-session call failed: {e}")
            # Clean up session on failure
            if self._current_session_id:
                try:
                    await self.close_session(self._current_session_id)
                    self._current_session_id = None
                    self.logger.info("🧹 Cleaned up failed session")
                except Exception as cleanup_error:
                    self.logger.warning(f"⚠️ Session cleanup failed: {cleanup_error}")
            raise

    async def call_tool_enhanced(self, name: str, arguments: dict = None) -> Any:
        """Enhanced non-streaming tool call with retry logic and custom configuration."""
        last_exception = None

        for attempt in range(self.retry_count + 1):
            try:
                return await self._make_enhanced_request(name, arguments or {})

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

    async def _make_enhanced_request(self, name: str, arguments: dict) -> Any:
        """Make enhanced MCP request with custom headers and configuration."""
        import os

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        # Build headers with custom configuration
        headers = {
            "Content-Type": self.default_content_type,
            "Accept": ", ".join(self.accepted_content_types),
        }

        # Add custom headers
        headers.update(self.custom_headers)

        # Add authentication headers if required
        if self.auth_required:
            auth_token = os.getenv("MCP_MESH_AUTH_TOKEN")
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            else:
                self.logger.warning("⚠️ Authentication required but no token available")

        # Inject trace context headers
        headers = self._inject_trace_headers(headers)

        url = f"{self.endpoint}/mcp"

        try:
            import httpx

            # Use configured timeout
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                # Check response size
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_response_size:
                    raise ValueError(
                        f"Response too large: {content_length} bytes > {self.max_response_size}"
                    )

                response.raise_for_status()

                result = response.json()
                if "error" in result:
                    raise Exception(f"MCP request failed: {result['error']}")

                # Apply existing content extraction
                from ..shared.content_extractor import ContentExtractor

                return ContentExtractor.extract_content(result.get("result"))

        except httpx.TimeoutException:
            raise Exception(f"Request timeout after {self.timeout}s")
        except httpx.ConnectError as e:
            raise Exception(f"Connection failed: {str(e)}")
        except Exception as e:
            self.logger.error(f"Enhanced request failed: {e}")
            raise

    async def call_tool_streaming_enhanced(
        self, name: str, arguments: dict = None, session_id: str = None
    ) -> AsyncIterator[dict]:
        """Enhanced streaming with auto-configuration and retry logic."""
        if not self.streaming_capable:
            raise ValueError(
                f"Tool {name} not configured for streaming (streaming=False in kwargs)"
            )

        async for chunk in self._make_streaming_request_enhanced(
            name, arguments or {}, session_id=session_id
        ):
            yield chunk

    async def _make_streaming_request_enhanced(
        self, name: str, arguments: dict, session_id: str = None
    ) -> AsyncIterator[dict]:
        """Make enhanced streaming request with kwargs configuration."""
        import os

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}

        # Add custom headers
        headers.update(self.custom_headers)

        # Add authentication headers if required
        if self.auth_required:
            auth_token = os.getenv("MCP_MESH_AUTH_TOKEN")
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

        # Add session ID header if provided
        if session_id:
            headers["X-Session-ID"] = session_id

        # Inject trace context headers
        headers = self._inject_trace_headers(headers)

        url = f"{self.endpoint}/mcp"

        try:
            import httpx

            # Use stream-specific timeout
            async with httpx.AsyncClient(timeout=self.stream_timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    response.raise_for_status()

                    # Use shared SSE stream processor
                    sse_processor = SSEStreamProcessor(f"EnhancedFullMCPProxy.{name}")

                    async for chunk_bytes in response.aiter_bytes(
                        max(self.buffer_size, 8192)
                    ):
                        chunks = sse_processor.process_chunk(chunk_bytes)
                        for chunk in chunks:
                            yield chunk

                    # Process any remaining data
                    final_chunks = sse_processor.finalize()
                    for chunk in final_chunks:
                        yield chunk

        except httpx.TimeoutException:
            raise Exception(f"Streaming timeout after {self.stream_timeout}s")
        except Exception as e:
            self.logger.error(f"Enhanced streaming request failed: {e}")
            raise

    async def cleanup_auto_session(self):
        """Clean up automatically created session."""
        if self._current_session_id and self.auto_session_management:
            try:
                await self.close_session(self._current_session_id)
                self.logger.info(
                    f"🧹 Auto-session cleaned up: {self._current_session_id}"
                )
                self._current_session_id = None
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to cleanup auto-session: {e}")

    def __del__(self):
        """Cleanup on object destruction."""
        # Note: async cleanup in __del__ is not ideal, but provides a safety net
        if hasattr(self, "_current_session_id") and self._current_session_id:
            import asyncio

            try:
                # Try to cleanup session on deletion
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    loop.create_task(self.cleanup_auto_session())
            except Exception:
                # Silent failure in destructor
                pass
