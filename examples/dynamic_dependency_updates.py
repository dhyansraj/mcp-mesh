#!/usr/bin/env python3
"""
Dynamic Dependency Updates Example

This example demonstrates how MCP Mesh can dynamically update dependencies
when better providers become available or when services change.

Key Features:
1. Dependencies are re-evaluated during heartbeats
2. Functions receive updated dependencies without restart
3. Configurable update strategies (immediate, delayed, manual)
4. No request failures during dependency transitions
"""

import os
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_dynamic_dependency_server() -> FastMCP:
    """Create a server demonstrating dynamic dependency updates."""

    # Create FastMCP server instance
    server = FastMCP(
        name="dynamic-dependency-demo",
        instructions="Demonstrates dynamic dependency updates in MCP Mesh.",
    )

    # ===== MAIN SERVICE WITH DEPENDENCIES =====

    @server.tool()
    @mesh_agent(
        capability="data_processor",
        dependencies=["cache_service", "database_service", "metrics_service"],
        version="1.0.0",
        tags=["dynamic", "dependencies"],
        description="Data processor that adapts to changing service availability",
    )
    async def process_data(
        data: str,
        cache_service: Any | None = None,
        database_service: Any | None = None,
        metrics_service: Any | None = None,
    ) -> dict[str, Any]:
        """Process data with dynamically updated dependencies."""

        result = {
            "data": data,
            "timestamp": datetime.now().isoformat(),
            "services_used": [],
            "processing_path": [],
        }

        # Try cache first (if available)
        if cache_service:
            try:
                cached_result = await cache_service.get(f"processed:{data}")
                if cached_result:
                    result["cached"] = True
                    result["services_used"].append("cache_service")
                    result["processing_path"].append("Retrieved from cache")
                    return cached_result
            except Exception as e:
                result["processing_path"].append(f"Cache failed: {e}")

        # Process the data
        processed_data = data.upper()  # Simple processing
        result["processed"] = processed_data
        result["processing_path"].append("Data processed")

        # Store in database (if available)
        if database_service:
            try:
                await database_service.store(
                    "processed_data",
                    {
                        "original": data,
                        "processed": processed_data,
                        "timestamp": result["timestamp"],
                    },
                )
                result["services_used"].append("database_service")
                result["processing_path"].append("Stored in database")
            except Exception as e:
                result["processing_path"].append(f"Database failed: {e}")

        # Update cache (if available)
        if cache_service:
            try:
                await cache_service.set(
                    f"processed:{data}", result, ttl=300  # 5 minutes
                )
                result["services_used"].append("cache_service")
                result["processing_path"].append("Updated cache")
            except Exception as e:
                result["processing_path"].append(f"Cache update failed: {e}")

        # Record metrics (if available)
        if metrics_service:
            try:
                await metrics_service.record(
                    "data_processed",
                    {
                        "size": len(data),
                        "services_available": len(result["services_used"]),
                    },
                )
                result["services_used"].append("metrics_service")
                result["processing_path"].append("Metrics recorded")
            except Exception as e:
                result["processing_path"].append(f"Metrics failed: {e}")

        return result

    @server.tool()
    @mesh_agent(
        capability="dependency_monitor",
        dependencies=["registry_service"],
        version="1.0.0",
        tags=["monitoring", "dependencies"],
        description="Monitors dependency changes in real-time",
    )
    async def monitor_dependencies(
        registry_service: Any | None = None,
    ) -> dict[str, Any]:
        """Monitor current dependency status and changes."""

        status = {
            "timestamp": datetime.now().isoformat(),
            "update_strategy": os.getenv("MCP_MESH_UPDATE_STRATEGY", "immediate"),
            "dynamic_updates_enabled": os.getenv("MCP_MESH_DYNAMIC_UPDATES", "true"),
            "dependencies": {},
        }

        if registry_service:
            try:
                # Get all registered services
                services = await registry_service.list_services()

                for service in services:
                    status["dependencies"][service["capability"]] = {
                        "agent_id": service["agent_id"],
                        "status": service["status"],
                        "last_heartbeat": service.get("last_heartbeat", "unknown"),
                    }

                status["registry_available"] = True
            except Exception as e:
                status["registry_available"] = False
                status["error"] = str(e)
        else:
            status["registry_available"] = False
            status["note"] = "Registry service not available for monitoring"

        return status

    @server.tool()
    @mesh_agent(
        capability="dependency_tester",
        dependencies=["test_service_a", "test_service_b", "test_service_c"],
        version="1.0.0",
        tags=["testing", "dependencies"],
        description="Tests dependency update behavior",
    )
    async def test_dependency_updates(
        test_service_a: Any | None = None,
        test_service_b: Any | None = None,
        test_service_c: Any | None = None,
    ) -> dict[str, Any]:
        """Test how dependencies are updated dynamically."""

        result = {
            "timestamp": datetime.now().isoformat(),
            "available_services": {
                "test_service_a": test_service_a is not None,
                "test_service_b": test_service_b is not None,
                "test_service_c": test_service_c is not None,
            },
            "service_details": {},
        }

        # Get details from each available service
        if test_service_a:
            try:
                result["service_details"]["a"] = await test_service_a.get_info()
            except Exception as e:
                result["service_details"]["a"] = f"Error: {e}"

        if test_service_b:
            try:
                result["service_details"]["b"] = await test_service_b.get_info()
            except Exception as e:
                result["service_details"]["b"] = f"Error: {e}"

        if test_service_c:
            try:
                result["service_details"]["c"] = await test_service_c.get_info()
            except Exception as e:
                result["service_details"]["c"] = f"Error: {e}"

        result["total_available"] = sum(result["available_services"].values())
        result["update_behavior"] = {
            "strategy": os.getenv("MCP_MESH_UPDATE_STRATEGY", "immediate"),
            "grace_period": os.getenv("MCP_MESH_UPDATE_GRACE_PERIOD", "30"),
            "description": "Dependencies will be updated based on the configured strategy",
        }

        return result

    # ===== CONFIGURATION AND STATUS TOOLS =====

    @server.tool()
    def get_update_configuration() -> dict[str, Any]:
        """Get current dynamic update configuration."""

        return {
            "dynamic_updates_enabled": os.getenv("MCP_MESH_DYNAMIC_UPDATES", "true"),
            "update_strategy": os.getenv("MCP_MESH_UPDATE_STRATEGY", "immediate"),
            "strategies": {
                "immediate": "Updates applied as soon as changes detected",
                "delayed": "Updates applied after grace period",
                "manual": "Changes logged but not applied automatically",
            },
            "grace_period_seconds": int(
                os.getenv("MCP_MESH_UPDATE_GRACE_PERIOD", "30")
            ),
            "environment_variables": {
                "MCP_MESH_DYNAMIC_UPDATES": "Enable/disable dynamic updates (true/false)",
                "MCP_MESH_UPDATE_STRATEGY": "Update strategy (immediate/delayed/manual)",
                "MCP_MESH_UPDATE_GRACE_PERIOD": "Grace period for delayed updates (seconds)",
            },
            "benefits": [
                "Zero-downtime dependency updates",
                "Automatic failover to better providers",
                "No function restarts required",
                "Configurable update behavior",
                "Seamless service evolution",
            ],
        }

    @server.tool()
    def simulate_dependency_change() -> dict[str, str]:
        """Simulate a dependency change scenario."""

        return {
            "scenario": "Dependency Update Simulation",
            "steps": [
                "1. Start this server with: mcp-mesh-dev start examples/dynamic_dependency_updates.py",
                "2. Call process_data() - note which services are available",
                "3. Start a cache service in another terminal",
                "4. Wait for next heartbeat (30s) or call process_data() again",
                "5. Notice cache_service is now automatically injected!",
                "6. Stop the cache service",
                "7. After next heartbeat, cache_service is removed",
                "8. Function continues working with available services",
            ],
            "key_points": [
                "Dependencies are checked every heartbeat interval",
                "New services are discovered automatically",
                "Failed services are removed from injection",
                "Functions adapt gracefully to changes",
                "No manual intervention required",
            ],
        }

    return server


def main():
    """Run the dynamic dependency updates demo server."""
    import signal
    import sys

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n📍 Received signal {signum}")
        print("🛑 Shutting down gracefully...")
        sys.exit(0)

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("🚀 Starting Dynamic Dependency Updates Demo Server...")
    print("\n⚙️ Configuration:")
    print(f"• Dynamic Updates: {os.getenv('MCP_MESH_DYNAMIC_UPDATES', 'true')}")
    print(f"• Update Strategy: {os.getenv('MCP_MESH_UPDATE_STRATEGY', 'immediate')}")
    print(f"• Grace Period: {os.getenv('MCP_MESH_UPDATE_GRACE_PERIOD', '30')}s")

    # Create the server
    server = create_dynamic_dependency_server()

    print(f"\n📡 Server name: {server.name}")
    print("\n🎯 Key Features:")
    print("• Dependencies re-evaluated during heartbeats")
    print("• Functions receive updates without restart")
    print("• Configurable update strategies")
    print("• Zero-downtime dependency transitions")
    print("\n💡 Try the simulate_dependency_change() tool for a walkthrough!")
    print("\n📝 Server ready on stdio transport...")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")


if __name__ == "__main__":
    main()
