#!/usr/bin/env python3
"""
Test FastMCP HTTP server to understand how it works.
"""

import asyncio

from fastmcp import FastMCP

# Create FastMCP server
server = FastMCP("test-server")


@server.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    print(f"🎯 hello() function called with name={name}")
    return f"Hello, {name}!"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    print(f"🎯 add() function called with a={a}, b={b}")
    return a + b


async def test_http_server():
    print("Setting up FastMCP HTTP server...")

    # Get the HTTP app
    http_app = server.http_app()
    print(f"HTTP app type: {type(http_app)}")

    # Check what routes it has
    if hasattr(http_app, "routes"):
        print("HTTP app routes:")
        for route in http_app.routes:
            if hasattr(route, "path"):
                print(f"  - {route.path}")

    # Start HTTP server
    print("\nStarting HTTP server on port 8080...")
    await server.run_http_async(port=8080)


if __name__ == "__main__":
    asyncio.run(test_http_server())
