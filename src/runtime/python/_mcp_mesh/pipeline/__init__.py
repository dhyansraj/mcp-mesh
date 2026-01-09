"""
MCP Mesh Pipeline Architecture

This module provides a clean, explicit pipeline-based architecture for processing
decorators and managing the mesh agent lifecycle. The Rust core handles registry
communication including heartbeats, dependency resolution, and deregistration.

Key Components:
- MeshPipeline: Main orchestrator that executes steps in sequence
- PipelineStep: Interface for individual processing steps
- PipelineResult: Result container with status and context
- Built-in steps for common operations (collection, config, etc.)
"""

from .mcp_heartbeat import rust_heartbeat_task
from .mcp_startup import (ConfigurationStep, DecoratorCollectionStep,
                          FastAPIServerSetupStep, FastMCPServerDiscoveryStep,
                          HeartbeatLoopStep, HeartbeatPreparationStep,
                          StartupPipeline)
from .shared import MeshPipeline, PipelineResult, PipelineStatus, PipelineStep

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
    "StartupPipeline",
    "rust_heartbeat_task",
]
