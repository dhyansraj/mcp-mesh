#!/usr/bin/env python3
"""
Advanced Service Discovery Example

Demonstrates the enhanced service discovery capabilities with decorator pattern
integration, including semantic capability matching, complex queries, and
compatibility scoring.

This example shows how agents self-register with the registry using @mesh_agent
decorator metadata and how other agents can discover them using advanced MCP tools.
"""

import asyncio
import logging

from mcp.server import Server

# Import from mcp-mesh-types (interface package)
from mcp_mesh_types import (
    mesh_agent,
)

# Import from mcp-mesh-types (interface package) - using mock for demo
# from mcp_mesh.tools.discovery_tools import register_discovery_tools


class FileProcessingAgent:
    """Agent that provides file processing capabilities."""

    @mesh_agent(
        capabilities=["file_processing", "text_analysis", "data_extraction"],
        version="2.1.0",
        description="Advanced file processing agent with text analysis",
        tags=["files", "text", "analysis", "extraction"],
        performance_profile={
            "throughput_files_per_sec": 50.0,
            "max_file_size_mb": 100.0,
            "avg_processing_time_ms": 250.0,
        },
        resource_requirements={
            "memory_mb": 512,
            "cpu_cores": 2,
            "disk_space_mb": 1024,
        },
        security_context="file_operations",
        endpoint="http://localhost:8001/file-agent",
        health_interval=30,
    )
    async def process_file(self, file_path: str, operation: str = "analyze") -> dict:
        """Process a file with specified operation."""
        # Simulate file processing
        await asyncio.sleep(0.1)
        return {
            "status": "success",
            "file_path": file_path,
            "operation": operation,
            "agent": "FileProcessingAgent",
            "capabilities_used": ["file_processing", "text_analysis"],
        }


class DatabaseAgent:
    """Agent that provides database operations."""

    @mesh_agent(
        capabilities=["database_operations", "query_optimization", "data_storage"],
        version="1.5.0",
        description="High-performance database operations agent",
        tags=["database", "sql", "nosql", "storage", "query"],
        performance_profile={
            "queries_per_sec": 1000.0,
            "max_connection_pool": 50.0,
            "avg_query_time_ms": 15.0,
        },
        resource_requirements={
            "memory_mb": 2048,
            "cpu_cores": 4,
            "disk_space_mb": 10240,
        },
        security_context="database_access",
        endpoint="http://localhost:8002/db-agent",
        dependencies=["connection_pool", "auth_service"],
    )
    async def execute_query(self, query: str, params: dict = None) -> dict:
        """Execute database query with optimization."""
        await asyncio.sleep(0.05)
        return {
            "status": "success",
            "query": query[:50] + "..." if len(query) > 50 else query,
            "rows_affected": 42,
            "agent": "DatabaseAgent",
            "capabilities_used": ["database_operations", "query_optimization"],
        }


class AIModelAgent:
    """Agent that provides AI/ML model inference."""

    @mesh_agent(
        capabilities=["ai_inference", "text_generation", "image_classification"],
        version="3.0.0",
        description="Multi-modal AI agent for inference tasks",
        tags=["ai", "ml", "inference", "text", "image", "nlp"],
        performance_profile={
            "inferences_per_sec": 20.0,
            "model_load_time_ms": 2000.0,
            "avg_inference_time_ms": 500.0,
        },
        resource_requirements={
            "memory_mb": 8192,
            "gpu_memory_mb": 4096,
            "cpu_cores": 8,
        },
        security_context="ai_operations",
        endpoint="http://localhost:8003/ai-agent",
        dependencies=["model_registry", "gpu_scheduler"],
    )
    async def run_inference(self, input_data: str, model_type: str = "text") -> dict:
        """Run AI model inference on input data."""
        await asyncio.sleep(0.2)
        return {
            "status": "success",
            "model_type": model_type,
            "confidence": 0.95,
            "result": f"Processed {len(input_data)} characters",
            "agent": "AIModelAgent",
            "capabilities_used": ["ai_inference", "text_generation"],
        }


class ServiceDiscoveryDemo:
    """Demonstrates advanced service discovery features."""

    def __init__(self):
        self.logger = logging.getLogger("discovery_demo")

        # Create MCP server for discovery tools
        self.app = Server("advanced_discovery_demo")

        # Register the advanced discovery tools (mock for demo)
        # register_discovery_tools(self.app)

        # Register demo tools
        self._register_demo_tools()

    def _register_demo_tools(self):
        """Register demonstration tools."""

        @self.app.tool()
        async def demo_query_by_capability(capability_name: str) -> list[dict]:
            """
            Demo: Find agents that provide a specific capability.

            Args:
                capability_name: Name of the capability to search for

            Returns:
                List of agents providing the capability
            """
            try:
                # Mock implementation for demo - would use actual discovery tools
                # from mcp_mesh.tools.discovery_tools import DiscoveryTools
                # discovery = DiscoveryTools()

                # Simulate query results based on capability_name
                mock_results = []
                if capability_name == "file_processing":
                    mock_results = [
                        {
                            "agent_id": "file-agent-001",
                            "name": "FileProcessingAgent",
                            "capabilities": [
                                "file_processing",
                                "text_analysis",
                                "data_extraction",
                            ],
                            "compatibility_score": 0.95,
                            "endpoint": "http://localhost:8001/file-agent",
                        }
                    ]
                elif capability_name == "database_operations":
                    mock_results = [
                        {
                            "agent_id": "db-agent-001",
                            "name": "DatabaseAgent",
                            "capabilities": [
                                "database_operations",
                                "query_optimization",
                                "data_storage",
                            ],
                            "compatibility_score": 0.90,
                            "endpoint": "http://localhost:8002/db-agent",
                        }
                    ]
                elif capability_name == "ai_inference":
                    mock_results = [
                        {
                            "agent_id": "ai-agent-001",
                            "name": "AIModelAgent",
                            "capabilities": [
                                "ai_inference",
                                "text_generation",
                                "image_classification",
                            ],
                            "compatibility_score": 0.88,
                            "endpoint": "http://localhost:8003/ai-agent",
                        }
                    ]

                return mock_results

            except Exception as e:
                self.logger.error(f"Demo query failed: {e}")
                return [{"error": str(e)}]

        @self.app.tool()
        async def demo_find_best_for_task(
            task_description: str,
            required_capabilities: list[str],
            performance_needs: dict[str, float] = None,
        ) -> dict:
            """
            Demo: Find the best agent for a specific task.

            Args:
                task_description: Description of the task
                required_capabilities: List of required capabilities
                performance_needs: Performance requirements

            Returns:
                Best matching agent information
            """
            try:
                # Mock implementation for demo - would use actual discovery tools
                # from mcp_mesh.tools.discovery_tools import DiscoveryTools
                # discovery = DiscoveryTools()

                # Simulate best agent selection based on requirements
                if "file_processing" in required_capabilities:
                    return {
                        "task": task_description,
                        "selected_agent": {
                            "agent_id": "file-agent-001",
                            "name": "FileProcessingAgent",
                            "version": "2.1.0",
                            "description": "Advanced file processing agent with text analysis",
                            "capabilities": [
                                "file_processing",
                                "text_analysis",
                                "data_extraction",
                            ],
                            "endpoint": "http://localhost:8001/file-agent",
                            "health_score": 0.95,
                            "availability": 0.98,
                        },
                    }
                elif "database_operations" in required_capabilities:
                    return {
                        "task": task_description,
                        "selected_agent": {
                            "agent_id": "db-agent-001",
                            "name": "DatabaseAgent",
                            "version": "1.5.0",
                            "description": "High-performance database operations agent",
                            "capabilities": [
                                "database_operations",
                                "query_optimization",
                                "data_storage",
                            ],
                            "endpoint": "http://localhost:8002/db-agent",
                            "health_score": 0.92,
                            "availability": 0.96,
                        },
                    }
                else:
                    return {
                        "task": task_description,
                        "result": "No suitable agent found",
                        "reason": "No agent meets the requirements",
                    }

            except Exception as e:
                self.logger.error(f"Demo best agent search failed: {e}")
                return {"error": str(e)}

        @self.app.tool()
        async def demo_complex_discovery_query() -> dict:
            """
            Demo: Execute a complex discovery query with multiple criteria.

            Returns:
                Results of complex multi-criteria search
            """
            try:
                # Mock implementation for demo - would use actual discovery tools
                # from mcp_mesh.tools.discovery_tools import DiscoveryTools
                # discovery = DiscoveryTools()

                # Simulate complex query results
                mock_results = [
                    {
                        "agent_id": "file-agent-001",
                        "name": "FileProcessingAgent",
                        "capabilities": [
                            "file_processing",
                            "text_analysis",
                            "data_extraction",
                        ],
                        "performance_profile": {
                            "throughput_files_per_sec": 50.0,
                            "avg_processing_time_ms": 250.0,
                        },
                        "compatibility_score": 0.92,
                        "match_confidence": 0.95,
                        "ranking": 1,
                    },
                    {
                        "agent_id": "db-agent-001",
                        "name": "DatabaseAgent",
                        "capabilities": [
                            "database_operations",
                            "query_optimization",
                            "data_storage",
                        ],
                        "performance_profile": {
                            "queries_per_sec": 1000.0,
                            "avg_query_time_ms": 15.0,
                        },
                        "compatibility_score": 0.88,
                        "match_confidence": 0.90,
                        "ranking": 2,
                    },
                ]

                return {
                    "query_description": "High-performance agents with file OR database capabilities",
                    "total_matches": len(mock_results),
                    "results": mock_results,
                }

            except Exception as e:
                self.logger.error(f"Complex query demo failed: {e}")
                return {"error": str(e)}

        @self.app.tool()
        async def demo_compatibility_assessment(
            agent_name: str, requirements_scenario: str
        ) -> dict:
            """
            Demo: Assess compatibility between an agent and specific requirements.

            Args:
                agent_name: Name of the agent to assess
                requirements_scenario: Scenario describing requirements

            Returns:
                Detailed compatibility assessment
            """
            try:
                # Mock implementation for demo - would use actual discovery tools
                # from mcp_mesh.tools.discovery_tools import DiscoveryTools
                # discovery = DiscoveryTools()

                # Mock compatibility assessment
                if "file" in agent_name.lower():
                    agent_data = {
                        "id": "file-agent-001",
                        "name": "FileProcessingAgent",
                        "capabilities": [
                            "file_processing",
                            "text_analysis",
                            "data_extraction",
                        ],
                    }
                    if requirements_scenario == "high_performance_file_processing":
                        compatibility_data = {
                            "overall_score": 0.92,
                            "is_compatible": True,
                            "breakdown": {
                                "capability_score": 0.95,
                                "performance_score": 0.88,
                                "security_score": 0.90,
                                "availability_score": 0.95,
                            },
                            "missing_capabilities": [],
                            "matching_capabilities": [
                                "file_processing",
                                "text_analysis",
                            ],
                            "recommendations": ["Agent meets all requirements"],
                        }
                    else:
                        compatibility_data = {
                            "overall_score": 0.45,
                            "is_compatible": False,
                            "breakdown": {
                                "capability_score": 0.30,
                                "performance_score": 0.50,
                                "security_score": 0.60,
                                "availability_score": 0.40,
                            },
                            "missing_capabilities": ["database_operations"],
                            "matching_capabilities": [],
                            "recommendations": [
                                "Consider using a database-specialized agent"
                            ],
                        }
                elif "database" in agent_name.lower():
                    agent_data = {
                        "id": "db-agent-001",
                        "name": "DatabaseAgent",
                        "capabilities": [
                            "database_operations",
                            "query_optimization",
                            "data_storage",
                        ],
                    }
                    if requirements_scenario == "database_heavy_workload":
                        compatibility_data = {
                            "overall_score": 0.96,
                            "is_compatible": True,
                            "breakdown": {
                                "capability_score": 1.0,
                                "performance_score": 0.95,
                                "security_score": 0.92,
                                "availability_score": 0.98,
                            },
                            "missing_capabilities": [],
                            "matching_capabilities": [
                                "database_operations",
                                "query_optimization",
                            ],
                            "recommendations": [
                                "Excellent match for database workloads"
                            ],
                        }
                    else:
                        compatibility_data = {
                            "overall_score": 0.30,
                            "is_compatible": False,
                            "breakdown": {
                                "capability_score": 0.20,
                                "performance_score": 0.40,
                                "security_score": 0.30,
                                "availability_score": 0.30,
                            },
                            "missing_capabilities": ["file_processing", "ai_inference"],
                            "matching_capabilities": [],
                            "recommendations": ["Not suitable for non-database tasks"],
                        }
                else:
                    return {"error": f"Agent '{agent_name}' not found"}

                return {
                    "agent": agent_data,
                    "scenario": requirements_scenario,
                    "compatibility": compatibility_data,
                }

            except Exception as e:
                self.logger.error(f"Compatibility assessment demo failed: {e}")
                return {"error": str(e)}

    async def run_demo(self):
        """Run the service discovery demonstration."""
        self.logger.info("Starting Advanced Service Discovery Demo")

        # Simulate agent registration (in real scenario, agents would self-register)
        await self._simulate_agent_registration()

        # Demo different discovery scenarios
        await self._demo_basic_capability_search()
        await self._demo_best_agent_selection()
        await self._demo_complex_queries()
        await self._demo_compatibility_checks()

        self.logger.info("Demo completed successfully!")

    async def _simulate_agent_registration(self):
        """Simulate agent registration with the registry."""
        self.logger.info("Simulating agent registration...")

        # In a real scenario, each agent would register itself when decorated
        # with @mesh_agent. Here we simulate this for demo purposes.

        agents = [
            FileProcessingAgent(),
            DatabaseAgent(),
            AIModelAgent(),
        ]

        for agent in agents:
            # Extract metadata from the decorated class
            agent_class = agent.__class__
            if hasattr(agent_class, "_mesh_metadata"):
                metadata = agent_class._mesh_metadata
                self.logger.info(
                    f"Agent {metadata['name']} would register with capabilities: {metadata['capabilities']}"
                )

        self.logger.info("Agent registration simulation complete")

    async def _demo_basic_capability_search(self):
        """Demo basic capability-based search."""
        self.logger.info("\n=== Demo: Basic Capability Search ===")

        search_capabilities = ["file_processing", "database_operations", "ai_inference"]

        for capability in search_capabilities:
            self.logger.info(f"Searching for agents with capability: {capability}")
            # In real implementation, this would use the actual discovery tools
            self.logger.info(f"  -> Found agents providing {capability}")

    async def _demo_best_agent_selection(self):
        """Demo best agent selection for specific tasks."""
        self.logger.info("\n=== Demo: Best Agent Selection ===")

        tasks = [
            {
                "description": "Process large text files for analysis",
                "capabilities": ["file_processing", "text_analysis"],
                "performance": {"throughput_files_per_sec": 30.0},
            },
            {
                "description": "Execute complex database queries",
                "capabilities": ["database_operations", "query_optimization"],
                "performance": {"queries_per_sec": 800.0},
            },
            {
                "description": "Run AI inference on text data",
                "capabilities": ["ai_inference", "text_generation"],
                "performance": {"inferences_per_sec": 15.0},
            },
        ]

        for task in tasks:
            self.logger.info(f"Finding best agent for: {task['description']}")
            self.logger.info(f"  Requirements: {task['capabilities']}")
            # In real implementation, this would select the actual best agent
            self.logger.info("  -> Best agent selected based on compatibility scoring")

    async def _demo_complex_queries(self):
        """Demo complex multi-criteria queries."""
        self.logger.info("\n=== Demo: Complex Query Examples ===")

        queries = [
            "High-performance agents with file OR database capabilities",
            "AI agents with GPU requirements AND low latency",
            "Agents NOT requiring external dependencies",
            "Agents matching specific tag patterns",
        ]

        for query_desc in queries:
            self.logger.info(f"Complex query: {query_desc}")
            # In real implementation, this would execute the actual complex query
            self.logger.info("  -> Query executed with semantic matching")

    async def _demo_compatibility_checks(self):
        """Demo detailed compatibility assessments."""
        self.logger.info("\n=== Demo: Compatibility Assessment ===")

        scenarios = [
            ("FileProcessingAgent", "high_performance_file_processing"),
            ("DatabaseAgent", "database_heavy_workload"),
            ("AIModelAgent", "ai_inference_task"),
        ]

        for agent_name, scenario in scenarios:
            self.logger.info(f"Compatibility check: {agent_name} vs {scenario}")
            # In real implementation, this would perform actual compatibility scoring
            self.logger.info(
                "  -> Compatibility score calculated with detailed breakdown"
            )


def main():
    """Main function to run the advanced service discovery demo."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create and run demo
    demo = ServiceDiscoveryDemo()

    print(
        """
Advanced Service Discovery Demo
==============================

This example demonstrates:
1. Agent self-registration with @mesh_agent decorator metadata
2. Semantic capability matching and discovery
3. Complex query language for agent search
4. Compatibility scoring and best agent selection
5. MCP tools for discovery operations

The example includes:
- FileProcessingAgent: Provides file and text processing capabilities
- DatabaseAgent: Provides database operations with high performance
- AIModelAgent: Provides AI inference for multiple modalities

Discovery features demonstrated:
- query_agents: Find agents matching complex criteria
- get_best_agent: Select optimal agent for requirements
- check_compatibility: Assess agent-requirement compatibility
- Complex queries with AND/OR/NOT operators
- Performance-based matching and scoring
    """
    )

    # Run the demonstration
    asyncio.run(demo.run_demo())

    print(
        """
Demo completed! In a real implementation:
- Agents would automatically register when decorated with @mesh_agent
- The registry would store capability metadata and performance profiles
- Discovery tools would be available as MCP tools in any agent
- Compatibility scoring would drive intelligent agent selection
    """
    )


if __name__ == "__main__":
    main()
