"""Synchronous HTTP client for cross-service MCP calls."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class SyncHttpClient:
    """Synchronous HTTP client for making MCP tool calls across services."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        """Initialize the sync HTTP client.

        Args:
        base_url: Base URL of the remote MCP service
        timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a remote MCP tool synchronously.

        Args:
        tool_name: Name of the tool to call
        arguments: Arguments for the tool

        Returns:
        The result from the tool call

        Raises:
        urllib.error.HTTPError: If the HTTP request fails
        RuntimeError: If the tool call returns an error
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        try:
            # Prepare the request
            url = f"{self.base_url}/mcp"
            data = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            # Make the request
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_data = response.read().decode("utf-8")

                # Debug logging
                logger.debug(f"🔍 RAW_RESPONSE_FORMAT: {response_data}")

                try:
                    result = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error(f"❌ INVALID_JSON_RESPONSE: {response_data}")
                    raise RuntimeError(f"Invalid JSON response: {response_data}")

                # Check for JSON-RPC error
                if "error" in result:
                    error_msg = result["error"].get("message", "Unknown error")
                    logger.error(f"❌ TOOL_CALL_ERROR: {error_msg}")
                    raise RuntimeError(f"Tool call error: {error_msg}")

                # Extract and return the result
                if "result" in result:
                    tool_result = result["result"]
                    logger.debug(f"✅ TOOL_CALL_SUCCESS: {tool_result}")
                    return tool_result
                else:
                    logger.error(f"❌ NO_RESULT_IN_RESPONSE: {result}")
                    raise RuntimeError(f"No result in response: {result}")

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else "No error body"
            logger.error(f"❌ HTTP_ERROR: {e.code} {e.reason} - {error_body}")
            raise RuntimeError(f"HTTP error {e.code}: {e.reason} - {error_body}")

        except Exception as e:
            logger.error(f"❌ TOOL_CALL_EXCEPTION: {e}")
            raise RuntimeError(f"Tool call failed: {e}")
