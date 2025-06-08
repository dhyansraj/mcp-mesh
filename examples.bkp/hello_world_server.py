#!/usr/bin/env python3
"""
Hello World MCP Server using FastMCP

A minimal MCP server demonstrating:
- Tool registration and execution
- Resource management
- Prompt definitions
- Protocol compliance with official MCP SDK

This serves as a foundation for understanding MCP server patterns.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent


def create_hello_world_server() -> FastMCP:
    """Create a Hello World MCP server with basic capabilities."""

    # Create FastMCP server instance
    app = FastMCP(
        name="hello-world-server",
        instructions="A simple Hello World MCP server demonstrating basic MCP protocol capabilities.",
    )

    # ===== TOOLS =====

    @app.tool()
    def say_hello(name: str = "World") -> str:
        """
        Say hello to someone.

        Args:
            name: The name to greet (defaults to "World")

        Returns:
            A greeting message
        """
        return f"Hello, {name}! Welcome to the MCP Mesh SDK."

    @app.tool()
    def echo(message: str) -> str:
        """
        Echo back a message.

        Args:
            message: The message to echo back

        Returns:
            The same message with "Echo:" prefix
        """
        return f"Echo: {message}"

    @app.tool()
    def add_numbers(a: float, b: float) -> float:
        """
        Add two numbers together.

        Args:
            a: First number
            b: Second number

        Returns:
            The sum of a and b
        """
        return a + b

    @app.tool()
    def get_server_info() -> dict[str, Any]:
        """
        Get information about this MCP server.

        Returns:
            Dictionary containing server information
        """
        return {
            "server_name": app.name,
            "description": "Hello World MCP Server",
            "version": "1.0.0",
            "capabilities": ["tools", "resources", "prompts"],
            "status": "running",
        }

    # ===== RESOURCES =====

    @app.resource("text://hello")
    def hello_resource() -> str:
        """A simple text resource containing a greeting."""
        return "Hello from the MCP Mesh SDK! This is a sample text resource."

    @app.resource("text://info")
    def info_resource() -> str:
        """Information about this MCP server."""
        return """
# MCP Hello World Server

This is a demonstration MCP server built with the official MCP Python SDK.

## Capabilities:
- Basic tool execution
- Resource serving
- Prompt management
- Protocol compliance testing

## Tools Available:
- say_hello: Greet someone by name
- echo: Echo back a message
- add_numbers: Perform simple arithmetic
- get_server_info: Get server metadata

Powered by MCP Mesh SDK
"""

    # ===== PROMPTS =====

    @app.prompt()
    def greeting_prompt(name: str = "there") -> list[PromptMessage]:
        """
        Generate a friendly greeting prompt.

        Args:
            name: The name to include in the greeting

        Returns:
            List of prompt messages for greeting
        """
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Please generate a warm and friendly greeting for {name}. "
                    f"Make it welcoming and mention that this is from the MCP Mesh SDK.",
                ),
            )
        ]

    @app.prompt()
    def help_prompt() -> list[PromptMessage]:
        """
        Generate a help prompt explaining server capabilities.

        Returns:
            List of prompt messages for help information
        """
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text="Please explain what this MCP server can do. Include information about "
                    "the available tools, resources, and how to use them effectively.",
                ),
            )
        ]

    return app


def main():
    """Run the Hello World MCP server."""
    print("🚀 Starting MCP Hello World Server...")

    # Create the server
    server = create_hello_world_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Server ready! Running on stdio transport...")
    print("💡 Use MCP client to connect and test the server.")
    print("📝 Press Ctrl+C to stop the server.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")


if __name__ == "__main__":
    main()
