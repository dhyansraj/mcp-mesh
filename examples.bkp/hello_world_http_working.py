#!/usr/bin/env python3
"""
Working example of Hello World with HTTP wrapper.

This demonstrates the proper way to enable HTTP transport for MCP agents.
"""

import asyncio
import logging
import signal
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent
from mcp_mesh.runtime.http_wrapper import HttpConfig, HttpMcpWrapper

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the FastMCP server
server = FastMCP(name="hello-world-http-working")


@server.tool()
@mesh_agent(
    capability="greeting",
    dependencies=["SystemAgent"],
    enable_http=True,
    http_port=8889,
    description="Greeting service with HTTP transport",
)
def greet_with_http(name: str = "World", SystemAgent: Any = None) -> dict[str, Any]:
    """Generate a greeting, optionally with system date."""
    result = {"greeting": f"Hello, {name}!", "transport": "http"}

    if SystemAgent:
        try:
            date_info = SystemAgent.getDate()
            result["system_date"] = date_info
            result["dependency_status"] = "connected"
        except Exception as e:
            result["dependency_error"] = str(e)
            result["dependency_status"] = "error"
    else:
        result["dependency_status"] = "not_available"

    return result


@server.tool()
def get_status() -> dict[str, Any]:
    """Get server status."""
    return {
        "server": server.name,
        "status": "healthy",
        "transport": ["stdio", "http"],
        "http_port": 8889,
    }


async def run_with_http_wrapper():
    """Run the server with HTTP wrapper enabled."""
    # Create HTTP wrapper configuration
    config = HttpConfig(host="0.0.0.0", port=8889, cors_enabled=True)

    # Create and start HTTP wrapper
    logger.info("Creating HTTP wrapper...")
    http_wrapper = HttpMcpWrapper(server, config)

    logger.info("Setting up HTTP wrapper...")
    await http_wrapper.setup()

    logger.info("Starting HTTP wrapper...")
    await http_wrapper.start()

    logger.info(f"🌐 HTTP wrapper started at {http_wrapper.get_endpoint()}")
    logger.info("📍 Test endpoints:")
    logger.info("  curl http://localhost:8889/health")
    logger.info("  curl http://localhost:8889/mesh/info")
    logger.info("  curl http://localhost:8889/mesh/tools")
    logger.info(
        '  curl -X POST http://localhost:8889/mcp -H "Content-Type: application/json" -d \'{"method": "tools/list"}\''
    )
    logger.info("")
    logger.info("🔧 Call the greeting function:")
    logger.info(
        '  curl -X POST http://localhost:8889/mcp -H "Content-Type: application/json" -d \'{"method": "tools/call", "params": {"name": "greet_with_http", "arguments": {"name": "HTTP User"}}}\''
    )
    logger.info("")

    # Setup signal handlers
    stop_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run both stdio server and HTTP wrapper
    logger.info("Starting stdio server in parallel...")

    # Create tasks for both transports
    stdio_task = asyncio.create_task(run_stdio_server(stop_event))

    try:
        # Wait for shutdown signal
        await stop_event.wait()
    finally:
        # Clean shutdown
        logger.info("Shutting down...")
        stdio_task.cancel()
        await http_wrapper.stop()

        # Wait for stdio task to complete
        try:
            await stdio_task
        except asyncio.CancelledError:
            pass

        logger.info("Shutdown complete")


async def run_stdio_server(stop_event: asyncio.Event):
    """Run the stdio server in a separate task."""
    try:
        # This would normally be server.run(transport="stdio")
        # but we need it to be async-compatible
        logger.info("Stdio transport ready (simulated)")
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("Stdio server cancelled")


def main():
    """Main entry point."""
    logger.info("🚀 Starting Hello World server with HTTP transport...")

    try:
        asyncio.run(run_with_http_wrapper())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
