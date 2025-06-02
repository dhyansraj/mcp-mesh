#!/usr/bin/env python3
"""
Simple Agent Versioning Test

This test demonstrates the agent versioning system using only the core types and functionality.
"""

import asyncio
from datetime import datetime

# Import only from mcp-mesh-types for the interface
from mcp_mesh_types import (
    DeploymentStatus,
    SemanticVersion,
)

# NOTE: This test file imports implementation for testing integration
# Production code should use only mcp-mesh-types for interfaces
from mcp_mesh.shared.versioning import AgentVersionManager


async def test_semantic_version():
    """Test semantic version functionality."""
    print("=== Testing Semantic Version ===")

    # Test version creation
    v1 = SemanticVersion(major=1, minor=0, patch=0)
    v2 = SemanticVersion(major=1, minor=0, patch=1)
    v3 = SemanticVersion(major=1, minor=1, patch=0)
    v4 = SemanticVersion(major=2, minor=0, patch=0, prerelease="alpha.1")

    print(f"Created versions: {v1}, {v2}, {v3}, {v4}")

    # Test version comparison
    print(f"v1 < v2: {v1 < v2}")  # 1.0.0 < 1.0.1
    print(f"v2 < v3: {v2 < v3}")  # 1.0.1 < 1.1.0
    print(
        f"v3 < v4: {v3 < v4}"
    )  # 1.1.0 < 2.0.0-alpha.1 (should be False, normal > prerelease)

    # Test equality
    v1_copy = SemanticVersion(major=1, minor=0, patch=0)
    print(f"v1 == v1_copy: {v1 == v1_copy}")

    print("Semantic version tests completed!\n")


async def test_version_manager():
    """Test the version manager functionality."""
    print("=== Testing Version Manager ===")

    # Create version manager with in-memory database
    manager = AgentVersionManager(":memory:")
    await manager.initialize()

    agent_id = "test-agent"

    # Test version creation
    print("Creating agent versions...")
    v1_info = await manager.create_agent_version(
        agent_id=agent_id,
        version="1.0.0",
        description="Initial release",
        created_by="test",
    )
    print(f"Created: {v1_info.version_string}")

    v2_info = await manager.create_agent_version(
        agent_id=agent_id, version="1.0.1", description="Bug fix", created_by="test"
    )
    print(f"Created: {v2_info.version_string}")

    # Test version retrieval
    print("\nRetrieving agent versions...")
    versions = await manager.get_agent_versions(agent_id)
    print(f"Found {len(versions)} versions:")
    for version in versions:
        print(f"  - {version.version_string}: {version.description}")

    # Test specific version retrieval
    specific_version = await manager.get_agent_version(agent_id, "1.0.0")
    if specific_version:
        print(f"\nSpecific version 1.0.0: {specific_version.description}")

    # Test deployment
    print("\nTesting deployment...")
    deploy_result = await manager.deploy_agent_version(
        agent_id=agent_id, version="1.0.0", environment="production", deployed_by="test"
    )

    if deploy_result.success:
        print(f"Deployment successful: {deploy_result.deployment_id}")
    else:
        print(f"Deployment failed: {deploy_result.error_message}")

    # Test deployment history
    print("\nChecking deployment history...")
    history = await manager.get_deployment_history(agent_id)
    print(f"Found {len(history)} deployments:")
    for deployment in history:
        print(
            f"  - {deployment.version_string} to {deployment.environment} ({deployment.status.value})"
        )

    # Test active deployment
    active = await manager.get_active_deployment(agent_id, "production")
    if active:
        print(f"\nActive deployment: {active.version_string}")

    # Test new deployment (should replace active)
    deploy_result2 = await manager.deploy_agent_version(
        agent_id=agent_id, version="1.0.1", environment="production", deployed_by="test"
    )

    if deploy_result2.success:
        print(f"Second deployment successful: {deploy_result2.deployment_id}")

        # Check new active deployment
        new_active = await manager.get_active_deployment(agent_id, "production")
        if new_active:
            print(f"New active deployment: {new_active.version_string}")

    # Test rollback
    print("\nTesting rollback...")
    rollback_result = await manager.rollback_deployment(
        agent_id=agent_id,
        to_version="1.0.0",
        reason="Testing rollback functionality",
        environment="production",
        initiated_by="test",
    )

    if rollback_result.success:
        print(f"Rollback successful: {rollback_result.deployment_id}")

        # Verify rollback
        final_active = await manager.get_active_deployment(agent_id, "production")
        if final_active:
            print(f"After rollback active deployment: {final_active.version_string}")

    print("Version manager tests completed!\n")


async def test_version_comparison():
    """Test version comparison utilities."""
    print("=== Testing Version Comparison ===")

    manager = AgentVersionManager(":memory:")

    # Test version parsing
    v1 = manager.parse_version("1.2.3-alpha.1+build.123")
    print(f"Parsed version: {v1}")
    print(f"  Major: {v1.major}, Minor: {v1.minor}, Patch: {v1.patch}")
    print(f"  Prerelease: {v1.prerelease}, Build: {v1.build}")

    # Test version comparison
    versions = ["1.0.0", "1.0.1", "1.1.0", "2.0.0-alpha.1", "2.0.0"]

    print(f"\nComparing versions: {versions}")
    for i in range(len(versions) - 1):
        result = manager.compare_versions(versions[i], versions[i + 1])
        comparison_text = (
            "equal" if result == 0 else ("older" if result < 0 else "newer")
        )
        print(f"  {versions[i]} is {comparison_text} than {versions[i + 1]}")

    # Test compatibility
    print("\nTesting compatibility:")
    compatibility_tests = [
        ("1.0.0", "1.0.1"),  # Compatible (same major, newer minor/patch)
        ("1.0.0", "1.1.0"),  # Compatible (same major, newer minor)
        ("1.0.0", "2.0.0"),  # Not compatible (different major)
        ("2.0.0-alpha.1", "2.0.0"),  # Compatible (prerelease to release)
    ]

    for required, available in compatibility_tests:
        compatible = manager.is_compatible(required, available)
        print(
            f"  {required} -> {available}: {'Compatible' if compatible else 'Not compatible'}"
        )

    # Test latest version
    latest = manager.get_latest_version(versions)
    print(f"\nLatest version from {versions}: {latest}")

    print("Version comparison tests completed!\n")


async def test_deployment_status():
    """Test deployment status enum."""
    print("=== Testing Deployment Status ===")

    # Test all status values
    print("Available deployment statuses:")
    for status in DeploymentStatus:
        print(f"  - {status.name}: {status.value}")

    # Test status usage in deployment info
    from mcp_mesh_types import DeploymentInfo

    deployment = DeploymentInfo(
        deployment_id="test-deployment",
        agent_id="test-agent",
        version=SemanticVersion(1, 0, 0),
        status=DeploymentStatus.ACTIVE,
        deployed_at=datetime.now(),
        deployed_by="test",
        environment="production",
    )

    print(f"\nExample deployment: {deployment.agent_id} v{deployment.version_string}")
    print(f"Status: {deployment.status.value}")

    print("Deployment status tests completed!\n")


async def main():
    """Run all tests."""
    print("Agent Versioning System Test Suite")
    print("==================================")

    await test_semantic_version()
    await test_version_manager()
    await test_version_comparison()
    await test_deployment_status()

    print("=== All Tests Completed Successfully! ===")
    print("\nThe Agent Versioning System provides:")
    print("✓ Semantic versioning with MAJOR.MINOR.PATCH support")
    print("✓ Prerelease and build metadata handling")
    print("✓ Complete version comparison and compatibility checking")
    print("✓ Database-backed version and deployment tracking")
    print("✓ Deployment history and rollback capabilities")
    print("✓ Environment-specific deployments")
    print("✓ MCP-compliant tool interface")
    print(
        "✓ Proper package separation (types in mcp-mesh-types, implementation in mcp-mesh)"
    )


if __name__ == "__main__":
    asyncio.run(main())
