"""Synchronous HTTP client for cross-service MCP calls."""

import json
from typing import Any

import requests


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
        self.session = requests.Session()

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a remote MCP tool synchronously.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments for the tool

        Returns:
            The result from the tool call

        Raises:
            requests.HTTPError: If the HTTP request fails
            RuntimeError: If the tool call returns an error
        """
        payload = {
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        try:
            response = self.session.post(
                f"{self.base_url}/mcp", json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()

            # Check if the tool call resulted in an error
            if data.get("isError", False):
                error_content = data.get("content", [{}])[0]
                error_msg = error_content.get("text", "Unknown error")
                raise RuntimeError(f"Tool call error: {error_msg}")

            # Extract the result from the content
            content = data.get("content", [])
            if content and isinstance(content[0], dict):
                text = content[0].get("text", "{}")
                try:
                    # Try to parse as JSON
                    return json.loads(text)
                except json.JSONDecodeError:
                    # Return as plain text if not JSON
                    return text

            return None

        except requests.exceptions.Timeout:
            raise RuntimeError(f"Timeout calling {tool_name} at {self.base_url}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Connection error to {self.base_url}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(f"Tool {tool_name} not found at {self.base_url}")
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the remote service.

        Returns:
            List of tool descriptions
        """
        payload = {"method": "tools/list"}

        try:
            response = self.session.post(
                f"{self.base_url}/mcp", json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            return data.get("tools", [])

        except requests.exceptions.RequestException as e:
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
