"""
API pipeline for MCP Mesh FastAPI integration.

Provides structured execution of API operations with proper error handling
and logging. Handles @mesh.route decorator collection, FastAPI app discovery,
route integration, and service registration.
"""

import logging

from ..shared.mesh_pipeline import MeshPipeline
from .api_server_setup import APIServerSetupStep
from .fastapi_discovery import FastAPIAppDiscoveryStep
from .middleware_integration import TracingMiddlewareIntegrationStep
from .route_collection import RouteCollectionStep
from .route_integration import RouteIntegrationStep

logger = logging.getLogger(__name__)


class APIPipeline(MeshPipeline):
    """
    Specialized pipeline for API operations.

    Executes the core API integration steps in sequence:
    1. Route collection (@mesh.route decorators)
    2. FastAPI app discovery (find user's FastAPI instances)
    3. Route integration (apply dependency injection)
    4. Tracing middleware integration (add telemetry to FastAPI apps)
    5. API server setup (service registration metadata)

    Unlike MCP agents, API services are consumers so we focus on:
    - Dependency injection into route handlers
    - Service registration for health monitoring
    - NO server creation or binding (user owns FastAPI app)
    """

    def __init__(self, name: str = "api-pipeline"):
        super().__init__(name=name)
        self._setup_api_steps()

    def _setup_api_steps(self) -> None:
        """Setup the API pipeline steps."""
        # Essential API integration steps
        steps = [
            RouteCollectionStep(),              # Collect @mesh.route decorators
            FastAPIAppDiscoveryStep(),          # Find user's FastAPI app instances
            RouteIntegrationStep(),             # Apply dependency injection to routes
            TracingMiddlewareIntegrationStep(), # Add tracing middleware to FastAPI apps
            APIServerSetupStep(),               # Prepare service registration metadata
            # Note: Heartbeat integration will be added in next phase
            # Note: User controls FastAPI server startup (uvicorn/gunicorn)
        ]

        self.add_steps(steps)
        self.logger.debug(f"API pipeline configured with {len(steps)} steps")
        
        # Log the pipeline strategy
        self.logger.info(
            f"🌐 [DEBUG] API Pipeline initialized: dependency injection for @mesh.route decorators"
        )
        self.logger.debug(
            f"📋 Pipeline steps: {[step.name for step in steps]}"
        )