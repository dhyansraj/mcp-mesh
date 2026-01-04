#!/usr/bin/env python3
"""
MCP Mesh Reload Runner - Entry point for file watching mode.

Usage:
    python -m _mcp_mesh.reload_runner <agent_script.py>

This module is invoked by `meshctl start --watch` to wrap agent execution
with file watching. When source files change, the agent process is
automatically restarted.

Environment variables:
    MCP_MESH_RELOAD_DEBOUNCE: Debounce delay in seconds (default: 0.5)
    MCP_MESH_RELOAD_PORT_DELAY: Port release delay in seconds (default: 0.5)
"""

import logging
import os
import sys

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for reload runner."""
    if len(sys.argv) < 2:
        print("Usage: python -m _mcp_mesh.reload_runner <agent_script.py>")
        sys.exit(1)

    script_path = sys.argv[1]

    if not os.path.exists(script_path):
        print(f"Error: Script not found: {script_path}")
        sys.exit(1)

    if not script_path.endswith(".py"):
        print(f"Error: Expected a Python script (.py), got: {script_path}")
        sys.exit(1)

    # Import and run with reload
    from .reload import run_with_reload

    run_with_reload(script_path)


if __name__ == "__main__":
    main()
