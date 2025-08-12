"""
API Startup pipeline components for MCP Mesh.

Handles @mesh.route decorator collection, FastAPI app discovery,
and dependency injection setup during API service initialization.
"""

from .api_pipeline import APIPipeline
from .api_server_setup import APIServerSetupStep
from .fastapi_discovery import FastAPIAppDiscoveryStep
from .route_collection import RouteCollectionStep
from .route_integration import RouteIntegrationStep

__all__ = [
    "RouteCollectionStep",
    "FastAPIAppDiscoveryStep",
    "RouteIntegrationStep",
    "APIServerSetupStep",
    "APIPipeline",
]
