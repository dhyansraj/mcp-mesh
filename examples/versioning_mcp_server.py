#!/usr/bin/env python3
"""
Agent Versioning MCP Server Example

This example shows how to create an MCP server that provides agent versioning capabilities.
The server exposes versioning tools that can be used by MCP clients.

This example demonstrates:
- Setting up an MCP server with versioning tools
- Using only mcp-mesh-types for type definitions
- Providing versioning capabilities via MCP protocol
"""

import asyncio

from fastmcp import FastMCP

# Import types from mcp-mesh-types only
from mcp_mesh_types import (
    AgentVersionInfo,
    DeploymentStatus,
    SemanticVersion,
)

# NOTE: This example imports implementation tools for demonstration
# In production, these tools would be provided by the MCP Mesh server
# and accessed only through the MCP protocol and mcp-mesh-types interfaces
from mcp_mesh.tools.versioning_tools import create_versioning_tools


def create_versioning_server(
    name: str = "Agent Versioning Server", db_path: str = ":memory:"
) -> FastMCP:
    """
    Create an MCP server with agent versioning capabilities.

    Args:
        name: Name of the MCP server
        db_path: Path to SQLite database for version storage

    Returns:
        Configured FastMCP server with versioning tools
    """
    # Create the MCP server
    app = FastMCP(name)

    # Add versioning tools to the server
    versioning_tools = create_versioning_tools(app, db_path)

    # Add a simple info tool
    @app.tool()
    async def get_server_info() -> dict:
        """Get information about the versioning server."""
        return {
            "name": name,
            "description": "Agent versioning and deployment management server",
            "version": "1.0.0",
            "capabilities": [
                "version_management",
                "deployment_tracking",
                "rollback_operations",
                "version_comparison",
            ],
            "tools": [
                "get_agent_versions",
                "get_agent_version",
                "create_agent_version",
                "deploy_agent_version",
                "get_deployment_history",
                "get_active_deployment",
                "rollback_deployment",
                "compare_versions",
                "get_latest_version",
            ],
        }

    return app


async def demonstrate_server_usage():
    """Demonstrate the versioning server in action."""
    print("Agent Versioning MCP Server Example")
    print("===================================")

    # Create the server
    server = create_versioning_server("Demo Versioning Server", ":memory:")

    # In a real scenario, the server would be started and clients would connect
    # Here we'll demonstrate the tools directly for testing

    print("Server created with versioning tools:")

    # Get server info
    tools = [name for name in dir(server) if not name.startswith("_")]
    print(f"Available tools: {len(tools)}")

    print("\nServer is ready to accept MCP connections.")
    print("Clients can use the following versioning tools:")
    print("- get_agent_versions(agent_id)")
    print("- create_agent_version(agent_id, version, description, ...)")
    print("- deploy_agent_version(agent_id, version, environment)")
    print("- get_deployment_history(agent_id)")
    print("- rollback_deployment(agent_id, to_version, reason)")
    print("- compare_versions(version1, version2)")

    return server


class VersioningClientExample:
    """Example of how a client would use the versioning tools."""

    def __init__(self, server: FastMCP):
        self.server = server
        # In a real client, this would be an MCP client connection
        self.versioning_tools = None
        for tool in server._tools:
            if hasattr(tool, "version_manager"):
                self.versioning_tools = tool
                break

    async def simulate_client_workflow(self):
        """Simulate a typical client workflow using versioning tools."""
        print("\n=== Simulating Client Workflow ===")

        if not self.versioning_tools:
            print("No versioning tools found on server")
            return

        agent_id = "example-agent"

        # Initialize the tools
        await self.versioning_tools._ensure_initialized()

        print(f"Working with agent: {agent_id}")

        # Step 1: Create initial version
        print("\n1. Creating initial version...")
        version_info = await self.versioning_tools.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.0.0",
            description="Initial release",
            changelog="- Basic functionality\n- Core features implemented",
            created_by="client-demo",
        )
        print(f"Created: {version_info.version_string}")

        # Step 2: Create a patch version
        print("\n2. Creating patch version...")
        patch_version = (
            await self.versioning_tools.version_manager.create_agent_version(
                agent_id=agent_id,
                version="1.0.1",
                description="Bug fix release",
                changelog="- Fixed critical bug\n- Improved stability",
                created_by="client-demo",
            )
        )
        print(f"Created: {patch_version.version_string}")

        # Step 3: Deploy to staging
        print("\n3. Deploying to staging...")
        deploy_result = (
            await self.versioning_tools.version_manager.deploy_agent_version(
                agent_id=agent_id,
                version="1.0.1",
                environment="staging",
                deployed_by="client-demo",
            )
        )

        if deploy_result.success:
            print(f"Successfully deployed to staging: {deploy_result.deployment_id}")
        else:
            print(f"Deployment failed: {deploy_result.error_message}")

        # Step 4: Deploy to production
        print("\n4. Deploying to production...")
        prod_result = await self.versioning_tools.version_manager.deploy_agent_version(
            agent_id=agent_id,
            version="1.0.1",
            environment="production",
            deployed_by="client-demo",
        )

        if prod_result.success:
            print(f"Successfully deployed to production: {prod_result.deployment_id}")

        # Step 5: Check deployment history
        print("\n5. Checking deployment history...")
        history = await self.versioning_tools.version_manager.get_deployment_history(
            agent_id
        )
        print(f"Found {len(history)} deployments:")
        for deployment in history:
            print(
                f"  - {deployment.version_string} to {deployment.environment} ({deployment.status.value})"
            )

        # Step 6: Get active deployment
        print("\n6. Checking active production deployment...")
        active = await self.versioning_tools.version_manager.get_active_deployment(
            agent_id, "production"
        )
        if active:
            print(
                f"Active deployment: {active.version_string} (deployed {active.deployed_at})"
            )

        # Step 7: Create a new version with issues
        print("\n7. Creating problematic version...")
        problem_version = await self.versioning_tools.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.1.0",
            description="Feature release with issues",
            changelog="- New features\n- Performance improvements\n- (Contains bugs)",
            created_by="client-demo",
        )

        # Deploy the problematic version
        bad_deploy = await self.versioning_tools.version_manager.deploy_agent_version(
            agent_id=agent_id,
            version="1.1.0",
            environment="production",
            deployed_by="client-demo",
        )

        if bad_deploy.success:
            print(f"Deployed problematic version: {bad_deploy.deployment_id}")

        # Step 8: Rollback due to issues
        print("\n8. Rolling back due to issues...")
        rollback_result = (
            await self.versioning_tools.version_manager.rollback_deployment(
                agent_id=agent_id,
                to_version="1.0.1",
                reason="Critical performance issues detected in v1.1.0",
                environment="production",
                initiated_by="client-demo",
            )
        )

        if rollback_result.success:
            print(f"Successfully rolled back: {rollback_result.deployment_id}")

            # Verify rollback
            new_active = (
                await self.versioning_tools.version_manager.get_active_deployment(
                    agent_id, "production"
                )
            )
            if new_active:
                print(
                    f"Current active version after rollback: {new_active.version_string}"
                )

        print("\nClient workflow simulation complete!")


def demonstrate_type_safety():
    """Demonstrate type safety with mcp-mesh-types."""
    print("\n=== Type Safety Demonstration ===")

    # Using only types from mcp-mesh-types
    from datetime import datetime

    # Create version using types
    version = SemanticVersion(major=2, minor=1, patch=0, prerelease="beta.1")
    print(f"Created semantic version: {version}")

    # Create version info
    version_info = AgentVersionInfo(
        agent_id="type-safe-agent",
        version=version,
        created_at=datetime.now(),
        created_by="type-demo",
        description="Demonstrating type safety",
    )
    print(f"Version info: {version_info.agent_id} v{version_info.version_string}")

    # Version comparison
    older_version = SemanticVersion(major=1, minor=9, patch=0)
    newer_version = SemanticVersion(major=2, minor=1, patch=1)

    print("Version comparison:")
    print(f"  {older_version} < {version}: {older_version < version}")
    print(f"  {version} < {newer_version}: {version < newer_version}")
    print(f"  {version} == {version}: {version == version}")

    # Deployment status
    print("\nDeployment statuses:")
    for status in DeploymentStatus:
        print(f"  - {status.value}")

    print("Type safety demonstration complete!")


async def main():
    """Main example function."""
    # Create and demonstrate the versioning server
    server = await demonstrate_server_usage()

    # Simulate client usage
    client = VersioningClientExample(server)
    await client.simulate_client_workflow()

    # Demonstrate type safety
    demonstrate_type_safety()

    print("\n=== Summary ===")
    print("This example demonstrated:")
    print("- Creating an MCP server with versioning tools")
    print("- Complete versioning workflow (create, deploy, rollback)")
    print("- Type-safe usage with mcp-mesh-types")
    print("- Integration between types and implementation packages")


if __name__ == "__main__":
    asyncio.run(main())
