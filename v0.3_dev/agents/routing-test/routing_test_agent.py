#!/usr/bin/env python3
"""
Routing Test Agent - For testing Phase 3 routing intelligence.

This agent provides capabilities with specific routing flags to test the
routing intelligence logging functionality.
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Routing Test Agent")

pod_ip = os.getenv("POD_IP", "localhost")


@app.tool()
@mesh.tool(
    capability="session_test",
    session_required=True,
    stateful=True,
    priority="high",
    description="Test capability with session affinity and stateful requirements",
)
def session_test(session_id: str = None) -> dict:
    """Test function that requires session affinity."""
    return {
        "test": "value",
        "session_id": session_id,
        "pod_ip": pod_ip,
        "routing_flags": {"session_required": True, "stateful": True},
        "custom_metadata": {"priority": "high"},
    }


@app.tool()
@mesh.tool(
    capability="full_mcp_test",
    full_mcp_access=True,
    streaming=True,
    complexity="medium",
    description="Test capability requiring full MCP access and streaming",
)
def full_mcp_test() -> dict:
    """Test function that requires full MCP access."""
    return {
        "test": "full_mcp_value",
        "pod_ip": pod_ip,
        "routing_flags": {"full_mcp_access": True, "streaming": True},
        "custom_metadata": {"complexity": "medium"},
    }


@app.tool()
@mesh.tool(
    capability="streaming_test",
    streaming=True,
    stateful=False,
    batch_size=100,
    description="Test capability with streaming support",
)
def streaming_test() -> dict:
    """Test function with streaming capability."""
    return {
        "test": "streaming_value",
        "pod_ip": pod_ip,
        "routing_flags": {"streaming": True, "stateful": False},
        "custom_metadata": {"batch_size": 100},
    }


@app.tool()
@mesh.tool(
    capability="complex_routing_test",
    session_required=True,
    stateful=True,
    full_mcp_access=True,
    streaming=True,
    priority="critical",
    timeout=30,
    description="Test capability with all routing flags enabled",
)
def complex_routing_test(session_id: str = None) -> dict:
    """Test function with all routing flags."""
    return {
        "test": "complex_value",
        "session_id": session_id,
        "pod_ip": pod_ip,
        "routing_flags": {
            "session_required": True,
            "stateful": True,
            "full_mcp_access": True,
            "streaming": True,
        },
        "custom_metadata": {"priority": "critical", "timeout": 30},
    }


# Simple capability for comparison
@app.tool()
@mesh.tool(
    capability="simple_test",
    description="Simple test capability with no special routing requirements",
)
def simple_test() -> dict:
    """Simple test function with no routing flags."""
    return {
        "test": "simple_value",
        "pod_ip": pod_ip,
        "routing_flags": {
            "session_required": False,
            "stateful": False,
            "full_mcp_access": False,
            "streaming": False,
        },
        "custom_metadata": {},
    }


# Health check
@app.tool()
@mesh.tool(
    capability="routing_test_health", description="Health check for routing test agent"
)
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "routing_test_agent",
        "test_capabilities": [
            "session_test (session_required=True, stateful=True)",
            "full_mcp_test (full_mcp_access=True, streaming=True)",
            "streaming_test (streaming=True)",
            "complex_routing_test (all flags=True)",
            "simple_test (no routing flags)",
        ],
    }


if __name__ == "__main__":
    print(f"🧪 Starting Routing Test Agent on pod {pod_ip}")
    print("🎯 Routing test capabilities:")
    print("  - session_test (session_required=True, stateful=True, priority=high)")
    print("  - full_mcp_test (full_mcp_access=True, streaming=True, complexity=medium)")
    print("  - streaming_test (streaming=True, batch_size=100)")
    print("  - complex_routing_test (all flags=True, priority=critical)")
    print("  - simple_test (no routing flags)")

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
