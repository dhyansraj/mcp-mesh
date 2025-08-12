"""
MCP Mesh Pipeline Architecture

This module provides a clean, explicit pipeline-based architecture for processing
decorators and managing the mesh agent lifecycle. This replaces the scattered
async processing with a clear, sequential flow that can be easily tested and debugged.

Key Components:
- MeshPipeline: Main orchestrator that executes steps in sequence
- PipelineStep: Interface for individual processing steps
- PipelineResult: Result container with status and context
- Built-in steps for common operations (collection, config, heartbeat, etc.)
"""

from .mcp_heartbeat import (
                        DependencyResolutionStep,
                        HeartbeatSendStep,
                        RegistryConnectionStep,
)
from .shared import MeshPipeline, PipelineResult, PipelineStatus, PipelineStep
from .mcp_startup import (
                        ConfigurationStep,
                        DecoratorCollectionStep,
                        FastAPIServerSetupStep,
                        FastMCPServerDiscoveryStep,
                        HeartbeatLoopStep,
                        HeartbeatPreparationStep,
                        StartupPipeline,
)

__all__ = [
    "MeshPipeline",
    "PipelineResult",
    "PipelineStatus",
    "PipelineStep",
    "DecoratorCollectionStep",
    "ConfigurationStep",
    "FastAPIServerSetupStep",
    "FastMCPServerDiscoveryStep",
    "HeartbeatLoopStep",
    "HeartbeatPreparationStep",
    "RegistryConnectionStep",
    "HeartbeatSendStep",
    "DependencyResolutionStep",
    "StartupPipeline",
]
