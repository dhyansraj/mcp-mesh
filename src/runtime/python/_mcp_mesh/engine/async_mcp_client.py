"""Async HTTP client for MCP JSON-RPC protocol."""

import asyncio
import atexit
import json
import logging
import urllib.error
import urllib.request
from typing import Any, ClassVar, Optional

from ..shared.sse_parser import SSEParser

logger = logging.getLogger(__name__)


class AsyncMCPClient:
    """Async HTTP client for MCP JSON-RPC protocol.

    Uses connection pooling to reuse HTTP connections across requests,
    reducing TCP/SSL handshake overhead and preventing port exhaustion.
    """

    # Class-level connection pool (shared across instances for same endpoint)
    _client_pool: ClassVar[dict[str, "httpx.AsyncClient"]] = {}
    _pool_lock: ClassVar[Optional[asyncio.Lock]] = None

    # Default connection limits for pooling
    DEFAULT_MAX_CONNECTIONS = 100
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20

    def __init__(self, endpoint: str, timeout: float = 30.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self.logger = logger.getChild(f"client.{endpoint}")

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """Get or create the class-level lock (handles event loop creation)."""
        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()
        return cls._pool_lock

    @classmethod
    async def _get_pooled_client(
        cls, endpoint: str, timeout: float
    ) -> "httpx.AsyncClient":
        """Get or create a pooled httpx client for the endpoint.

        This enables connection reuse across multiple requests to the same endpoint,
        significantly reducing overhead from TCP connection establishment and SSL handshakes.
        """
        import httpx

        async with cls._get_lock():
            if endpoint not in cls._client_pool:
                cls._client_pool[endpoint] = httpx.AsyncClient(
                    timeout=timeout,
                    limits=httpx.Limits(
                        max_connections=cls.DEFAULT_MAX_CONNECTIONS,
                        max_keepalive_connections=cls.DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                    ),
                )
                logger.debug(f"Created pooled client for endpoint: {endpoint}")
            return cls._client_pool[endpoint]

    @classmethod
    async def close_all_clients(cls) -> None:
        """Close all pooled clients. Call during application shutdown."""
        async with cls._get_lock():
            for endpoint, client in list(cls._client_pool.items()):
                try:
                    await client.aclose()
                    logger.debug(f"Closed pooled client for: {endpoint}")
                except Exception as e:
                    logger.warning(f"Error closing client for {endpoint}: {e}")
            cls._client_pool.clear()

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
        """Make async HTTP request to MCP endpoint using pooled connections."""
        url = f"{self.endpoint}/mcp"

        try:
            # Use httpx with connection pooling for better resource management
            import httpx

            # Get pooled client (reuses connections across requests)
            client = await self._get_pooled_client(self.endpoint, self.timeout)

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

            # Use shared SSE parser
            data = SSEParser.parse_sse_response(
                response_text, f"AsyncMCPClient.{self.endpoint}"
            )

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
        """Close client instance (no-op as connections are pooled at class level).

        Connection pooling is managed at the class level for efficiency.
        To close all pooled connections during shutdown, use:
            await AsyncMCPClient.close_all_clients()
        """
        pass
