"""
Example File Agent with MCP + Mesh Integration

Demonstrates proper MCP SDK compliance with optional mesh enhancement.
Shows dual decorator pattern for seamless portability.
"""

import asyncio
import logging

from mcp.server.fastmcp import FastMCP
from mcp_mesh_types import mesh_agent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create MCP server instance
server = FastMCP("file-agent")


class FileAgent:
    """Example file agent with MCP + mesh integration."""

    def __init__(self):
        self.name = "file-agent"
        self._setup_tools()

    def _setup_tools(self):
        """Setup MCP tools with dual decorators (MCP + Mesh)."""

        @server.tool()
        @mesh_agent(
            capabilities=["file_read"],
            dependencies=["auth_service", "audit_logger"],
            health_interval=30,
            security_context="file_operations",
            agent_name="file-agent-01",
        )
        async def read_file(path: str, encoding: str = "utf-8") -> str:
            """
            Read file contents with security validation.

            Dual decorator pattern:
            - @server.tool(): Registers as standard MCP tool
            - @mesh_agent(): Adds mesh capabilities (no-op if unavailable)

            Mesh features (when available):
            1. Registers "file_read" capability with registry
            2. Injects auth_service and audit_logger from dependencies
            3. Sends periodic heartbeats every 30 seconds
            4. Handles registry connection failures gracefully
            """
            logger.info(f"Reading file: {path}")

            # Perform the file operation
            try:
                with open(path, encoding=encoding) as f:
                    content = f.read()
                logger.info(f"Successfully read {len(content)} characters from {path}")
                return content
            except FileNotFoundError as e:
                raise FileNotFoundError(f"File not found: {path}") from e
            except PermissionError as e:
                raise PermissionError(f"Permission denied: {path}") from e

        @server.tool()
        @mesh_agent(
            capabilities=["file_write"],
            dependencies=["auth_service", "audit_logger", "backup_service"],
            health_interval=30,
            security_context="file_operations",
            agent_name="file-agent-01",
        )
        async def write_file(path: str, content: str, encoding: str = "utf-8") -> bool:
            """
            Write content to file with backup and audit logging.

            Dual decorator pattern ensures MCP compliance + optional mesh features.
            """
            logger.info(f"Writing to file: {path}")

            # Perform the write operation
            try:
                with open(path, "w", encoding=encoding) as f:
                    f.write(content)

                logger.info(f"Successfully wrote {len(content)} characters to {path}")
                return True

            except PermissionError as e:
                raise PermissionError(f"Permission denied: {path}") from e

        @server.tool()
        @mesh_agent(
            capabilities=["file_list"],
            dependencies=["auth_service"],
            health_interval=60,
            security_context="file_operations",
            agent_name="file-agent-01",
        )
        async def list_files(directory: str) -> list:
            """List files in directory with authentication."""
            logger.info(f"Listing files in: {directory}")

            try:
                import os

                files = os.listdir(directory)
                logger.info(f"Found {len(files)} files in {directory}")
                return files
            except FileNotFoundError as e:
                raise FileNotFoundError(f"Directory not found: {directory}") from e
            except PermissionError as e:
                raise PermissionError(f"Permission denied: {directory}") from e

        # Store references to decorated functions
        self.read_file = read_file
        self.write_file = write_file
        self.list_files = list_files


async def demo():
    """Demo the File Agent functionality."""
    print("Starting File Agent Demo with MCP + Mesh Integration...")

    # Create file agent instance (registers tools with MCP server)
    agent = FileAgent()

    # Example 1: Read a file (create test file first)
    test_content = "Hello, MCP Mesh World!\nThis is a test file."

    try:
        # Write test file
        print("\n1. Writing test file...")
        await agent.write_file("/tmp/test_mesh.txt", test_content)

        # Read test file
        print("\n2. Reading test file...")
        content = await agent.read_file("/tmp/test_mesh.txt")
        print(f"File content: {content}")

        # List files in directory
        print("\n3. Listing files in /tmp...")
        files = await agent.list_files("/tmp")
        print(f"Found files: {files[:10]}...")  # Show first 10 files

        print("\n✅ File Agent demo completed successfully!")

    except Exception as e:
        print(f"❌ Error during demo: {e}")

    finally:
        print("\n4. Cleanup completed (using lightweight definitions package)!")


async def main():
    """Main entry point - run as MCP server or demo."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # Run the demo
        await demo()
    else:
        # Run as MCP server (default)
        print("Starting MCP File Agent Server...")
        print("Tools registered with both MCP SDK and optional mesh integration.")

        # Create agent to register tools
        FileAgent()

        # Run the MCP server
        await server.run()


if __name__ == "__main__":
    # Usage:
    # python file_agent_example.py          # Run as MCP server
    # python file_agent_example.py --demo   # Run demo
    asyncio.run(main())
