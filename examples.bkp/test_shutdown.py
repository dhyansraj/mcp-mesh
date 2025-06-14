#!/usr/bin/env python3
"""
Test shutdown behavior for MCP Mesh agents.

This minimal example helps debug shutdown issues.
"""

import signal
import sys
import time

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_test_server() -> FastMCP:
    """Create a minimal test server."""

    server = FastMCP(
        name="shutdown-test",
        instructions="Test server for debugging shutdown behavior.",
    )

    @server.tool()
    def simple_tool() -> str:
        """Simple tool without mesh decorator."""
        return "Hello from simple tool"

    @server.tool()
    @mesh_agent(
        capabilities=["test"],
        health_interval=5,  # Short interval for testing
        fallback_mode=True,
    )
    def mesh_tool() -> str:
        """Tool with mesh decorator."""
        return "Hello from mesh tool"

    return server


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print(f"\n📍 Received signal {signum}")
    print("🛑 Shutting down gracefully...")
    sys.exit(0)


def main():
    """Run the test server."""
    print("🚀 Starting shutdown test server...")
    print("📝 This server tests graceful shutdown behavior")
    print("🛑 Press Ctrl+C to test shutdown\n")

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create server
    server = create_test_server()

    print(f"📡 Server name: {server.name}")
    print("▶️  Starting server on stdio transport...")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user (KeyboardInterrupt)")
    except SystemExit:
        print("🛑 Server stopped (SystemExit)")
    except Exception as e:
        print(f"❌ Server error: {e}")
    finally:
        try:
            print("🏁 Server shutdown complete")
            # Give a moment for cleanup
            time.sleep(0.5)
        except (ValueError, OSError):
            # Handle closed stdout on shutdown
            pass


if __name__ == "__main__":
    main()
