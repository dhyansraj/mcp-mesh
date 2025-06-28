"""
Startup pipeline for MCP Mesh initialization and service setup.

Provides structured execution of startup operations with proper error handling
and logging. Handles decorator collection, configuration, heartbeat setup,
and FastAPI server preparation.
"""

import logging

from ..shared import RegistryConnectionStep
from ..shared.mesh_pipeline import MeshPipeline
from . import (
    ConfigurationStep,
    DecoratorCollectionStep,
    FastAPIServerSetupStep,
    FastMCPServerDiscoveryStep,
    HeartbeatLoopStep,
    HeartbeatPreparationStep,
)

logger = logging.getLogger(__name__)


class StartupPipeline(MeshPipeline):
    """
    Specialized pipeline for startup operations.

    Executes the core startup steps in sequence:
    1. Decorator collection
    2. Configuration setup
    3. Heartbeat preparation
    4. FastMCP server discovery
    5. Registry connection
    6. Heartbeat loop setup
    7. FastAPI server setup

    Each step builds context for subsequent steps.
    """

    def __init__(self, name: str = "startup-pipeline"):
        super().__init__(name=name)
        self._setup_startup_steps()

    def _setup_startup_steps(self) -> None:
        """Setup the startup pipeline steps."""
        # Essential startup steps - optimized to skip redundant heartbeat during startup
        steps = [
            DecoratorCollectionStep(),
            ConfigurationStep(),
            HeartbeatPreparationStep(),  # Prepare heartbeat payload structure
            FastMCPServerDiscoveryStep(),  # Discover user's FastMCP instances
            RegistryConnectionStep(),  # Connect to registry
            # REMOVED: HeartbeatSendStep() - redundant, background loop handles this
            # REMOVED: DependencyResolutionStep() - redundant, background loop handles this
            HeartbeatLoopStep(),  # Setup background heartbeat config
            FastAPIServerSetupStep(),  # Setup FastAPI app with background heartbeat
            # Note: FastAPI server will be started with uvicorn.run() after pipeline
        ]

        self.add_steps(steps)
        self.logger.debug(f"Startup pipeline configured with {len(steps)} steps")
