"""
A2A pipeline for MCP Mesh A2A surface integration (issue #903 Phase 1B).

Sibling pipeline to ``APIPipeline`` (handles ``@mesh.route``) and the
mcp-startup ``StartupPipeline`` (handles ``@mesh.agent`` / ``@mesh.tool``).
Triggered when the user has declared ``@mesh.a2a`` or
``mesh.a2a.mount(...)`` surfaces — the user owns the FastAPI app AND
the uvicorn lifecycle, mesh handles discovery + heartbeat + DI bookkeeping.

Pipeline shape:

  1. A2A surface collection      (read ``mesh_a2a`` markers from registry)
  2. FastAPI app discovery       (locate the user's FastAPI instance)
  3. Tracing middleware          (attach distributed-tracing middleware)
  4. A2A server setup            (heartbeat config + ``service_type=a2a``)

DI is wired by the ``@mesh.a2a`` decorator itself at module import (mirrors
``@mesh.route``), so this pipeline has no equivalent of
``RouteIntegrationStep``.
"""

import logging

from ..api_startup.middleware_integration import \
    TracingMiddlewareIntegrationStep
from ..shared.mesh_pipeline import MeshPipeline
from .a2a_server_setup import A2AServerSetupStep
from .a2a_surface_collection import A2ASurfaceCollectionStep
from .fastapi_discovery import A2AFastAPIDiscoveryStep

logger = logging.getLogger(__name__)


class A2APipeline(MeshPipeline):
    """
    Specialized pipeline for A2A surface operations.

    Executes the A2A integration steps in sequence:
    1. A2A surface collection (read ``mesh_a2a`` markers)
    2. FastAPI app discovery (locate the user's FastAPI instance)
    3. Tracing middleware integration (shared with api_startup)
    4. A2A server setup (heartbeat metadata + ``service_type=a2a``)

    Like ``APIPipeline``, this is a consumer-style pipeline:
    - No FastAPI server is created (user owns the app + uvicorn).
    - DI is already wired by ``@mesh.a2a`` at module import.
    - The pipeline only contributes registration metadata + heartbeat.
    """

    def __init__(self, name: str = "a2a-pipeline"):
        super().__init__(name=name)
        self._setup_a2a_steps()

    def _setup_a2a_steps(self) -> None:
        """Setup the A2A pipeline steps."""
        steps = [
            A2ASurfaceCollectionStep(),  # Collect mesh_a2a markers
            A2AFastAPIDiscoveryStep(),  # Find user's FastAPI app
            TracingMiddlewareIntegrationStep(),  # Add tracing middleware
            A2AServerSetupStep(),  # Heartbeat + service_type=a2a
        ]

        self.add_steps(steps)
        self.logger.debug(f"A2A pipeline configured with {len(steps)} steps")

        self.logger.info(
            "🌐 [DEBUG] A2A Pipeline initialized: surface registration for @mesh.a2a decorators"
        )
        self.logger.debug(f"📋 Pipeline steps: {[step.name for step in steps]}")
