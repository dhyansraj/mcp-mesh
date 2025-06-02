#!/usr/bin/env python3
"""
Simple MCP Server Example

Demonstrates basic MCP server implementation using the official MCP SDK.
This serves as a foundation for the mesh service implementations.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool


def create_simple_server() -> Server:
    """Create a simple MCP server with basic capabilities."""
    server = Server("mcp-mesh-example")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="echo",
                description="Echo back the input message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to echo back",
                        }
                    },
                    "required": ["message"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict]:
        """Handle tool calls."""
        if name == "echo":
            message = arguments.get("message", "")
            return [{"type": "text", "text": f"Echo: {message}"}]
        else:
            raise ValueError(f"Unknown tool: {name}")

    return server


async def main():
    """Run the simple MCP server."""
    server = create_simple_server()

    # Run the server using stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
