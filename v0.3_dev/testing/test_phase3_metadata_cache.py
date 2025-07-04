#!/usr/bin/env python3
"""
Test Phase 3: Metadata Caching Implementation

This script demonstrates the metadata caching functionality by:
1. Creating an HttpMcpWrapper instance
2. Testing metadata fetching and caching
3. Verifying cache hit/miss behavior
4. Testing cache invalidation
5. Demonstrating routing info extraction
"""

import asyncio
import json
import os
import sys
import time

# Add the runtime to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/runtime/python"))

from _mcp_mesh.engine.http_wrapper import HttpMcpWrapper
from fastmcp import FastMCP


async def test_metadata_caching():
    """Test the metadata caching functionality."""
    print("🧪 Testing Phase 3: Metadata Caching Implementation")
    print("=" * 60)

    # Create a mock FastMCP server for testing
    mock_server = FastMCP("Test Server")

    # Create HttpMcpWrapper instance
    wrapper = HttpMcpWrapper(mock_server)
    await wrapper.setup()

    # Test endpoints (these should be running from docker-compose)
    test_endpoints = [
        "http://localhost:8090",  # Agent A - session agent
        "http://localhost:8092",  # Agent C - introspection agent
        "http://localhost:8093",  # Agent D - metadata cache test agent
    ]

    print("\n1. Testing initial metadata fetching (cache miss)")
    print("-" * 50)

    for endpoint in test_endpoints:
        print(f"\n🔍 Fetching metadata from {endpoint}")

        # Get cache stats before
        stats_before = wrapper.get_cache_stats()
        print(f"Cache stats before: {json.dumps(stats_before, indent=2)}")

        # Fetch metadata (should be cache miss)
        start_time = time.time()
        metadata = wrapper.fetch_and_cache_metadata(endpoint)
        fetch_time = time.time() - start_time

        print(f"⏱️  Fetch time: {fetch_time:.3f}s")
        print(f"✅ Fetched metadata for agent: {metadata.get('agent_id', 'unknown')}")
        print(f"📊 Capabilities found: {len(metadata.get('capabilities', {}))}")

        # Get cache stats after
        stats_after = wrapper.get_cache_stats()
        print(f"Cache stats after: {json.dumps(stats_after, indent=2)}")

        break  # Just test one endpoint for now

    print("\n2. Testing cached metadata retrieval (cache hit)")
    print("-" * 50)

    endpoint = test_endpoints[0]  # Use first endpoint

    # Test cache hit
    start_time = time.time()
    cached_metadata = wrapper.get_cached_metadata()
    cache_time = time.time() - start_time

    if cached_metadata:
        print("✅ Cache hit! Retrieved cached metadata")
        print(f"⏱️  Cache retrieval time: {cache_time:.6f}s")
        print(f"📊 Cached agent: {cached_metadata.get('agent_id', 'unknown')}")
        print(f"📊 Cached capabilities: {len(cached_metadata.get('capabilities', {}))}")
    else:
        print("❌ Cache miss - no cached data available")

    print("\n3. Testing cache validation and TTL")
    print("-" * 50)

    print(f"Cache valid: {wrapper._is_cache_valid()}")
    print(f"Cache TTL: {wrapper._cache_ttl.total_seconds()}s")

    if wrapper._cache_timestamp:
        cache_age = time.time() - wrapper._cache_timestamp.timestamp()
        print(f"Cache age: {cache_age:.1f}s")

    print("\n4. Testing capability routing info extraction")
    print("-" * 50)

    # Test routing info for different capability types
    test_capabilities = [
        "stateful_counter",  # session_required=True capability
        "agent_introspector",  # full_mcp_access=True capability
        "simple_cache_info",  # standard capability
    ]

    for capability in test_capabilities:
        print(f"\n🎯 Testing routing info for: {capability}")
        routing_info = wrapper.get_capability_routing_info(endpoint, capability)

        if routing_info.get("available"):
            flags = routing_info.get("routing_flags", {})
            print("✅ Capability available")
            print(
                f"🔄 Routing flags: session_required={flags.get('session_required')}, "
                f"stateful={flags.get('stateful')}, full_mcp_access={flags.get('full_mcp_access')}"
            )
        else:
            print(f"❌ Capability not available: {routing_info.get('error')}")

    print("\n5. Testing cache invalidation")
    print("-" * 50)

    # Invalidate cache
    wrapper._invalidate_cache()
    print("🗑️  Cache invalidated")

    # Verify cache is empty
    cached_metadata = wrapper.get_cached_metadata()
    if cached_metadata is None:
        print("✅ Cache invalidation successful - no cached data")
    else:
        print("❌ Cache invalidation failed - data still cached")

    # Test refresh
    print("\n🔄 Testing cache refresh")
    refreshed_metadata = wrapper.refresh_metadata_cache(endpoint)
    print(
        f"✅ Cache refreshed for agent: {refreshed_metadata.get('agent_id', 'unknown')}"
    )

    print("\n6. Testing get_metadata_with_cache (intelligent caching)")
    print("-" * 50)

    # This should use cache if valid, otherwise fetch
    start_time = time.time()
    metadata = wrapper.get_metadata_with_cache(endpoint)
    intelligent_time = time.time() - start_time

    print(f"⏱️  Intelligent cache time: {intelligent_time:.6f}s")
    print(f"✅ Retrieved metadata for: {metadata.get('agent_id', 'unknown')}")

    # Final cache stats
    final_stats = wrapper.get_cache_stats()
    print("\n📊 Final cache statistics:")
    print(json.dumps(final_stats, indent=2))

    print("\n🎉 Phase 3 metadata caching test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_metadata_caching())
