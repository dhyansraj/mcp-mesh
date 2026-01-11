"""MCP Mesh Core - Rust runtime for MCP Mesh agents.

This module is implemented in Rust and provides:
- AgentSpec: Configuration for agent registration
- AgentHandle: Handle to running agent runtime
- MeshEvent: Events from topology changes
- EventType: Type-safe event type enum
- start_agent: Start agent runtime
- Config resolution functions (ENV > param > default)
"""

# Tracing publish functions
# Config resolution functions
from .mcp_mesh_core import (AgentHandle, AgentSpec, DependencySpec, EventType,
                            LlmAgentSpec, LlmToolInfo, MeshEvent, ToolSpec,
                            auto_detect_ip_py, get_default_py, get_env_var_py,
                            get_redis_url_py, init_trace_publisher_py,
                            is_trace_publisher_available_py,
                            is_tracing_enabled_py, publish_span_py,
                            resolve_config_bool_py, resolve_config_int_py,
                            resolve_config_py)
from .mcp_mesh_core import start_agent_py as start_agent

__all__ = [
    "AgentSpec",
    "AgentHandle",
    "ToolSpec",
    "DependencySpec",
    "LlmAgentSpec",
    "LlmToolInfo",
    "MeshEvent",
    "EventType",
    "start_agent",
    # Config functions
    "resolve_config_py",
    "resolve_config_bool_py",
    "resolve_config_int_py",
    "is_tracing_enabled_py",
    "get_redis_url_py",
    "auto_detect_ip_py",
    "get_default_py",
    "get_env_var_py",
    # Tracing publish functions
    "init_trace_publisher_py",
    "publish_span_py",
    "is_trace_publisher_available_py",
]
