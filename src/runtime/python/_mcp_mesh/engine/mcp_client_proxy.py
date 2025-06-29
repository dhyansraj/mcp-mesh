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
        url = f"{self.endpoint}/mcp"

        try:
            # Use httpx for proper async HTTP requests (better threading support than aiohttp)
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

                if response.status_code == 404:
                    raise RuntimeError(f"MCP endpoint not found at {url}")
                elif response.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP error {response.status_code}: {response.reason_phrase}"
                    )

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
        url = f"{self.endpoint}/mcp"
        data = json.dumps(payload).encode("utf-8")

        # Create request
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
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
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        result = await self._make_request(payload)
        return result.get("tools", [])

    async def close(self):
        """Close client (no persistent connection to close)."""
        pass
