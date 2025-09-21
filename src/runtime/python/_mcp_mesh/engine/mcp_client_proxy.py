"""MCP Client Proxy using HTTP JSON-RPC for MCP protocol compliance."""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

from ..shared.content_extractor import ContentExtractor
from ..shared.sse_parser import SSEParser
from .async_mcp_client import AsyncMCPClient

logger = logging.getLogger(__name__)


class MCPClientProxy:
    """Synchronous MCP client proxy for dependency injection.

    Replaces SyncHttpClient with official MCP SDK integration while
    maintaining the same callable interface for dependency injection.

    NO CONNECTION POOLING - Creates new connection per request for K8s load balancing.
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: Optional[dict] = None
    ):
        """Initialize MCP client proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call
            kwargs_config: Optional kwargs configuration from @mesh.tool decorator
        """
        self.endpoint = endpoint.rstrip("/")
        self.function_name = function_name
        self.kwargs_config = kwargs_config or {}
        self.logger = logger.getChild(f"proxy.{function_name}")

        # Log kwargs configuration if provided
        if self.kwargs_config:
            self.logger.debug(
                f"🔧 MCPClientProxy initialized with kwargs: {self.kwargs_config}"
            )

    def _run_async(self, coro):
        """Convert async coroutine to sync call."""

        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, need to run in thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            else:
                # No running loop, safe to use loop.run_until_complete
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop exists, create new one
            return asyncio.run(coro)

    def __call__(self, **kwargs) -> Any:
        """Callable interface for dependency injection.

        Makes HTTP MCP calls to remote services. This proxy is only used
        for cross-service dependencies - self-dependencies use SelfDependencyProxy.
        """
        self.logger.debug(f"🔌 MCP call to '{self.function_name}' with args: {kwargs}")

        try:
            result = self._sync_call(**kwargs)
            self.logger.debug(f"✅ MCP call to '{self.function_name}' succeeded")
            return result
        except Exception as e:
            self.logger.error(f"❌ MCP call to '{self.function_name}' failed: {e}")
            raise

    def _sync_call(self, **kwargs) -> Any:
        """Make synchronous MCP tool call to remote service."""
        try:
            # Prepare JSON-RPC payload
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": self.function_name, "arguments": kwargs},
            }

            url = f"{self.endpoint}/mcp"  # Remove trailing slash to avoid 307 redirect
            data = json.dumps(payload).encode("utf-8")

            # Build headers with trace context injection
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",  # FastMCP requires both
            }

            # Inject trace headers for distributed tracing
            from ..tracing.trace_context_helper import TraceContextHelper

            TraceContextHelper.inject_trace_headers_to_request(
                headers, url, self.logger
            )

            req = urllib.request.Request(url, data=data, headers=headers)

            with urllib.request.urlopen(req, timeout=30.0) as response:
                response_data = response.read().decode("utf-8")

                # Use shared SSE parser
                data = SSEParser.parse_sse_response(
                    response_data, f"MCPClientProxy.{self.function_name}"
                )

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Return the result
            if "result" in data:
                result = data["result"]
                return ContentExtractor.extract_content(result)
            return None

        except Exception as e:
            self.logger.error(f"Failed to call {self.function_name}: {e}")
            raise RuntimeError(f"Error calling {self.function_name}: {e}")

    async def _async_call(self, **kwargs) -> Any:
        """Make async MCP tool call with fresh connection."""
        client = None
        try:
            # Create new client for each request (K8s load balancing)
            client = AsyncMCPClient(self.endpoint)
            result = await client.call_tool(self.function_name, kwargs)
            return ContentExtractor.extract_content(result)
        except Exception as e:
            self.logger.error(f"Failed to call {self.function_name}: {e}")
            raise RuntimeError(f"Error calling {self.function_name}: {e}")
        finally:
            # Always clean up connection
            if client:
                await client.close()


class EnhancedMCPClientProxy(MCPClientProxy):
    """Enhanced MCP client proxy with kwargs-based auto-configuration.

    Auto-configures based on kwargs from @mesh.tool decorator:
    - timeout: Request timeout in seconds
    - retry_count: Number of retries for failed requests
    - retry_delay: Base delay between retries (seconds)
    - retry_backoff: Backoff multiplier for retry delays
    - custom_headers: Dict of additional headers to send
    - auth_required: Whether authentication is required
    - accepts: List of accepted content types
    - content_type: Default content type for requests
    - max_response_size: Maximum allowed response size
    """

    def __init__(
        self, endpoint: str, function_name: str, kwargs_config: Optional[dict] = None
    ):
        """Initialize Enhanced MCP Client Proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call
            kwargs_config: Optional kwargs configuration from @mesh.tool decorator
        """
        super().__init__(endpoint, function_name, kwargs_config)

        # Auto-configure from kwargs
        self._configure_from_kwargs()

        self.logger = logger.getChild(f"enhanced_proxy.{function_name}")

    def _configure_from_kwargs(self):
        """Auto-configure proxy settings from kwargs."""
        # Timeout configuration
        self.timeout = self.kwargs_config.get("timeout", 30)

        # Retry configuration
        self.retry_count = self.kwargs_config.get("retry_count", 1)
        self.max_retries = self.retry_count
        self.retry_delay = self.kwargs_config.get("retry_delay", 1.0)
        self.retry_backoff = self.kwargs_config.get("retry_backoff", 2.0)

        # Header configuration
        self.custom_headers = self.kwargs_config.get("custom_headers", {})
        self.auth_required = self.kwargs_config.get("auth_required", False)

        # Content type configuration
        self.accepted_content_types = self.kwargs_config.get(
            "accepts", ["application/json"]
        )
        self.default_content_type = self.kwargs_config.get(
            "content_type", "application/json"
        )
        self.max_response_size = self.kwargs_config.get(
            "max_response_size", 10 * 1024 * 1024
        )  # 10MB default

        # Streaming configuration
        self.streaming_capable = self.kwargs_config.get("streaming", False)

        self.logger.info(
            f"🔧 Enhanced proxy configured - timeout: {self.timeout}s, "
            f"retries: {self.retry_count}, streaming: {self.streaming_capable}"
        )

    def __call__(self, **kwargs) -> Any:
        """Enhanced callable interface with retry logic and custom configuration."""
        self.logger.debug(
            f"🔌 Enhanced MCP call to '{self.function_name}' with args: {kwargs}"
        )

        try:
            result = self._sync_call_with_retries(**kwargs)
            self.logger.debug(
                f"✅ Enhanced MCP call to '{self.function_name}' succeeded"
            )
            return result
        except Exception as e:
            self.logger.error(
                f"❌ Enhanced MCP call to '{self.function_name}' failed: {e}"
            )
            raise

    def _sync_call_with_retries(self, **kwargs) -> Any:
        """Make synchronous MCP request with automatic retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return self._enhanced_sync_call(**kwargs)

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries:
                    # Calculate retry delay with backoff
                    delay = self.retry_delay * (self.retry_backoff**attempt)

                    self.logger.warning(
                        f"🔄 Request failed (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )

                    import time

                    time.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ All {self.max_retries + 1} attempts failed for {self.function_name}"
                    )

        raise last_exception

    def _enhanced_sync_call(self, **kwargs) -> Any:
        """Make enhanced synchronous MCP request with custom headers and configuration."""
        try:
            # Prepare JSON-RPC payload
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {"name": self.function_name, "arguments": kwargs},
            }

            url = f"{self.endpoint}/mcp/"
            data = json.dumps(payload).encode("utf-8")

            # Build headers with custom configuration
            headers = {
                "Content-Type": self.default_content_type,
                "Accept": ", ".join(self.accepted_content_types),
            }

            # Add custom headers
            headers.update(self.custom_headers)

            # Inject trace headers for distributed tracing
            from ..tracing.trace_context_helper import TraceContextHelper

            TraceContextHelper.inject_trace_headers_to_request(
                headers, url, self.logger
            )

            # Add authentication headers if required
            if self.auth_required:
                auth_token = os.getenv("MCP_MESH_AUTH_TOKEN")
                if auth_token:
                    headers["Authorization"] = f"Bearer {auth_token}"
                else:
                    self.logger.warning(
                        "⚠️ Authentication required but no token available"
                    )

            req = urllib.request.Request(url, data=data, headers=headers)

            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                # Check response size
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_response_size:
                    raise ValueError(
                        f"Response too large: {content_length} bytes > {self.max_response_size}"
                    )

                response_data = response.read().decode("utf-8")

                # Handle Server-Sent Events format from FastMCP
                if response_data.startswith("event:"):
                    # Parse SSE format: extract JSON from "data:" lines
                    json_data = None
                    for line in response_data.split("\n"):
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
                    data = json.loads(response_data)

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Return the result
            if "result" in data:
                result = data["result"]
                return ContentExtractor.extract_content(result)
            return None

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"MCP endpoint not found at {url}")
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error to {url}: {e.reason}")
        except Exception as e:
            self.logger.error(f"Enhanced sync call failed: {e}")
            raise RuntimeError(f"Error calling {self.function_name}: {e}")

    async def _enhanced_async_call(self, **kwargs) -> Any:
        """Make enhanced async MCP tool call with retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._make_enhanced_async_request(**kwargs)

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries:
                    # Calculate retry delay with backoff
                    delay = self.retry_delay * (self.retry_backoff**attempt)

                    self.logger.warning(
                        f"🔄 Async request failed (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )

                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ All {self.max_retries + 1} async attempts failed for {self.function_name}"
                    )

        raise last_exception

    async def _make_enhanced_async_request(self, **kwargs) -> Any:
        """Make enhanced async HTTP request with custom configuration."""
        try:
            # Try to use httpx for better async support
            import httpx

            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {"name": self.function_name, "arguments": kwargs},
            }

            # Build headers with custom configuration
            headers = {
                "Content-Type": self.default_content_type,
                "Accept": ", ".join(self.accepted_content_types),
            }

            # Add custom headers
            headers.update(self.custom_headers)

            # Inject trace headers for distributed tracing
            from ..tracing.trace_context_helper import TraceContextHelper

            TraceContextHelper.inject_trace_headers_to_request(
                headers, url, self.logger
            )

            # Add authentication headers if required
            if self.auth_required:
                auth_token = os.getenv("MCP_MESH_AUTH_TOKEN")
                if auth_token:
                    headers["Authorization"] = f"Bearer {auth_token}"

            url = f"{self.endpoint}/mcp/"

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
                return ContentExtractor.extract_content(result.get("result"))

        except ImportError:
            # Fallback to using AsyncMCPClient
            client = AsyncMCPClient(self.endpoint, timeout=self.timeout)
            try:
                result = await client.call_tool(self.function_name, kwargs)
                return ContentExtractor.extract_content(result)
            finally:
                await client.close()
        except Exception as e:
            self.logger.error(f"Enhanced async request failed: {e}")
            raise
