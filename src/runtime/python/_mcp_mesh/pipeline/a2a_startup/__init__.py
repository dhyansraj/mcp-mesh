"""
A2A Startup pipeline components for MCP Mesh (issue #903 Phase 1B).

Handles ``@mesh.a2a`` / ``mesh.a2a.mount`` surface registration on a
user-owned FastAPI app. Sibling pipeline to ``api_startup`` (which
handles ``@mesh.route``) and ``mcp_startup`` (which handles
``@mesh.agent`` / ``@mesh.tool``).

The A2A pipeline differs from ``api_startup`` in two ways:

  * There are no ``@mesh.route`` decorators to collect — the
    ``mesh.a2a.mount`` helper has already wired the agent-card and
    JSON-RPC routes onto the user's FastAPI app at module import time.
  * Dependency injection is performed by ``@mesh.a2a`` itself (mirrors
    ``@mesh.route``), so no ``RouteIntegrationStep`` is needed.

The pipeline therefore reduces to: discover the user's FastAPI app,
attach tracing middleware, and prepare the heartbeat metadata
(``service_type=a2a`` + the ``surfaces`` array sent on each registry
heartbeat round-trip).
"""

from .a2a_pipeline import A2APipeline
from .a2a_server_setup import A2AServerSetupStep
from .a2a_surface_collection import A2ASurfaceCollectionStep
from .fastapi_discovery import A2AFastAPIDiscoveryStep

__all__ = [
    "A2APipeline",
    "A2AServerSetupStep",
    "A2ASurfaceCollectionStep",
    "A2AFastAPIDiscoveryStep",
]
