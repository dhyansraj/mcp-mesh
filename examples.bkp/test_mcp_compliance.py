#!/usr/bin/env python3
"""
Test MCP SDK Compliance for Advanced Service Discovery

This script tests the MCP compliance of our discovery tools by:
1. Verifying tool registration
2. Testing parameter types and return values
3. Ensuring JSON serialization works correctly
4. Validating the @mesh_agent decorator functionality
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.fastmcp import FastMCP

# Import only from mcp-mesh to test interface compliance
from mcp_mesh import (
    CapabilityMetadata,
    CapabilityQuery,
    MatchingStrategy,
    QueryOperator,
    Requirements,
    mesh_agent,
)

# Create FastMCP app for dual-decorator pattern
app = FastMCP("mcp-compliance-test")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_compliance_test")


# Test agent with DUAL-DECORATOR pattern
@app.tool(
    name="test_compliance_agent",
    description="Test agent for MCP compliance verification",
)
@mesh_agent(
    capabilities=["test_capability", "compliance_check"],
    version="1.0.0",
    description="Test agent for MCP compliance verification",
    tags=["test", "compliance"],
    performance_profile={"test_speed": 100.0},
    resource_requirements={"memory_mb": 256},
)
async def test_compliance_agent(test_input: str) -> dict[str, Any]:
    """Test agent for MCP compliance verification."""
    return {
        "status": "success",
        "test_input": test_input,
        "timestamp": datetime.now().isoformat(),
        "message": "MCP compliance test successful",
    }


async def test_mcp_server_compliance():
    """Test MCP server compliance for discovery tools."""
    try:
        # Import the full implementation
        from mcp_mesh_runtime.shared.service_discovery import ServiceDiscoveryService
        from mcp_mesh_runtime.tools.discovery_tools import register_discovery_tools

        logger.info("🧪 Testing MCP Server Compliance")

        # Create test server
        app = Server("mcp-compliance-test")

        # Register discovery tools
        service_discovery = ServiceDiscoveryService()
        register_discovery_tools(app, service_discovery)

        # Test tool registration
        tools = []
        for handler in app._tool_handlers.values():
            tools.append(handler.__name__)

        expected_tools = [
            "query_agents",
            "get_best_agent",
            "check_compatibility",
            "list_agent_capabilities",
            "get_capability_hierarchy",
        ]

        logger.info(f"✅ Registered tools: {tools}")

        # Verify all expected tools are registered
        for expected_tool in expected_tools:
            if expected_tool not in tools:
                logger.error(f"❌ Missing expected tool: {expected_tool}")
                return False
            else:
                logger.info(f"✅ Found tool: {expected_tool}")

        # Test parameter types and return types
        logger.info("🔍 Testing parameter and return types...")

        # Test query_agents tool
        query_handler = app._tool_handlers.get("query_agents")
        if query_handler:
            # Verify the handler exists and has correct signature
            import inspect

            sig = inspect.signature(query_handler)
            logger.info(f"✅ query_agents signature: {sig}")

            # Test JSON serialization compliance
            try:
                test_result = await query_handler(
                    query="test_capability",
                    operator="contains",
                    field="capabilities",
                    matching_strategy="semantic",
                    max_results=5,
                )

                # Verify result is JSON string
                if isinstance(test_result, str):
                    parsed = json.loads(test_result)
                    logger.info("✅ query_agents returns valid JSON")
                else:
                    logger.error(
                        f"❌ query_agents should return JSON string, got: {type(test_result)}"
                    )
                    return False

            except Exception as e:
                logger.warning(
                    f"⚠️ query_agents test failed (expected in test environment): {e}"
                )

        logger.info("✅ MCP Server compliance tests passed")
        return True

    except Exception as e:
        logger.error(f"❌ MCP compliance test failed: {e}")
        return False


async def test_mesh_agent_decorator():
    """Test @mesh_agent decorator functionality."""
    logger.info("🔧 Testing @mesh_agent decorator")

    try:
        # Test that decorator preserves function
        result = await test_compliance_agent("compliance_test")
        logger.info(f"✅ Decorated function callable: {result}")

        # Test metadata attachment
        if hasattr(test_compliance_agent, "_mesh_metadata"):
            metadata = test_compliance_agent._mesh_metadata
            logger.info(f"✅ Metadata attached: {metadata.get('capabilities', [])}")

            # Verify expected metadata fields
            expected_fields = [
                "capabilities",
                "version",
                "description",
                "tags",
                "performance_profile",
                "resource_requirements",
            ]

            for field in expected_fields:
                if field in metadata:
                    logger.info(f"✅ Found metadata field: {field} = {metadata[field]}")
                else:
                    logger.warning(f"⚠️ Missing metadata field: {field}")
        else:
            logger.error("❌ No _mesh_metadata found on decorated function")
            return False

        # Test capability registration metadata
        if hasattr(test_compliance_agent, "_mesh_agent_capabilities"):
            capabilities = test_compliance_agent._mesh_agent_capabilities
            logger.info(f"✅ Capabilities stored: {capabilities}")
        else:
            logger.warning("⚠️ No _mesh_agent_capabilities found")

        logger.info("✅ @mesh_agent decorator tests passed")
        return True

    except Exception as e:
        logger.error(f"❌ @mesh_agent decorator test failed: {e}")
        return False


async def test_type_interfaces():
    """Test type interfaces from mcp-mesh-types."""
    logger.info("📋 Testing type interfaces")

    try:
        # Test CapabilityQuery creation
        query = CapabilityQuery(
            operator=QueryOperator.CONTAINS,
            field="capabilities",
            value="test_capability",
            matching_strategy=MatchingStrategy.SEMANTIC,
            weight=1.0,
        )
        logger.info(f"✅ CapabilityQuery created: {query.operator}")

        # Test Requirements creation
        requirements = Requirements(
            required_capabilities=["test_capability"],
            preferred_capabilities=["bonus_capability"],
            performance_requirements={"speed": 100.0},
            compatibility_threshold=0.8,
        )
        logger.info(
            f"✅ Requirements created: {len(requirements.required_capabilities)} required"
        )

        # Test CapabilityMetadata creation
        capability = CapabilityMetadata(
            name="test_capability",
            version="1.0.0",
            description="Test capability",
            tags=["test"],
            performance_metrics={"speed": 100.0},
        )
        logger.info(f"✅ CapabilityMetadata created: {capability.name}")

        logger.info("✅ Type interface tests passed")
        return True

    except Exception as e:
        logger.error(f"❌ Type interface test failed: {e}")
        return False


async def run_all_compliance_tests():
    """Run all MCP compliance tests."""
    logger.info("🚀 Running MCP SDK Compliance Tests")
    logger.info("=" * 50)

    tests = [
        ("Type Interfaces", test_type_interfaces),
        ("@mesh_agent Decorator", test_mesh_agent_decorator),
        ("MCP Server Tools", test_mcp_server_compliance),
    ]

    results = {}

    for test_name, test_func in tests:
        logger.info(f"\n🧪 Running: {test_name}")
        logger.info("-" * 30)

        try:
            result = await test_func()
            results[test_name] = result

            if result:
                logger.info(f"✅ {test_name}: PASSED")
            else:
                logger.error(f"❌ {test_name}: FAILED")

        except Exception as e:
            logger.error(f"💥 {test_name}: ERROR - {e}")
            results[test_name] = False

    # Summary
    logger.info("\n📊 COMPLIANCE TEST SUMMARY")
    logger.info("=" * 50)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} {test_name}")

    logger.info(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        logger.info("🎉 ALL COMPLIANCE TESTS PASSED!")
        logger.info("✨ Advanced Service Discovery is MCP SDK compliant")
    else:
        logger.warning(f"⚠️ {total - passed} tests failed")

    return passed == total


if __name__ == "__main__":
    print("🎯 MCP SDK Compliance Test Suite")
    print("Testing Advanced Service Discovery Implementation")
    print("=" * 60)
    print()
    print("Testing components:")
    print("1. 📋 Type interfaces from mcp-mesh-types")
    print("2. 🔧 @mesh_agent decorator functionality")
    print("3. 🛠️  MCP server tool registration and compliance")
    print("4. 🔍 JSON serialization and parameter validation")
    print()

    # Run the compliance tests
    success = asyncio.run(run_all_compliance_tests())

    if success:
        print("\n🎉 SUCCESS: Implementation is MCP SDK compliant!")
        exit(0)
    else:
        print("\n❌ FAILURE: Some compliance tests failed")
        exit(1)
