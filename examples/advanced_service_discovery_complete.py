#!/usr/bin/env python3
"""
Complete Advanced Service Discovery Example with @mesh_agent Decorator

This example demonstrates:
1. Using @mesh_agent decorator with enhanced capability metadata
2. Agent-initiated capability registration
3. Discovery through MCP tools (query_agents, get_best_agent, check_compatibility)
4. Full workflow from registration to discovery

This example imports ONLY from mcp-mesh-types to demonstrate the clean interface.
"""

import asyncio
import logging
from datetime import datetime

from mcp import Server, StdioServerTransport

# Import ONLY from mcp-mesh-types for clean interface demonstration
from mcp_mesh_types import (
    CapabilityQuery,
    MatchingStrategy,
    QueryOperator,
    Requirements,
    mesh_agent,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("advanced_discovery_example")


# Example agent implementations using @mesh_agent decorator
@mesh_agent(
    capabilities=["file_operations", "data_processing", "csv_handling"],
    version="2.1.0",
    description="Advanced file processing agent with CSV specialization",
    endpoint="http://localhost:8001/api",
    tags=["files", "csv", "data", "batch"],
    performance_profile={
        "throughput_files_per_second": 50.0,
        "max_file_size_mb": 100.0,
        "concurrent_operations": 10.0,
    },
    resource_requirements={
        "memory_mb": 512,
        "cpu_cores": 2,
        "disk_space_gb": 10,
    },
    security_context="elevated",
    health_interval=15,
    dependencies=["storage_service", "validation_service"],
    category="data_processing",
    reliability_tier="production",
)
async def advanced_file_processor(
    file_path: str,
    operation: str = "process",
    storage_service: str | None = None,  # Injected dependency
    validation_service: str | None = None,  # Injected dependency
) -> dict:
    """Advanced file processing with dependency injection."""
    logger.info(f"Processing file: {file_path} with operation: {operation}")
    logger.info(f"Using storage: {storage_service}, validation: {validation_service}")

    # Simulate advanced processing
    await asyncio.sleep(0.1)

    return {
        "status": "success",
        "file_path": file_path,
        "operation": operation,
        "processed_at": datetime.now().isoformat(),
        "dependencies_used": {
            "storage_service": storage_service,
            "validation_service": validation_service,
        },
        "capabilities_used": ["file_operations", "data_processing", "csv_handling"],
    }


@mesh_agent(
    capabilities=["text_analysis", "nlp", "sentiment_analysis", "language_detection"],
    version="1.5.2",
    description="Natural language processing agent with sentiment analysis",
    endpoint="http://localhost:8002/api",
    tags=["nlp", "text", "ai", "sentiment"],
    performance_profile={
        "throughput_texts_per_second": 25.0,
        "max_text_length": 10000,
        "accuracy_score": 0.92,
        "response_time_ms": 150.0,
    },
    resource_requirements={
        "memory_mb": 1024,
        "cpu_cores": 4,
        "gpu_required": True,
    },
    security_context="standard",
    health_interval=30,
    dependencies=["ml_model_service"],
    category="ai_analysis",
    reliability_tier="production",
)
async def nlp_analyzer(
    text: str,
    analysis_type: str = "sentiment",
    ml_model_service: str | None = None,  # Injected dependency
) -> dict:
    """NLP analysis with model service dependency."""
    logger.info(f"Analyzing text: '{text[:50]}...' for {analysis_type}")
    logger.info(f"Using ML model service: {ml_model_service}")

    # Simulate NLP processing
    await asyncio.sleep(0.2)

    return {
        "status": "success",
        "text_preview": text[:100] + "..." if len(text) > 100 else text,
        "analysis_type": analysis_type,
        "sentiment_score": 0.75,  # Simulated
        "confidence": 0.92,
        "language": "en",
        "processed_at": datetime.now().isoformat(),
        "model_service": ml_model_service,
        "capabilities_used": ["text_analysis", "nlp", "sentiment_analysis"],
    }


@mesh_agent(
    capabilities=["basic_calc", "math_operations"],
    version="1.0.0",
    description="Simple mathematical operations agent",
    endpoint="http://localhost:8003/api",
    tags=["math", "calculator", "basic"],
    performance_profile={
        "operations_per_second": 1000.0,
        "precision_digits": 15,
    },
    resource_requirements={
        "memory_mb": 64,
        "cpu_cores": 1,
    },
    security_context="standard",
    health_interval=60,
    category="utilities",
    reliability_tier="development",
)
async def basic_calculator(operation: str, a: float, b: float) -> dict:
    """Basic mathematical operations."""
    logger.info(f"Performing {operation} on {a} and {b}")

    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        result = a / b if b != 0 else None
    else:
        result = None

    return {
        "status": "success" if result is not None else "error",
        "operation": operation,
        "operands": [a, b],
        "result": result,
        "processed_at": datetime.now().isoformat(),
        "capabilities_used": ["basic_calc", "math_operations"],
    }


# MCP Server with Discovery Tools
async def create_discovery_server():
    """Create MCP server with advanced discovery tools."""
    from src.mcp_mesh.tools.discovery_tools import register_discovery_tools

    app = Server("advanced-discovery-demo")

    # Register the advanced discovery tools
    register_discovery_tools(app)

    # Add demonstration tools
    @app.tool()
    async def demo_query_file_agents() -> list[dict]:
        """Demo: Find all agents capable of file operations."""
        from src.mcp_mesh.shared.service_discovery import ServiceDiscoveryService

        discovery = ServiceDiscoveryService()

        # Query for file operation capabilities
        query = CapabilityQuery(
            operator=QueryOperator.CONTAINS,
            field="capabilities",
            value="file_operations",
            matching_strategy=MatchingStrategy.SEMANTIC,
            weight=1.0,
        )

        matches = await discovery.query_agents(query)

        return [
            {
                "agent_id": match.agent_info.agent_id,
                "name": match.agent_info.agent_metadata.name,
                "capabilities": [
                    cap.name for cap in match.agent_info.agent_metadata.capabilities
                ],
                "compatibility_score": match.compatibility_score.overall_score,
                "rank": match.rank,
                "endpoint": match.agent_info.agent_metadata.endpoint,
            }
            for match in matches
        ]

    @app.tool()
    async def demo_find_best_nlp_agent() -> dict | None:
        """Demo: Find best agent for NLP tasks with specific requirements."""
        from src.mcp_mesh.shared.service_discovery import ServiceDiscoveryService

        discovery = ServiceDiscoveryService()

        # Define requirements for NLP tasks
        requirements = Requirements(
            required_capabilities=["text_analysis", "nlp"],
            preferred_capabilities=["sentiment_analysis"],
            performance_requirements={
                "accuracy_score": 0.85,
                "response_time_ms": 200.0,
            },
            min_availability=0.95,
            compatibility_threshold=0.8,
        )

        best_agent = await discovery.get_best_agent(requirements)

        if best_agent:
            return {
                "agent_id": best_agent.agent_id,
                "name": best_agent.agent_metadata.name,
                "capabilities": [
                    cap.name for cap in best_agent.agent_metadata.capabilities
                ],
                "performance_profile": best_agent.agent_metadata.performance_profile,
                "health_score": best_agent.health_score,
                "availability": best_agent.availability,
                "endpoint": best_agent.agent_metadata.endpoint,
            }
        return None

    @app.tool()
    async def demo_check_compatibility() -> dict:
        """Demo: Check compatibility of specific agent against requirements."""
        from src.mcp_mesh.shared.service_discovery import ServiceDiscoveryService

        discovery = ServiceDiscoveryService()

        # Check compatibility of file processor for data processing tasks
        requirements = Requirements(
            required_capabilities=["data_processing", "file_operations"],
            performance_requirements={
                "throughput_files_per_second": 30.0,
                "max_file_size_mb": 50.0,
            },
            security_requirements={"security_context": "elevated"},
            compatibility_threshold=0.7,
        )

        # Assume we know the agent_id from registration
        agent_id = "agent-file-processor"  # This would be the actual registered ID
        compatibility = await discovery.check_compatibility(agent_id, requirements)

        return {
            "agent_id": compatibility.agent_id,
            "overall_score": compatibility.overall_score,
            "is_compatible": compatibility.is_compatible(),
            "capability_score": compatibility.capability_score,
            "performance_score": compatibility.performance_score,
            "security_score": compatibility.security_score,
            "missing_capabilities": compatibility.missing_capabilities,
            "matching_capabilities": compatibility.matching_capabilities,
            "recommendations": compatibility.recommendations,
        }

    @app.tool()
    async def demo_complex_query() -> list[dict]:
        """Demo: Complex query with AND/OR logic."""
        from src.mcp_mesh.shared.service_discovery import ServiceDiscoveryService

        discovery = ServiceDiscoveryService()

        # Complex query: Find agents that have EITHER file operations OR NLP capabilities
        # AND are production-ready
        file_query = CapabilityQuery(
            operator=QueryOperator.CONTAINS,
            field="capabilities",
            value=["file_operations", "data_processing"],
            matching_strategy=MatchingStrategy.SEMANTIC,
            weight=0.6,
        )

        nlp_query = CapabilityQuery(
            operator=QueryOperator.CONTAINS,
            field="capabilities",
            value=["nlp", "text_analysis"],
            matching_strategy=MatchingStrategy.SEMANTIC,
            weight=0.6,
        )

        production_query = CapabilityQuery(
            operator=QueryOperator.CONTAINS,
            field="tags",
            value="production",
            matching_strategy=MatchingStrategy.EXACT,
            weight=0.4,
        )

        # Combine with OR for capabilities, AND for production
        capability_or_query = CapabilityQuery(
            operator=QueryOperator.OR, subqueries=[file_query, nlp_query], weight=0.7
        )

        final_query = CapabilityQuery(
            operator=QueryOperator.AND,
            subqueries=[capability_or_query, production_query],
            weight=1.0,
        )

        matches = await discovery.query_agents(final_query)

        return [
            {
                "agent_id": match.agent_info.agent_id,
                "name": match.agent_info.agent_metadata.name,
                "capabilities": [
                    cap.name for cap in match.agent_info.agent_metadata.capabilities
                ],
                "tags": match.agent_info.agent_metadata.tags,
                "compatibility_score": match.compatibility_score.overall_score,
                "match_confidence": match.match_confidence,
                "matching_reason": match.matching_reason,
            }
            for match in matches
        ]

    return app


async def run_demo():
    """Run the complete advanced service discovery demonstration."""
    logger.info("🚀 Starting Advanced Service Discovery Demo")

    # Simulate agent registration by calling the decorated functions
    # This will trigger the @mesh_agent decorator initialization
    logger.info("📋 Registering agents with enhanced capabilities...")

    try:
        # Trigger registration by calling functions (which initializes decorators)
        await advanced_file_processor("test.csv", "validate")
        await nlp_analyzer(
            "This is a test sentence for sentiment analysis.", "sentiment"
        )
        await basic_calculator("add", 10, 5)

        logger.info("✅ All agents registered with enhanced metadata")

        # Wait a moment for registration to complete
        await asyncio.sleep(2)

        # Create and run the MCP server
        logger.info("🔍 Starting MCP Discovery Server...")
        app = await create_discovery_server()

        # Run with stdio transport
        transport = StdioServerTransport()
        await app.run(transport)

    except Exception as e:
        logger.error(f"❌ Demo failed: {e}")
        raise


if __name__ == "__main__":
    # Example of how to use the demo
    print("🎯 Advanced Service Discovery with @mesh_agent Decorator")
    print("=" * 60)
    print()
    print("This demo shows:")
    print("1. ✨ Enhanced @mesh_agent decorator with capability metadata")
    print("2. 🔄 Agent-initiated capability registration")
    print("3. 🎯 Advanced discovery through MCP tools:")
    print("   - query_agents(query: CapabilityQuery)")
    print("   - get_best_agent(requirements: Requirements)")
    print("   - check_compatibility(agent_id, requirements)")
    print("4. 🏗️  Complex query examples with AND/OR logic")
    print("5. 📊 Compatibility scoring and recommendations")
    print()
    print("🔧 Run with: python -m examples.advanced_service_discovery_complete")
    print("📡 Use MCP client to interact with the tools")
    print()
    print("Available MCP Tools:")
    print("- query_agents: Search agents by capability queries")
    print("- get_best_agent: Find optimal agent for requirements")
    print("- check_compatibility: Score agent-requirement compatibility")
    print("- list_agent_capabilities: List all agent capabilities")
    print("- get_capability_hierarchy: View capability inheritance")
    print("- demo_*: Demonstration tools with examples")
    print()

    # Run the demo
    asyncio.run(run_demo())
