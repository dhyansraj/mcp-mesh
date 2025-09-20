"""
Startup pipeline components for MCP Mesh.

Handles decorator collection, configuration, FastMCP server discovery,
and FastAPI server setup during mesh agent initialization.
"""

from .configuration import ConfigurationStep
from .decorator_collection import DecoratorCollectionStep
from .fastapiserver_setup import FastAPIServerSetupStep
from .fastmcpserver_discovery import FastMCPServerDiscoveryStep
from .heartbeat_loop import HeartbeatLoopStep
from .heartbeat_preparation import HeartbeatPreparationStep
from .startup_orchestrator import (
                                   MeshOrchestrator,
                                   clear_debounce_coordinator,
                                   get_debounce_coordinator,
                                   get_global_orchestrator,
                                   start_runtime,
)
from .startup_pipeline import StartupPipeline

__all__ = [
    "ConfigurationStep",
    "DecoratorCollectionStep",
    "FastAPIServerSetupStep",
    "FastMCPServerDiscoveryStep",
    "HeartbeatLoopStep",
    "HeartbeatPreparationStep",
    "MeshOrchestrator",
    "StartupPipeline",
    "clear_debounce_coordinator",
    "get_global_orchestrator",
    "get_debounce_coordinator",
    "start_runtime",
]
