"""
Example showing how Python runtime uses registry endpoints.
"""


class ProcessorUsageExample:
    """Shows how the processor uses different registry endpoints."""

    async def startup_flow(self):
        """Initial startup - uses /agents/register"""

        # 1. Collect all tools from decorators
        tools = []
        for func_name, decorated_func in get_all_mesh_agents():
            tools.append(
                {
                    "function_name": func_name,
                    "capability": decorated_func.capability,
                    "version": decorated_func.version,
                    "dependencies": decorated_func.dependencies,
                    # ... all other parameters
                }
            )

        # 2. Single registration call
        response = await registry_client.register_agent(
            agent_id="myservice-abc123",
            metadata={
                "name": "myservice-abc123",
                "endpoint": "http://localhost:8889",
                "tools": tools,
            },
        )

        # 3. Process dependency resolution
        if "dependencies_resolved" in response:
            for tool_name, deps in response["dependencies_resolved"].items():
                # Inject proxies for each tool
                inject_dependencies(tool_name, deps)

    async def heartbeat_flow(self):
        """Regular heartbeat - uses /heartbeat"""

        # Send lightweight heartbeat
        response = await registry_client.send_heartbeat(
            agent_id="myservice-abc123",
            metadata={
                # Only send if endpoint changed
                "endpoint": "http://localhost:8889"
            },
        )

        # Check if dependencies changed
        if "dependencies_resolved" in response:
            # Dependencies changed! Update proxies
            for tool_name, deps in response["dependencies_resolved"].items():
                update_dependencies(tool_name, deps)

    async def recovery_flow(self):
        """After restart/reconnect - uses /agents/{id}"""

        # Get full agent state
        agent_data = await registry_client.get_agent("myservice-abc123")

        if agent_data:
            # Restore all tool dependencies
            for tool in agent_data["tools"]:
                if "dependencies_resolved" in tool:
                    inject_dependencies(tool["name"], tool["dependencies_resolved"])
        else:
            # Agent not found, need to re-register
            await self.startup_flow()

    # CLI/Dashboard would use different endpoints:

    async def cli_discover_flow(self):
        """CLI discovery - uses /capabilities"""

        # Find all greeting services
        providers = await registry_client.search_capabilities(
            capability="greeting", version=">=1.0.0", tags=["production"]
        )

        print("Available greeting services:")
        for provider in providers:
            print(f"- {provider['agent_name']} ({provider['version']})")
            print(f"  Endpoint: {provider['endpoint']}")
            print(f"  Tool: {provider['tool_name']}")

    async def dashboard_monitoring_flow(self):
        """Dashboard monitoring - uses /agents"""

        # List all healthy agents
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{registry_url}/agents?status=healthy") as resp:
                data = await resp.json()

                print(f"Total agents: {data['count']}")
                for agent in data["agents"]:
                    print(f"- {agent['name']}: {agent['tool_count']} tools")
                    print(f"  Last seen: {agent['last_heartbeat']}")


# Summary of endpoint usage:
#
# Python Runtime:
# - /agents/register - Once at startup
# - /heartbeat - Every 30 seconds
# - /agents/{id} - On recovery/reconnect
#
# CLI/Dashboard:
# - /capabilities - Service discovery
# - /agents - Monitoring
# - /health - Health checks
