# MCP Protocol Integration Points

## Overview

This document defines how the File Agent integrates with the Model Context Protocol (MCP) and exposes file operations through the standard MCP interfaces: Tools, Resources, and Prompts.

## Tools Integration

### File Operation Tools

The File Agent exposes all file operations as MCP tools that can be called by MCP clients (like Claude Desktop).

```python
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from mcp_mesh_sdk.decorators import mesh_agent

class FileAgentMCPIntegration:
    """MCP protocol integration for File Agent."""

    def __init__(self):
        self.app = FastMCP(
            name="file-agent",
            instructions="Secure file system operations with mesh integration and MCP compliance."
        )
        self._register_tools()
        self._register_resources()
        self._register_prompts()

    def _register_tools(self):
        """Register all file operation tools with MCP."""

        @mesh_agent(
            capabilities=["file_read"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def read_file(
            path: str,
            encoding: str = "utf-8",
            max_size: int = 1024 * 1024,  # 1MB default
            auth_service: str = None
        ) -> str:
            """
            Read the contents of a file.

            Args:
                path: Absolute or relative path to the file
                encoding: Text encoding (default: utf-8)
                max_size: Maximum file size to read in bytes

            Returns:
                File contents as string

            Raises:
                FileNotFoundError: If file doesn't exist
                PermissionError: If access is denied
                FileTooLargeError: If file exceeds max_size
            """
            return await self._execute_read_file(path, encoding, max_size, auth_service)

        @mesh_agent(
            capabilities=["file_write"],
            dependencies=["auth_service", "backup_service"],
            health_interval=30
        )
        @self.app.tool()
        async def write_file(
            path: str,
            content: str,
            encoding: str = "utf-8",
            create_dirs: bool = False,
            backup: bool = True,
            auth_service: str = None,
            backup_service: Any = None
        ) -> bool:
            """
            Write content to a file.

            Args:
                path: Absolute or relative path to the file
                content: Content to write to the file
                encoding: Text encoding (default: utf-8)
                create_dirs: Create parent directories if they don't exist
                backup: Create backup before overwriting existing file

            Returns:
                True if successful

            Raises:
                PermissionError: If write access is denied
                DirectoryNotFoundError: If parent directory doesn't exist and create_dirs=False
            """
            return await self._execute_write_file(
                path, content, encoding, create_dirs, backup, auth_service, backup_service
            )

        @mesh_agent(
            capabilities=["directory_list"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def list_directory(
            path: str = ".",
            pattern: str = "*",
            include_hidden: bool = False,
            recursive: bool = False,
            auth_service: str = None
        ) -> List[Dict[str, Any]]:
            """
            List contents of a directory.

            Args:
                path: Directory path to list (default: current directory)
                pattern: Glob pattern to filter files (default: all files)
                include_hidden: Include hidden files/directories
                recursive: List subdirectories recursively

            Returns:
                List of file/directory information dictionaries

            Raises:
                DirectoryNotFoundError: If directory doesn't exist
                PermissionError: If access is denied
            """
            return await self._execute_list_directory(
                path, pattern, include_hidden, recursive, auth_service
            )

        @mesh_agent(
            capabilities=["file_info"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def get_file_info(
            path: str,
            auth_service: str = None
        ) -> Dict[str, Any]:
            """
            Get detailed information about a file or directory.

            Args:
                path: Path to the file or directory

            Returns:
                Dictionary containing file metadata

            Raises:
                FileNotFoundError: If path doesn't exist
                PermissionError: If access is denied
            """
            return await self._execute_get_file_info(path, auth_service)

        @mesh_agent(
            capabilities=["file_delete"],
            dependencies=["auth_service", "backup_service"],
            health_interval=30
        )
        @self.app.tool()
        async def delete_file(
            path: str,
            backup: bool = True,
            recursive: bool = False,
            auth_service: str = None,
            backup_service: Any = None
        ) -> bool:
            """
            Delete a file or directory.

            Args:
                path: Path to delete
                backup: Create backup before deletion
                recursive: Delete directories recursively

            Returns:
                True if successful

            Raises:
                FileNotFoundError: If path doesn't exist
                PermissionError: If deletion is denied
                DirectoryNotEmptyError: If trying to delete non-empty directory without recursive=True
            """
            return await self._execute_delete_file(path, backup, recursive, auth_service, backup_service)

        @mesh_agent(
            capabilities=["file_copy"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def copy_file(
            source: str,
            destination: str,
            overwrite: bool = False,
            preserve_metadata: bool = True,
            auth_service: str = None
        ) -> bool:
            """
            Copy a file or directory.

            Args:
                source: Source path
                destination: Destination path
                overwrite: Overwrite destination if it exists
                preserve_metadata: Preserve file timestamps and permissions

            Returns:
                True if successful

            Raises:
                FileNotFoundError: If source doesn't exist
                FileExistsError: If destination exists and overwrite=False
                PermissionError: If access is denied
            """
            return await self._execute_copy_file(
                source, destination, overwrite, preserve_metadata, auth_service
            )

        @mesh_agent(
            capabilities=["file_move"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def move_file(
            source: str,
            destination: str,
            overwrite: bool = False,
            auth_service: str = None
        ) -> bool:
            """
            Move or rename a file or directory.

            Args:
                source: Source path
                destination: Destination path
                overwrite: Overwrite destination if it exists

            Returns:
                True if successful

            Raises:
                FileNotFoundError: If source doesn't exist
                FileExistsError: If destination exists and overwrite=False
                PermissionError: If access is denied
            """
            return await self._execute_move_file(source, destination, overwrite, auth_service)

        @mesh_agent(
            capabilities=["directory_create"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def create_directory(
            path: str,
            parents: bool = False,
            mode: int = 0o755,
            auth_service: str = None
        ) -> bool:
            """
            Create a directory.

            Args:
                path: Directory path to create
                parents: Create parent directories if they don't exist
                mode: Directory permissions (octal notation)

            Returns:
                True if successful

            Raises:
                FileExistsError: If directory already exists
                PermissionError: If creation is denied
                DirectoryNotFoundError: If parent doesn't exist and parents=False
            """
            return await self._execute_create_directory(path, parents, mode, auth_service)
```

## Resources Integration

### File System Resources

The File Agent exposes file system information and configuration as MCP resources.

```python
    def _register_resources(self):
        """Register file system resources with MCP."""

        @self.app.resource("file://agent/config")
        async def agent_config() -> str:
            """
            Get File Agent configuration.

            Returns:
                JSON configuration of the File Agent
            """
            config = {
                "agent_name": self.agent_name,
                "capabilities": self.capabilities,
                "security_mode": self.security_mode,
                "max_file_size": self.max_file_size,
                "allowed_extensions": self.allowed_extensions,
                "base_directory": str(self.base_directory) if self.base_directory else None
            }
            return json.dumps(config, indent=2)

        @self.app.resource("file://agent/status")
        async def agent_status() -> str:
            """
            Get current File Agent status.

            Returns:
                JSON status information
            """
            status = await self._get_agent_status()
            return json.dumps(status, indent=2, default=str)

        @self.app.resource("file://agent/stats")
        async def agent_stats() -> str:
            """
            Get File Agent operation statistics.

            Returns:
                JSON statistics about file operations
            """
            stats = await self._get_operation_stats()
            return json.dumps(stats, indent=2)

        @self.app.resource("file://system/info")
        async def system_info() -> str:
            """
            Get file system information.

            Returns:
                JSON information about the file system
            """
            info = await self._get_file_system_info()
            return json.dumps(info, indent=2)

        @self.app.resource("file://health")
        async def health_status() -> str:
            """
            Get comprehensive health status.

            Returns:
                JSON health check results
            """
            health = await self.health_check()
            return json.dumps(health.dict(), indent=2, default=str)
```

## Prompts Integration

### File Operation Prompts

The File Agent provides prompts for common file analysis and operation tasks.

```python
    def _register_prompts(self):
        """Register file operation prompts with MCP."""

        @self.app.prompt()
        async def analyze_file(file_path: str) -> List[PromptMessage]:
            """
            Generate prompts for analyzing a file.

            Args:
                file_path: Path to the file to analyze

            Returns:
                List of prompt messages for file analysis
            """
            # Get file info first
            try:
                file_info = await self.get_file_info(file_path)
                file_content = await self.read_file(file_path) if file_info["size"] < 100000 else "File too large to include"
            except Exception:
                file_info = {"error": "Could not access file"}
                file_content = "Could not read file content"

            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Analyze the file at {file_path}.

File Information:
{json.dumps(file_info, indent=2, default=str)}

File Content:
{file_content[:5000]}{"..." if len(file_content) > 5000 else ""}

Please provide:
1. File type and format analysis
2. Content structure and organization
3. Potential issues or improvements
4. Security considerations if applicable
5. Recommendations for handling this file"""
                    )
                )
            ]

        @self.app.prompt()
        async def file_operation_help() -> List[PromptMessage]:
            """
            Generate help prompt for file operations.

            Returns:
                List of prompt messages explaining available file operations
            """
            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="""Help me understand the available file operations in this File Agent.

Please explain:
1. What file operations are available?
2. How to use each operation safely?
3. Security considerations and best practices
4. Error handling and troubleshooting
5. Integration with other mesh services

Available operations include: read_file, write_file, list_directory, get_file_info, delete_file, copy_file, move_file, create_directory.

Provide practical examples and usage patterns."""
                    )
                )
            ]

        @self.app.prompt()
        async def directory_summary(directory_path: str = ".") -> List[PromptMessage]:
            """
            Generate prompts for summarizing directory contents.

            Args:
                directory_path: Path to the directory to summarize

            Returns:
                List of prompt messages for directory analysis
            """
            try:
                directory_listing = await self.list_directory(directory_path, recursive=True)
            except Exception:
                directory_listing = [{"error": "Could not access directory"}]

            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Analyze and summarize the directory structure at {directory_path}.

Directory Contents:
{json.dumps(directory_listing, indent=2, default=str)}

Please provide:
1. Overview of directory structure and organization
2. File types and distributions
3. Largest files and potential cleanup opportunities
4. Security analysis (permissions, sensitive files)
5. Recommendations for better organization
6. Potential automation opportunities"""
                    )
                )
            ]

        @self.app.prompt()
        async def file_workflow(operation_type: str) -> List[PromptMessage]:
            """
            Generate workflow prompts for complex file operations.

            Args:
                operation_type: Type of workflow (backup, migration, cleanup, etc.)

            Returns:
                List of prompt messages for workflow planning
            """
            workflows = {
                "backup": "Create a comprehensive backup strategy",
                "migration": "Plan a safe file migration process",
                "cleanup": "Develop a file cleanup and organization strategy",
                "security": "Perform a security audit of file permissions",
                "organization": "Reorganize files for better structure"
            }

            workflow_description = workflows.get(operation_type, "Plan a file operation workflow")

            return [
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Help me {workflow_description}.

Please provide:
1. Step-by-step workflow plan
2. Pre-operation checklist and validation
3. Safety measures and backup strategies
4. Error handling and rollback procedures
5. Post-operation verification steps
6. Best practices and recommendations

Consider:
- File safety and integrity
- Permission management
- Performance implications
- Recovery procedures
- Automation possibilities"""
                    )
                )
            ]
```

## Error Handling and Type Safety

### MCP-Compliant Error Responses

```python
from mcp.types import McpError

class FileAgentMCPErrors:
    """MCP-compliant error handling for File Agent."""

    @staticmethod
    def file_not_found(path: str) -> McpError:
        return McpError(
            code="FILE_NOT_FOUND",
            message=f"File not found: {path}"
        )

    @staticmethod
    def permission_denied(path: str, operation: str) -> McpError:
        return McpError(
            code="PERMISSION_DENIED",
            message=f"Permission denied for {operation} on {path}"
        )

    @staticmethod
    def file_too_large(path: str, size: int, max_size: int) -> McpError:
        return McpError(
            code="FILE_TOO_LARGE",
            message=f"File {path} ({size} bytes) exceeds maximum size ({max_size} bytes)"
        )

    @staticmethod
    def invalid_path(path: str) -> McpError:
        return McpError(
            code="INVALID_PATH",
            message=f"Invalid or unsafe path: {path}"
        )

    @staticmethod
    def directory_not_empty(path: str) -> McpError:
        return McpError(
            code="DIRECTORY_NOT_EMPTY",
            message=f"Directory not empty: {path}. Use recursive=true to delete."
        )
```

## Tool Annotations and Schema

```python
from mcp.types import ToolAnnotations

# Example tool with complete MCP annotations
@mesh_agent(capabilities=["file_read"])
@self.app.tool(
    annotations=ToolAnnotations(
        name="read_file",
        description="Read the contents of a file with security validation",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read"
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default: utf-8)",
                    "default": "utf-8"
                },
                "max_size": {
                    "type": "integer",
                    "description": "Maximum file size to read in bytes",
                    "default": 1048576
                }
            },
            "required": ["path"]
        }
    )
)
async def read_file(path: str, encoding: str = "utf-8", max_size: int = 1024*1024) -> str:
    """Implementation here"""
    pass
```

## Server Initialization and Transport

```python
def create_file_agent_server() -> FastMCP:
    """Create and configure the File Agent MCP server."""

    # Initialize File Agent with MCP integration
    file_agent = FileAgentMCPIntegration()

    return file_agent.app

def main():
    """Run the File Agent MCP server."""
    print("🚀 Starting MCP File Agent Server...")

    # Create the server
    server = create_file_agent_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 File Agent ready with the following capabilities:")
    print("   • read_file - Read file contents")
    print("   • write_file - Write content to files")
    print("   • list_directory - List directory contents")
    print("   • get_file_info - Get file metadata")
    print("   • delete_file - Delete files/directories")
    print("   • copy_file - Copy files/directories")
    print("   • move_file - Move/rename files")
    print("   • create_directory - Create directories")
    print("\n💡 Use MCP client to connect and test the server.")
    print("📝 Press Ctrl+C to stop the server.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 File Agent stopped by user.")
    except Exception as e:
        print(f"❌ File Agent error: {e}")

if __name__ == "__main__":
    main()
```

This MCP protocol integration provides a complete interface for file operations that can be consumed by any MCP client, while leveraging the mesh infrastructure for security, monitoring, and dependency management.
