#!/usr/bin/env python3
"""
HTTP Distributed Agent Example - Revolutionary MCP Architecture

This example demonstrates how MCP Mesh transforms local MCP functions into
distributed, containerizable HTTP services. This is the foundation for
Kubernetes-native MCP deployments.

Key Features Demonstrated:
1. Automatic HTTP server creation with port auto-assignment
2. MCP server mounted at /mcp endpoint for protocol compliance
3. Health check endpoints for Kubernetes probes
4. Service discovery registration with HTTP endpoints
5. Cross-container dependency injection readiness
"""

import asyncio
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_distributed_weather_service() -> FastMCP:
    """Create a weather service that can run in containers."""

    server = FastMCP(
        name="weather-service",
        instructions="Distributed weather service with HTTP endpoints for container deployment",
    )

    @server.tool()
    @mesh_agent(
        capabilities=["weather", "forecast", "distributed"],
        dependencies=["LocationService"],  # Can be injected from another container!
        health_interval=10,  # Frequent health checks for K8s
        enable_http=True,  # Force HTTP mode
        http_port=0,  # Auto-assign port
        version="2.0.0",
        description="Containerized weather service with HTTP transport",
        tags=["kubernetes", "microservice", "weather"],
        performance_profile={"response_time_ms": 100.0},
    )
    async def get_weather(
        location: str, LocationService: Any | None = None
    ) -> dict[str, Any]:
        """
        Get weather for a location with distributed service support.

        This function demonstrates:
        - Automatic HTTP endpoint creation
        - Cross-container dependency injection
        - Kubernetes-ready health monitoring

        Args:
            location: Location name or coordinates
            LocationService: Auto-injected from another container

        Returns:
            Weather data with location details
        """
        weather_data = {
            "location": location,
            "temperature": "22°C",
            "conditions": "Partly cloudy",
            "humidity": "65%",
            "wind": "10 km/h NW",
        }

        # If LocationService is available (from another container), enhance data
        if LocationService:
            try:
                location_details = await LocationService.get_details(location)
                weather_data["location_details"] = location_details
                weather_data["source"] = "distributed-mesh"
            except Exception as e:
                weather_data["location_error"] = str(e)
        else:
            weather_data["source"] = "local-only"

        return weather_data

    @server.tool()
    @mesh_agent(
        capabilities=["forecast", "distributed"],
        enable_http=True,
        version="2.0.0",
    )
    async def get_forecast(location: str, days: int = 5) -> dict[str, Any]:
        """
        Get weather forecast with HTTP endpoint.

        Args:
            location: Location for forecast
            days: Number of days to forecast

        Returns:
            Forecast data
        """
        return {
            "location": location,
            "days": days,
            "forecast": [
                {"day": i, "temp": f"{20+i}°C", "conditions": "Sunny"}
                for i in range(1, days + 1)
            ],
            "transport": "http",
            "endpoint": os.getenv("MCP_MESH_HTTP_ENDPOINT", "auto-assigned"),
        }

    @server.tool()
    def get_service_info() -> dict[str, Any]:
        """Get information about this distributed service."""
        return {
            "service": "weather-service",
            "version": "2.0.0",
            "deployment": "distributed-http",
            "features": [
                "Auto HTTP endpoint creation",
                "Port auto-assignment",
                "Kubernetes health checks",
                "Cross-container dependency injection",
                "Service mesh integration",
            ],
            "endpoints": {
                "http": os.getenv("MCP_MESH_HTTP_ENDPOINT", "pending"),
                "mcp": os.getenv("MCP_MESH_MCP_ENDPOINT", "pending"),
                "health": "/health",
                "ready": "/ready",
                "metrics": "/metrics",
            },
            "container_ready": os.getenv("KUBERNETES_SERVICE_HOST") is not None,
        }

    return server


def create_location_service() -> FastMCP:
    """Create a location service that can be injected into weather service."""

    server = FastMCP(
        name="location-service",
        instructions="Location service for distributed deployment",
    )

    @server.tool()
    @mesh_agent(
        capabilities=["location", "geocoding", "distributed"],
        enable_http=True,
        version="1.0.0",
        description="Location service for cross-container injection",
    )
    async def get_location_details(location: str) -> dict[str, Any]:
        """Get detailed location information."""
        # Simulate location lookup
        locations = {
            "San Francisco": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "timezone": "PST",
                "country": "USA",
                "population": 873965,
            },
            "London": {
                "latitude": 51.5074,
                "longitude": -0.1278,
                "timezone": "GMT",
                "country": "UK",
                "population": 8982000,
            },
        }

        return locations.get(
            location,
            {
                "error": "Location not found",
                "suggestion": "Try 'San Francisco' or 'London'",
            },
        )

    return server


async def demonstrate_distributed_deployment():
    """Demonstrate the distributed deployment capabilities."""

    print("🚀 MCP Mesh - Distributed HTTP Agent Demonstration")
    print("=" * 60)

    print("\n📊 Architecture Overview:")
    print("• Each @mesh_agent function gets an HTTP wrapper")
    print("• Auto-assigned ports for container deployment")
    print("• MCP protocol served at /mcp endpoint")
    print("• Kubernetes-ready health checks at /health")
    print("• Service discovery with HTTP endpoints")

    print("\n🌐 Deployment Scenarios:")
    print("1. Local: Functions run in same process (current)")
    print("2. Docker: Each service in its own container")
    print("3. Kubernetes: Scaled replicas with load balancing")
    print("4. Service Mesh: Full observability and traffic management")

    print("\n🔧 Environment Variables:")
    print(f"• MCP_MESH_HTTP_ENABLED: {os.getenv('MCP_MESH_HTTP_ENABLED', 'auto')}")
    print(
        f"• KUBERNETES_SERVICE_HOST: {os.getenv('KUBERNETES_SERVICE_HOST', 'not set')}"
    )
    print(f"• CONTAINER_MODE: {os.getenv('CONTAINER_MODE', 'not set')}")

    print("\n💡 Try this:")
    print("1. Set MCP_MESH_HTTP_ENABLED=true before running")
    print("2. Watch for auto-assigned HTTP endpoints in logs")
    print("3. Access health check: curl http://localhost:<port>/health")
    print("4. Use MCP client at: http://localhost:<port>/mcp")

    print("\n🐳 Container Deployment:")
    print("docker build -t weather-service .")
    print("docker run -e MCP_MESH_HTTP_ENABLED=true weather-service")

    print("\n☸️ Kubernetes Deployment:")
    print("kubectl apply -f k8s/weather-service.yaml")
    print("kubectl scale deployment weather-service --replicas=3")


def main():
    """Run the distributed agent demonstration."""
    import sys

    # Check if we should run the demo or actual service
    if "--demo" in sys.argv:
        asyncio.run(demonstrate_distributed_deployment())
        return

    # Determine which service to run
    service_name = os.getenv("SERVICE_NAME", "weather-service")

    if service_name == "weather-service":
        print("🌤️ Starting Distributed Weather Service...")
        server = create_distributed_weather_service()
    elif service_name == "location-service":
        print("📍 Starting Distributed Location Service...")
        server = create_location_service()
    else:
        print(f"❌ Unknown service: {service_name}")
        sys.exit(1)

    print(f"📡 Service: {server.name}")
    print(f"🚀 Transport: {'HTTP' if os.getenv('MCP_MESH_HTTP_ENABLED') else 'stdio'}")

    if os.getenv("MCP_MESH_HTTP_ENABLED", "").lower() in ("true", "1", "yes"):
        print("\n🌐 HTTP endpoints will be auto-created by mesh decorator")
        print("📊 Watch for port assignment in logs above")
        print("💓 Health endpoint will be available for K8s probes")

    print("\n▶️ Starting service...")

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print(f"\n🛑 {server.name} stopped by user.")
    except Exception as e:
        print(f"❌ Service error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
