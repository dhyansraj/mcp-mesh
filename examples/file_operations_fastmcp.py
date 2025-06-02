"""
MCP File Operations Server with FastMCP

This example demonstrates building an MCP server using the FastMCP framework.
It shows:

1. Core MCP SDK patterns with FastMCP
2. Standard file operation tools
3. MCP resources and prompts
4. Optional mesh integration for advanced features

Perfect for learning MCP fundamentals before exploring mesh enhancements.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_mesh_types import (
    FileOperationError,
    FileOperations,
    PermissionDeniedError,
    SecurityValidationError,
)


# Mock FastMCP for demonstration (in real usage: from mcp.server.fastmcp import FastMCP)
class MockFastMCP:
    """Mock FastMCP for demonstration purposes."""

    def __init__(self, name: str, instructions: str = ""):
        self.name = name
        self.instructions = instructions
        self.tools = []
        self.resources = []
        self.prompts = []

    def tool(self, name: str | None = None, description: str | None = None):
        """Mock tool decorator."""

        def decorator(func):
            func._tool_name = name or func.__name__
            func._tool_description = description or func.__doc__
            self.tools.append(func)
            return func

        return decorator

    def resource(self, uri: str):
        """Mock resource decorator."""

        def decorator(func):
            func._resource_uri = uri
            self.resources.append(func)
            return func

        return decorator

    def prompt(self, name: str | None = None):
        """Mock prompt decorator."""

        def decorator(func):
            func._prompt_name = name or func.__name__
            self.prompts.append(func)
            return func

        return decorator


# Import file operations - start with basic operations, then optionally add mesh features

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileOperationsServer:
    """
    MCP File Operations Server using FastMCP.

    This example shows how to build a proper MCP server with:
    - Standard MCP tools using FastMCP decorators
    - MCP resources for server metadata
    - MCP prompts for guided interactions
    - Optional mesh enhancements for production features

    Start here to learn MCP, then explore mesh features for advanced use cases.
    """

    def __init__(
        self,
        base_directory: str | None = None,
        max_file_size: int = 10 * 1024 * 1024,
    ):
        """
        Initialize MCP File Operations Server.

        Args:
            base_directory: Optional base directory for operations
            max_file_size: Maximum file size in bytes
        """
        self.base_directory = base_directory
        self.max_file_size = max_file_size

        # Initialize FastMCP app - this is the core MCP pattern
        self.app = MockFastMCP(
            name="file-operations-server",
            instructions="Secure file operations via MCP protocol",
        )

        # Initialize file operations with basic security
        self.file_ops = FileOperations(
            base_directory=base_directory, max_file_size=max_file_size
        )

        # Setup MCP components - tools, resources, and prompts
        self._setup_mcp_tools()
        self._setup_mcp_resources()
        self._setup_mcp_prompts()

        # Optional: Enable mesh features for production
        self._setup_mesh_enhancements()

    def _setup_mcp_tools(self):
        """Setup core MCP tools using FastMCP decorators."""

        @self.app.tool(name="read_file", description="Read file contents safely")
        async def read_file_tool(path: str, encoding: str = "utf-8") -> str:
            """
            Standard MCP tool for reading file contents.

            This demonstrates the basic MCP pattern:
            1. Use FastMCP @tool decorator
            2. Define clear parameters and return types
            3. Handle errors appropriately
            4. Delegate to secure file operations
            """
            try:
                return await self.file_ops.read_file(path, encoding)
            except (
                FileOperationError,
                SecurityValidationError,
                PermissionDeniedError,
            ) as e:
                logger.error(f"File read error: {e}")
                raise

        @self.app.tool(
            name="write_file", description="Write content to file with backup"
        )
        async def write_file_tool(
            path: str, content: str, encoding: str = "utf-8", create_backup: bool = True
        ) -> bool:
            """
            Standard MCP tool for writing file contents.

            Includes security validation and optional backup creation.
            """
            try:
                return await self.file_ops.write_file(
                    path, content, encoding, create_backup
                )
            except (
                FileOperationError,
                SecurityValidationError,
                PermissionDeniedError,
            ) as e:
                logger.error(f"File write error: {e}")
                raise

        @self.app.tool(name="list_directory", description="List directory contents")
        async def list_directory_tool(
            path: str, include_hidden: bool = False, include_details: bool = False
        ) -> list[Any]:
            """
            Standard MCP tool for directory listing.

            Shows how to handle complex parameters and return structured data.
            """
            try:
                return await self.file_ops.list_directory(
                    path, include_hidden, include_details
                )
            except (
                FileOperationError,
                SecurityValidationError,
                PermissionDeniedError,
            ) as e:
                logger.error(f"Directory list error: {e}")
                raise

        @self.app.tool(
            name="get_file_info", description="Get detailed file information"
        )
        async def get_file_info_tool(path: str) -> dict[str, Any]:
            """
            Standard MCP tool for file information.

            Returns structured metadata about files and directories.
            This is the basic version - see mesh enhancement below for advanced features.
            """
            try:
                # Validate path using file operations security
                validated_path = await self.file_ops._validate_path(path, "read")

                # Get file information
                stat_info = validated_path.stat()

                return {
                    "path": str(validated_path),
                    "name": validated_path.name,
                    "type": "directory" if validated_path.is_dir() else "file",
                    "size": stat_info.st_size,
                    "created": stat_info.st_ctime,
                    "modified": stat_info.st_mtime,
                    "accessed": stat_info.st_atime,
                    "permissions": oct(stat_info.st_mode)[-3:],
                    "is_readable": validated_path.exists()
                    and os.access(validated_path, os.R_OK),
                    "is_writable": validated_path.exists()
                    and os.access(validated_path, os.W_OK),
                    "extension": validated_path.suffix,
                }

            except Exception as e:
                logger.error(f"Get file info error: {e}")
                raise FileOperationError(
                    f"Failed to get file info for {path}: {e}"
                ) from e

        # Store references for potential mesh enhancement
        self.basic_tools = {
            "read_file": read_file_tool,
            "write_file": write_file_tool,
            "list_directory": list_directory_tool,
            "get_file_info": get_file_info_tool,
        }

    def _setup_mcp_resources(self):
        """Setup MCP resources for server metadata and status."""

        @self.app.resource("file://server/config")
        async def server_config_resource() -> str:
            """
            MCP resource providing server configuration.

            Resources in MCP are read-only data sources that clients can access.
            This shows how to expose server metadata as a resource.
            """
            config = {
                "name": "file-operations-server",
                "description": "MCP server for secure file operations",
                "base_directory": (
                    str(self.base_directory) if self.base_directory else None
                ),
                "max_file_size": self.max_file_size,
                "allowed_extensions": list(self.file_ops.allowed_extensions),
                "capabilities": [
                    "file_read",
                    "file_write",
                    "directory_list",
                    "file_info",
                ],
                "security_features": [
                    "path_validation",
                    "file_extension_filtering",
                    "size_limits",
                    "permission_checking",
                ],
            }
            return json.dumps(config, indent=2)

        @self.app.resource("file://server/health")
        async def server_health_resource() -> str:
            """
            MCP resource providing server health status.

            Demonstrates how to expose dynamic status information via resources.
            """
            try:
                health_status = await self.file_ops.health_check()
                return json.dumps(health_status, indent=2)
            except Exception as e:
                error_status = {"status": "error", "error": str(e), "timestamp": "now"}
                return json.dumps(error_status, indent=2)

        @self.app.resource("file://server/stats")
        async def server_stats_resource() -> str:
            """
            MCP resource providing server statistics.

            Shows how to expose runtime metrics and capabilities.
            """
            stats = {
                "tools_registered": len(self.app.tools),
                "resources_registered": len(self.app.resources),
                "prompts_registered": len(self.app.prompts),
                "mcp_version": "1.0",
                "server_capabilities": ["tools", "resources", "prompts"],
                "file_operations": ["read", "write", "list", "info"],
            }
            return json.dumps(stats, indent=2)

    def _setup_mcp_prompts(self):
        """Setup MCP prompts for guided file operations."""

        @self.app.prompt("file_analysis")
        async def file_analysis_prompt(file_path: str) -> list[dict[str, Any]]:
            """
            MCP prompt for file analysis assistance.

            Prompts in MCP provide template conversations or guided interactions.
            This shows how to create dynamic prompts based on file content.
            """
            try:
                # Get file info first
                validated_path = await self.file_ops._validate_path(file_path, "read")

                if validated_path.is_file():
                    content_preview = ""
                    try:
                        # Read first 500 characters for preview
                        content = await self.file_ops.read_file(str(validated_path))
                        content_preview = content[:500] + (
                            "..." if len(content) > 500 else ""
                        )
                    except Exception:
                        content_preview = "[Unable to read file content]"

                    prompt_text = f"""
Analyze the file at {file_path}:

File Information:
- Path: {validated_path}
- Type: {validated_path.suffix or 'No extension'}
- Size: {validated_path.stat().st_size} bytes

Content Preview:
{content_preview}

Please provide insights about:
1. File type and format
2. Content structure and patterns
3. Potential use cases
4. Security considerations
5. Suggested operations
"""
                else:
                    # Directory analysis
                    entries = await self.file_ops.list_directory(
                        str(validated_path), include_details=True
                    )
                    entry_summary = f"Contains {len(entries)} items"

                    prompt_text = f"""
Analyze the directory at {file_path}:

Directory Information:
- Path: {validated_path}
- {entry_summary}

Please provide insights about:
1. Directory structure and organization
2. File types and patterns
3. Potential use cases
4. Security considerations
5. Suggested operations
"""

                return [
                    {"role": "user", "content": {"type": "text", "text": prompt_text}}
                ]

            except Exception as e:
                error_prompt = f"Error analyzing {file_path}: {e}"
                return [
                    {"role": "user", "content": {"type": "text", "text": error_prompt}}
                ]

        @self.app.prompt("getting_started")
        async def getting_started_prompt() -> list[dict[str, Any]]:
            """
            MCP prompt for getting started with file operations.

            Provides guidance on using the available tools and understanding MCP concepts.
            """
            guide_text = """
Getting Started with MCP File Operations:

Understanding MCP:
- MCP (Model Context Protocol) enables AI assistants to securely access external tools
- This server provides file operation tools through the MCP protocol
- Tools, Resources, and Prompts are the three main MCP primitives

Available Tools:
1. read_file - Read file contents with security validation
2. write_file - Write content with backup and validation
3. list_directory - List directory contents with filtering
4. get_file_info - Get detailed file information

Available Resources:
- file://server/config - Server configuration and capabilities
- file://server/health - Current server health status
- file://server/stats - Runtime statistics and metrics

Security Features:
- Path traversal protection
- File extension validation
- Size limits enforcement
- Permission checking

Best Practices:
1. Always validate paths before operations
2. Use appropriate encoding for text files
3. Enable backups for important write operations
4. Check file permissions before operations
5. Use base directory restrictions when possible

Want to see mesh enhancements? This server also demonstrates optional
mesh integration features for production deployments.
"""

            return [
                {"role": "assistant", "content": {"type": "text", "text": guide_text}}
            ]

    def _setup_mesh_enhancements(self):
        """
        Optional: Add mesh features for production deployments.

        This section shows how to enhance basic MCP tools with mesh capabilities:
        - Authentication and authorization
        - Health monitoring and heartbeats
        - Dependency injection
        - Audit logging
        - Service discovery

        These features are optional and the server works fine without them.
        Uncomment and modify as needed for production use.
        """
        # Example: Enhanced file info tool with mesh features
        # Uncomment to enable mesh integration

        """
        # Import mesh decorator (only needed if using mesh features)
        from mcp_mesh_types import mesh_agent
        @mesh_agent(
            capabilities=["file_info", "secure_access"],
            dependencies=["auth_service"],
            health_interval=60,
            security_context="file_operations",
            agent_name="file-operations-agent",
            fallback_mode=True
        )
        async def enhanced_file_info_tool(
            path: str,
            auth_service: Optional[str] = None  # Injected by mesh
        ) -> Dict[str, Any]:
            '''
            Enhanced file info tool with mesh integration.

            Additional features when mesh is available:- Authentication via injected auth_service
            - Audit logging of all access attempts
            - Health monitoring and heartbeats
            - Service registry integration
            '''
            # Use auth service if available (injected by mesh)
            if auth_service:
                logger.info(f"Using auth service: {auth_service}")
                # In full mesh: validate permissions, log access, etc.
            # Delegate to standard file info implementation
            return await self.basic_tools['get_file_info'](path)
        # Replace basic tool with enhanced version
        self.enhanced_file_info_tool = enhanced_file_info_tool
        """

        logger.info("Mesh enhancements configured (currently disabled for demo)")

    async def cleanup(self):
        """Cleanup server resources."""
        logger.info("Starting File Operations Server cleanup...")

        # Cleanup file operations (basic cleanup)
        if hasattr(self.file_ops, "cleanup"):
            await self.file_ops.cleanup()

        # Cleanup mesh-enhanced tools if they exist
        if hasattr(self, "enhanced_file_info_tool") and hasattr(
            self.enhanced_file_info_tool, "_mesh_agent_metadata"
        ):
            decorator_instance = self.enhanced_file_info_tool._mesh_agent_metadata[
                "decorator_instance"
            ]
            await decorator_instance.cleanup()

        logger.info("File Operations Server cleanup completed")


async def main():
    """Demonstrate MCP File Operations Server with FastMCP."""
    print("🚀 MCP File Operations Server Demo")
    print("=" * 40)
    print("Learn MCP fundamentals with optional mesh enhancements")
    print("=" * 40)

    # Initialize MCP server with restricted base directory
    base_dir = "/tmp/mcp_demo"
    Path(base_dir).mkdir(exist_ok=True)

    server = FileOperationsServer(
        base_directory=base_dir, max_file_size=1024 * 1024  # 1MB for demo
    )

    try:
        print(f"\n📁 Base directory: {base_dir}")
        print(f"🔧 Registered {len(server.app.tools)} MCP tools")
        print(f"📚 Registered {len(server.app.resources)} MCP resources")
        print(f"💬 Registered {len(server.app.prompts)} MCP prompts")

        print("\n🎯 Testing Core MCP Tools:")
        print("-" * 30)

        # Test file operations using the basic tools
        print("\n1. Testing write_file tool...")
        test_content = f"""# MCP File Operations Demo

This file demonstrates MCP (Model Context Protocol) file operations.

Core MCP Features Demonstrated:
- Tools: Secure file operations via MCP tools
- Resources: Server metadata and status
- Prompts: Guided interactions and assistance
- Security: Path validation and access control

Optional Mesh Features Available:
- Enhanced authentication and authorization
- Health monitoring and heartbeats
- Dependency injection
- Audit logging and compliance
- Service discovery and coordination

Generated at: {datetime.now()}
"""

        success = await server.file_ops.write_file(
            path=f"{base_dir}/mcp_demo.md", content=test_content
        )
        print(f"✅ Write successful: {success}")

        print("\n2. Testing read_file tool...")
        content = await server.file_ops.read_file(f"{base_dir}/mcp_demo.md")
        print(f"✅ Read {len(content)} characters")
        print(f"Preview: {content[:100]}...")

        print("\n3. Testing list_directory tool...")
        entries = await server.file_ops.list_directory(base_dir, include_details=True)
        print(f"✅ Found {len(entries)} entries")
        for entry in entries[:3]:  # Show first 3
            if isinstance(entry, dict):
                print(
                    f"  - {entry['name']} ({entry['type']}, {entry.get('size', 'N/A')} bytes)"
                )
            else:
                print(f"  - {entry}")

        print("\n4. Testing get_file_info tool...")
        file_info = await server.basic_tools["get_file_info"](f"{base_dir}/mcp_demo.md")
        print("✅ File info retrieved:")
        print(f"  - Size: {file_info['size']} bytes")
        print(f"  - Type: {file_info['type']}")
        print(f"  - Readable: {file_info['is_readable']}")
        print(f"  - Writable: {file_info['is_writable']}")

        print("\n📊 Testing MCP Resources:")
        print("-" * 25)

        print("\n5. Testing server health resource...")
        health = await server.file_ops.health_check()
        print(f"✅ Health status: {health['status']}")
        print("  - Available via: file://server/health")

        print("\n🔒 Testing Security Features:")
        print("-" * 27)

        print("\n6. Testing security validation...")
        try:
            await server.file_ops.read_file("../../../etc/passwd")  # Should fail
        except SecurityValidationError as e:
            print(f"✅ Security validation working: {e}")

        print("\n🎉 MCP Server Demo Completed Successfully!")
        print("\n💡 Next Steps:")
        print("  - Explore MCP resources at file://server/config")
        print("  - Try MCP prompts: 'getting_started' and 'file_analysis'")
        print(
            "  - For production: uncomment mesh enhancements in _setup_mesh_enhancements()"
        )

    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        await server.cleanup()
        print("✅ Cleanup completed!")


if __name__ == "__main__":
    # Run the demo
    asyncio.run(main())
