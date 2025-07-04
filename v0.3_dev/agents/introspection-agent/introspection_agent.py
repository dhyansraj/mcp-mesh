#!/usr/bin/env python3
"""
Introspection Agent - For testing full MCP protocol access.

This agent provides capabilities that require full MCP protocol access:
- Agent introspection (tools/list, resources/list, prompts/list)
- Dynamic capability discovery
- Agent network mapping

Used for testing Phases 2, 6 of the progressive implementation.
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Introspection Agent")

pod_ip = os.getenv("POD_IP", "localhost")


@app.tool()
@mesh.tool(
    capability="agent_introspector",
    full_mcp_access=True,
    description="Introspect remote agent capabilities using full MCP protocol",
)
def introspect_agent(target_agent: str = None) -> dict:
    """
    Introspect a target agent's capabilities using full MCP protocol.

    This function demonstrates full MCP access by calling:
    - tools/list to get available tools
    - resources/list to get available resources
    - prompts/list to get available prompts
    """
    result = {
        "introspector_pod": pod_ip,
        "target_agent": target_agent,
        "full_mcp_access": True,
    }

    if target_agent:
        # In a real implementation, this would use the injected agent proxy
        # to call target_agent.list_tools(), target_agent.list_resources(), etc.
        result.update(
            {
                "tools_available": "Would call target_agent.list_tools()",
                "resources_available": "Would call target_agent.list_resources()",
                "prompts_available": "Would call target_agent.list_prompts()",
                "mcp_methods_used": ["tools/list", "resources/list", "prompts/list"],
            }
        )
    else:
        result["error"] = "No target agent specified"

    return result


@app.tool()
@mesh.tool(
    capability="network_mapper",
    full_mcp_access=True,
    description="Map the agent network using MCP protocol",
)
def map_agent_network() -> dict:
    """
    Map the entire agent network by discovering all agents and their capabilities.

    This would use the registry to find all agents, then use full MCP protocol
    to introspect each agent's capabilities.
    """
    return {
        "mapper_pod": pod_ip,
        "network_map": {
            "discovered_agents": "Would query registry for all agents",
            "capability_matrix": "Would introspect each agent using MCP protocol",
            "dependency_graph": "Would build agent dependency relationships",
        },
        "mcp_methods_used": ["tools/list", "resources/list", "prompts/list"],
        "full_mcp_access": True,
    }


@app.tool()
@mesh.tool(
    capability="capability_discoverer",
    full_mcp_access=True,
    description="Dynamically discover new capabilities as they come online",
)
def discover_capabilities(agent_pattern: str = "*") -> dict:
    """
    Discover capabilities matching a pattern across all agents.

    Uses full MCP protocol to query all agents matching the pattern.
    """
    return {
        "discoverer_pod": pod_ip,
        "search_pattern": agent_pattern,
        "discovery_results": {
            "matching_agents": "Would search registry for pattern",
            "capabilities_found": "Would use MCP protocol to list capabilities",
            "new_capabilities": "Would compare with known capabilities",
        },
        "mcp_methods_used": ["tools/list"],
        "full_mcp_access": True,
    }


# Regular capabilities (no full MCP access required)
@app.tool()
@mesh.tool(
    capability="simple_info",
    description="Simple info endpoint that doesn't need full MCP access",
)
def get_agent_info() -> dict:
    """Get basic agent information."""
    return {
        "agent_type": "introspection_agent",
        "pod_ip": pod_ip,
        "capabilities": [
            "agent_introspector (full_mcp_access=True)",
            "network_mapper (full_mcp_access=True)",
            "capability_discoverer (full_mcp_access=True)",
            "simple_info (standard capability)",
        ],
        "full_mcp_access": False,  # This particular capability doesn't need it
    }


# Health check
@app.tool()
@mesh.tool(
    capability="introspection_health",
    description="Health check for introspection agent",
)
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "introspection_agent",
        "full_mcp_capabilities": [
            "agent_introspector",
            "network_mapper",
            "capability_discoverer",
        ],
    }


if __name__ == "__main__":
    print(f"🔍 Starting Introspection Agent on pod {pod_ip}")
    print("🔓 Full MCP access capabilities:")
    print("  - agent_introspector (full_mcp_access=True)")
    print("  - network_mapper (full_mcp_access=True)")
    print("  - capability_discoverer (full_mcp_access=True)")
    print("📊 Standard capabilities:")
    print("  - simple_info")

    # Don't call app.run() - MCP Mesh runtime handles server startup
    print("🚀 MCP Mesh runtime will handle server startup")

    # Keep the script running
    import signal
    import sys

    def signal_handler(sig, frame):
        print("🛑 Graceful shutdown")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait indefinitely - MCP Mesh runtime runs the server
    signal.pause()
