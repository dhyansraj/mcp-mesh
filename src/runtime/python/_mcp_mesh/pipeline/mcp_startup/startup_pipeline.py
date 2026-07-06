"""
Startup pipeline for MCP Mesh initialization and service setup.

Provides structured execution of startup operations with proper error handling
and logging. Handles decorator collection, configuration, heartbeat setup,
and FastAPI server preparation.
"""

import logging

from ..shared.mesh_pipeline import MeshPipeline
from . import (ConfigurationStep, DecoratorCollectionStep,
               DualModuleCheckStep, FastAPIServerSetupStep,
               FastMCPServerDiscoveryStep, HeartbeatLoopStep,
               HeartbeatPreparationStep, JobsCancelRouteStep,
               JobsClaimWorkersStep, JobsHelperToolsStep,
               MediaStoreValidationStep, ServiceViewProducerServingStep)
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
            # Issue #1031: abort if the same @mesh.tool was registered
            # under both __main__.X and <module>.X (the python main.py +
            # from main import X footgun). Runs early — after decorators
            # have fired but before any heartbeat / server bring-up — so
            # the user sees the error immediately.
            DualModuleCheckStep(),
            ConfigurationStep(),
            # Eagerly initialize the media store so MCP_MESH_MEDIA_STORAGE=s3
            # misconfiguration (missing boto3, missing bucket, bad creds when
            # validation is enabled) fails at startup instead of at first LLM
            # call. Issue #846 (#1, #2).
            MediaStoreValidationStep(),
            FastMCPServerDiscoveryStep(),  # Discover user's FastMCP instances (MOVED UP for Phase 2)
            # Phase 1 MeshJob: register helper tools on the FastMCP server
            # BEFORE FastAPIServerSetup mounts it (so they appear in /tools/list).
            JobsHelperToolsStep(),
            # RFC #1280: attach @mesh.service producer-sugar tools to the served
            # FastMCP server(s) — same late-bind timing as the job helpers, so
            # sugar-published tools appear in /tools/list and answer tools/call.
            ServiceViewProducerServingStep(),
            HeartbeatPreparationStep(),  # Prepare heartbeat payload structure (can now access FastMCP schemas)
            ServerDiscoveryStep(),  # Discover existing uvicorn servers from immediate startup
            HeartbeatLoopStep(),  # Setup background heartbeat config (handles no registry gracefully)
            FastAPIServerSetupStep(),  # Setup FastAPI app with background heartbeat
            # Phase 1 MeshJob: cancel route needs the FastAPI app prepared
            # by FastAPIServerSetup, so it runs AFTER it.
            JobsCancelRouteStep(),
            # Phase 1 MeshJob: spawn one Python claim worker per
            # @mesh.tool(task=True) handler (skipped when no task tools).
            JobsClaimWorkersStep(),
            # Issue #903 Phase 1B: A2A discovery + JSON-RPC routes are
            # NOT auto-mounted here — users opt in by calling
            # ``mesh.a2a.mount(app, path=...)`` on their own FastAPI
            # app (mirrors the @mesh.route UX). Heartbeat preparation
            # still picks up the @mesh.a2a metadata and emits
            # agent_type=a2a + the surfaces array on registration.
            # Note: Registry connection is handled in heartbeat pipeline for retry behavior
            # Note: FastAPI server will be started with uvicorn.run() after pipeline (or reused if discovered)
        ]

        self.add_steps(steps)
        self.logger.debug(f"Startup pipeline configured with {len(steps)} steps")
