#!/usr/bin/env python3
"""
Agent Versioning System Example

This example demonstrates the complete agent versioning system including:
- Creating and managing agent versions
- Deploying specific versions
- Tracking deployment history
- Rolling back deployments
- Version comparison and compatibility checking

This example imports only from mcp-mesh to show the interface usage.
"""

import asyncio
from datetime import datetime

# Mock implementation for demo - would use actual versioning tools
# from mcp_mesh.shared.versioning import AgentVersionManager
# from mcp_mesh.tools.versioning_tools import create_versioning_tools
from fastmcp import FastMCP

# Import only from mcp-mesh (interfaces only)
from mcp_mesh import (
    AgentVersionInfo,
    SemanticVersion,
    VersionComparisonProtocol,
    VersioningProtocol,
)


class VersioningExample:
    """Example demonstrating agent versioning capabilities."""

    def __init__(self):
        # Mock version manager for demo
        # self.version_manager = AgentVersionManager(":memory:")

        # Create FastMCP app for tools demonstration
        self.app = FastMCP("Agent Versioning Example")
        # self.versioning_tools = create_versioning_tools(self.app, ":memory:")

    async def initialize(self):
        """Initialize the versioning system."""
        # await self.version_manager.initialize()
        print("Versioning system initialized (mock)")

    async def demonstrate_version_creation(self):
        """Demonstrate creating agent versions."""
        print("=== Creating Agent Versions ===")

        agent_id = "my-chat-agent"

        # Create initial version
        v1 = await self.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.0.0",
            description="Initial release of chat agent",
            changelog="- Basic chat functionality\n- Simple message processing",
            created_by="developer",
        )
        print(f"Created version: {v1.version_string}")

        # Create patch version
        v1_1 = await self.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.0.1",
            description="Bug fix release",
            changelog="- Fixed memory leak in message processing\n- Improved error handling",
            created_by="developer",
        )
        print(f"Created version: {v1_1.version_string}")

        # Create minor version
        v1_1_0 = await self.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.1.0",
            description="Feature release",
            changelog="- Added conversation history\n- Improved response quality\n- Added configuration options",
            created_by="developer",
        )
        print(f"Created version: {v1_1_0.version_string}")

        # Create prerelease version
        v2_0_alpha = await self.version_manager.create_agent_version(
            agent_id=agent_id,
            version="2.0.0-alpha.1",
            description="Major rewrite alpha",
            changelog="- Complete rewrite with new architecture\n- Experimental AI improvements\n- Breaking API changes",
            created_by="developer",
        )
        print(f"Created version: {v2_0_alpha.version_string}")

        return [v1, v1_1, v1_1_0, v2_0_alpha]

    async def demonstrate_version_queries(self, agent_id: str):
        """Demonstrate querying version information."""
        print("\n=== Querying Version Information ===")

        # Get all versions
        versions = await self.version_manager.get_agent_versions(agent_id)
        print(f"Found {len(versions)} versions for agent {agent_id}:")
        for version in versions:
            print(f"  - {version.version_string}: {version.description}")

        # Get specific version
        version_info = await self.version_manager.get_agent_version(agent_id, "1.1.0")
        if version_info:
            print("\nVersion 1.1.0 details:")
            print(f"  Created: {version_info.created_at}")
            print(f"  Created by: {version_info.created_by}")
            print(f"  Description: {version_info.description}")
            print(f"  Changelog:\n{version_info.changelog}")

    async def demonstrate_version_comparison(self):
        """Demonstrate version comparison features."""
        print("\n=== Version Comparison ===")

        versions_to_compare = [
            ("1.0.0", "1.0.1"),
            ("1.0.1", "1.1.0"),
            ("1.1.0", "2.0.0-alpha.1"),
            ("2.0.0-alpha.1", "2.0.0"),
        ]

        for v1, v2 in versions_to_compare:
            try:
                result = self.version_manager.compare_versions(v1, v2)
                compatibility = self.version_manager.is_compatible(v1, v2)

                comparison_text = (
                    "equal" if result == 0 else ("older" if result < 0 else "newer")
                )
                print(
                    f"{v1} is {comparison_text} than {v2}, compatible: {compatibility}"
                )
            except ValueError as e:
                print(f"Error comparing {v1} and {v2}: {e}")

        # Find latest version
        version_list = ["1.0.0", "1.0.1", "1.1.0", "2.0.0-alpha.1"]
        latest = self.version_manager.get_latest_version(version_list)
        print(f"\nLatest version from {version_list}: {latest}")

    async def demonstrate_deployments(self, agent_id: str):
        """Demonstrate deployment operations."""
        print("\n=== Deployment Operations ===")

        # Deploy initial version to staging
        result = await self.version_manager.deploy_agent_version(
            agent_id=agent_id,
            version="1.0.0",
            environment="staging",
            deployed_by="ci-system",
        )

        if result.success:
            print(f"Successfully deployed {agent_id} v1.0.0 to staging")
            print(f"Deployment ID: {result.deployment_id}")
        else:
            print(f"Deployment failed: {result.error_message}")

        # Deploy to production
        result = await self.version_manager.deploy_agent_version(
            agent_id=agent_id,
            version="1.0.1",
            environment="production",
            deployed_by="ops-team",
        )

        if result.success:
            print(f"Successfully deployed {agent_id} v1.0.1 to production")

        # Deploy newer version
        result = await self.version_manager.deploy_agent_version(
            agent_id=agent_id,
            version="1.1.0",
            environment="production",
            deployed_by="ops-team",
        )

        if result.success:
            print(f"Successfully deployed {agent_id} v1.1.0 to production")

    async def demonstrate_deployment_history(self, agent_id: str):
        """Demonstrate deployment history tracking."""
        print("\n=== Deployment History ===")

        # Get deployment history
        history = await self.version_manager.get_deployment_history(agent_id)

        print(f"Deployment history for {agent_id}:")
        for deployment in history:
            print(f"  {deployment.version_string} -> {deployment.environment}")
            print(f"    Status: {deployment.status.value}")
            print(f"    Deployed: {deployment.deployed_at}")
            print(f"    Deployed by: {deployment.deployed_by}")
            if deployment.error_message:
                print(f"    Error: {deployment.error_message}")
            print()

        # Get active deployment
        active = await self.version_manager.get_active_deployment(
            agent_id, "production"
        )
        if active:
            print(f"Active production deployment: {active.version_string}")
            print(f"  Deployed: {active.deployed_at}")
            print(f"  Status: {active.status.value}")

    async def demonstrate_rollback(self, agent_id: str):
        """Demonstrate rollback operations."""
        print("\n=== Rollback Operations ===")

        # Get current active deployment
        current = await self.version_manager.get_active_deployment(
            agent_id, "production"
        )
        if current:
            print(f"Current production version: {current.version_string}")

            # Rollback to previous version
            result = await self.version_manager.rollback_deployment(
                agent_id=agent_id,
                to_version="1.0.1",
                reason="Performance issues detected in v1.1.0",
                environment="production",
                initiated_by="ops-team",
            )

            if result.success:
                print("Successfully rolled back to v1.0.1")
                print(f"Rollback deployment ID: {result.deployment_id}")

                # Verify rollback
                new_active = await self.version_manager.get_active_deployment(
                    agent_id, "production"
                )
                if new_active:
                    print(f"New active version: {new_active.version_string}")
            else:
                print(f"Rollback failed: {result.error_message}")

    async def demonstrate_mcp_tools(self):
        """Demonstrate the MCP tools interface."""
        print("\n=== MCP Tools Demonstration ===")

        # Note: In a real MCP server, these tools would be called via MCP protocol
        # Here we simulate the tool calls for demonstration

        agent_id = "demo-agent"

        # Create versions using the tools interface
        print("Creating versions via MCP tools...")

        # Simulate tool calls (in real usage, these would come via MCP protocol)
        await self.versioning_tools._ensure_initialized()

        # Create a version
        await self.versioning_tools.version_manager.create_agent_version(
            agent_id=agent_id,
            version="1.0.0",
            description="Demo version via MCP tools",
            created_by="mcp-client",
        )

        # Get versions
        versions = await self.versioning_tools.version_manager.get_agent_versions(
            agent_id
        )
        print(f"Retrieved {len(versions)} versions via tools interface")

        # Deploy version
        result = await self.versioning_tools.version_manager.deploy_agent_version(
            agent_id=agent_id, version="1.0.0", environment="production"
        )

        if result.success:
            print("Deployment via MCP tools successful")

        print("MCP tools demonstration complete")

    async def run_complete_example(self):
        """Run the complete versioning example."""
        print("Agent Versioning System Example")
        print("===============================")

        await self.initialize()

        agent_id = "my-chat-agent"

        # Run all demonstrations
        await self.demonstrate_version_creation()
        await self.demonstrate_version_queries(agent_id)
        await self.demonstrate_version_comparison()
        await self.demonstrate_deployments(agent_id)
        await self.demonstrate_deployment_history(agent_id)
        await self.demonstrate_rollback(agent_id)
        await self.demonstrate_mcp_tools()

        print("\n=== Example Complete ===")
        print("The agent versioning system provides:")
        print("- Semantic versioning with full MAJOR.MINOR.PATCH support")
        print("- Deployment tracking across multiple environments")
        print("- Complete deployment history and rollback capabilities")
        print("- MCP-compliant tools for remote operation")
        print("- Version comparison and compatibility checking")


# Protocol compliance examples
def demonstrate_protocol_interfaces():
    """Demonstrate how the protocols can be used for type checking."""
    print("\n=== Protocol Interface Examples ===")

    # Example of using the protocols for type hints
    async def version_aware_function(
        versioning: VersioningProtocol, comparison: VersionComparisonProtocol
    ):
        """Example function that accepts versioning protocols."""
        # This function can work with any implementation that follows the protocols
        versions = await versioning.get_agent_versions("some-agent")

        if len(versions) >= 2:
            latest = comparison.get_latest_version([v.version for v in versions])
            print(f"Latest version detected: {latest}")

    # Example of version manipulation using types
    def version_manipulation_example():
        """Example of working with version types."""
        # Create a semantic version
        version = SemanticVersion(major=1, minor=2, patch=3, prerelease="alpha.1")
        print(f"Created version: {version}")

        # Version comparison
        newer_version = SemanticVersion(major=1, minor=2, patch=4)
        print(f"Version {version} < {newer_version}: {version < newer_version}")

        # Create version info
        version_info = AgentVersionInfo(
            agent_id="test-agent",
            version=version,
            created_at=datetime.now(),
            created_by="example",
            description="Example version",
        )
        print(f"Version info: {version_info.agent_id} v{version_info.version_string}")

    version_manipulation_example()
    print("Protocol interface examples complete")


async def main():
    """Main example function."""
    example = VersioningExample()

    # Run the complete example
    await example.run_complete_example()

    # Demonstrate protocol interfaces
    demonstrate_protocol_interfaces()


if __name__ == "__main__":
    asyncio.run(main())
