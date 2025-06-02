#!/usr/bin/env python3
"""
Example demonstrating intelligent agent selection algorithms.

This example shows how to use the new agent selection features:
- Round-robin selection across healthy agents
- Weighted selection based on capability match and performance
- Health-aware selection excluding degraded agents
"""

import asyncio

# Mock implementation for demo - would use actual selection tools
# from mcp_mesh.shared.agent_selection import AgentSelector
# from mcp_mesh.tools.selection_tools import SelectionTools


class MockRegistryClient:
    """Mock registry client for testing."""

    def __init__(self):
        # Sample agent data
        self.agents = [
            {
                "id": "file-agent-1",
                "name": "File Operations Agent",
                "version": "1.0.0",
                "status": "healthy",
                "health_score": 0.95,
                "availability": 0.99,
                "current_load": 0.3,
                "response_time_ms": 150.0,
                "success_rate": 0.98,
                "capabilities": [
                    {"name": "file_read", "version": "1.0.0"},
                    {"name": "file_write", "version": "1.0.0"},
                ],
                "tags": ["local", "filesystem"],
            },
            {
                "id": "file-agent-2",
                "name": "File Operations Agent",
                "version": "1.1.0",
                "status": "healthy",
                "health_score": 0.87,
                "availability": 0.95,
                "current_load": 0.6,
                "response_time_ms": 200.0,
                "success_rate": 0.96,
                "capabilities": [
                    {"name": "file_read", "version": "1.1.0"},
                    {"name": "file_write", "version": "1.1.0"},
                    {"name": "file_search", "version": "1.0.0"},
                ],
                "tags": ["remote", "filesystem"],
            },
            {
                "id": "web-agent-1",
                "name": "Web Operations Agent",
                "version": "2.0.0",
                "status": "degraded",
                "health_score": 0.65,
                "availability": 0.85,
                "current_load": 0.9,
                "response_time_ms": 500.0,
                "success_rate": 0.88,
                "capabilities": [
                    {"name": "web_fetch", "version": "2.0.0"},
                    {"name": "web_search", "version": "1.5.0"},
                ],
                "tags": ["remote", "web"],
            },
            {
                "id": "compute-agent-1",
                "name": "Compute Agent",
                "version": "1.2.0",
                "status": "healthy",
                "health_score": 0.92,
                "availability": 0.97,
                "current_load": 0.2,
                "response_time_ms": 100.0,
                "success_rate": 0.99,
                "capabilities": [
                    {"name": "data_processing", "version": "1.2.0"},
                    {"name": "file_read", "version": "1.0.0"},
                ],
                "tags": ["local", "compute"],
            },
        ]

    async def get_all_agents(self):
        """Get all registered agents."""
        return self.agents

    async def get_agent(self, agent_id: str):
        """Get specific agent by ID."""
        for agent in self.agents:
            if agent["id"] == agent_id:
                return agent
        return None


async def demonstrate_round_robin_selection():
    """Demonstrate round-robin selection algorithm."""
    print("🔄 Demonstrating Round-Robin Selection")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Perform multiple round-robin selections
    for i in range(5):
        result = await tools.select_agent(
            capability="file_read",
            algorithm="round_robin",
            exclude_unhealthy=True,
            min_health_score=0.8,
        )

        if result["success"]:
            agent = result["selected_agent"]
            print(
                f"Selection {i+1}: {agent['name']} (ID: {agent['agent_id']}) - Health: {agent['health_score']:.2f}"
            )
        else:
            print(
                f"Selection {i+1}: Failed - {result.get('error', 'No agent selected')}"
            )

    print()


async def demonstrate_weighted_selection():
    """Demonstrate weighted selection algorithm."""
    print("⚖️  Demonstrating Weighted Selection")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Perform weighted selections with different criteria
    algorithms = [
        ("weighted", "Standard weighted selection"),
        ("weighted", "Performance-focused selection"),
    ]

    for i, (algorithm, description) in enumerate(algorithms):
        if i == 1:
            # Update weights for performance focus
            await tools.update_selection_weights(
                agent_id="global",
                weights={
                    "health_weight": 0.2,
                    "performance_weight": 0.5,
                    "availability_weight": 0.15,
                    "capability_weight": 0.1,
                    "load_weight": 0.05,
                },
                apply_globally=True,
                reason="Focus on performance",
            )

        result = await tools.select_agent(capability="file_read", algorithm=algorithm)

        if result["success"]:
            agent = result["selected_agent"]
            score = result.get("selection_score", "N/A")
            print(f"{description}:")
            print(f"  Selected: {agent['name']} (ID: {agent['agent_id']})")
            print(f"  Score: {score}")
            print(
                f"  Health: {agent['health_score']:.2f}, Load: {agent['current_load']:.2f}"
            )
            print(f"  Response Time: {agent['response_time_ms']}ms")
            print()


async def demonstrate_health_aware_selection():
    """Demonstrate health-aware selection algorithm."""
    print("🏥 Demonstrating Health-Aware Selection")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Test with different health thresholds
    thresholds = [0.9, 0.8, 0.6]

    for threshold in thresholds:
        result = await tools.select_agent(
            capability="file_read",
            algorithm="health_aware",
            min_health_score=threshold,
            exclude_unhealthy=True,
        )

        if result["success"]:
            agent = result["selected_agent"]
            print(
                f"Threshold {threshold}: Selected {agent['name']} (Health: {agent['health_score']:.2f})"
            )
        else:
            print(
                f"Threshold {threshold}: {result.get('selection_reason', 'No selection')}"
            )

    print()


async def demonstrate_agent_health_monitoring():
    """Demonstrate agent health monitoring."""
    print("📊 Demonstrating Agent Health Monitoring")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Get health for all agents
    for agent_data in mock_client.agents:
        agent_id = agent_data["id"]
        health = await tools.get_agent_health(agent_id)

        if health["success"]:
            print(f"Agent: {agent_id}")
            print(f"  Status: {health['status']}")
            print(f"  Health Score: {health['health_score']:.2f}")
            print(f"  Success Rate: {health['success_rate']:.2f}")
            print(f"  Current Load: {health['current_load']:.2f}")
            print(f"  Response Time: {health.get('response_time_ms', 'N/A')}ms")
            print()


async def demonstrate_available_agents_query():
    """Demonstrate querying available agents."""
    print("🔍 Demonstrating Available Agents Query")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Query available agents for different capabilities
    capabilities = ["file_read", "web_fetch", "data_processing"]

    for capability in capabilities:
        result = await tools.get_available_agents(
            capability=capability, min_health_score=0.7, exclude_unhealthy=True
        )

        if result["success"]:
            print(f"Capability: {capability}")
            print(f"  Available agents: {result['count']}")
            for agent in result["agents"]:
                print(f"    - {agent['name']} (Health: {agent['health_score']:.2f})")
            print()


async def demonstrate_selection_statistics():
    """Demonstrate selection statistics."""
    print("📈 Demonstrating Selection Statistics")
    print("=" * 50)

    # Setup
    selector = AgentSelector()
    tools = SelectionTools(selector)
    mock_client = MockRegistryClient()

    selector.set_registry_client(mock_client)
    tools.set_registry_client(mock_client)

    # Perform several selections to generate statistics
    for i in range(10):
        await tools.select_agent(capability="file_read", algorithm="round_robin")

    # Get statistics
    stats = await tools.get_selection_stats()

    if stats["success"]:
        print("Selection Statistics:")
        print(f"  Selections made: {stats['selection_history_length']}")
        print(f"  Unique agents used: {stats['unique_agents_selected']}")
        print(f"  Round-robin index: {stats['round_robin_index']}")
        print("  Most selected agents:")
        for agent_stat in stats["most_selected_agents"]:
            print(f"    - {agent_stat['agent_id']}: {agent_stat['count']} times")
        print()


async def main():
    """Main demonstration function."""
    print("🚀 MCP Mesh - Intelligent Agent Selection Demonstration")
    print("=" * 60)
    print()

    # Run all demonstrations
    await demonstrate_round_robin_selection()
    await demonstrate_weighted_selection()
    await demonstrate_health_aware_selection()
    await demonstrate_agent_health_monitoring()
    await demonstrate_available_agents_query()
    await demonstrate_selection_statistics()

    print("✅ All demonstrations completed successfully!")
    print("\nKey Features Demonstrated:")
    print("- Round-robin selection across healthy agents")
    print("- Weighted selection based on performance and health")
    print("- Health-aware selection with degradation handling")
    print("- Agent health monitoring and status reporting")
    print("- Available agents querying with filtering")
    print("- Selection statistics and state management")


if __name__ == "__main__":
    asyncio.run(main())
