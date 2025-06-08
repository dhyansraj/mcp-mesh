#!/usr/bin/env python3
"""
Example REST client for MCP Mesh Registry Service.

Demonstrates how agents interact with the PULL-based REST endpoints:
- POST /heartbeat (agents call this to report status)
- GET /agents (for service discovery)
- GET /capabilities (for capability discovery)

This follows the PASSIVE pull-based architecture where agents call the registry.
"""

import asyncio
from typing import Any

import httpx


class MeshRegistryClient:
    """Client for interacting with MCP Mesh Registry REST API."""

    def __init__(self, registry_url: str = "http://localhost:8000"):
        self.registry_url = registry_url.rstrip("/")

    async def send_heartbeat(
        self, agent_id: str, status: str = "healthy", metadata: dict[str, Any] = None
    ) -> dict[str, Any]:
        """Send heartbeat to registry (PULL-based - agent calls registry)."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.registry_url}/heartbeat",
                json={
                    "agent_id": agent_id,
                    "status": status,
                    "metadata": metadata or {},
                },
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise ValueError(f"Agent {agent_id} not found in registry")
            else:
                response.raise_for_status()

    async def discover_agents(
        self,
        namespace: str = None,
        status: str = None,
        capability: str = None,
        label_selector: str = None,
    ) -> list[dict[str, Any]]:
        """Discover agents by criteria (PULL-based service discovery)."""
        params = {}
        if namespace:
            params["namespace"] = namespace
        if status:
            params["status"] = status
        if capability:
            params["capability"] = capability
        if label_selector:
            params["label_selector"] = label_selector

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.registry_url}/agents", params=params)
            response.raise_for_status()
            data = response.json()
            return data["agents"]

    async def discover_capabilities(
        self, agent_id: str = None, capability_name: str = None
    ) -> list[dict[str, Any]]:
        """Discover capabilities (PULL-based capability discovery)."""
        params = {}
        if agent_id:
            params["agent_id"] = agent_id
        if capability_name:
            params["capability_name"] = capability_name

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.registry_url}/capabilities", params=params
            )

            if response.status_code == 404 and agent_id:
                raise ValueError(f"Agent {agent_id} not found")

            response.raise_for_status()
            data = response.json()
            return data["capabilities"]

    async def check_registry_health(self) -> dict[str, Any]:
        """Check if registry service is healthy."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.registry_url}/health")

            if response.status_code == 503:
                raise ConnectionError("Registry service is unhealthy")

            response.raise_for_status()
            return response.json()


async def demo_pull_based_interactions():
    """Demonstrate PULL-based interactions with the registry."""
    client = MeshRegistryClient()

    print("🚀 MCP Mesh Registry REST Client Demo")
    print("🔄 Demonstrating PASSIVE pull-based architecture")
    print("=" * 60)

    # 1. Check registry health
    print("1. Checking registry health...")
    try:
        health = await client.check_registry_health()
        print(f"   ✅ Registry is healthy: {health}")
    except Exception as e:
        print(f"   ❌ Registry health check failed: {e}")
        return

    print()

    # 2. Discover agents (empty registry)
    print("2. Discovering agents (empty registry)...")
    try:
        agents = await client.discover_agents()
        print(f"   Found {len(agents)} agents")
        for agent in agents:
            print(f"     - {agent['name']} ({agent['id']})")
    except Exception as e:
        print(f"   ❌ Agent discovery failed: {e}")

    print()

    # 3. Discover capabilities (empty registry)
    print("3. Discovering capabilities (empty registry)...")
    try:
        capabilities = await client.discover_capabilities()
        print(f"   Found {len(capabilities)} capabilities")
        for cap in capabilities:
            print(f"     - {cap['name']} from {cap['agent_name']}")
    except Exception as e:
        print(f"   ❌ Capability discovery failed: {e}")

    print()

    # 4. Try to send heartbeat for non-existent agent
    print("4. Sending heartbeat for non-existent agent...")
    try:
        result = await client.send_heartbeat("test-agent-123")
        print(f"   ✅ Heartbeat sent: {result}")
    except ValueError as e:
        print(f"   ❌ Expected error: {e}")
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")

    print()

    # 5. Discover agents with filters
    print("5. Discovering agents with filters...")
    try:
        # Test various filter combinations
        test_cases = [
            {"namespace": "production"},
            {"status": "healthy"},
            {"capability": "file_operations"},
            {"label_selector": "env=prod,team=backend"},
        ]

        for test_case in test_cases:
            agents = await client.discover_agents(**test_case)
            print(f"   Filter {test_case}: {len(agents)} agents found")

    except Exception as e:
        print(f"   ❌ Filtered discovery failed: {e}")

    print()

    # 6. Test invalid label selector
    print("6. Testing invalid label selector...")
    try:
        agents = await client.discover_agents(label_selector="invalid-format")
        print(f"   ❌ Should have failed but got: {len(agents)} agents")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            print(f"   ✅ Expected 400 error: {e.response.json()}")
        else:
            print(f"   ❌ Unexpected error: {e}")
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")

    print()

    # 7. Test capability discovery for non-existent agent
    print("7. Testing capability discovery for non-existent agent...")
    try:
        capabilities = await client.discover_capabilities(agent_id="non-existent")
        print(f"   ❌ Should have failed but got: {len(capabilities)} capabilities")
    except ValueError as e:
        print(f"   ✅ Expected error: {e}")
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")

    print()
    print("🎉 Demo completed!")
    print()
    print("Key Observations:")
    print("- ✅ Registry follows PASSIVE pull-based architecture")
    print("- ✅ Agents call registry (registry doesn't call agents)")
    print("- ✅ Proper HTTP status codes (200, 404, 400, etc.)")
    print("- ✅ RESTful API design with query parameters")
    print("- ✅ Service discovery through GET /agents")
    print("- ✅ Capability discovery through GET /capabilities")
    print("- ✅ Heartbeat mechanism through POST /heartbeat")


if __name__ == "__main__":
    print("Starting MCP Mesh Registry REST Client Demo...")
    print("Make sure the registry server is running on localhost:8000")
    print()

    asyncio.run(demo_pull_based_interactions())
