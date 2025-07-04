#!/usr/bin/env python3
"""
Cache Agent - Distributed cache service for MCP Mesh.

This agent provides distributed caching capabilities:
- Redis-backed key-value storage
- TTL support for automatic expiration
- High-performance caching operations

Used for testing Phase 7 auto-dependency injection.
"""

import os

import redis
from _mcp_mesh import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Cache Agent")

pod_ip = os.getenv("POD_IP", "localhost")
redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

# Initialize Redis connection
try:
    redis_client = redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
    redis_available = True
    print(f"✅ Connected to Redis: {redis_url}")
except Exception as e:
    redis_available = False
    print(f"❌ Redis connection failed: {e}")


@app.tool()
@mesh.tool(
    capability="redis_cache", description="Distributed Redis cache for MCP Mesh system"
)
def set(key: str, value: str, ttl: int = 3600) -> dict:
    """Set a key-value pair in the distributed cache with TTL."""
    if not redis_available:
        return {"error": "Redis not available", "pod_ip": pod_ip, "operation": "set"}

    try:
        redis_client.setex(key, ttl, value)
        return {
            "success": True,
            "key": key,
            "ttl": ttl,
            "pod_ip": pod_ip,
            "operation": "set",
        }
    except Exception as e:
        return {"error": str(e), "pod_ip": pod_ip, "operation": "set"}


@app.tool()
@mesh.tool(capability="redis_cache", description="Get value from distributed cache")
def get(key: str) -> dict:
    """Get a value from the distributed cache."""
    if not redis_available:
        return {"error": "Redis not available", "pod_ip": pod_ip, "operation": "get"}

    try:
        value = redis_client.get(key)
        return {
            "success": True,
            "key": key,
            "value": value,
            "found": value is not None,
            "pod_ip": pod_ip,
            "operation": "get",
        }
    except Exception as e:
        return {"error": str(e), "pod_ip": pod_ip, "operation": "get"}


@app.tool()
@mesh.tool(capability="redis_cache", description="Delete key from distributed cache")
def delete(key: str) -> dict:
    """Delete a key from the distributed cache."""
    if not redis_available:
        return {"error": "Redis not available", "pod_ip": pod_ip, "operation": "delete"}

    try:
        deleted = redis_client.delete(key)
        return {
            "success": True,
            "key": key,
            "deleted": bool(deleted),
            "pod_ip": pod_ip,
            "operation": "delete",
        }
    except Exception as e:
        return {"error": str(e), "pod_ip": pod_ip, "operation": "delete"}


@app.tool()
@mesh.tool(capability="redis_cache", description="Get cache statistics")
def stats() -> dict:
    """Get cache statistics and health information."""
    if not redis_available:
        return {
            "error": "Redis not available",
            "pod_ip": pod_ip,
            "redis_available": False,
        }

    try:
        info = redis_client.info()
        return {
            "success": True,
            "pod_ip": pod_ip,
            "redis_available": True,
            "redis_version": info.get("redis_version"),
            "connected_clients": info.get("connected_clients"),
            "used_memory": info.get("used_memory"),
            "used_memory_human": info.get("used_memory_human"),
            "total_commands_processed": info.get("total_commands_processed"),
        }
    except Exception as e:
        return {"error": str(e), "pod_ip": pod_ip, "redis_available": False}


# Health check
@app.tool()
@mesh.tool(capability="cache_health", description="Health check for cache agent")
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "cache_agent",
        "redis_available": redis_available,
        "redis_url": redis_url,
        "capabilities": ["redis_cache"],
    }


if __name__ == "__main__":
    print(f"💾 Starting Cache Agent on pod {pod_ip}")
    print(f"🔗 Redis URL: {redis_url}")
    print("📊 Cache capabilities:")
    print("  - redis_cache (set, get, delete, stats)")

    if redis_available:
        print("✅ Redis connection: OK")
    else:
        print("❌ Redis connection: FAILED")

    app.run(host="0.0.0.0", port=8080)
