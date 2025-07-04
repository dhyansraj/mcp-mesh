"""MCP Client Proxy using HTTP JSON-RPC for MCP protocol compliance."""

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..shared.content_extractor import ContentExtractor

logger = logging.getLogger(__name__)


class MCPClientProxy:
    """Synchronous MCP client proxy for dependency injection.

    Replaces SyncHttpClient with official MCP SDK integration while
    maintaining the same callable interface for dependency injection.

    NO CONNECTION POOLING - Creates new connection per request for K8s load balancing.
    """

    def __init__(self, endpoint: str, function_name: str):
        """Initialize MCP client proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call
        """
        self.endpoint = endpoint.rstrip("/")
        self.function_name = function_name
        self.logger = logger.getChild(f"proxy.{function_name}")

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

            url = f"{self.endpoint}/mcp/"  # Use trailing slash to avoid 307 redirect
            data = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",  # FastMCP requires both
                },
            )

            with urllib.request.urlopen(req, timeout=30.0) as response:
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

        except Exception as e:
            self.logger.error(f"Failed to call {self.function_name}: {e}")
            raise RuntimeError(f"Error calling {self.function_name}: {e}")

    # Phase 2: Full MCP Protocol Support
    def list_tools(self) -> list:
        """List available tools from remote agent."""
        self.logger.debug(f"🔍 Listing tools from {self.endpoint}")
        try:
            return self._run_async(self._async_list_tools())
        except Exception as e:
            self.logger.error(f"❌ Failed to list tools: {e}")
            raise RuntimeError(f"Error listing tools: {e}")

    async def _async_list_tools(self) -> list:
        """Async implementation that delegates to AsyncMCPClient."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_tools()
        finally:
            await client.close()

    def list_resources(self) -> list:
        """List available resources from remote agent."""
        self.logger.debug(f"🔍 Listing resources from {self.endpoint}")
        try:
            return self._run_async(self._async_list_resources())
        except Exception as e:
            self.logger.error(f"❌ Failed to list resources: {e}")
            raise RuntimeError(f"Error listing resources: {e}")

    async def _async_list_resources(self) -> list:
        """Async implementation that delegates to AsyncMCPClient."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_resources()
        finally:
            await client.close()

    def read_resource(self, uri: str) -> Any:
        """Read resource contents from remote agent."""
        self.logger.debug(f"📖 Reading resource '{uri}' from {self.endpoint}")
        try:
            return self._run_async(self._async_read_resource(uri))
        except Exception as e:
            self.logger.error(f"❌ Failed to read resource '{uri}': {e}")
            raise RuntimeError(f"Error reading resource '{uri}': {e}")

    async def _async_read_resource(self, uri: str) -> Any:
        """Async implementation that delegates to AsyncMCPClient."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.read_resource(uri)
        finally:
            await client.close()

    def list_prompts(self) -> list:
        """List available prompts from remote agent."""
        self.logger.debug(f"🔍 Listing prompts from {self.endpoint}")
        try:
            return self._run_async(self._async_list_prompts())
        except Exception as e:
            self.logger.error(f"❌ Failed to list prompts: {e}")
            raise RuntimeError(f"Error listing prompts: {e}")

    async def _async_list_prompts(self) -> list:
        """Async implementation that delegates to AsyncMCPClient."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.list_prompts()
        finally:
            await client.close()

    def get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Get prompt template from remote agent."""
        self.logger.debug(f"📝 Getting prompt '{name}' from {self.endpoint}")
        try:
            return self._run_async(self._async_get_prompt(name, arguments))
        except Exception as e:
            self.logger.error(f"❌ Failed to get prompt '{name}': {e}")
            raise RuntimeError(f"Error getting prompt '{name}': {e}")

    async def _async_get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Async implementation that delegates to AsyncMCPClient."""
        client = AsyncMCPClient(self.endpoint)
        try:
            return await client.get_prompt(name, arguments)
        finally:
            await client.close()

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


class AsyncMCPClient:
    """Async HTTP client for MCP JSON-RPC protocol."""

    def __init__(self, endpoint: str, timeout: float = 30.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self.logger = logger.getChild(f"client.{endpoint}")

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call remote tool using MCP JSON-RPC protocol."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            # Make async HTTP request
            result = await self._make_request(payload)
            self.logger.debug(f"Tool call successful: {tool_name}")
            return result
        except Exception as e:
            self.logger.error(f"Tool call failed: {tool_name} - {e}")
            raise

    async def _make_request(self, payload: dict) -> dict:
        """Make async HTTP request to MCP endpoint."""
        url = f"{self.endpoint}/mcp/"

        try:
            # Use httpx for proper async HTTP requests (better threading support than aiohttp)
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )

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
            # Fallback to sync urllib if httpx not available
            self.logger.warning("httpx not available, falling back to sync urllib")
            return await self._make_request_sync(payload)

    async def _make_request_sync(self, payload: dict) -> dict:
        """Fallback sync HTTP request using urllib."""
        url = f"{self.endpoint}/mcp/"
        data = json.dumps(payload).encode("utf-8")

        # Create request
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        try:
            # Make synchronous request (will run in thread pool)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_data = response.read().decode("utf-8")
                data = json.loads(response_data)

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Return the result
            if "result" in data:
                return data["result"]
            return data

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"MCP endpoint not found at {url}")
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error to {url}: {e.reason}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response: {e}")

    async def list_tools(self) -> list:
        """List available tools."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        result = await self._make_request(payload)
        return result.get("tools", [])

    async def list_resources(self) -> list:
        """List available resources."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
        result = await self._make_request(payload)
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> Any:
        """Read resource contents."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": uri},
        }
        result = await self._make_request(payload)
        return result.get("contents", [])

    async def list_prompts(self) -> list:
        """List available prompts."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}}
        result = await self._make_request(payload)
        return result.get("prompts", [])

    async def get_prompt(self, name: str, arguments: dict = None) -> Any:
        """Get prompt template."""
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        payload = {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": params}
        result = await self._make_request(payload)
        return result

    async def close(self):
        """Close client (no persistent connection to close)."""
        pass


class FullMCPProxy(MCPClientProxy):
    """Full MCP Protocol Proxy with streaming support and complete MCP method access.

    This proxy extends MCPClientProxy to provide:
    1. Full MCP protocol support (tools, resources, prompts)
    2. Streaming tool calls using FastMCP's text/event-stream
    3. Direct method access for developers (not just __call__)
    4. Multihop streaming capabilities (A→B→C chains)

    Designed to replace the prototype McpMeshAgent with proper dependency injection.
    """

    def __init__(self, endpoint: str, function_name: str):
        """Initialize Full MCP Proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call (for __call__ compatibility)
        """
        super().__init__(endpoint, function_name)
        self.logger = logger.getChild(f"full_proxy.{function_name}")

    # Phase 6: Streaming Support - THE BREAKTHROUGH METHOD!
    async def call_tool_streaming(
        self, name: str, arguments: dict = None
    ) -> "AsyncIterator[dict]":
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
            # Import here to avoid circular imports
            import asyncio
            import json

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

                url = f"{self.endpoint}/mcp/"

                async with httpx.AsyncClient(timeout=30.0) as client:
                    async with client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "text/event-stream",  # THIS IS THE KEY!
                        },
                    ) as response:
                        if response.status_code >= 400:
                            raise RuntimeError(f"HTTP error {response.status_code}")

                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    data_str = line[6:]  # Remove "data: " prefix
                                    if data_str.strip():
                                        chunk = json.loads(data_str)
                                        yield chunk
                                except json.JSONDecodeError:
                                    continue

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

    async def read_resource(self, uri: str) -> "Any":
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

    async def get_prompt(self, name: str, arguments: dict = None) -> "Any":
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
        import uuid
        
        # Generate unique session ID
        session_id = f"session:{uuid.uuid4().hex[:16]}"
        
        # For Phase 6, we just return the ID. The session routing middleware
        # will handle the actual session assignment when calls are made with
        # the session ID in headers.
        self.logger.debug(f"Created session ID: {session_id}")
        return session_id

    async def call_with_session(self, session_id: str, **kwargs) -> "Any":
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
            import json
            
            # Build MCP tool call request
            # Add session_id to function arguments if the function expects it
            function_args = kwargs.copy()
            function_args["session_id"] = session_id  # Pass session_id as function parameter
            
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
            url = f"{self.endpoint.rstrip('/')}/mcp/"

            # Add session ID to headers for session routing
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",  # Required by FastMCP
                "X-Session-ID": session_id,  # Key header for session routing
            }

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
