"""MCP Mesh Core - Rust runtime for MCP Mesh agents.

This module is implemented in Rust and provides:
- AgentSpec: Configuration for agent registration
- AgentHandle: Handle to running agent runtime
- MeshEvent: Events from topology changes
- start_agent: Start agent runtime
"""

from .mcp_mesh_core import (AgentHandle, AgentSpec, DependencySpec,
                            HealthStatus, LlmAgentSpec, LlmToolInfo, MeshEvent,
                            ToolSpec, start_agent)

__all__ = [
    "AgentSpec",
    "AgentHandle",
    "ToolSpec",
    "DependencySpec",
    "LlmAgentSpec",
    "LlmToolInfo",
    "MeshEvent",
    "HealthStatus",
    "start_agent",
]
