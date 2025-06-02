#!/usr/bin/env python3
"""
Simple Hello World MCP Server

A minimal MCP server using the core Server class for better control and debugging.
Demonstrates basic MCP protocol operations without FastMCP abstractions.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Prompt, PromptMessage, Resource, TextContent, Tool


def create_simple_server() -> Server:
    """Create a simple MCP server with basic tools."""

    server = Server("simple-hello-world")

    # ===== TOOLS =====

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="say_hello",
                description="Say hello to someone",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name to greet",
                            "default": "World",
                        }
                    },
                },
            ),
            Tool(
                name="echo",
                description="Echo back a message",
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
            ),
            Tool(
                name="add",
                description="Add two numbers",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"},
                    },
                    "required": ["a", "b"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle tool calls."""
        if name == "say_hello":
            name_arg = arguments.get("name", "World")
            return [
                TextContent(
                    type="text", text=f"Hello, {name_arg}! Welcome to the MCP Mesh SDK."
                )
            ]

        elif name == "echo":
            message = arguments.get("message", "")
            return [TextContent(type="text", text=f"Echo: {message}")]

        elif name == "add":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            result = a + b
            return [TextContent(type="text", text=f"The sum of {a} + {b} = {result}")]

        else:
            raise ValueError(f"Unknown tool: {name}")

    # ===== RESOURCES =====

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """List available resources."""
        return [
            Resource(
                uri="text://hello",
                name="Hello Resource",
                description="A simple greeting resource",
                mimeType="text/plain",
            ),
            Resource(
                uri="text://info",
                name="Server Info",
                description="Information about this MCP server",
                mimeType="text/plain",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        """Read resource content."""
        if uri == "text://hello":
            return "Hello from the MCP Mesh SDK! This is a simple text resource."
        elif uri == "text://info":
            return """# Simple MCP Hello World Server

This is a demonstration MCP server built with the official MCP Python SDK.

## Capabilities:
- Tools: say_hello, echo, add
- Resources: hello, info
- Protocol: MCP 2024-11-05

Powered by MCP Mesh SDK"""
        else:
            raise ValueError(f"Unknown resource: {uri}")

    # ===== PROMPTS =====

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        """List available prompts."""
        return [
            Prompt(
                name="greeting",
                description="Generate a friendly greeting",
                arguments=[
                    {"name": "name", "description": "Name to greet", "required": False}
                ],
            )
        ]

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict) -> list[PromptMessage]:
        """Get prompt content."""
        if name == "greeting":
            target_name = arguments.get("name", "there")
            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Please generate a warm and friendly greeting for {target_name}. "
                        f"Make it welcoming and mention that this is from the MCP Mesh SDK.",
                    ),
                )
            ]
        else:
            raise ValueError(f"Unknown prompt: {name}")

    return server


async def main():
    """Run the simple MCP server."""
    print("🚀 Starting Simple MCP Hello World Server...")

    # Create server
    server = create_simple_server()
    print(f"📡 Server name: {server.name}")
    print("🎯 Server ready! Listening on stdio...")

    # Run server with stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")
        import traceback

        traceback.print_exc()
