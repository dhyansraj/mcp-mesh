#!/usr/bin/env python3
"""
Registry Lifecycle Management Example

Demonstrates registry-level lifecycle management including:
- Agent registration with lifecycle events
- Graceful drain operations
- Agent deregistration
"""

import asyncio
import json

# Mock implementation for demo - would use actual lifecycle tools
# from mcp_mesh.server.registry import RegistryService
# from mcp_mesh.shared.lifecycle_manager import LifecycleManager
# from mcp_mesh.tools.lifecycle_tools import LifecycleTools


async def lifecycle_event_handler(event_data):
    """Handle lifecycle events for demonstration."""
    print(f"🔄 Lifecycle Event: {event_data['event_type']}")
    print(f"   Agent: {event_data['agent_name']} ({event_data['agent_id']})")
    print(f"   Message: {event_data['message']}")
    if event_data.get("old_status") and event_data.get("new_status"):
        print(
            f"   Status Transition: {event_data['old_status']} → {event_data['new_status']}"
        )
    print()


async def main():
    """Demonstrate registry lifecycle management."""
    print("🚀 Registry Lifecycle Management Demo")
    print("=" * 50)

    # Create registry service
    registry = RegistryService()
    await registry.initialize()

    # Subscribe to lifecycle events
    registry.lifecycle_manager.subscribe_to_lifecycle_events(lifecycle_event_handler)

    try:
        # Example 1: Register a new agent with lifecycle management
        print("📝 Example 1: Agent Registration with Lifecycle Management")
        print("-" * 50)

        agent_info = {
            "id": "example-agent-001",
            "name": "example-file-processor",
            "namespace": "production",
            "endpoint": "http://localhost:8081",
            "capabilities": [
                "file_processing",
                "data_transformation",
                "batch_operations",
            ],
            "dependencies": ["database", "storage"],
            "health_interval": 30,
            "security_context": "standard",
            "metadata": {
                "version": "1.2.0",
                "team": "data-platform",
                "environment": "prod",
            },
            "labels": {"app": "file-processor", "version": "v1.2.0", "tier": "backend"},
        }

        result = await registry.lifecycle_tools.register_agent(agent_info)
        print(f"Registration Result: {json.dumps(result, indent=2)}")
        print()

        # Check lifecycle status
        status_result = await registry.lifecycle_tools.get_agent_lifecycle_status(
            "example-agent-001"
        )
        print(f"Lifecycle Status: {json.dumps(status_result, indent=2)}")
        print()

        # Example 2: List agents by lifecycle status
        print("📋 Example 2: List Agents by Lifecycle Status")
        print("-" * 50)

        active_agents = await registry.lifecycle_tools.list_agents_by_lifecycle_status(
            "active"
        )
        print(f"Active Agents: {json.dumps(active_agents, indent=2)}")
        print()

        # Example 3: Drain an agent
        print("🔄 Example 3: Drain Agent from Selection Pool")
        print("-" * 50)

        drain_result = await registry.lifecycle_tools.drain_agent("example-agent-001")
        print(f"Drain Result: {json.dumps(drain_result, indent=2)}")
        print()

        # Check status after drain
        status_after_drain = await registry.lifecycle_tools.get_agent_lifecycle_status(
            "example-agent-001"
        )
        print(f"Status After Drain: {json.dumps(status_after_drain, indent=2)}")
        print()

        # Example 4: Graceful deregistration
        print("🗑️  Example 4: Graceful Agent Deregistration")
        print("-" * 50)

        deregister_result = await registry.lifecycle_tools.deregister_agent(
            "example-agent-001", graceful=True
        )
        print(f"Deregistration Result: {json.dumps(deregister_result, indent=2)}")
        print()

        # Example 5: Register multiple agents and demonstrate bulk operations
        print("🔄 Example 5: Multiple Agent Lifecycle Demo")
        print("-" * 50)

        # Register multiple agents
        agents = [
            {
                "id": f"worker-agent-{i:03d}",
                "name": f"worker-{i:03d}",
                "namespace": "workers",
                "endpoint": f"http://localhost:808{i}",
                "capabilities": ["task_processing", "queue_management"],
                "dependencies": ["redis", "database"],
                "metadata": {"worker_type": "general", "capacity": 100},
            }
            for i in range(1, 4)
        ]

        for agent in agents:
            result = await registry.lifecycle_tools.register_agent(agent)
            print(f"Registered: {agent['name']} - Success: {result['success']}")

        print()

        # List all active agents
        active_agents = await registry.lifecycle_tools.list_agents_by_lifecycle_status(
            "active"
        )
        print(f"Total Active Agents: {active_agents['count']}")

        # Drain one worker
        drain_result = await registry.lifecycle_tools.drain_agent("worker-agent-002")
        print(f"Drained worker-002: {drain_result['success']}")

        # List draining agents
        draining_agents = (
            await registry.lifecycle_tools.list_agents_by_lifecycle_status("draining")
        )
        print(f"Draining Agents: {draining_agents['count']}")

        # Deregister all workers
        print("\n🧹 Cleaning up workers...")
        for i in range(1, 4):
            agent_id = f"worker-agent-{i:03d}"
            result = await registry.lifecycle_tools.deregister_agent(
                agent_id, graceful=True
            )
            print(f"Deregistered {agent_id}: {result['success']}")

        print()

        # Example 6: Error handling demonstration
        print("⚠️  Example 6: Error Handling")
        print("-" * 50)

        # Try to register agent with missing required fields
        invalid_agent = {"name": "incomplete-agent"}
        result = await registry.lifecycle_tools.register_agent(invalid_agent)
        print(f"Invalid Registration: {json.dumps(result, indent=2)}")

        # Try to drain non-existent agent
        drain_result = await registry.lifecycle_tools.drain_agent("non-existent-agent")
        print(f"Drain Non-existent: {json.dumps(drain_result, indent=2)}")

        # Try to get status of non-existent agent
        status_result = await registry.lifecycle_tools.get_agent_lifecycle_status(
            "non-existent-agent"
        )
        print(f"Status Non-existent: {json.dumps(status_result, indent=2)}")

        print()
        print("✅ Registry Lifecycle Management Demo Completed!")

    except Exception as e:
        print(f"❌ Error in demo: {e}")
        raise
    finally:
        await registry.close()


if __name__ == "__main__":
    asyncio.run(main())
