"""MCP Mesh Core - Rust runtime for MCP Mesh agents.

This module is implemented in Rust and provides:
- AgentSpec: Configuration for agent registration
- AgentHandle: Handle to running agent runtime
- MeshEvent: Events from topology changes
- EventType: Type-safe event type enum
- start_agent: Start agent runtime
- Config resolution functions (ENV > param > default)
- Response parsing (JSON extraction, code fence stripping)
- Schema normalization (strict mode, sanitize, media detection)
- Trace context propagation (W3C trace/span IDs, header injection)
- MCP client helpers (JSON-RPC, SSE, tool calls)
- Provider helpers (output mode, system prompt, response format)
- Agentic loop (create, process, tool results, state)
"""

from .mcp_mesh_core import (
    AgentHandle,
    AgentSpec,
    DependencySpec,
    EventType,
    LlmAgentSpec,
    LlmToolInfo,
    MeshEvent,
    ToolSpec,
    add_tool_results_py,
    auto_detect_ip_py,
    build_jsonrpc_request_py,
    build_response_format_py,
    call_tool_py,
    create_agentic_loop_py,
    detect_media_params_py,
    determine_output_mode_py,
    extract_content_py,
    extract_json_py,
    extract_trace_context_py,
    filter_propagation_headers_py,
    format_system_prompt_py,
    generate_request_id_py,
    generate_span_id_py,
    generate_trace_id_py,
    get_default_py,
    get_env_var_py,
    get_loop_state_py,
    get_redis_url_py,
    get_tls_config_py,
    get_vendor_capabilities_py,
    init_trace_publisher_py,
    inject_trace_context_py,
    is_simple_schema_py,
    is_trace_publisher_available_py,
    is_tracing_enabled_py,
    make_schema_strict_py,
    matches_propagate_header_py,
    parse_sse_response_py,
    parse_sse_response_to_dict_py,
    prepare_tls_py,
    process_llm_response_py,
    publish_span_py,
    resolve_config_bool_py,
    resolve_config_int_py,
    resolve_config_py,
    sanitize_schema_py,
)
from .mcp_mesh_core import start_agent_py as start_agent
from .mcp_mesh_core import strip_code_fences_py

__all__ = [
    "AgentHandle",
    "AgentSpec",
    "DependencySpec",
    "EventType",
    "LlmAgentSpec",
    "LlmToolInfo",
    "MeshEvent",
    "ToolSpec",
    "start_agent",
    "add_tool_results_py",
    "auto_detect_ip_py",
    "build_jsonrpc_request_py",
    "build_response_format_py",
    "call_tool_py",
    "create_agentic_loop_py",
    "detect_media_params_py",
    "determine_output_mode_py",
    "extract_content_py",
    "extract_json_py",
    "extract_trace_context_py",
    "filter_propagation_headers_py",
    "format_system_prompt_py",
    "generate_request_id_py",
    "generate_span_id_py",
    "generate_trace_id_py",
    "get_default_py",
    "get_env_var_py",
    "get_loop_state_py",
    "get_redis_url_py",
    "get_tls_config_py",
    "get_vendor_capabilities_py",
    "init_trace_publisher_py",
    "inject_trace_context_py",
    "is_simple_schema_py",
    "is_trace_publisher_available_py",
    "is_tracing_enabled_py",
    "make_schema_strict_py",
    "matches_propagate_header_py",
    "parse_sse_response_py",
    "parse_sse_response_to_dict_py",
    "prepare_tls_py",
    "process_llm_response_py",
    "publish_span_py",
    "resolve_config_bool_py",
    "resolve_config_int_py",
    "resolve_config_py",
    "sanitize_schema_py",
    "strip_code_fences_py",
]
