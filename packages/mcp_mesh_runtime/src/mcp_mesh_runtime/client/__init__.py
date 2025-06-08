"""
MCP Mesh Client Components

MCP client implementations built on the official MCP SDK.
Provides client capabilities for service mesh communication.
"""

from mcp.client.session import ClientSession

# Re-export official MCP client components
__all__ = [
    "ClientSession",
]
