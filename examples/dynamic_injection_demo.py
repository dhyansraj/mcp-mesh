#!/usr/bin/env python3
"""
Demo: Dynamic Dependency Injection with Topology Changes

This example shows how MCP Mesh handles:
1. Initial dependency injection
2. Services coming online/offline
3. Service updates (e.g., version changes)
4. Graceful degradation
"""

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

# Use the new consolidated package
from mcp_mesh import mesh_agent

# Import the injector for demo purposes
from mcp_mesh.runtime.dependency_injector import get_global_injector


# Mock services that can appear/disappear
class DatabaseService:
    def __init__(self, host: str, version: str):
        self.host = host
        self.version = version
        self.connected = True

    def query(self, sql: str) -> dict:
        if not self.connected:
            raise Exception("Database disconnected")
        return {
            "host": self.host,
            "version": self.version,
            "result": f"Results for: {sql}",
            "rows": 42,
        }


class CacheService:
    def __init__(self, backend: str):
        self.backend = backend
        self._data = {}

    def get(self, key: str) -> Any:
        return self._data.get(key, f"No cached value for {key}")

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._data[key] = value


class MetricsService:
    def __init__(self):
        self._metrics = {}

    def increment(self, metric: str, value: int = 1) -> None:
        self._metrics[metric] = self._metrics.get(metric, 0) + value

    def get_metrics(self) -> dict:
        return self._metrics.copy()


# Create the server
server = FastMCP(name="dynamic-injection-demo")


# Define functions that use these services
@mesh_agent(
    capability="data_api",
    dependencies=["Database", "Cache", "Metrics"],
    version="1.0.0",
)
@server.tool()
def fetch_user_data(
    user_id: int,
    use_cache: bool = True,
    Database: Any = None,
    Cache: Any = None,
    Metrics: Any = None,
) -> dict:
    """
    Fetch user data with caching and metrics.

    This function gracefully handles missing dependencies.
    """
    result = {"user_id": user_id, "source": "unknown", "data": None}

    # Track metrics if available
    if Metrics:
        Metrics.increment("api.fetch_user_data.calls")

    # Try cache first if requested and available
    cache_key = f"user:{user_id}"
    if use_cache and Cache:
        cached = Cache.get(cache_key)
        if isinstance(cached, str) and cached.startswith("No cached"):
            # Cache miss - continue to database
            pass
        else:
            # Cache hit
            result["source"] = "cache"
            result["data"] = cached
            if Metrics:
                Metrics.increment("api.fetch_user_data.cache_hits")
            return result

    # Fall back to database if available
    if Database:
        try:
            db_result = Database.query(f"SELECT * FROM users WHERE id = {user_id}")
            result["source"] = f"database ({Database.host} v{Database.version})"
            result["data"] = db_result

            # Update cache if available
            if Cache and use_cache:
                Cache.set(cache_key, db_result)

            if Metrics:
                Metrics.increment("api.fetch_user_data.db_queries")

            return result
        except Exception as e:
            result["error"] = str(e)

    # No dependencies available
    result["source"] = "none"
    result["error"] = "No data sources available"
    return result


@mesh_agent(capability="health_check", dependencies=["Database", "Cache", "Metrics"])
@server.tool()
def system_health(Database: Any = None, Cache: Any = None, Metrics: Any = None) -> dict:
    """Check health of all system components."""
    health = {"status": "healthy", "components": {}}

    # Check database
    if Database:
        try:
            Database.query("SELECT 1")
            health["components"]["database"] = {
                "status": "up",
                "host": Database.host,
                "version": Database.version,
            }
        except Exception:
            health["components"]["database"] = {"status": "down"}
            health["status"] = "degraded"
    else:
        health["components"]["database"] = {"status": "not_available"}
        health["status"] = "degraded"

    # Check cache
    if Cache:
        health["components"]["cache"] = {"status": "up", "backend": Cache.backend}
    else:
        health["components"]["cache"] = {"status": "not_available"}

    # Check metrics
    if Metrics:
        health["components"]["metrics"] = {
            "status": "up",
            "stats": Metrics.get_metrics(),
        }
    else:
        health["components"]["metrics"] = {"status": "not_available"}

    return health


async def simulate_topology_changes():
    """Simulate a realistic scenario of services coming and going."""

    print("🚀 Dynamic Dependency Injection Demo")
    print("=" * 50)

    injector = get_global_injector()

    # Phase 1: No services available
    print("\n📍 Phase 1: System starting (no services)")
    result = await server.call_tool("system_health", {})
    print(f"Health: {result[0].text}")

    result = await server.call_tool("fetch_user_data", {"user_id": 123})
    print(f"Fetch user 123: {result[0].text}")

    # Phase 2: Database comes online
    print("\n📍 Phase 2: Database service starts")
    db_primary = DatabaseService("db-primary.local", "1.0")
    await injector.register_dependency("Database", db_primary)
    await asyncio.sleep(0.1)

    result = await server.call_tool("system_health", {})
    print(f"Health: {result[0].text}")

    result = await server.call_tool("fetch_user_data", {"user_id": 123})
    print(f"Fetch user 123: {result[0].text}")

    # Phase 3: Cache comes online
    print("\n📍 Phase 3: Cache service starts")
    cache = CacheService("Redis")
    await injector.register_dependency("Cache", cache)
    await asyncio.sleep(0.1)

    # First call hits database
    result = await server.call_tool("fetch_user_data", {"user_id": 456})
    print(f"Fetch user 456 (first call): {result[0].text}")

    # Second call hits cache
    result = await server.call_tool("fetch_user_data", {"user_id": 456})
    print(f"Fetch user 456 (cached): {result[0].text}")

    # Phase 4: Metrics service starts
    print("\n📍 Phase 4: Metrics service starts")
    metrics = MetricsService()
    await injector.register_dependency("Metrics", metrics)
    await asyncio.sleep(0.1)

    # Make some calls to generate metrics
    for user_id in [789, 456, 999]:
        await server.call_tool("fetch_user_data", {"user_id": user_id})

    result = await server.call_tool("system_health", {})
    print(f"Health with metrics: {result[0].text}")

    # Phase 5: Database failover
    print("\n📍 Phase 5: Database failover to secondary")
    db_secondary = DatabaseService("db-secondary.local", "1.0")
    await injector.register_dependency("Database", db_secondary)
    await asyncio.sleep(0.1)

    result = await server.call_tool(
        "fetch_user_data", {"user_id": 111, "use_cache": False}
    )
    print(f"Fetch user 111 (from secondary): {result[0].text}")

    # Phase 6: Database upgrade
    print("\n📍 Phase 6: Database upgraded to v2.0")
    db_v2 = DatabaseService("db-primary.local", "2.0")
    await injector.register_dependency("Database", db_v2)
    await asyncio.sleep(0.1)

    result = await server.call_tool(
        "fetch_user_data", {"user_id": 222, "use_cache": False}
    )
    print(f"Fetch user 222 (from v2.0): {result[0].text}")

    # Phase 7: Services go down
    print("\n📍 Phase 7: Services shutting down")
    await injector.unregister_dependency("Database")
    await injector.unregister_dependency("Cache")
    await asyncio.sleep(0.1)

    result = await server.call_tool("system_health", {})
    print(f"Health (degraded): {result[0].text}")

    result = await server.call_tool("fetch_user_data", {"user_id": 333})
    print(f"Fetch user 333 (no services): {result[0].text}")

    print("\n✅ Demo complete! The function adapted to all topology changes.")


def main():
    """Run the demo or start as a server."""
    # Suppress runtime messages for cleaner demo
    import logging
    import sys

    logging.getLogger("mcp_mesh").setLevel(logging.WARNING)

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        # Run the demo
        asyncio.run(simulate_topology_changes())
    else:
        # Start as MCP server
        print("Starting Dynamic Injection Demo Server...")
        print("Functions available:")
        print("  - fetch_user_data: Fetches user data with caching")
        print("  - system_health: Reports health of all components")
        print("\nRun with 'demo' argument to see topology simulation")
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
