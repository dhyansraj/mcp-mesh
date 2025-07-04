#!/usr/bin/env python3
"""
Metadata Cache Test Agent - For testing Phase 3 metadata caching.

This agent provides capabilities for testing metadata caching functionality:
- Test metadata fetching with caching
- Cache invalidation testing
- Cache statistics monitoring
- Routing information extraction

Used for testing Phase 3 of the progressive implementation.
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Metadata Cache Test Agent")

pod_ip = os.getenv("POD_IP", "localhost")


@app.tool()
@mesh.tool(
    capability="metadata_cache_tester",
    description="Test metadata caching functionality with remote agents",
)
def test_metadata_cache(target_endpoint: str = "http://localhost:8090") -> dict:
    """
    Test metadata caching by fetching metadata from a target endpoint.

    This function demonstrates the metadata caching functionality by:
    - Fetching metadata from a remote agent
    - Using cache when available
    - Returning cache statistics
    """
    # In a real implementation, this would use the HttpMcpWrapper's caching methods
    # For testing, we'll simulate the caching behavior

    result = {
        "tester_pod": pod_ip,
        "target_endpoint": target_endpoint,
        "cache_test_results": {
            "cache_hit": "Would check HttpMcpWrapper.get_cached_metadata()",
            "cache_miss": "Would call HttpMcpWrapper.fetch_and_cache_metadata()",
            "cache_stats": "Would call HttpMcpWrapper.get_cache_stats()",
            "cache_invalidation": "Would call HttpMcpWrapper._invalidate_cache()",
        },
        "expected_metadata_structure": {
            "agent_id": "target-agent-id",
            "capabilities": {
                "example_capability": {
                    "function_name": "example_function",
                    "session_required": False,
                    "stateful": False,
                    "full_mcp_access": False,
                }
            },
            "timestamp": "2025-07-03T12:00:00.000Z",
            "status": "healthy",
        },
    }

    return result


@app.tool()
@mesh.tool(
    capability="routing_info_extractor",
    description="Extract routing information for specific capabilities",
)
def extract_routing_info(target_endpoint: str, capability: str) -> dict:
    """
    Extract routing information for a specific capability from target agent.

    This demonstrates how cached metadata can be used for intelligent routing.
    """
    return {
        "tester_pod": pod_ip,
        "target_endpoint": target_endpoint,
        "requested_capability": capability,
        "routing_extraction": {
            "method": "HttpMcpWrapper.get_capability_routing_info()",
            "cache_usage": "Uses cached metadata when available",
            "routing_decision": "Based on session_required, stateful, full_mcp_access flags",
        },
        "expected_routing_info": {
            "available": True,
            "capability": capability,
            "routing_flags": {
                "session_required": False,
                "stateful": False,
                "streaming": False,
                "full_mcp_access": False,
            },
            "function_name": "example_function",
            "description": "Example capability description",
            "version": "1.0.0",
            "agent_id": "target-agent-id",
            "endpoint": target_endpoint,
        },
    }


@app.tool()
@mesh.tool(
    capability="cache_performance_monitor",
    description="Monitor cache performance and statistics",
)
def monitor_cache_performance() -> dict:
    """
    Monitor cache performance and provide statistics.

    This demonstrates cache monitoring and performance tracking.
    """
    return {
        "monitor_pod": pod_ip,
        "cache_monitoring": {
            "cache_hit_rate": "Would track cache hits vs misses",
            "cache_size": "Would track number of cached entries",
            "cache_age": "Would track cache timestamp and TTL",
            "cache_efficiency": "Would measure time saved by caching",
        },
        "cache_statistics": {
            "cache_size": 0,
            "cache_timestamp": None,
            "cache_ttl_seconds": 300,  # 5 minutes
            "cache_valid": False,
            "cache_entries": [],
        },
        "performance_metrics": {
            "avg_cache_fetch_time": "< 1ms",
            "avg_remote_fetch_time": "100-500ms",
            "cache_efficiency_ratio": "100x-500x faster when cached",
        },
    }


@app.tool()
@mesh.tool(
    capability="cache_invalidation_tester",
    description="Test cache invalidation scenarios",
)
def test_cache_invalidation(scenario: str = "manual") -> dict:
    """
    Test different cache invalidation scenarios.

    Scenarios:
    - manual: Manual cache invalidation
    - ttl_expiry: TTL-based cache expiry
    - error_invalidation: Invalidation on fetch errors
    """
    return {
        "tester_pod": pod_ip,
        "invalidation_scenario": scenario,
        "test_results": {
            "manual": {
                "description": "Manual invalidation via refresh_metadata_cache()",
                "expected_behavior": "Cache cleared, fresh fetch on next request",
            },
            "ttl_expiry": {
                "description": "TTL-based expiry after 5 minutes",
                "expected_behavior": "Cache invalid after TTL, fresh fetch triggered",
            },
            "error_invalidation": {
                "description": "Invalidation when remote fetch fails",
                "expected_behavior": "Cache cleared on persistent errors",
            },
        },
        "invalidation_methods": [
            "HttpMcpWrapper._invalidate_cache()",
            "HttpMcpWrapper.refresh_metadata_cache()",
            "Automatic TTL expiry via _is_cache_valid()",
        ],
    }


# Regular capabilities (no special routing required)
@app.tool()
@mesh.tool(
    capability="simple_cache_info", description="Simple cache information endpoint"
)
def get_cache_info() -> dict:
    """Get basic cache information."""
    return {
        "agent_type": "metadata_cache_test_agent",
        "pod_ip": pod_ip,
        "cache_capabilities": [
            "metadata_cache_tester",
            "routing_info_extractor",
            "cache_performance_monitor",
            "cache_invalidation_tester",
        ],
        "cache_features": {
            "ttl_based_expiry": True,
            "manual_invalidation": True,
            "performance_monitoring": True,
            "routing_info_extraction": True,
        },
    }


# Health check
@app.tool()
@mesh.tool(
    capability="cache_test_health",
    description="Health check for metadata cache test agent",
)
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "metadata_cache_test_agent",
        "cache_testing_ready": True,
    }


if __name__ == "__main__":
    print(f"🧪 Starting Metadata Cache Test Agent on pod {pod_ip}")
    print("📋 Cache testing capabilities:")
    print("  - metadata_cache_tester")
    print("  - routing_info_extractor")
    print("  - cache_performance_monitor")
    print("  - cache_invalidation_tester")

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
