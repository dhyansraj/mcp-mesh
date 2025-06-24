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

                # Debug: Log raw response format to see if we're getting SSE
                logger.debug(
                    f"🔍 RAW_RESPONSE_FORMAT: First 100 chars: {response_data[:100]}"
                )
                logger.debug(
                    f"🔍 RAW_RESPONSE_FORMAT: Starts with 'event: ': {response_data.startswith('event: ')}"
                )

                # Handle Server-Sent Events (SSE) format from FastMCP
                if response_data.startswith("event: "):
                    logger.debug("🔍 RAW_RESPONSE_FORMAT: Using SSE parsing path")
                    # Parse SSE format: extract JSON from "data: {...}" line
                    lines = response_data.strip().split("\n")
                    for line in lines:
                        if line.startswith("data: "):
                            json_data = line[6:]  # Remove "data: " prefix
                            data = json.loads(json_data)
                            break
                    else:
                        raise RuntimeError("No data line found in SSE response")
                else:
                    logger.debug(
                        "🔍 RAW_RESPONSE_FORMAT: Using regular JSON parsing path"
                    )
                    # Regular JSON response
                    data = json.loads(response_data)

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                error_msg = error.get("message", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Extract the result
            if "result" in data:
                result = data["result"]
                # Handle MCP response format
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if content and isinstance(content[0], dict):
                        content_item = content[0]

                        # Handle different content types
                        if "object" in content_item:
                            # Return the object directly
                            return content_item["object"]
                        elif "text" in content_item:
                            text = content_item["text"]
                            try:
                                # Try to parse as JSON
                                return json.loads(text)
                            except json.JSONDecodeError:
                                # Return as plain text if not JSON
                                return text
                        else:
                            # Fallback to empty dict
                            return {}
                else:
                    return result
            return None

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"Tool {tool_name} not found at {self.base_url}")
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error to {self.base_url}: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"Error calling {tool_name}: {e}")

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the remote service.

        Returns:
            List of tool descriptions
        """
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

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

                # Debug: Log raw response format to see if we're getting SSE
                logger.debug(
                    f"🔍 RAW_RESPONSE_FORMAT: First 100 chars: {response_data[:100]}"
                )
                logger.debug(
                    f"🔍 RAW_RESPONSE_FORMAT: Starts with 'event: ': {response_data.startswith('event: ')}"
                )

                # Handle Server-Sent Events (SSE) format from FastMCP
                if response_data.startswith("event: "):
                    logger.debug("🔍 RAW_RESPONSE_FORMAT: Using SSE parsing path")
                    # Parse SSE format: extract JSON from "data: {...}" line
                    lines = response_data.strip().split("\n")
                    for line in lines:
                        if line.startswith("data: "):
                            json_data = line[6:]  # Remove "data: " prefix
                            data = json.loads(json_data)
                            break
                    else:
                        raise RuntimeError("No data line found in SSE response")
                else:
                    logger.debug(
                        "🔍 RAW_RESPONSE_FORMAT: Using regular JSON parsing path"
                    )
                    # Regular JSON response
                    data = json.loads(response_data)

            if "result" in data:
                return data["result"].get("tools", [])
            return []

        except Exception as e:
            raise RuntimeError(f"Failed to list tools: {e}")

    def health_check(self) -> bool:
        """Check if the remote service is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5.0)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
