"""
Registry Client Example

Demonstrates how agents interact with the Registry Service
using only mcp-mesh-types package for vanilla MCP SDK compatibility.

Shows the PASSIVE pull-based architecture where agents:
1. Register themselves with the registry
2. Send periodic heartbeats
3. Discover other services
4. Update their capabilities
"""

import asyncio

import httpx
from mcp_mesh_types import mesh_agent


# Example 1: File Agent that registers with registry
@mesh_agent(
    capabilities=["file_read", "file_write", "secure_access"],
    dependencies=["auth_service"],
    health_interval=30,
    security_context="file_operations",
    registry_endpoint="http://localhost:8000",  # Registry service endpoint
)
async def file_agent_tool(path: str, operation: str = "read") -> str:
    """File operations tool that auto-registers with mesh registry."""
    # The @mesh_agent decorator automatically:
    # 1. Registers this agent with the registry on startup
    # 2. Sends periodic heartbeats to maintain health status
    # 3. Discovers and injects auth_service dependency
    # 4. Handles registry communication behind the scenes

    if operation == "read":
        try:
            with open(path) as f:
                content = f.read()
            return f"Successfully read {len(content)} characters from {path}"
        except Exception as e:
            return f"Error reading file: {e}"
    elif operation == "write":
        # In real implementation, would use auth_service for security
        return f"Write operation to {path} (would use auth service)"
    else:
        return f"Unknown operation: {operation}"


# Example 2: System Monitor Agent
@mesh_agent(
    capabilities=["system_monitoring", "health_check"],
    dependencies=["alert_service", "metrics_collector"],
    health_interval=15,  # More frequent heartbeat for monitoring
    security_context="system_access",
)
async def system_monitor_tool(metric: str = "cpu") -> dict:
    """System monitoring tool that integrates with service mesh."""
    # This agent will automatically register its monitoring capabilities
    # Other agents can discover it through the registry


    import psutil

    if metric == "cpu":
        return {"metric": "cpu_usage", "value": psutil.cpu_percent(), "unit": "%"}
    elif metric == "memory":
        mem = psutil.virtual_memory()
        return {"metric": "memory_usage", "value": mem.percent, "unit": "%"}
    else:
        return {"metric": "unknown", "value": 0, "unit": ""}


class RegistryClient:
    """Direct registry client for demonstration purposes."""

    def __init__(self, registry_url: str = "http://localhost:8000"):
        self.registry_url = registry_url
        self.client = httpx.AsyncClient()

    async def register_agent(self, registration_data: dict) -> dict:
        """Register agent with the registry."""
        try:
            # In real implementation, this would be done via MCP protocol
            # This is just for demonstration
            response = await self.client.post(
                f"{self.registry_url}/tools/register_agent",
                json={"registration_data": registration_data},
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def discover_services(self, query: dict = None) -> dict:
        """Discover services from registry."""
        try:
            response = await self.client.post(
                f"{self.registry_url}/tools/discover_services",
                json={"query": query or {}},
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def send_heartbeat(self, agent_id: str) -> dict:
        """Send heartbeat to registry."""
        try:
            response = await self.client.post(
                f"{self.registry_url}/tools/heartbeat", json={"agent_id": agent_id}
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


async def demonstrate_registry_interaction():
    """Demonstrate how agents interact with the registry."""
    print("🔗 MCP Mesh Registry Client Demo")
    print("=" * 50)

    # Create registry client
    client = RegistryClient()

    try:
        # 1. Register a file agent
        print("\n1. Registering file agent...")
        file_agent_registration = {
            "name": "file-agent-001",
            "namespace": "default",
            "endpoint": "stdio://file-agent",
            "capabilities": [
                {
                    "name": "file_read",
                    "description": "Read files securely",
                    "version": "1.0.0",
                    "security_requirements": ["authentication"],
                },
                {
                    "name": "file_write",
                    "description": "Write files securely",
                    "version": "1.0.0",
                    "security_requirements": ["authentication", "authorization"],
                },
            ],
            "dependencies": ["auth_service"],
            "security_context": "file_operations",
            "health_interval": 30,
            "labels": {"type": "file-agent", "version": "1.0.0"},
        }

        reg_result = await client.register_agent(file_agent_registration)
        print(f"   Registration result: {reg_result}")

        if reg_result.get("status") == "success":
            agent_id = reg_result.get("agent_id")

            # 2. Send heartbeat
            print(f"\n2. Sending heartbeat for agent {agent_id}...")
            heartbeat_result = await client.send_heartbeat(agent_id)
            print(f"   Heartbeat result: {heartbeat_result}")

            # 3. Discover services with file capabilities
            print("\n3. Discovering services with file capabilities...")
            discovery_result = await client.discover_services(
                {"capabilities": ["file_read"], "status": "healthy"}
            )
            print(f"   Found {discovery_result.get('count', 0)} services")
            for agent in discovery_result.get("agents", []):
                print(
                    f"   - {agent['name']}: {[cap['name'] for cap in agent['capabilities']]}"
                )

            # 4. Discover all services in default namespace
            print("\n4. Discovering all services in default namespace...")
            all_services = await client.discover_services({"namespace": "default"})
            print(
                f"   Total services in default namespace: {all_services.get('count', 0)}"
            )

        # 5. Register system monitor agent
        print("\n5. Registering system monitor agent...")
        monitor_registration = {
            "name": "system-monitor-001",
            "namespace": "monitoring",
            "endpoint": "stdio://system-monitor",
            "capabilities": [
                {
                    "name": "system_monitoring",
                    "description": "Monitor system metrics",
                    "version": "1.0.0",
                },
                {
                    "name": "health_check",
                    "description": "Health check capabilities",
                    "version": "1.0.0",
                },
            ],
            "dependencies": ["alert_service", "metrics_collector"],
            "health_interval": 15,
            "labels": {"type": "monitor", "category": "system"},
        }

        monitor_result = await client.register_agent(monitor_registration)
        print(f"   Monitor registration: {monitor_result}")

        # 6. Cross-namespace discovery
        print("\n6. Cross-namespace service discovery...")
        cross_ns_result = await client.discover_services(
            {"capabilities": ["system_monitoring"]}
        )
        print(f"   Found monitoring services: {cross_ns_result.get('count', 0)}")

    except Exception as e:
        print(f"❌ Demo error: {e}")

    finally:
        await client.close()

    print("\n✅ Registry interaction demo completed!")
    print("\nKey Points:")
    print("- Registry follows PASSIVE pull-based architecture")
    print("- Agents register themselves and send heartbeats")
    print("- Service discovery is capability and label-based")
    print("- @mesh_agent decorator handles all registry interactions")
    print("- Compatible with vanilla MCP SDK via mcp-mesh-types")


async def demonstrate_mesh_agent_usage():
    """Demonstrate the @mesh_agent decorator usage."""
    print("\n🎯 @mesh_agent Decorator Demo")
    print("=" * 50)

    try:
        # Test file agent tool
        print("\n1. Testing file agent (with mesh integration)...")
        result = await file_agent_tool("/tmp/test.txt", "read")
        print(f"   Result: {result}")

        # Test system monitor tool
        print("\n2. Testing system monitor (with mesh integration)...")
        cpu_result = await system_monitor_tool("cpu")
        print(f"   CPU Metrics: {cpu_result}")

        memory_result = await system_monitor_tool("memory")
        print(f"   Memory Metrics: {memory_result}")

    except Exception as e:
        print(f"❌ Mesh agent demo error: {e}")

    print("\n✅ @mesh_agent decorator demo completed!")


async def main():
    """Main demo function."""
    print("🚀 MCP Mesh Registry & Agent Integration Demo")
    print("Demonstrates PASSIVE pull-based service mesh architecture")
    print("=" * 70)

    # Note: In a real scenario, the registry service would be running
    # This demo shows the interaction patterns

    await demonstrate_registry_interaction()
    await demonstrate_mesh_agent_usage()

    print("\n📋 Summary:")
    print("- Registry Service provides centralized coordination")
    print("- Agents use @mesh_agent decorator for seamless integration")
    print("- Pull-based architecture: agents call registry, not vice versa")
    print("- Compatible with vanilla MCP SDK through mcp-mesh-types")
    print("- Kubernetes API server patterns for resource management")


if __name__ == "__main__":
    asyncio.run(main())
