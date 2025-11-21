"""
Startup pipeline for MCP Mesh initialization and service setup.

Provides structured execution of startup operations with proper error handling
and logging. Handles decorator collection, configuration, heartbeat setup,
and FastAPI server preparation.
"""

import logging

from ..shared.mesh_pipeline import MeshPipeline
from . import (
    ConfigurationStep,
    DecoratorCollectionStep,
    FastAPIServerSetupStep,
    FastMCPServerDiscoveryStep,
    HeartbeatLoopStep,
    HeartbeatPreparationStep,
)
from .server_discovery import ServerDiscoveryStep

logger = logging.getLogger(__name__)


class StartupPipeline(MeshPipeline):
    """
    Specialized pipeline for startup operations.

    Executes the core startup steps in sequence:
    1. Decorator collection
    2. Configuration setup
    3. Heartbeat preparation
    4. Server discovery (existing uvicorn servers)
    5. FastMCP server discovery
    6. Heartbeat loop setup
    7. FastAPI server setup

    Registry connection is handled in the heartbeat pipeline for automatic
    retry behavior. Agents start immediately regardless of registry availability.
    """

    def __init__(self, name: str = "startup-pipeline"):
        super().__init__(name=name)
        self._setup_startup_steps()

    def _setup_startup_steps(self) -> None:
        """Setup the startup pipeline steps."""
        # Essential startup steps - agent preparation without registry dependency
        steps = [
            DecoratorCollectionStep(),
            ConfigurationStep(),
            FastMCPServerDiscoveryStep(),  # Discover user's FastMCP instances (MOVED UP for Phase 2)
            HeartbeatPreparationStep(),  # Prepare heartbeat payload structure (can now access FastMCP schemas)
            ServerDiscoveryStep(),  # Discover existing uvicorn servers from immediate startup
            HeartbeatLoopStep(),  # Setup background heartbeat config (handles no registry gracefully)
            FastAPIServerSetupStep(),  # Setup FastAPI app with background heartbeat
            # Note: Registry connection is handled in heartbeat pipeline for retry behavior
            # Note: FastAPI server will be started with uvicorn.run() after pipeline (or reused if discovered)
        ]

        self.add_steps(steps)
        self.logger.debug(f"Startup pipeline configured with {len(steps)} steps")
