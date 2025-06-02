#!/usr/bin/env python3
"""
Complete Registry Workflow Example

Demonstrates the full end-to-end workflow of the MCP Mesh Registry Service
including agent registration, service discovery, health monitoring, and
graceful degradation scenarios.

Only imports from mcp-mesh-types for MCP SDK compatibility.
"""

import asyncio

import aiohttp

# Import only from mcp-mesh-types for MCP SDK compatibility


class RegistryWorkflowDemo:
    """Comprehensive demonstration of registry workflows."""

    def __init__(self, registry_url: str = "http://localhost:8000"):
        self.registry_url = registry_url
        self.agents = []

    async def run_complete_workflow(self):
        """Run the complete registry workflow demonstration."""
        print("🚀 Starting Complete Registry Workflow Demo")
        print("=" * 60)

        try:
            # Step 1: Verify registry is available
            await self.verify_registry_availability()

            # Step 2: Register multiple agents
            await self.register_sample_agents()

            # Step 3: Demonstrate service discovery
            await self.demonstrate_service_discovery()

            # Step 4: Show capability search
            await self.demonstrate_capability_search()

            # Step 5: Test heartbeat workflows
            await self.demonstrate_heartbeat_workflows()

            # Step 6: Monitor health and metrics
            await self.monitor_health_and_metrics()

            # Step 7: Test version constraints
            await self.test_version_constraints()

            # Step 8: Demonstrate graceful degradation
            await self.demonstrate_graceful_degradation()

            # Step 9: Show advanced filtering
            await self.demonstrate_advanced_filtering()

            # Step 10: Cleanup
            await self.cleanup_agents()

        except Exception as e:
            print(f"❌ Demo failed: {e}")
            raise

        print("✅ Complete Registry Workflow Demo finished successfully!")

    async def verify_registry_availability(self):
        """Verify that the registry service is available."""
        print("\n📡 Step 1: Verifying Registry Availability")
        print("-" * 40)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.registry_url}/health") as resp:
                    if resp.status == 200:
                        health_data = await resp.json()
                        print(f"✅ Registry is healthy: {health_data['service']}")
                    else:
                        raise Exception(f"Registry health check failed: {resp.status}")

                # Get registry info
                async with session.get(f"{self.registry_url}/") as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        print(f"📝 Registry Service: {info['service']}")
                        print(f"📊 Version: {info['version']}")
                        print(f"🏗️  Architecture: {info['architecture']}")
                        print("🌐 Available Endpoints:")
                        for endpoint, desc in info["endpoints"].items():
                            print(f"   • {endpoint}: {desc}")

        except Exception as e:
            print(f"❌ Registry not available: {e}")
            print("💡 Make sure to start the registry first:")
            print("   python -m mcp_mesh.server --host localhost --port 8000")
            raise

    async def register_sample_agents(self):
        """Register sample agents of different types."""
        print("\n📝 Step 2: Registering Sample Agents")
        print("-" * 40)

        # File Agent
        file_agent = {
            "id": "demo-file-agent-001",
            "name": "Demo File Operations Agent",
            "namespace": "system",
            "agent_type": "file_agent",
            "endpoint": "http://localhost:8001/mcp",
            "capabilities": [
                {
                    "name": "read_file",
                    "description": "Read file contents with security validation",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "security"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to file",
                            },
                            "encoding": {"type": "string", "default": "utf-8"},
                        },
                        "required": ["file_path"],
                    },
                },
                {
                    "name": "write_file",
                    "description": "Write content to filesystem with backup",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "write"],
                },
                {
                    "name": "list_directory",
                    "description": "List directory contents with filtering",
                    "category": "file_operations",
                    "version": "1.2.0",
                    "stability": "stable",
                    "tags": ["io", "filesystem", "directory"],
                },
            ],
            "labels": {
                "env": "demo",
                "team": "platform",
                "zone": "us-west-2a",
                "criticality": "high",
            },
            "security_context": "standard",
            "health_interval": 30.0,
        }

        # Command Agent
        command_agent = {
            "id": "demo-command-agent-001",
            "name": "Demo Command Execution Agent",
            "namespace": "system",
            "agent_type": "command_agent",
            "endpoint": "http://localhost:8002/mcp",
            "capabilities": [
                {
                    "name": "execute_command",
                    "description": "Execute system commands with audit trail",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "stable",
                    "tags": ["shell", "system", "audit"],
                },
                {
                    "name": "monitor_process",
                    "description": "Monitor running processes and resource usage",
                    "category": "system_operations",
                    "version": "2.1.0",
                    "stability": "beta",
                    "tags": ["monitoring", "process", "resources"],
                },
                {
                    "name": "authentication",
                    "description": "User authentication and session management",
                    "category": "security",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["auth", "security"],
                },
                {
                    "name": "authorization",
                    "description": "Permission and access control checks",
                    "category": "security",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["authz", "security"],
                },
                {
                    "name": "audit",
                    "description": "Security audit logging and compliance",
                    "category": "security",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["audit", "compliance", "security"],
                },
            ],
            "labels": {
                "env": "demo",
                "team": "devops",
                "zone": "us-west-2b",
                "criticality": "critical",
            },
            "security_context": "high_security",
            "health_interval": 15.0,
        }

        # Developer Agent
        developer_agent = {
            "id": "demo-developer-agent-001",
            "name": "Demo Developer Assistant Agent",
            "namespace": "development",
            "agent_type": "developer_agent",
            "endpoint": "http://localhost:8003/mcp",
            "capabilities": [
                {
                    "name": "code_review",
                    "description": "Automated code review with quality metrics",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "stable",
                    "tags": ["code", "review", "quality", "analysis"],
                },
                {
                    "name": "test_generation",
                    "description": "Generate comprehensive unit and integration tests",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "experimental",
                    "tags": ["testing", "automation", "generation"],
                },
                {
                    "name": "refactor_code",
                    "description": "Intelligent code refactoring suggestions",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "beta",
                    "tags": ["refactoring", "optimization"],
                },
                {
                    "name": "documentation_generation",
                    "description": "Generate technical documentation and API docs",
                    "category": "development",
                    "version": "1.5.2",
                    "stability": "stable",
                    "tags": ["documentation", "api", "technical"],
                },
            ],
            "labels": {
                "env": "development",
                "team": "engineering",
                "zone": "us-east-1a",
                "criticality": "medium",
            },
            "security_context": "standard",
            "health_interval": 60.0,
        }

        self.agents = [file_agent, command_agent, developer_agent]

        # Register each agent
        async with aiohttp.ClientSession() as session:
            for i, agent in enumerate(self.agents):
                print(f"📝 Registering Agent {i+1}: {agent['name']}")

                async with session.post(
                    f"{self.registry_url}/mcp/tools/register_agent",
                    json={"registration_data": agent},
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result["status"] == "success":
                            print(f"   ✅ Registered: {result['agent_id']}")
                            print(
                                f"   📋 Resource Version: {result['resource_version']}"
                            )
                        else:
                            print(f"   ❌ Registration failed: {result.get('message')}")
                    else:
                        print(f"   ❌ HTTP Error: {resp.status}")

        print(f"✅ Successfully registered {len(self.agents)} agents")

    async def demonstrate_service_discovery(self):
        """Demonstrate various service discovery patterns."""
        print("\n🔍 Step 3: Demonstrating Service Discovery")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # 1. Discover all agents
            print("🔍 Discovering all agents:")
            async with session.get(f"{self.registry_url}/agents") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} total agents")
                    for agent in data["agents"]:
                        print(
                            f"   • {agent['name']} ({agent['id']}) - {agent['status']}"
                        )

            # 2. Discover by namespace
            print("\\n🏷️  Discovering agents in 'system' namespace:")
            async with session.get(
                f"{self.registry_url}/agents?namespace=system"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} system agents")
                    for agent in data["agents"]:
                        print(f"   • {agent['name']} - {agent['namespace']}")

            # 3. Discover by capability category
            print("\\n⚙️  Discovering agents with file operations:")
            async with session.get(
                f"{self.registry_url}/agents?capability_category=file_operations"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} file operation agents")
                    for agent in data["agents"]:
                        caps = [
                            cap["name"]
                            for cap in agent["capabilities"]
                            if cap["category"] == "file_operations"
                        ]
                        print(f"   • {agent['name']}: {', '.join(caps)}")

            # 4. Discover by labels
            print("\\n🏷️  Discovering agents in demo environment:")
            async with session.get(
                f"{self.registry_url}/agents?label_selector=env=demo"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} demo agents")
                    for agent in data["agents"]:
                        print(
                            f"   • {agent['name']} - Team: {agent['labels'].get('team', 'N/A')}"
                        )

            # 5. Fuzzy capability matching
            print("\\n🔍 Fuzzy search for 'command' capabilities:")
            async with session.get(
                f"{self.registry_url}/agents?capability=command&fuzzy_match=true"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(
                        f"   📊 Found {data['count']} agents with command-like capabilities"
                    )
                    for agent in data["agents"]:
                        matching_caps = [
                            cap["name"]
                            for cap in agent["capabilities"]
                            if "command" in cap["name"].lower()
                        ]
                        if matching_caps:
                            print(f"   • {agent['name']}: {', '.join(matching_caps)}")

    async def demonstrate_capability_search(self):
        """Demonstrate advanced capability search functionality."""
        print("\\n🔧 Step 4: Demonstrating Capability Search")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # 1. Search by capability category
            print("🔍 Searching capabilities by category:")
            for category in [
                "file_operations",
                "development",
                "system_operations",
                "security",
            ]:
                async with session.get(
                    f"{self.registry_url}/capabilities?category={category}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"   📊 {category}: {data['count']} capabilities")

            # 2. Search by stability level
            print("\\n⚖️  Searching by stability level:")
            for stability in ["stable", "beta", "experimental"]:
                async with session.get(
                    f"{self.registry_url}/capabilities?stability={stability}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"   📊 {stability}: {data['count']} capabilities")

            # 3. Search by tags
            print("\\n🏷️  Searching capabilities with 'security' tag:")
            async with session.get(
                f"{self.registry_url}/capabilities?tags=security"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} security-related capabilities")
                    for cap in data["capabilities"][:5]:  # Show first 5
                        print(
                            f"   • {cap['name']} ({cap['agent_name']}) - {cap['description']}"
                        )

            # 4. Fuzzy search by name
            print("\\n🔍 Fuzzy search for capabilities containing 'file':")
            async with session.get(
                f"{self.registry_url}/capabilities?name=file&fuzzy_match=true"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} file-related capabilities")
                    for cap in data["capabilities"]:
                        print(f"   • {cap['name']} - {cap['description']}")

            # 5. Search by description content
            print("\\n📝 Searching capabilities by description content:")
            async with session.get(
                f"{self.registry_url}/capabilities?description_contains=monitor"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(
                        f"   📊 Found {data['count']} monitoring-related capabilities"
                    )
                    for cap in data["capabilities"]:
                        print(f"   • {cap['name']} - {cap['description']}")

    async def demonstrate_heartbeat_workflows(self):
        """Demonstrate agent heartbeat workflows."""
        print("\\n💓 Step 5: Demonstrating Heartbeat Workflows")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # Send heartbeats for all registered agents
            print("💓 Sending heartbeats for all agents:")
            for agent in self.agents:
                async with session.post(
                    f"{self.registry_url}/heartbeat",
                    json={"agent_id": agent["id"], "status": "healthy"},
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        print(f"   ✅ {agent['name']}: {result['message']}")
                    else:
                        print(
                            f"   ❌ {agent['name']}: Heartbeat failed ({resp.status})"
                        )

            # Wait a moment then check agent health
            await asyncio.sleep(1)

            print("\\n🏥 Checking individual agent health:")
            for agent in self.agents:
                async with session.get(
                    f"{self.registry_url}/health/{agent['id']}"
                ) as resp:
                    if resp.status == 200:
                        health = await resp.json()
                        print(f"   📊 {agent['name']}:")
                        print(f"      Status: {health['status']}")
                        print(f"      Last heartbeat: {health['last_heartbeat']}")
                        print(
                            f"      Time since heartbeat: {health['time_since_heartbeat']:.2f}s"
                        )
                        print(
                            f"      Timeout threshold: {health['timeout_threshold']}s"
                        )
                    else:
                        print(f"   ❌ {agent['name']}: Health check failed")

    async def monitor_health_and_metrics(self):
        """Monitor registry health and metrics."""
        print("\\n📊 Step 6: Monitoring Health and Metrics")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # Get registry metrics
            print("📊 Registry Metrics:")
            async with session.get(f"{self.registry_url}/metrics") as resp:
                if resp.status == 200:
                    metrics = await resp.json()
                    print(f"   📈 Total Agents: {metrics['total_agents']}")
                    print(f"   💚 Healthy Agents: {metrics['healthy_agents']}")
                    print(f"   🟡 Degraded Agents: {metrics['degraded_agents']}")
                    print(f"   🔴 Expired Agents: {metrics['expired_agents']}")
                    print(f"   📱 Total Capabilities: {metrics['total_capabilities']}")
                    print(
                        f"   🔧 Unique Capability Types: {metrics['unique_capability_types']}"
                    )
                    print(f"   ⏰ Uptime: {metrics['uptime_seconds']:.0f} seconds")
                    print(
                        f"   💓 Heartbeats Processed: {metrics['heartbeats_processed']}"
                    )
                    print(
                        f"   📝 Registrations Processed: {metrics['registrations_processed']}"
                    )

            # Show agent status distribution
            print("\\n📊 Agent Status Distribution:")
            async with session.get(f"{self.registry_url}/agents") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status_counts = {}
                    for agent in data["agents"]:
                        status = agent["status"]
                        status_counts[status] = status_counts.get(status, 0) + 1

                    for status, count in status_counts.items():
                        print(f"   {status}: {count} agents")

            # Sample Prometheus metrics
            print("\\n📊 Sample Prometheus Metrics:")
            async with session.get(f"{self.registry_url}/metrics/prometheus") as resp:
                if resp.status == 200:
                    prometheus_data = await resp.text()
                    lines = prometheus_data.split("\\n")
                    for line in lines[:15]:  # Show first 15 lines
                        if line.strip() and not line.startswith("#"):
                            print(f"   {line}")
                    print("   ... (truncated)")

    async def test_version_constraints(self):
        """Test version constraint filtering."""
        print("\\n🔢 Step 7: Testing Version Constraints")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            version_tests = [
                (">=2.0.0", "Should match Command Agent v2.1.0"),
                (">=1.0.0", "Should match all agents"),
                ("~1.5.0", "Should match Developer Agent v1.5.2"),
                ("^1.0.0", "Should match File and Developer agents"),
                ("<2.0.0", "Should match File and Developer agents"),
            ]

            for constraint, description in version_tests:
                print(f"🔍 Testing constraint '{constraint}': {description}")

                # URL encode the constraint
                import urllib.parse

                encoded_constraint = urllib.parse.quote(constraint)

                async with session.get(
                    f"{self.registry_url}/agents?version_constraint={encoded_constraint}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"   📊 Found {data['count']} matching agents:")
                        for agent in data["agents"]:
                            versions = list(
                                set(cap["version"] for cap in agent["capabilities"])
                            )
                            print(f"      • {agent['name']}: versions {versions}")
                    else:
                        print(f"   ❌ Query failed: {resp.status}")

    async def demonstrate_graceful_degradation(self):
        """Demonstrate graceful degradation scenarios."""
        print("\\n🛡️  Step 8: Demonstrating Graceful Degradation")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # Test with non-existent agent
            print("🔍 Testing heartbeat with non-existent agent:")
            async with session.post(
                f"{self.registry_url}/heartbeat",
                json={"agent_id": "non-existent-agent"},
            ) as resp:
                print(f"   📊 Response status: {resp.status}")
                if resp.status != 200:
                    print("   ✅ Correctly rejected non-existent agent")

            # Test health check for non-existent agent
            print("\\n🏥 Testing health check for non-existent agent:")
            async with session.get(
                f"{self.registry_url}/health/non-existent-agent"
            ) as resp:
                print(f"   📊 Response status: {resp.status}")
                if resp.status == 404:
                    print("   ✅ Correctly returned 404 for non-existent agent")

            # Test invalid query parameters
            print("\\n🔍 Testing invalid query parameters:")
            async with session.get(
                f"{self.registry_url}/agents?invalid_param=test"
            ) as resp:
                print(f"   📊 Response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(
                        f"   ✅ Gracefully ignored invalid parameters, returned {data['count']} agents"
                    )

            # Test malformed label selector
            print("\\n🏷️  Testing malformed label selector:")
            async with session.get(
                f"{self.registry_url}/agents?label_selector=invalid-format"
            ) as resp:
                print(f"   📊 Response status: {resp.status}")
                if resp.status == 400:
                    print("   ✅ Correctly rejected malformed label selector")

    async def demonstrate_advanced_filtering(self):
        """Demonstrate advanced filtering capabilities."""
        print("\\n🎯 Step 9: Demonstrating Advanced Filtering")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            # Complex multi-criteria filtering
            print(
                "🔍 Complex filtering: Demo environment + High criticality + Stable capabilities:"
            )
            async with session.get(
                f"{self.registry_url}/capabilities",
                params={
                    "agent_namespace": "system",
                    "stability": "stable",
                    "agent_status": "healthy",
                    "include_deprecated": "false",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} matching capabilities")

                    # Group by agent
                    agents_caps = {}
                    for cap in data["capabilities"]:
                        agent_name = cap["agent_name"]
                        if agent_name not in agents_caps:
                            agents_caps[agent_name] = []
                        agents_caps[agent_name].append(cap["name"])

                    for agent_name, caps in agents_caps.items():
                        print(f"   • {agent_name}: {', '.join(caps)}")

            # Capability filtering with multiple tags
            print("\\n🏷️  Filtering capabilities with multiple tags (security + audit):")
            async with session.get(
                f"{self.registry_url}/capabilities?tags=security,audit"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} security & audit capabilities")
                    for cap in data["capabilities"]:
                        print(
                            f"   • {cap['name']} ({cap['agent_name']}) - Tags: {cap['tags']}"
                        )

            # Agent filtering by multiple criteria
            print(
                "\\n🎯 Multi-criteria agent filtering (system namespace + demo env + high criticality):"
            )
            async with session.get(
                f"{self.registry_url}/agents",
                params={
                    "namespace": "system",
                    "label_selector": "env=demo,criticality=high",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   📊 Found {data['count']} matching agents")
                    for agent in data["agents"]:
                        print(
                            f"   • {agent['name']} - Criticality: {agent['labels'].get('criticality')}"
                        )

    async def cleanup_agents(self):
        """Clean up registered agents."""
        print("\\n🧹 Step 10: Cleaning Up Agents")
        print("-" * 40)

        async with aiohttp.ClientSession() as session:
            for agent in self.agents:
                print(f"🗑️  Unregistering: {agent['name']}")
                async with session.post(
                    f"{self.registry_url}/mcp/tools/unregister_agent",
                    json={"agent_id": agent["id"]},
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result["status"] == "success":
                            print(f"   ✅ Unregistered: {agent['id']}")
                        else:
                            print(
                                f"   ❌ Unregistration failed: {result.get('message')}"
                            )
                    else:
                        print(f"   ❌ HTTP Error: {resp.status}")

            # Verify cleanup
            print("\\n🔍 Verifying cleanup:")
            async with session.get(f"{self.registry_url}/agents") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    remaining_demo_agents = [
                        agent
                        for agent in data["agents"]
                        if agent["id"].startswith("demo-")
                    ]
                    print(f"   📊 Remaining demo agents: {len(remaining_demo_agents)}")
                    if len(remaining_demo_agents) == 0:
                        print("   ✅ All demo agents successfully cleaned up")


async def main():
    """Main entry point for the demo."""
    print("MCP Mesh Registry - Complete Workflow Demo")
    print("==========================================")
    print()
    print("This demo showcases the complete workflow of the MCP Mesh Registry Service")
    print(
        "including agent registration, service discovery, health monitoring, and more."
    )
    print()
    print("Prerequisites:")
    print("1. Start the registry service: python -m mcp_mesh.server")
    print("2. Ensure the registry is running on http://localhost:8000")
    print()

    # Wait for user confirmation
    input("Press Enter to start the demo (or Ctrl+C to cancel)...")
    print()

    demo = RegistryWorkflowDemo()

    try:
        await demo.run_complete_workflow()
    except KeyboardInterrupt:
        print("\\n🛑 Demo interrupted by user")
    except Exception as e:
        print(f"\\n❌ Demo failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
