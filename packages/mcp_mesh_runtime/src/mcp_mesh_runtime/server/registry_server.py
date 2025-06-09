"""
Registry Server Startup Script

Provides command-line interface to start the MCP Mesh Registry Service
using FastMCP with proper ASGI server integration.
"""

import argparse
import asyncio
import signal
import sys
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .models import (
    CapabilitySearchQuery,
    HealthStatus,
    RegistryMetrics,
    ServiceDiscoveryQuery,
)
from .registry import RegistryService


class HeartbeatRequest(BaseModel):
    """Request model for heartbeat endpoint."""

    agent_id: str
    status: str | None = "healthy"
    metadata: dict[str, Any] | None = {}


class RegisterAgentRequest(BaseModel):
    """Request model for agent registration with metadata."""

    agent_id: str
    metadata: dict[str, Any]
    timestamp: str


class AgentsResponse(BaseModel):
    """Response model for agents endpoint."""

    agents: list[dict[str, Any]]
    count: int
    timestamp: str


class CapabilitiesResponse(BaseModel):
    """Response model for capabilities endpoint."""

    capabilities: list[dict[str, Any]]
    count: int
    timestamp: str


class RegistryServer:
    """Registry server wrapper with proper lifecycle management."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.registry_service: RegistryService | None = None
        self.server: uvicorn.Server | None = None
        self.rest_app: FastAPI | None = None

    async def start(self):
        """Start the registry server."""
        # Create registry service
        self.registry_service = RegistryService()
        await self.registry_service.initialize()

        # Start health monitoring
        await self.registry_service.start_health_monitoring()

        # Create combined application
        combined_app = self._create_combined_app()

        # Configure uvicorn server
        config = uvicorn.Config(
            app=combined_app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=True,
        )

        self.server = uvicorn.Server(config)

        print("🚀 Starting MCP Mesh Registry Service")
        print(f"📡 Server: http://{self.host}:{self.port}")
        print(f"🔗 MCP Endpoint: http://{self.host}:{self.port}/mcp")
        print("📊 Health monitoring: enabled")
        print("🏗️  Architecture: Kubernetes API Server pattern")
        print("🔄 Mode: PASSIVE (pull-based)")
        print("🌐 REST Endpoints:")
        print("   POST /heartbeat - Agent status updates")
        print(
            "   POST /agents/register_with_metadata - Agent registration with metadata"
        )
        print("   GET  /agents - Service discovery (with fuzzy matching & filtering)")
        print("   GET  /capabilities - Capability discovery (with advanced search)")
        print("   GET  /health - Health check")
        print("   GET  /health/{agent_id} - Agent health status")
        print("   GET  /metrics - Registry metrics")
        print("   GET  /metrics/prometheus - Prometheus metrics")
        print("🚀 Features:")
        print("   ✓ Response caching (30s TTL)")
        print("   ✓ Fuzzy matching for capabilities")
        print("   ✓ Version constraint filtering")
        print("   ✓ Pydantic validation schemas")
        print("   ✓ Kubernetes-style label selectors")
        print("   ✓ Timer-based health monitoring")
        print("   ✓ Configurable timeout thresholds per agent type")
        print("   ✓ Automatic agent eviction (passive)")
        print("   ✓ Prometheus metrics export")
        print("-" * 60)

        # Start server
        await self.server.serve()

    async def stop(self):
        """Stop the registry server."""
        print("🛑 Shutting down registry service...")

        if self.registry_service:
            await self.registry_service.stop_health_monitoring()

        if self.server:
            self.server.should_exit = True

        print("✅ Registry service stopped")

    def _create_combined_app(self) -> FastAPI:
        """Create a combined FastAPI app with both MCP and REST endpoints."""
        # Create main FastAPI app
        app = FastAPI(
            title="MCP Mesh Registry Service",
            description="Service discovery and registration for MCP agents",
            version="1.0.0",
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Add REST endpoints
        self._add_rest_endpoints(app)

        # Mount the MCP app
        app.mount("/mcp", self.registry_service.get_app())

        return app

    def _add_rest_endpoints(self, app: FastAPI):
        """Add REST endpoints to the FastAPI app."""

        @app.post(
            "/heartbeat",
            response_model=dict[str, Any],
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Heartbeat recorded successfully"},
                404: {"description": "Agent not found"},
                500: {"description": "Internal server error"},
            },
        )
        async def heartbeat_endpoint(request: HeartbeatRequest):
            """POST /heartbeat - Agents call this with status updates."""
            try:
                success = await self.registry_service.storage.update_heartbeat(
                    request.agent_id
                )

                if success:
                    from datetime import datetime, timezone

                    return {
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": "Heartbeat recorded",
                    }
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent {request.agent_id} not found",
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to process heartbeat: {str(e)}",
                )

        @app.post(
            "/agents/register_with_metadata",
            response_model=dict[str, Any],
            status_code=status.HTTP_201_CREATED,
            responses={
                201: {"description": "Agent registered successfully"},
                400: {"description": "Invalid registration data"},
                500: {"description": "Internal server error"},
            },
        )
        async def register_agent_with_metadata(request: RegisterAgentRequest):
            """POST /agents/register_with_metadata - Register agent with enhanced metadata."""
            try:
                from datetime import datetime, timezone

                from .models import AgentCapability, AgentRegistration

                # Convert metadata to AgentRegistration format
                metadata = request.metadata

                # Build capabilities list from metadata
                capabilities = []
                if "capabilities" in metadata and metadata["capabilities"]:
                    for cap_data in metadata["capabilities"]:
                        if isinstance(cap_data, dict):
                            capability = AgentCapability(
                                name=cap_data.get("name", "unknown"),
                                version=cap_data.get("version", "1.0.0"),
                                description=cap_data.get("description", ""),
                                tags=cap_data.get("tags", []),
                                parameters=cap_data.get("parameters", {}),
                                performance_metrics=cap_data.get(
                                    "performance_metrics", {}
                                ),
                                security_level=cap_data.get(
                                    "security_level", "standard"
                                ),
                                resource_requirements=cap_data.get(
                                    "resource_requirements", {}
                                ),
                                metadata=cap_data.get("metadata", {}),
                            )
                            capabilities.append(capability)

                # Normalize names to comply with validation rules (lowercase alphanumeric with hyphens)
                def normalize_name(name: str) -> str:
                    """Convert name to lowercase alphanumeric with hyphens."""
                    import re

                    # Replace underscores and other characters with hyphens
                    normalized = re.sub(r"[^a-z0-9-]", "-", name.lower())
                    # Remove consecutive hyphens
                    normalized = re.sub(r"-+", "-", normalized)
                    # Remove leading/trailing hyphens
                    normalized = normalized.strip("-")
                    return normalized or "agent"

                agent_name = normalize_name(metadata.get("name", request.agent_id))
                agent_type = normalize_name(metadata.get("agent_type", "mesh-agent"))

                # Create a valid HTTP endpoint for stdio agents
                agent_endpoint = metadata.get("endpoint")
                if not agent_endpoint or not agent_endpoint.startswith(
                    ("http://", "https://")
                ):
                    # For MCP stdio agents, create a placeholder HTTP endpoint
                    agent_endpoint = f"http://localhost:0/{agent_name}"

                # Create AgentRegistration object
                registration = AgentRegistration(
                    name=agent_name,
                    namespace=metadata.get("namespace", "default"),
                    endpoint=agent_endpoint,
                    capabilities=capabilities,
                    dependencies=metadata.get("dependencies", []),
                    health_interval=metadata.get("health_interval", 30),
                    agent_type=agent_type,
                    config=metadata.get("metadata", {}),
                    security_context=metadata.get("security_context"),
                    labels=(
                        metadata.get("tags", {})
                        if isinstance(metadata.get("tags"), dict)
                        else {}
                    ),
                    annotations={
                        "registered_via": "register_with_metadata",
                        "timestamp": request.timestamp,
                        "original_name": metadata.get("name", request.agent_id),
                        "original_agent_type": metadata.get("agent_type", "mesh_agent"),
                        "original_endpoint": metadata.get(
                            "endpoint", f"stdio://{request.agent_id}"
                        ),
                    },
                )

                # Register agent using existing storage method
                registered_agent = await self.registry_service.storage.register_agent(
                    registration
                )

                return {
                    "status": "success",
                    "agent_id": request.agent_id,
                    "resource_version": registered_agent.resource_version,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Agent registered successfully",
                }

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to register agent: {str(e)}",
                )

        @app.get(
            "/agents",
            response_model=AgentsResponse,
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Successfully retrieved agents"},
                400: {"description": "Invalid query parameters"},
                500: {"description": "Internal server error"},
            },
        )
        async def get_agents(
            namespace: str | None = None,
            status: str | None = None,
            capability: str | None = None,
            capability_category: str | None = None,
            capability_stability: str | None = None,
            capability_tags: str | None = None,
            label_selector: str | None = None,
            fuzzy_match: bool = False,
            version_constraint: str | None = None,
        ):
            """GET /agents - Service discovery endpoint."""
            try:
                # Build query from parameters
                query_params = {}
                if namespace:
                    query_params["namespace"] = namespace
                if status:
                    query_params["status"] = status
                if capability:
                    query_params["capabilities"] = [capability]
                if capability_category:
                    query_params["capability_category"] = capability_category
                if capability_stability:
                    query_params["capability_stability"] = capability_stability
                if capability_tags:
                    query_params["capability_tags"] = capability_tags.split(",")
                if version_constraint:
                    query_params["version_constraint"] = version_constraint
                query_params["fuzzy_match"] = fuzzy_match

                # Parse label selector (simple format: key=value)
                if label_selector:
                    labels = {}
                    for selector in label_selector.split(","):
                        if "=" in selector:
                            key, value = selector.split("=", 1)
                            labels[key.strip()] = value.strip()
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid label selector format: {selector}. Expected 'key=value'",
                            )
                    if labels:
                        query_params["labels"] = labels

                query = ServiceDiscoveryQuery(**query_params) if query_params else None
                agents = await self.registry_service.storage.list_agents(query)

                from datetime import datetime, timezone

                return AgentsResponse(
                    agents=[agent.model_dump() for agent in agents],
                    count=len(agents),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to list agents: {str(e)}",
                )

        @app.get(
            "/capabilities",
            response_model=CapabilitiesResponse,
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Successfully retrieved capabilities"},
                404: {"description": "Agent not found (when agent_id specified)"},
                500: {"description": "Internal server error"},
            },
        )
        async def get_capabilities(
            agent_id: str | None = None,
            name: str | None = None,
            description_contains: str | None = None,
            category: str | None = None,
            tags: str | None = None,
            stability: str | None = None,
            version_constraint: str | None = None,
            fuzzy_match: bool = False,
            include_deprecated: bool = False,
            agent_namespace: str | None = None,
            agent_status: str | None = "healthy",
        ):
            """GET /capabilities - Capability discovery endpoint with enhanced search."""
            try:
                # Use enhanced search if any search parameters are provided
                search_params = {
                    "name": name,
                    "description_contains": description_contains,
                    "category": category,
                    "stability": stability,
                    "version_constraint": version_constraint,
                    "fuzzy_match": fuzzy_match,
                    "include_deprecated": include_deprecated,
                    "agent_namespace": agent_namespace,
                    "agent_status": agent_status,
                }

                if tags:
                    search_params["tags"] = tags.split(",")

                # Filter out None values
                search_params = {
                    k: v for k, v in search_params.items() if v is not None
                }

                if agent_id:
                    # Legacy behavior: get capabilities for specific agent
                    agent = await self.registry_service.storage.get_agent(agent_id)
                    if not agent:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Agent {agent_id} not found",
                        )

                    capabilities = []
                    for cap in agent.capabilities:
                        cap_dict = cap.dict()
                        cap_dict.update(
                            {
                                "agent_id": agent.id,
                                "agent_name": agent.name,
                                "agent_namespace": agent.namespace,
                                "agent_status": agent.status,
                                "agent_endpoint": agent.endpoint,
                            }
                        )

                        # Apply name filter if specified (for backward compatibility)
                        if name and cap.name != name:
                            continue

                        capabilities.append(cap_dict)

                elif search_params:
                    # Use enhanced search
                    query = CapabilitySearchQuery(**search_params)
                    capabilities = (
                        await self.registry_service.storage.search_capabilities(query)
                    )

                else:
                    # Fallback to getting all capabilities
                    agents = await self.registry_service.storage.list_agents()
                    capabilities = []
                    for agent in agents:
                        if agent:
                            for cap in agent.capabilities:
                                cap_dict = cap.dict()
                                cap_dict.update(
                                    {
                                        "agent_id": agent.id,
                                        "agent_name": agent.name,
                                        "agent_namespace": agent.namespace,
                                        "agent_status": agent.status,
                                        "agent_endpoint": agent.endpoint,
                                    }
                                )
                                capabilities.append(cap_dict)

                from datetime import datetime, timezone

                return CapabilitiesResponse(
                    capabilities=capabilities,
                    count=len(capabilities),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to list capabilities: {str(e)}",
                )

        @app.get(
            "/health",
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Service is healthy"},
                503: {"description": "Service is unhealthy"},
            },
        )
        async def health_check():
            """Health check endpoint."""
            try:
                # Check database connectivity if available
                if self.registry_service.storage._database_enabled:
                    # Simple database ping
                    await self.registry_service.storage.database.get_database_stats()

                return {"status": "healthy", "service": "mcp-mesh-registry"}
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Service unhealthy: {str(e)}",
                )

        @app.get("/")
        async def root():
            """Root endpoint with service information."""
            return {
                "service": "MCP Mesh Registry Service",
                "version": "1.0.0",
                "endpoints": {
                    "heartbeat": "POST /heartbeat - Agent status updates",
                    "register_agent": "POST /agents/register_with_metadata - Agent registration with metadata",
                    "agents": "GET /agents - Service discovery with advanced filtering",
                    "capabilities": "GET /capabilities - Capability discovery with search",
                    "health": "GET /health - Health check",
                    "agent_health": "GET /health/{agent_id} - Agent health status",
                    "metrics": "GET /metrics - Registry metrics",
                    "prometheus": "GET /metrics/prometheus - Prometheus metrics",
                    "mcp": "/mcp - MCP protocol endpoint",
                },
                "features": {
                    "caching": "Response caching with 30s TTL",
                    "fuzzy_matching": "Fuzzy string matching for capability search",
                    "version_constraints": "Semantic version constraint filtering",
                    "validation": "Pydantic validation schemas for all inputs",
                    "label_selectors": "Kubernetes-style label filtering",
                    "health_monitoring": "Timer-based passive health monitoring",
                    "configurable_timeouts": "Per-agent-type timeout thresholds",
                    "automatic_eviction": "Passive agent eviction on timeout",
                    "prometheus_metrics": "Prometheus metrics export",
                },
                "architecture": "Kubernetes API Server pattern (PASSIVE pull-based)",
                "description": "Enhanced service registry for MCP agent mesh with advanced discovery capabilities",
            }

        @app.get(
            "/health/{agent_id}",
            response_model=HealthStatus,
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Agent health status retrieved"},
                404: {"description": "Agent not found"},
                500: {"description": "Internal server error"},
            },
        )
        async def get_agent_health(agent_id: str):
            """GET /health/{agent_id} - Get health status for specific agent."""
            try:
                health_status = await self.registry_service.storage.get_agent_health(
                    agent_id
                )

                if health_status:
                    return health_status
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Agent {agent_id} not found",
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get agent health: {str(e)}",
                )

        @app.get(
            "/metrics",
            response_model=RegistryMetrics,
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Registry metrics retrieved"},
                500: {"description": "Internal server error"},
            },
        )
        async def get_registry_metrics():
            """GET /metrics - Get registry metrics and statistics."""
            try:
                return await self.registry_service.storage.get_registry_metrics()
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get registry metrics: {str(e)}",
                )

        @app.get(
            "/metrics/prometheus",
            status_code=status.HTTP_200_OK,
            responses={
                200: {
                    "description": "Prometheus metrics retrieved",
                    "content": {
                        "text/plain": {
                            "example": "# HELP mcp_registry_agents_total Total number of registered agents"
                        }
                    },
                },
                500: {"description": "Internal server error"},
            },
        )
        async def get_prometheus_metrics():
            """GET /metrics/prometheus - Get metrics in Prometheus format."""
            try:
                prometheus_data = (
                    await self.registry_service.storage.get_prometheus_metrics()
                )
                return Response(content=prometheus_data, media_type="text/plain")
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get Prometheus metrics: {str(e)}",
                )


def setup_signal_handlers(server: RegistryServer):
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(signum, frame):
        print(f"Received signal {signum}, initiating graceful shutdown...")
        asyncio.create_task(server.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point for registry server."""
    parser = argparse.ArgumentParser(
        description="MCP Mesh Registry Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m mcp_mesh.server.registry_server
  python -m mcp_mesh.server.registry_server --host 0.0.0.0 --port 9000

The registry service provides:
  - Agent registration and discovery
  - Capability-based service matching
  - Health monitoring and heartbeat tracking
  - Kubernetes API server patterns
  - PASSIVE pull-based architecture
        """,
    )

    parser.add_argument(
        "--host",
        default="localhost",
        help="Host to bind the server to (default: localhost)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )

    parser.add_argument(
        "--version", action="store_true", help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        print("MCP Mesh Registry Service v0.1.0")
        print("Built on FastMCP and Kubernetes API Server patterns")
        return

    # Create and start server
    server = RegistryServer(host=args.host, port=args.port)
    setup_signal_handlers(server)

    try:
        await server.start()
    except Exception as e:
        print(f"❌ Failed to start registry service: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
