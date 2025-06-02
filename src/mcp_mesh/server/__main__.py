"""
MCP Mesh Registry Service - Main Entry Point

Command-line entry point for the MCP Mesh Registry Service.
Provides both MCP and REST endpoints with pull-based architecture.

Usage:
    python -m mcp_mesh.server
    python -m mcp_mesh.server --host 0.0.0.0 --port 9000
    python -m mcp_mesh.server --help
"""

import asyncio
import sys

from .registry_server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Registry service interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Registry service failed: {e}")
        sys.exit(1)
