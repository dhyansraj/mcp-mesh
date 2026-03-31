//! MCP Mesh Core - Rust runtime for MCP Mesh agents.
//!
//! This crate provides the core runtime functionality for MCP Mesh agents:
//! - Agent startup and registration
//! - Heartbeat loop (fast HEAD + conditional POST)
//! - Topology management and change detection
//! - Event streaming to language SDKs
//!
//! # Architecture
//!
//! ```text
//! Language SDK                   Rust Core
//! ───────────────────────────────────────────
//! Decorators          →
//! Metadata collection →          AgentSpec
//!                                ↓
//!                               start_agent()
//!                                ↓
//!                               AgentRuntime
//!                                ├─ HeartbeatLoop
//!                                ├─ RegistryClient
//!                                └─ TopologyManager
//!                                ↓
//! Event listener      ←         EventStream
//! DI updates          ←         MeshEvent
//! ```
//!
//! # Features
//!
//! - `python` (default): Enable Python bindings via PyO3
//! - `typescript`: Enable TypeScript/Node.js bindings via napi-rs
//! - `ffi`: Enable C FFI bindings for multi-language SDK support

pub mod agentic_loop;
pub mod config;
pub mod events;
pub mod handle;
pub mod heartbeat;
pub mod registry;
pub mod response_parser;
pub mod runtime;
pub mod provider;
pub mod schema;
pub mod spec;
pub mod tls;
pub mod mcp_client;
pub mod trace_context;
pub mod tracing_publish;
pub mod vault;
#[cfg(feature = "spire")]
pub mod spire;

// C FFI bindings module
pub mod ffi;

// Node.js/TypeScript bindings module (napi-rs)
#[cfg(feature = "typescript")]
pub mod napi;

#[cfg(feature = "python")]
use pyo3::prelude::*;

use std::sync::Arc;
use std::thread;
use tokio::sync::RwLock;
use tracing::info;
use tracing_subscriber::EnvFilter;

use events::{EventType, HealthStatus, LlmToolInfo, MeshEvent};
use handle::{AgentHandle, HandleState};
use runtime::RuntimeConfig;
use spec::{AgentSpec, DependencySpec, LlmAgentSpec, ToolSpec};

/// Initialize logging with tracing.
///
/// Uses RUST_LOG environment variable for configuration.
/// Falls back to info level for mcp_mesh_core if not set.
pub fn init_logging() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::from_default_env()
                .add_directive("mcp_mesh_core=info".parse().expect("hardcoded tracing directive must be valid")),
        )
        .try_init();
}

/// Start an agent runtime with the given specification.
///
/// This spawns a background Tokio runtime that handles:
/// - Registration with the mesh registry
/// - Periodic heartbeats
/// - Topology change detection
/// - Event streaming
///
/// # Arguments
/// * `spec` - Agent specification including name, capabilities, dependencies
///
/// # Returns
/// Handle to the running agent runtime
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (spec))]
fn start_agent_py(_py: Python<'_>, spec: AgentSpec) -> PyResult<AgentHandle> {
    init_logging();
    start_agent_internal(spec).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
}

/// Internal agent start function (language-agnostic).
///
/// This is the core implementation used by both Python bindings and FFI.
pub fn start_agent_internal(spec: AgentSpec) -> Result<AgentHandle, String> {
    info!("Starting agent '{}' with Rust core", spec.name);

    // Create runtime config from spec
    let config = RuntimeConfig {
        heartbeat: heartbeat::HeartbeatConfig {
            interval: std::time::Duration::from_secs(spec.heartbeat_interval),
            ..Default::default()
        },
        ..Default::default()
    };

    // We need to spawn a tokio runtime in a background thread
    // because Python's asyncio and tokio don't mix well in the same thread
    let (event_rx, shared_state, shutdown_tx, command_tx) = {
        // Create channels that will be used by both the spawned thread and the handle
        let (event_tx, event_rx) = tokio::sync::mpsc::channel(config.event_buffer_size);
        let (shutdown_tx, shutdown_rx) = tokio::sync::mpsc::channel(1);
        let (command_tx, command_rx) = tokio::sync::mpsc::channel::<runtime::RuntimeCommand>(10);
        let shared_state = Arc::new(RwLock::new(HandleState::default()));

        let spec_clone = spec.clone();
        let config_clone = config.clone();
        let event_tx_clone = event_tx;
        let shared_state_clone = shared_state.clone();

        // Spawn background thread with tokio runtime
        thread::spawn(move || {
            // Initialize Python in this thread to allow PyO3 object creation
            #[cfg(feature = "python")]
            {
                // Ensure Python is attached to this thread for PyO3 operations
                pyo3::Python::attach(|_| {});
            }

            let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
            rt.block_on(async {
                match runtime::AgentRuntime::new(
                    spec_clone,
                    config_clone,
                    event_tx_clone,
                    shared_state_clone,
                    shutdown_rx,
                    command_rx,
                ).await {
                    Ok(agent_runtime) => {
                        agent_runtime.run().await;
                    }
                    Err(e) => {
                        tracing::error!("Failed to create agent runtime: {}", e);
                    }
                }
            });
        });

        (event_rx, shared_state, shutdown_tx, command_tx)
    };

    // Create the handle
    let handle = AgentHandle::new(event_rx, shared_state, shutdown_tx, command_tx);

    Ok(handle)
}

/// Extract JSON from LLM response text (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn extract_json_py(text: &str) -> Option<String> {
    response_parser::extract_json(text)
}

/// Strip markdown code fences from content (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn strip_code_fences_py(text: &str) -> String {
    response_parser::strip_code_fences(text)
}

/// Make a JSON schema strict for structured output (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (schema_json, add_all_required=true))]
fn make_schema_strict_py(schema_json: &str, add_all_required: bool) -> PyResult<String> {
    schema::make_schema_strict(schema_json, add_all_required)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Sanitize a JSON schema by removing unsupported validation keywords (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn sanitize_schema_py(schema_json: &str) -> PyResult<String> {
    schema::sanitize_schema(schema_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Check if any tool schema property contains x-media-type (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn detect_media_params_py(schema_json: &str) -> bool {
    schema::detect_media_params(schema_json)
}

/// Check if a JSON schema is simple enough for hint mode (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn is_simple_schema_py(schema_json: &str) -> bool {
    schema::is_simple_schema(schema_json)
}

/// Generate OpenTelemetry-compliant trace ID (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn generate_trace_id_py() -> String {
    trace_context::generate_trace_id()
}

/// Generate OpenTelemetry-compliant span ID (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn generate_span_id_py() -> String {
    trace_context::generate_span_id()
}

/// Inject trace context into JSON-RPC arguments (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (args_json, trace_id, span_id, propagated_headers_json=None))]
fn inject_trace_context_py(args_json: &str, trace_id: &str, span_id: &str, propagated_headers_json: Option<&str>) -> PyResult<String> {
    trace_context::inject_trace_context(args_json, trace_id, span_id, propagated_headers_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Extract trace context from HTTP headers with body fallback (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (headers_json, body_json=None))]
fn extract_trace_context_py(headers_json: &str, body_json: Option<&str>) -> String {
    trace_context::extract_trace_context(headers_json, body_json)
}

/// Filter headers by propagation allowlist (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn filter_propagation_headers_py(headers_json: &str, allowlist_csv: &str) -> PyResult<String> {
    trace_context::filter_propagation_headers(headers_json, allowlist_csv)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Check if a header matches the propagation allowlist (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn matches_propagate_header_py(header_name: &str, allowlist_csv: &str) -> bool {
    trace_context::matches_propagate_header(header_name, allowlist_csv)
}

// =============================================================================
// Provider (Python bindings)
// =============================================================================

/// Determine output mode for a vendor given the context (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (provider, is_string_type, has_tools, override_mode=None))]
fn determine_output_mode_py(provider: &str, is_string_type: bool, has_tools: bool, override_mode: Option<&str>) -> String {
    provider::determine_output_mode(provider, is_string_type, has_tools, override_mode)
}

/// Build complete system prompt with vendor-specific additions (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (provider, base_prompt, has_tools, has_media_params, schema_json=None, schema_name=None, output_mode="text"))]
fn format_system_prompt_py(provider: &str, base_prompt: &str, has_tools: bool, has_media_params: bool, schema_json: Option<&str>, schema_name: Option<&str>, output_mode: &str) -> String {
    provider::format_system_prompt(provider, base_prompt, has_tools, has_media_params, schema_json, schema_name, output_mode)
}

/// Build response_format JSON object for structured output (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn build_response_format_py(provider: &str, schema_json: &str, schema_name: &str, has_tools: bool) -> Option<String> {
    provider::build_response_format(provider, schema_json, schema_name, has_tools)
}

/// Get vendor capabilities as JSON (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn get_vendor_capabilities_py(provider: &str) -> String {
    provider::get_vendor_capabilities(provider)
}

// =============================================================================
// MCP Client (Python bindings)
// =============================================================================

/// Build a JSON-RPC 2.0 request envelope (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn build_jsonrpc_request_py(method: &str, params_json: &str, request_id: &str) -> PyResult<String> {
    mcp_client::build_jsonrpc_request(method, params_json, request_id)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Generate a unique request ID (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn generate_request_id_py() -> String {
    mcp_client::generate_request_id()
}

/// Parse SSE or plain JSON response (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn parse_sse_response_py(response_text: &str) -> PyResult<String> {
    mcp_client::parse_sse_response(response_text)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Extract text content from MCP CallToolResult (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn extract_content_py(result_json: &str) -> PyResult<String> {
    mcp_client::extract_content(result_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Call a remote MCP tool via HTTP POST with retry (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (endpoint, tool_name, args_json=None, headers_json=None, timeout_ms=30000, max_retries=1))]
fn call_tool_py(
    py: Python<'_>,
    endpoint: &str,
    tool_name: &str,
    args_json: Option<&str>,
    headers_json: Option<&str>,
    timeout_ms: u64,
    max_retries: u32,
) -> PyResult<String> {
    let endpoint = endpoint.to_string();
    let tool_name = tool_name.to_string();
    let args = args_json.map(|s| s.to_string());
    let headers = headers_json.map(|s| s.to_string());

    pyo3_async_runtimes::tokio::get_runtime().block_on(py.allow_threads(|| async {
        mcp_client::call_tool(
            &endpoint, &tool_name,
            args.as_deref(), headers.as_deref(),
            timeout_ms, max_retries,
        ).await.map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }))
}

// =============================================================================
// Agentic Loop (Python bindings)
// =============================================================================

/// Create initial agentic loop state (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn create_agentic_loop_py(config_json: &str) -> PyResult<String> {
    agentic_loop::create_loop(config_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Process an LLM response in the agentic loop (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn process_llm_response_py(state_json: &str, llm_response_json: &str) -> PyResult<String> {
    agentic_loop::process_response(state_json, llm_response_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Add tool results to the agentic loop (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn add_tool_results_py(state_json: &str, tool_results_json: &str) -> PyResult<String> {
    agentic_loop::add_tool_results(state_json, tool_results_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Get loop state for debugging/logging (Python binding).
#[cfg(feature = "python")]
#[pyfunction]
fn get_loop_state_py(state_json: &str) -> PyResult<String> {
    agentic_loop::get_loop_state(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// MCP Mesh Core Python module.
#[cfg(feature = "python")]
#[pymodule]
fn mcp_mesh_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Initialize logging on module import
    init_logging();

    // Register types
    m.add_class::<AgentSpec>()?;
    m.add_class::<ToolSpec>()?;
    m.add_class::<DependencySpec>()?;
    m.add_class::<LlmAgentSpec>()?;
    m.add_class::<AgentHandle>()?;
    m.add_class::<MeshEvent>()?;
    m.add_class::<LlmToolInfo>()?;
    m.add_class::<EventType>()?;
    m.add_class::<HealthStatus>()?;

    // Register functions - use the Python wrapper
    m.add_function(wrap_pyfunction!(start_agent_py, m)?)?;

    // Config resolution functions (defined in config.rs)
    m.add_function(wrap_pyfunction!(config::resolve_config_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::resolve_config_bool_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::resolve_config_int_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::is_tracing_enabled_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::get_redis_url_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::auto_detect_ip_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::get_default_py, m)?)?;
    m.add_function(wrap_pyfunction!(config::get_env_var_py, m)?)?;

    // TLS configuration
    m.add_function(wrap_pyfunction!(tls::get_tls_config_py, m)?)?;
    m.add_function(wrap_pyfunction!(tls::prepare_tls_py, m)?)?;

    // Tracing publish functions (defined in tracing_publish.rs)
    m.add_function(wrap_pyfunction!(tracing_publish::init_trace_publisher_py, m)?)?;
    m.add_function(wrap_pyfunction!(tracing_publish::publish_span_py, m)?)?;
    m.add_function(wrap_pyfunction!(tracing_publish::is_trace_publisher_available_py, m)?)?;

    // Response parsing
    m.add_function(wrap_pyfunction!(extract_json_py, m)?)?;
    m.add_function(wrap_pyfunction!(strip_code_fences_py, m)?)?;

    // Schema normalization
    m.add_function(wrap_pyfunction!(make_schema_strict_py, m)?)?;
    m.add_function(wrap_pyfunction!(sanitize_schema_py, m)?)?;
    m.add_function(wrap_pyfunction!(detect_media_params_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_simple_schema_py, m)?)?;

    // Trace context
    m.add_function(wrap_pyfunction!(generate_trace_id_py, m)?)?;
    m.add_function(wrap_pyfunction!(generate_span_id_py, m)?)?;
    m.add_function(wrap_pyfunction!(inject_trace_context_py, m)?)?;
    m.add_function(wrap_pyfunction!(extract_trace_context_py, m)?)?;
    m.add_function(wrap_pyfunction!(filter_propagation_headers_py, m)?)?;
    m.add_function(wrap_pyfunction!(matches_propagate_header_py, m)?)?;

    // MCP Client
    m.add_function(wrap_pyfunction!(build_jsonrpc_request_py, m)?)?;
    m.add_function(wrap_pyfunction!(generate_request_id_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_sse_response_py, m)?)?;
    m.add_function(wrap_pyfunction!(extract_content_py, m)?)?;
    m.add_function(wrap_pyfunction!(call_tool_py, m)?)?;

    // Provider
    m.add_function(wrap_pyfunction!(determine_output_mode_py, m)?)?;
    m.add_function(wrap_pyfunction!(format_system_prompt_py, m)?)?;
    m.add_function(wrap_pyfunction!(build_response_format_py, m)?)?;
    m.add_function(wrap_pyfunction!(get_vendor_capabilities_py, m)?)?;

    // Agentic Loop
    m.add_function(wrap_pyfunction!(create_agentic_loop_py, m)?)?;
    m.add_function(wrap_pyfunction!(process_llm_response_py, m)?)?;
    m.add_function(wrap_pyfunction!(add_tool_results_py, m)?)?;
    m.add_function(wrap_pyfunction!(get_loop_state_py, m)?)?;

    Ok(())
}
