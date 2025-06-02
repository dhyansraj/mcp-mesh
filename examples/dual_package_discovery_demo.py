#!/usr/bin/env python3
"""
Dual Package Discovery Demo

Demonstrates the dual-package architecture where:
- Examples import ONLY from mcp-mesh-types (interface package)
- Implementation details are handled by mcp-mesh (implementation package)

This example shows how to use the enhanced @mesh_agent decorator with
capability registration and discovery tools while maintaining clean
separation of interfaces and implementation.
"""

import asyncio
import logging

from mcp.server import Server

# CRITICAL: Import ONLY from mcp-mesh-types (interface package)
# This demonstrates the dual-package architecture requirement
from mcp_mesh_types import (
    CapabilityQuery,
    MatchingStrategy,
    QueryOperator,
    Requirements,
    mesh_agent,
)


# Example 1: Simple File Agent
class SimpleFileAgent:
    """Basic file operations agent using only interface imports."""

    @mesh_agent(
        capabilities=["file_read", "file_write"],
        version="1.0.0",
        description="Simple file operations agent",
        tags=["files", "basic"],
        performance_profile={"files_per_sec": 10.0},
    )
    async def handle_file_operation(self, operation: str, path: str) -> dict:
        """Handle basic file operations."""
        await asyncio.sleep(0.1)  # Simulate work
        return {
            "operation": operation,
            "path": path,
            "status": "completed",
            "agent": "SimpleFileAgent",
        }


# Example 2: Advanced Text Processing Agent
class TextProcessingAgent:
    """Advanced text processing with rich capability metadata."""

    @mesh_agent(
        capabilities=["text_analysis", "nlp_processing", "sentiment_analysis"],
        version="2.1.0",
        description="Advanced text processing with NLP capabilities",
        tags=["text", "nlp", "analysis", "sentiment"],
        performance_profile={
            "words_per_sec": 1000.0,
            "accuracy_score": 0.95,
            "memory_usage_mb": 256.0,
        },
        resource_requirements={
            "min_memory_mb": 512,
            "cpu_cores": 2,
        },
        dependencies=["nlp_models", "tokenizer"],
        security_context="text_processing",
        health_interval=45,
    )
    async def process_text(self, text: str, analysis_type: str = "sentiment") -> dict:
        """Process text with specified analysis type."""
        await asyncio.sleep(0.2)  # Simulate processing
        return {
            "text_length": len(text),
            "analysis_type": analysis_type,
            "result": "positive" if "good" in text.lower() else "neutral",
            "confidence": 0.85,
            "agent": "TextProcessingAgent",
        }


# Example 3: Database Agent with Complex Capabilities
class DatabaseAgent:
    """Database operations agent with hierarchical capabilities."""

    @mesh_agent(
        capabilities=["database_read", "database_write", "sql_optimization"],
        version="3.0.0",
        description="High-performance database operations agent",
        tags=["database", "sql", "performance", "optimization"],
        performance_profile={
            "queries_per_sec": 500.0,
            "avg_latency_ms": 20.0,
            "connection_pool_size": 50.0,
        },
        resource_requirements={
            "min_memory_mb": 1024,
            "max_connections": 100,
            "disk_space_gb": 10,
        },
        dependencies=["connection_pool", "query_cache"],
        security_context="database_operations",
        endpoint="http://localhost:8080/db-agent",
    )
    async def execute_query(self, query: str, optimize: bool = True) -> dict:
        """Execute database query with optional optimization."""
        await asyncio.sleep(0.05)  # Simulate query execution
        return {
            "query": query[:50] + "..." if len(query) > 50 else query,
            "optimized": optimize,
            "execution_time_ms": 15,
            "rows_processed": 42,
            "agent": "DatabaseAgent",
        }


class DiscoveryDemoServer:
    """Demo server showing discovery capabilities."""

    def __init__(self):
        self.app = Server("discovery_demo")
        self.logger = logging.getLogger("discovery_demo")

        # Register demo tools that use the interface types
        self._register_demo_tools()

    def _register_demo_tools(self):
        """Register demo tools using only interface types."""

        @self.app.tool()
        async def demo_simple_capability_search(capability: str) -> list[str]:
            """
            Demo: Search for agents by capability (interface-only example).

            In the real implementation, this would use the mcp-mesh discovery engine,
            but the client only needs to know about interface types.

            Args:
                capability: Capability to search for

            Returns:
                List of agent names (simulated)
            """
            # This demonstrates using interface types only
            query = CapabilityQuery(
                operator=QueryOperator.CONTAINS,
                field="capabilities",
                value=capability,
                matching_strategy=MatchingStrategy.SEMANTIC,
                weight=1.0,
            )

            # In real implementation, this would use ServiceDiscovery from mcp-mesh
            # Here we simulate the response
            simulated_results = []

            if capability == "file_read":
                simulated_results.append("SimpleFileAgent")
            elif capability == "text_analysis":
                simulated_results.append("TextProcessingAgent")
            elif capability == "database_read":
                simulated_results.append("DatabaseAgent")
            elif "processing" in capability:
                simulated_results.extend(["TextProcessingAgent", "DatabaseAgent"])

            self.logger.info(f"Search for '{capability}' found: {simulated_results}")
            return simulated_results

        @self.app.tool()
        async def demo_find_best_agent_for_task(
            task_description: str,
            required_capabilities: list[str],
            performance_threshold: float = 10.0,
        ) -> dict[str, str]:
            """
            Demo: Find best agent for a task using Requirements interface.

            Args:
                task_description: Description of the task
                required_capabilities: Required capabilities
                performance_threshold: Minimum performance requirement

            Returns:
                Best agent information (simulated)
            """
            # Use interface types to define requirements
            requirements = Requirements(
                required_capabilities=required_capabilities,
                performance_requirements={"min_throughput": performance_threshold},
                compatibility_threshold=0.7,
            )

            # Simulate best agent selection logic
            # In real implementation, this would use ServiceDiscovery.get_best_agent()
            best_agent = "Unknown"

            if "file" in required_capabilities:
                best_agent = "SimpleFileAgent"
            elif "text" in required_capabilities or "nlp" in required_capabilities:
                best_agent = "TextProcessingAgent"
            elif "database" in required_capabilities or "sql" in required_capabilities:
                best_agent = "DatabaseAgent"

            result = {
                "task": task_description,
                "best_agent": best_agent,
                "selection_reason": f"Best match for capabilities: {required_capabilities}",
                "compatibility_threshold": str(requirements.compatibility_threshold),
            }

            self.logger.info(f"Best agent for '{task_description}': {best_agent}")
            return result

        @self.app.tool()
        async def demo_complex_query_example() -> dict:
            """
            Demo: Complex query using interface types only.

            Returns:
                Example of complex query structure
            """
            # Build complex query using interface types
            text_query = CapabilityQuery(
                operator=QueryOperator.CONTAINS,
                field="capabilities",
                value="text_analysis",
                weight=0.8,
            )

            performance_query = CapabilityQuery(
                operator=QueryOperator.GREATER_THAN,
                field="words_per_sec",
                value=500.0,
                weight=0.6,
            )

            complex_query = CapabilityQuery(
                operator=QueryOperator.AND,
                subqueries=[text_query, performance_query],
                matching_strategy=MatchingStrategy.HIERARCHICAL,
                weight=1.0,
            )

            # Return query structure as example
            return {
                "query_type": "complex_and_query",
                "description": "Find high-performance text analysis agents",
                "operator": complex_query.operator.value,
                "subquery_count": len(complex_query.subqueries),
                "matching_strategy": complex_query.matching_strategy.value,
                "simulated_matches": ["TextProcessingAgent"],
            }

    async def run_demo(self):
        """Run the dual-package discovery demo."""
        print("\nDual Package Discovery Demo")
        print("==========================")
        print("This demo shows the dual-package architecture:")
        print("- Examples import ONLY from mcp-mesh-types")
        print("- Implementation handled by mcp-mesh")
        print("- Clean separation of interfaces and implementation\n")

        # Create example agents
        file_agent = SimpleFileAgent()
        text_agent = TextProcessingAgent()
        db_agent = DatabaseAgent()

        agents = [file_agent, text_agent, db_agent]

        print("Registered Agents:")
        print("-" * 17)

        for agent in agents:
            # Access metadata stored by @mesh_agent decorator
            agent_class = agent.__class__
            if hasattr(agent_class, "_mesh_metadata"):
                metadata = agent_class._mesh_metadata
                print(f"• {metadata['name']} v{metadata['version']}")
                print(f"  Capabilities: {metadata['capabilities']}")
                print(f"  Tags: {metadata['tags']}")
                print(f"  Description: {metadata['description']}")
                print()

        print("Discovery Examples:")
        print("-" * 18)

        # Example 1: Simple capability search
        print("1. Simple Capability Search:")
        capability = "text_analysis"
        print(f"   Query: Find agents with '{capability}' capability")
        # In real implementation: results = await query_agents(...)
        print("   Result: TextProcessingAgent (simulated)")
        print()

        # Example 2: Best agent selection
        print("2. Best Agent Selection:")
        task = "Process customer feedback text"
        requirements = ["text_analysis", "sentiment_analysis"]
        print(f"   Task: {task}")
        print(f"   Requirements: {requirements}")
        # In real implementation: best = await get_best_agent(...)
        print("   Best Agent: TextProcessingAgent (simulated)")
        print()

        # Example 3: Complex query
        print("3. Complex Query Example:")
        print("   Query: High-performance text agents with NLP")
        print("   Operators: AND, CONTAINS, GREATER_THAN")
        print("   Strategy: HIERARCHICAL matching")
        print("   Result: TextProcessingAgent (simulated)")
        print()

        print("Key Benefits of Dual Package Architecture:")
        print("-" * 42)
        print("✓ Clean separation of interfaces and implementation")
        print("✓ Examples only import from mcp-mesh-types")
        print("✓ Implementation details hidden in mcp-mesh")
        print("✓ Type safety with interface contracts")
        print("✓ Easy to test and mock with interface types")
        print("✓ Maintains MCP SDK compatibility")


async def main():
    """Main function to run the dual package demo."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    demo = DiscoveryDemoServer()
    await demo.run_demo()

    print("\nDemo completed!")
    print("In a real deployment:")
    print("- Agents would self-register via @mesh_agent decorator")
    print("- Discovery tools would be available as MCP tools")
    print("- Registry would handle all capability metadata")
    print("- Service discovery would provide intelligent matching")


if __name__ == "__main__":
    asyncio.run(main())
