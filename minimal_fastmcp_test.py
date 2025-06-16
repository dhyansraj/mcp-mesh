#!/usr/bin/env python3
"""
Minimal FastMCP server test to understand the basics.
"""

from fastmcp import FastMCP

# Create FastMCP server
server = FastMCP("test-server")


@server.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    import asyncio

    async def main():
        print("Starting minimal FastMCP server...")
        print("Available tools:")
        tools = await server.get_tools()
        for tool in tools:
            print(f"  - {tool}")  # tools might be strings

        print("\nRunning FastMCP server on stdio...")
        print("Send JSON-RPC messages to test tools")

        # Run the server
        await server.run_async()

    asyncio.run(main())
