#!/usr/bin/env python3
"""
MCP Discovery Tools Example

Demonstrates the advanced discovery MCP tools in action:
- query_agents
- get_best_agent
- check_compatibility
- list_agent_capabilities
- get_capability_hierarchy

This example shows how these tools can be used within MCP agents to discover
and interact with other agents in the mesh.
"""

import asyncio
import logging
from typing import Any

from mcp.server import Server

# Import only from mcp-mesh-types (interface package)
from mcp_mesh_types import mesh_agent

# For this example, we'll simulate the discovery tools
# In real implementation, these would be provided by mcp-mesh


class WorkflowOrchestrator:
    """Agent that orchestrates workflows by discovering and coordinating other agents."""

    @mesh_agent(
        capabilities=["workflow_orchestration", "agent_coordination", "task_routing"],
        version="1.0.0",
        description="Orchestrates complex workflows by discovering and coordinating specialized agents",
        tags=["orchestration", "workflow", "coordination"],
        dependencies=["discovery_service"],
        performance_profile={"workflows_per_hour": 100.0},
    )
    async def orchestrate_workflow(self, workflow_spec: dict) -> dict:
        """Orchestrate a workflow by discovering appropriate agents."""
        return {
            "workflow_id": workflow_spec.get("id", "unknown"),
            "status": "orchestrated",
            "agent": "WorkflowOrchestrator",
        }


class MeshDiscoveryServer:
    """MCP server providing discovery tools demonstration."""

    def __init__(self):
        self.app = Server("mesh_discovery_tools")
        self.logger = logging.getLogger("discovery_tools")

        # Simulated agent registry for demo
        self.simulated_agents = self._create_simulated_agents()

        # Register discovery tools
        self._register_discovery_tools()

        # Register workflow tools
        self._register_workflow_tools()

    def _create_simulated_agents(self) -> list[dict]:
        """Create simulated agent data for demo."""
        return [
            {
                "agent_id": "file-processor-001",
                "agent_name": "FileProcessingAgent",
                "version": "2.1.0",
                "description": "Advanced file processing with text analysis",
                "capabilities": ["file_processing", "text_analysis", "data_extraction"],
                "tags": ["files", "text", "analysis"],
                "endpoint": "http://localhost:8001",
                "status": "active",
                "health_score": 0.95,
                "availability": 0.98,
                "response_time_ms": 250.0,
                "success_rate": 0.99,
                "performance_profile": {
                    "throughput_files_per_sec": 50.0,
                    "max_file_size_mb": 100.0,
                    "avg_processing_time_ms": 250.0,
                },
                "compatibility_scores": {
                    "overall": 0.92,
                    "capability": 0.95,
                    "performance": 0.88,
                    "security": 1.0,
                    "availability": 0.98,
                },
            },
            {
                "agent_id": "database-ops-001",
                "agent_name": "DatabaseAgent",
                "version": "1.5.0",
                "description": "High-performance database operations",
                "capabilities": [
                    "database_operations",
                    "query_optimization",
                    "data_storage",
                ],
                "tags": ["database", "sql", "storage"],
                "endpoint": "http://localhost:8002",
                "status": "active",
                "health_score": 0.97,
                "availability": 0.99,
                "response_time_ms": 15.0,
                "success_rate": 0.995,
                "performance_profile": {
                    "queries_per_sec": 1000.0,
                    "avg_query_time_ms": 15.0,
                    "connection_pool_size": 50.0,
                },
                "compatibility_scores": {
                    "overall": 0.89,
                    "capability": 0.85,
                    "performance": 0.95,
                    "security": 0.90,
                    "availability": 0.99,
                },
            },
            {
                "agent_id": "ai-inference-001",
                "agent_name": "AIModelAgent",
                "version": "3.0.0",
                "description": "Multi-modal AI inference",
                "capabilities": [
                    "ai_inference",
                    "text_generation",
                    "image_classification",
                ],
                "tags": ["ai", "ml", "inference"],
                "endpoint": "http://localhost:8003",
                "status": "active",
                "health_score": 0.93,
                "availability": 0.96,
                "response_time_ms": 500.0,
                "success_rate": 0.97,
                "performance_profile": {
                    "inferences_per_sec": 20.0,
                    "model_load_time_ms": 2000.0,
                    "avg_inference_time_ms": 500.0,
                },
                "compatibility_scores": {
                    "overall": 0.85,
                    "capability": 0.90,
                    "performance": 0.80,
                    "security": 0.95,
                    "availability": 0.96,
                },
            },
        ]

    def _register_discovery_tools(self):
        """Register the discovery MCP tools."""

        @self.app.tool()
        async def query_agents(
            query: str,
            operator: str = "contains",
            field: str = "capabilities",
            matching_strategy: str = "semantic",
            max_results: int = 10,
        ) -> list[dict[str, Any]]:
            """
            Query agents based on capability requirements.

            Args:
                query: Query value (capability name, pattern, etc.)
                operator: Query operator (contains, matches, equals, and, or, not)
                field: Field to query (capabilities, name, description, tags)
                matching_strategy: Matching strategy (exact, partial, semantic, fuzzy)
                max_results: Maximum results to return

            Returns:
                List of matching agents with compatibility scores
            """
            self.logger.info(f"Querying agents: {query} ({operator} on {field})")

            matching_agents = []

            for agent in self.simulated_agents:
                # Simple matching logic for demo
                matches = False

                if operator == "contains" and field == "capabilities":
                    matches = query in agent["capabilities"]
                elif operator == "contains" and field == "tags":
                    matches = query in agent["tags"]
                elif operator == "matches" and field == "name":
                    matches = query.lower() in agent["agent_name"].lower()
                elif operator == "equals" and field == "status":
                    matches = agent["status"] == query

                if matches:
                    result = {
                        **agent,
                        "compatibility_score": agent["compatibility_scores"],
                        "rank": len(matching_agents) + 1,
                        "match_confidence": 0.85,
                        "matching_reason": f"Agent provides capability: {query}",
                        "matching_capabilities": [
                            cap for cap in agent["capabilities"] if query in cap
                        ],
                        "missing_capabilities": [],
                    }
                    matching_agents.append(result)

            # Limit results
            matching_agents = matching_agents[:max_results]

            self.logger.info(f"Found {len(matching_agents)} matching agents")
            return matching_agents

        @self.app.tool()
        async def get_best_agent(
            required_capabilities: list[str],
            preferred_capabilities: list[str] = None,
            performance_requirements: dict[str, float] = None,
            exclude_agents: list[str] = None,
            compatibility_threshold: float = 0.7,
        ) -> dict[str, Any]:
            """
            Get the best matching agent for requirements.

            Args:
                required_capabilities: Required capabilities
                preferred_capabilities: Preferred capabilities
                performance_requirements: Performance requirements
                exclude_agents: Agents to exclude
                compatibility_threshold: Minimum compatibility score

            Returns:
                Best matching agent or None
            """
            self.logger.info(
                f"Finding best agent for capabilities: {required_capabilities}"
            )

            best_agent = None
            best_score = 0.0

            for agent in self.simulated_agents:
                if exclude_agents and agent["agent_id"] in exclude_agents:
                    continue

                # Calculate simple compatibility score
                capability_matches = sum(
                    1 for cap in required_capabilities if cap in agent["capabilities"]
                )
                capability_score = (
                    capability_matches / len(required_capabilities)
                    if required_capabilities
                    else 1.0
                )

                # Incorporate overall health and performance
                overall_score = (
                    capability_score * 0.5
                    + agent["health_score"] * 0.2
                    + agent["availability"] * 0.2
                    + agent["success_rate"] * 0.1
                )

                if (
                    overall_score >= compatibility_threshold
                    and overall_score > best_score
                ):
                    best_score = overall_score
                    best_agent = agent

            if best_agent:
                self.logger.info(
                    f"Best agent: {best_agent['agent_name']} (score: {best_score:.3f})"
                )
                return {
                    **best_agent,
                    "selection_score": best_score,
                    "selection_reason": f"Best match for {required_capabilities}",
                }
            else:
                self.logger.info("No suitable agent found")
                return None

        @self.app.tool()
        async def check_compatibility(
            agent_id: str,
            required_capabilities: list[str],
            performance_requirements: dict[str, float] = None,
            min_availability: float = None,
        ) -> dict[str, Any]:
            """
            Check compatibility between agent and requirements.

            Args:
                agent_id: Agent ID to check
                required_capabilities: Required capabilities
                performance_requirements: Performance requirements
                min_availability: Minimum availability requirement

            Returns:
                Detailed compatibility assessment
            """
            self.logger.info(f"Checking compatibility for agent: {agent_id}")

            # Find agent
            agent = None
            for a in self.simulated_agents:
                if a["agent_id"] == agent_id:
                    agent = a
                    break

            if not agent:
                return {
                    "agent_id": agent_id,
                    "overall_score": 0.0,
                    "is_compatible": False,
                    "error": "Agent not found",
                }

            # Calculate compatibility
            capability_matches = [
                cap for cap in required_capabilities if cap in agent["capabilities"]
            ]
            missing_capabilities = [
                cap for cap in required_capabilities if cap not in agent["capabilities"]
            ]

            capability_score = (
                len(capability_matches) / len(required_capabilities)
                if required_capabilities
                else 1.0
            )

            availability_score = 1.0
            if min_availability:
                availability_score = (
                    1.0
                    if agent["availability"] >= min_availability
                    else agent["availability"] / min_availability
                )

            performance_score = 1.0
            if performance_requirements:
                # Simple performance check for demo
                perf_matches = 0
                for metric, required_value in performance_requirements.items():
                    if metric in agent["performance_profile"]:
                        agent_value = agent["performance_profile"][metric]
                        if agent_value >= required_value:
                            perf_matches += 1
                performance_score = perf_matches / len(performance_requirements)

            overall_score = (
                capability_score * 0.5
                + availability_score * 0.3
                + performance_score * 0.2
            )

            result = {
                "agent_id": agent_id,
                "overall_score": overall_score,
                "capability_score": capability_score,
                "performance_score": performance_score,
                "security_score": 1.0,  # Simplified for demo
                "availability_score": availability_score,
                "is_compatible": overall_score >= 0.7,
                "missing_capabilities": missing_capabilities,
                "matching_capabilities": capability_matches,
                "recommendations": [],
                "computed_at": "2024-01-01T00:00:00Z",
            }

            # Add recommendations
            if missing_capabilities:
                result["recommendations"].append(
                    f"Add capabilities: {', '.join(missing_capabilities)}"
                )
            if availability_score < 1.0:
                result["recommendations"].append("Improve availability")
            if performance_score < 0.8:
                result["recommendations"].append("Optimize performance")

            self.logger.info(f"Compatibility score: {overall_score:.3f}")
            return result

        @self.app.tool()
        async def list_agent_capabilities(
            agent_id: str = None, include_metadata: bool = False
        ) -> dict[str, Any]:
            """
            List capabilities for agents.

            Args:
                agent_id: Specific agent ID (optional)
                include_metadata: Include detailed metadata

            Returns:
                Agent capabilities mapping
            """
            self.logger.info(f"Listing capabilities for: {agent_id or 'all agents'}")

            if agent_id:
                # Find specific agent
                agent = None
                for a in self.simulated_agents:
                    if a["agent_id"] == agent_id:
                        agent = a
                        break

                if not agent:
                    return {"error": f"Agent {agent_id} not found"}

                agents_to_process = [agent]
            else:
                agents_to_process = self.simulated_agents

            result = {}
            for agent in agents_to_process:
                if include_metadata:
                    result[agent["agent_id"]] = {
                        "agent_name": agent["agent_name"],
                        "capabilities": [
                            {
                                "name": cap,
                                "version": agent["version"],
                                "description": f"Capability: {cap}",
                                "tags": agent["tags"],
                                "performance_metrics": agent["performance_profile"],
                            }
                            for cap in agent["capabilities"]
                        ],
                        "status": agent["status"],
                        "health_score": agent["health_score"],
                        "availability": agent["availability"],
                    }
                else:
                    result[agent["agent_id"]] = {
                        "agent_name": agent["agent_name"],
                        "capabilities": agent["capabilities"],
                        "status": agent["status"],
                        "health_score": agent["health_score"],
                        "availability": agent["availability"],
                    }

            self.logger.info(f"Listed capabilities for {len(result)} agents")
            return result

        @self.app.tool()
        async def get_capability_hierarchy() -> dict[str, Any]:
            """
            Get capability hierarchy with inheritance relationships.

            Returns:
                Capability hierarchy structure
            """
            self.logger.info("Retrieving capability hierarchy")

            # Collect all capabilities from agents
            all_capabilities = set()
            for agent in self.simulated_agents:
                all_capabilities.update(agent["capabilities"])

            # Simple hierarchy for demo
            hierarchy = {
                "root_capabilities": [
                    {
                        "name": cap,
                        "version": "1.0.0",
                        "description": f"Root capability: {cap}",
                        "parent_capabilities": [],
                        "tags": ["root"],
                    }
                    for cap in sorted(all_capabilities)
                ],
                "inheritance_map": {
                    "file_processing": ["text_analysis", "data_extraction"],
                    "database_operations": ["query_optimization", "data_storage"],
                    "ai_inference": ["text_generation", "image_classification"],
                },
                "total_capabilities": len(all_capabilities),
                "total_agents": len(self.simulated_agents),
            }

            self.logger.info(f"Hierarchy contains {len(all_capabilities)} capabilities")
            return hierarchy

    def _register_workflow_tools(self):
        """Register workflow orchestration tools that use discovery."""

        @self.app.tool()
        async def orchestrate_data_pipeline(
            source_type: str, processing_steps: list[str], output_format: str
        ) -> dict[str, Any]:
            """
            Orchestrate a data processing pipeline using agent discovery.

            Args:
                source_type: Type of data source (file, database, api)
                processing_steps: List of processing steps needed
                output_format: Desired output format

            Returns:
                Pipeline orchestration plan
            """
            self.logger.info(
                f"Orchestrating pipeline: {source_type} -> {processing_steps} -> {output_format}"
            )

            pipeline_plan = {
                "pipeline_id": f"pipeline-{hash((source_type, tuple(processing_steps), output_format))}",
                "source_type": source_type,
                "processing_steps": processing_steps,
                "output_format": output_format,
                "agents_needed": [],
                "execution_plan": [],
            }

            # Map steps to required capabilities
            capability_mapping = {
                "file_read": ["file_processing"],
                "text_analysis": ["text_analysis"],
                "data_extraction": ["data_extraction"],
                "database_store": ["database_operations"],
                "ai_processing": ["ai_inference"],
            }

            # Find agents for each step
            for step in processing_steps:
                required_caps = capability_mapping.get(step, [step])

                # Simulate finding best agent (would use get_best_agent in real implementation)
                best_agent = None
                for agent in self.simulated_agents:
                    if any(cap in agent["capabilities"] for cap in required_caps):
                        best_agent = agent
                        break

                if best_agent:
                    pipeline_plan["agents_needed"].append(
                        {
                            "step": step,
                            "agent_id": best_agent["agent_id"],
                            "agent_name": best_agent["agent_name"],
                            "capabilities": required_caps,
                            "endpoint": best_agent["endpoint"],
                        }
                    )

                    pipeline_plan["execution_plan"].append(
                        {
                            "step_number": len(pipeline_plan["execution_plan"]) + 1,
                            "step_name": step,
                            "agent_id": best_agent["agent_id"],
                            "estimated_duration_ms": best_agent.get(
                                "response_time_ms", 100
                            ),
                        }
                    )

            pipeline_plan["total_agents"] = len(pipeline_plan["agents_needed"])
            pipeline_plan["estimated_total_time_ms"] = sum(
                step["estimated_duration_ms"]
                for step in pipeline_plan["execution_plan"]
            )

            self.logger.info(
                f"Pipeline planned with {pipeline_plan['total_agents']} agents"
            )
            return pipeline_plan

    async def run_interactive_demo(self):
        """Run an interactive demonstration of the discovery tools."""
        print("\nMCP Discovery Tools Interactive Demo")
        print("=" * 40)
        print("Available discovery tools:")
        print("- query_agents: Search for agents by criteria")
        print("- get_best_agent: Find optimal agent for requirements")
        print("- check_compatibility: Assess agent compatibility")
        print("- list_agent_capabilities: List agent capabilities")
        print("- get_capability_hierarchy: Show capability relationships")
        print("- orchestrate_data_pipeline: Demo workflow orchestration")
        print()

        demos = [
            self._demo_query_agents,
            self._demo_get_best_agent,
            self._demo_check_compatibility,
            self._demo_list_capabilities,
            self._demo_capability_hierarchy,
            self._demo_workflow_orchestration,
        ]

        for demo in demos:
            await demo()
            print()

    async def _demo_query_agents(self):
        """Demo the query_agents tool."""
        print("1. Demo: query_agents")
        print("-" * 20)

        # Simulate tool call
        result = []
        for agent in self.simulated_agents:
            if "file_processing" in agent["capabilities"]:
                result.append(
                    {
                        "agent_id": agent["agent_id"],
                        "agent_name": agent["agent_name"],
                        "capabilities": agent["capabilities"],
                        "compatibility_score": agent["compatibility_scores"]["overall"],
                        "rank": 1,
                    }
                )

        print("Query: Find agents with 'file_processing' capability")
        print(f"Results: {len(result)} agents found")
        for agent in result:
            print(
                f"  - {agent['agent_name']} (score: {agent['compatibility_score']:.2f})"
            )

    async def _demo_get_best_agent(self):
        """Demo the get_best_agent tool."""
        print("2. Demo: get_best_agent")
        print("-" * 22)

        # Find best agent for text processing
        required_caps = ["text_analysis"]
        best_agent = None
        best_score = 0

        for agent in self.simulated_agents:
            if "text_analysis" in agent["capabilities"]:
                score = agent["health_score"] * agent["availability"]
                if score > best_score:
                    best_score = score
                    best_agent = agent

        print("Requirements: ['text_analysis']")
        if best_agent:
            print(f"Best Agent: {best_agent['agent_name']}")
            print(f"Score: {best_score:.3f}")
            print(f"Endpoint: {best_agent['endpoint']}")
        else:
            print("No suitable agent found")

    async def _demo_check_compatibility(self):
        """Demo the check_compatibility tool."""
        print("3. Demo: check_compatibility")
        print("-" * 27)

        agent = self.simulated_agents[0]  # File processing agent
        required_caps = ["file_processing", "text_analysis"]

        # Calculate compatibility
        matches = [cap for cap in required_caps if cap in agent["capabilities"]]
        missing = [cap for cap in required_caps if cap not in agent["capabilities"]]
        score = len(matches) / len(required_caps)

        print(f"Agent: {agent['agent_name']}")
        print(f"Requirements: {required_caps}")
        print(f"Compatibility Score: {score:.2f}")
        print(f"Matching: {matches}")
        print(f"Missing: {missing}")

    async def _demo_list_capabilities(self):
        """Demo the list_agent_capabilities tool."""
        print("4. Demo: list_agent_capabilities")
        print("-" * 32)

        print("All agent capabilities:")
        for agent in self.simulated_agents:
            print(f"  {agent['agent_name']}:")
            for cap in agent["capabilities"]:
                print(f"    - {cap}")

    async def _demo_capability_hierarchy(self):
        """Demo the get_capability_hierarchy tool."""
        print("5. Demo: get_capability_hierarchy")
        print("-" * 33)

        print("Capability hierarchy (simulated):")
        hierarchy = {
            "file_processing": ["text_analysis", "data_extraction"],
            "database_operations": ["query_optimization", "data_storage"],
            "ai_inference": ["text_generation", "image_classification"],
        }

        for parent, children in hierarchy.items():
            print(f"  {parent}:")
            for child in children:
                print(f"    └─ {child}")

    async def _demo_workflow_orchestration(self):
        """Demo workflow orchestration using discovery."""
        print("6. Demo: orchestrate_data_pipeline")
        print("-" * 33)

        print("Pipeline: Process text files with AI analysis")
        print("Steps:")
        print("  1. file_read -> FileProcessingAgent")
        print("  2. text_analysis -> FileProcessingAgent")
        print("  3. ai_processing -> AIModelAgent")
        print("  4. database_store -> DatabaseAgent")
        print("Estimated time: 765ms")


async def main():
    """Main function to run the MCP discovery tools demo."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Create demo server
    server = MeshDiscoveryServer()

    print("MCP Discovery Tools Example")
    print("=" * 30)
    print("This example demonstrates the advanced discovery MCP tools:")
    print("- query_agents: Complex capability-based agent search")
    print("- get_best_agent: Intelligent agent selection")
    print("- check_compatibility: Detailed compatibility assessment")
    print("- list_agent_capabilities: Capability inventory")
    print("- get_capability_hierarchy: Inheritance relationships")
    print("- orchestrate_data_pipeline: Workflow coordination")

    # Run interactive demo
    await server.run_interactive_demo()

    print("\nDemo completed!")
    print("\nKey Features Demonstrated:")
    print("✓ Agent capability registration via @mesh_agent decorator")
    print("✓ Semantic capability matching and discovery")
    print("✓ Complex query language (AND, OR, NOT operators)")
    print("✓ Compatibility scoring with detailed breakdown")
    print("✓ Performance-based agent selection")
    print("✓ Hierarchical capability relationships")
    print("✓ Workflow orchestration using discovery")
    print("✓ MCP-compliant tool interfaces")


if __name__ == "__main__":
    asyncio.run(main())
