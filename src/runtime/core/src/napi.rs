//! Node.js/TypeScript bindings via napi-rs.
//!
//! This module provides bindings for the TypeScript SDK (@mcpmesh/sdk).
//! It mirrors the Python bindings but uses napi-rs instead of PyO3.

use napi::bindgen_prelude::*;
use napi_derive::napi;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::events::{EventType, HealthStatus, LlmToolInfo, LlmProviderInfo, MeshEvent};
use crate::handle::AgentHandle as RustAgentHandle;
use crate::spec::{
    AgentSpec as RustAgentSpec, DependencySpec as RustDependencySpec,
    LlmAgentSpec as RustLlmAgentSpec, ToolSpec as RustToolSpec,
};
use crate::start_agent_internal;

/// Dependency specification for TypeScript.
#[napi(object)]
#[derive(Clone)]
pub struct JsDependencySpec {
    /// Capability name to depend on
    pub capability: String,
    /// Tags for filtering (e.g., ["+fast", "-deprecated"])
    pub tags: Vec<String>,
    /// Version constraint (e.g., ">=2.0.0")
    pub version: Option<String>,
}

impl From<JsDependencySpec> for RustDependencySpec {
    fn from(js: JsDependencySpec) -> Self {
        RustDependencySpec::new(js.capability, Some(js.tags), js.version)
    }
}

/// LLM agent specification for TypeScript.
/// Used to register LLM-powered tools with the mesh.
#[napi(object)]
#[derive(Clone)]
pub struct JsLlmAgentSpec {
    /// Unique identifier for this LLM function (matches the tool's function_name)
    pub function_id: String,
    /// Provider selector - serialized JSON string
    /// e.g., '{"capability": "llm", "tags": ["+claude"]}'
    pub provider: String,
    /// Tool filter specification - serialized JSON string
    /// e.g., '[{"capability": "calculator"}, {"tags": ["tools"]}]'
    pub filter: Option<String>,
    /// Filter mode: "all", "best_match", or "*"
    pub filter_mode: String,
    /// Maximum agentic loop iterations
    pub max_iterations: u32,
}

impl From<JsLlmAgentSpec> for RustLlmAgentSpec {
    fn from(js: JsLlmAgentSpec) -> Self {
        RustLlmAgentSpec::new(
            js.function_id,
            js.provider,
            js.filter,
            js.filter_mode,
            js.max_iterations,
        )
    }
}

/// LLM tool information returned in llm_tools_updated events.
/// Contains resolved tool metadata for LLM agents to use.
#[napi(object)]
#[derive(Clone)]
pub struct JsLlmToolInfo {
    /// Function name of the tool
    pub function_name: String,
    /// Capability name
    pub capability: String,
    /// Endpoint URL to call
    pub endpoint: String,
    /// Agent ID providing this tool
    pub agent_id: String,
    /// Input schema (serialized JSON string)
    pub input_schema: Option<String>,
}

impl From<LlmToolInfo> for JsLlmToolInfo {
    fn from(info: LlmToolInfo) -> Self {
        JsLlmToolInfo {
            function_name: info.function_name,
            capability: info.capability,
            endpoint: info.endpoint,
            agent_id: info.agent_id,
            input_schema: info.input_schema,
        }
    }
}

/// LLM provider information returned in llm_provider_available events.
#[napi(object)]
#[derive(Clone)]
pub struct JsLlmProviderInfo {
    /// Function ID of the LLM function that requested this provider
    pub function_id: String,
    /// Agent ID providing this capability
    pub agent_id: String,
    /// Endpoint URL to call
    pub endpoint: String,
    /// Function name to call
    pub function_name: String,
    /// Model name (optional)
    pub model: Option<String>,
}

impl From<LlmProviderInfo> for JsLlmProviderInfo {
    fn from(info: LlmProviderInfo) -> Self {
        JsLlmProviderInfo {
            function_id: info.function_id,
            agent_id: info.agent_id,
            endpoint: info.endpoint,
            function_name: info.function_name,
            model: info.model,
        }
    }
}

/// Tool specification for TypeScript.
#[napi(object)]
#[derive(Clone)]
pub struct JsToolSpec {
    /// Function name in the code
    pub function_name: String,
    /// Capability name for discovery
    pub capability: String,
    /// Version of this capability
    pub version: String,
    /// Tags for filtering
    pub tags: Vec<String>,
    /// Human-readable description
    pub description: String,
    /// Dependencies required by this tool
    pub dependencies: Vec<JsDependencySpec>,
    /// JSON Schema for input parameters (MCP format) - serialized JSON string
    pub input_schema: Option<String>,
    /// LLM filter specification (for @mesh.llm decorated functions) - serialized JSON string
    pub llm_filter: Option<String>,
    /// LLM provider specification (for mesh delegation) - serialized JSON string
    pub llm_provider: Option<String>,
}

impl From<JsToolSpec> for RustToolSpec {
    fn from(js: JsToolSpec) -> Self {
        RustToolSpec::new(
            js.function_name,
            js.capability,
            js.version,
            js.description,
            Some(js.tags),
            Some(js.dependencies.into_iter().map(|d| d.into()).collect()),
            js.input_schema,
            js.llm_filter,
            js.llm_provider,
            None, // kwargs - not needed for TypeScript
        )
    }
}

/// Agent specification for TypeScript.
#[napi(object)]
#[derive(Clone)]
pub struct JsAgentSpec {
    /// Unique agent name/identifier
    pub name: String,
    /// Agent version (semver)
    pub version: String,
    /// Human-readable description
    pub description: String,
    /// Registry URL (e.g., "http://localhost:8100")
    pub registry_url: String,
    /// HTTP port for this agent
    pub http_port: u16,
    /// HTTP host announced to registry
    pub http_host: String,
    /// Namespace for isolation
    pub namespace: String,
    /// Agent type: "mcp_agent" (provides capabilities) or "api" (only consumes)
    /// Defaults to "mcp_agent" if not specified
    pub agent_type: Option<String>,
    /// SDK runtime type: "python" or "typescript"
    /// Defaults to "typescript" for TypeScript SDK
    pub runtime: Option<String>,
    /// Tools/capabilities provided by this agent
    pub tools: Vec<JsToolSpec>,
    /// LLM agent specifications for tools using mesh.llm()
    pub llm_agents: Option<Vec<JsLlmAgentSpec>>,
    /// Heartbeat interval in seconds
    pub heartbeat_interval: u32,
}

impl From<JsAgentSpec> for RustAgentSpec {
    fn from(js: JsAgentSpec) -> Self {
        RustAgentSpec::new(
            js.name,
            js.registry_url,
            js.version,
            js.description,
            js.http_port,
            js.http_host,
            js.namespace,
            js.agent_type, // "mcp_agent" or "api", defaults to "mcp_agent"
            // Default to "typescript" for TypeScript SDK
            Some(js.runtime.unwrap_or_else(|| "typescript".to_string())),
            Some(js.tools.into_iter().map(|t| t.into()).collect()),
            js.llm_agents.map(|agents| agents.into_iter().map(|a| a.into()).collect()),
            js.heartbeat_interval as u64,
        )
    }
}

/// Mesh event for TypeScript.
#[napi(object)]
pub struct JsMeshEvent {
    /// Event type (e.g., "dependency_available", "agent_registered", "llm_tools_updated")
    pub event_type: String,
    /// Capability name (for dependency events)
    pub capability: Option<String>,
    /// Endpoint URL (for dependency_available)
    pub endpoint: Option<String>,
    /// Function name to call (for dependency_available)
    pub function_name: Option<String>,
    /// Agent ID (for dependency events)
    pub agent_id: Option<String>,
    /// Function that requested this dependency (for dependency events)
    /// This is the tool/function that declared the dependency.
    pub requesting_function: Option<String>,
    /// Dependency index within the requesting function (for dependency events)
    /// This allows SDKs to inject the resolved dependency at the correct position.
    pub dep_index: Option<u32>,
    /// Function ID of the LLM agent (for llm_tools_updated, llm_provider_available)
    pub function_id: Option<String>,
    /// List of available tools (for llm_tools_updated event)
    pub tools: Option<Vec<JsLlmToolInfo>>,
    /// Provider info (for llm_provider_available event)
    pub provider_info: Option<JsLlmProviderInfo>,
    /// Error message (for error events)
    pub error: Option<String>,
    /// Reason for event (for disconnect events)
    pub reason: Option<String>,
}

impl From<MeshEvent> for JsMeshEvent {
    fn from(event: MeshEvent) -> Self {
        JsMeshEvent {
            event_type: event.event_type.as_str().to_string(),
            capability: event.capability,
            endpoint: event.endpoint,
            function_name: event.function_name,
            agent_id: event.agent_id,
            requesting_function: event.requesting_function,
            dep_index: event.dep_index,
            function_id: event.function_id,
            tools: event.tools.map(|t| t.into_iter().map(|info| info.into()).collect()),
            provider_info: event.provider_info.map(|p| p.into()),
            error: event.error,
            reason: event.reason,
        }
    }
}

/// Handle to a running agent runtime (TypeScript wrapper).
#[napi]
pub struct JsAgentHandle {
    inner: Arc<Mutex<RustAgentHandle>>,
}

#[napi]
impl JsAgentHandle {
    /// Wait for and return the next mesh event.
    ///
    /// This is an async method that blocks until an event is available.
    /// Returns a JsMeshEvent with eventType "shutdown" when the runtime has shut down.
    #[napi]
    pub async fn next_event(&self) -> Result<JsMeshEvent> {
        let handle = self.inner.lock().await;

        // Get the event receiver from the handle via the accessor method
        let event_rx = handle.event_rx();
        drop(handle); // Release the lock before awaiting

        let mut rx = event_rx.lock().await;
        match rx.recv().await {
            Some(event) => Ok(event.into()),
            None => Ok(MeshEvent::shutdown().into()),
        }
    }

    /// Get current dependency endpoints.
    ///
    /// Returns an object mapping capability names to endpoint URLs.
    #[napi]
    pub async fn get_dependencies(&self) -> Result<HashMap<String, String>> {
        let handle = self.inner.lock().await;
        Ok(handle.get_dependencies_internal())
    }

    /// Get current agent health status.
    #[napi]
    pub async fn get_status(&self) -> Result<String> {
        let handle = self.inner.lock().await;
        Ok(handle.get_status_internal().as_api_str().to_string())
    }

    /// Get the agent ID assigned by the registry.
    #[napi]
    pub async fn get_agent_id(&self) -> Result<Option<String>> {
        let handle = self.inner.lock().await;
        Ok(handle.get_agent_id_internal())
    }

    /// Check if shutdown has been requested.
    #[napi]
    pub async fn is_shutdown_requested(&self) -> Result<bool> {
        let handle = self.inner.lock().await;
        Ok(handle.is_shutdown_requested_internal())
    }

    /// Request graceful shutdown of the agent runtime.
    #[napi]
    pub async fn shutdown(&self) -> Result<()> {
        let handle = self.inner.lock().await;
        handle.shutdown_async().await;
        Ok(())
    }

    /// Update the tools/routes registered with the registry.
    ///
    /// Uses smart diffing - only triggers a heartbeat if tools have changed.
    /// Call this after Express route introspection to update route names
    /// from placeholders (e.g., "route_0_UNKNOWN:UNKNOWN") to proper names
    /// (e.g., "GET:/time").
    ///
    /// @param tools - Array of tool specifications with updated function names
    /// @returns true if the update was sent successfully
    #[napi]
    pub async fn update_tools(&self, tools: Vec<JsToolSpec>) -> Result<bool> {
        let handle = self.inner.lock().await;
        let rust_tools: Vec<crate::spec::ToolSpec> = tools.into_iter().map(|t| t.into()).collect();
        Ok(handle.update_tools_async(rust_tools).await)
    }

    /// Update the HTTP port (e.g., after auto-detection from Express).
    ///
    /// @param port - The detected HTTP port
    /// @returns true if the update was sent successfully
    #[napi]
    pub async fn update_port(&self, port: u16) -> Result<bool> {
        let handle = self.inner.lock().await;
        Ok(handle.update_port_async(port).await)
    }
}

/// Start an agent runtime with the given specification.
///
/// This spawns a background Tokio runtime that handles:
/// - Registration with the mesh registry
/// - Periodic heartbeats
/// - Topology change detection
/// - Event streaming
#[napi]
pub fn start_agent(spec: JsAgentSpec) -> Result<JsAgentHandle> {
    crate::init_logging();

    let rust_spec: RustAgentSpec = spec.into();

    match start_agent_internal(rust_spec) {
        Ok(handle) => Ok(JsAgentHandle {
            inner: Arc::new(Mutex::new(handle)),
        }),
        Err(e) => Err(Error::from_reason(e)),
    }
}

// =============================================================================
// Config resolution functions
// =============================================================================

/// Resolve configuration value with priority: ENV > param > default.
///
/// @param keyName - Config key (e.g., "registry_url", "http_host", "namespace")
/// @param paramValue - Optional value from code/config
/// @returns Resolved value or empty string if unknown key
#[napi]
pub fn resolve_config(key_name: String, param_value: Option<String>) -> String {
    crate::config::resolve_config_by_name(&key_name, param_value.as_deref())
}

/// Resolve boolean configuration value with priority: ENV > param > default.
///
/// @param keyName - Config key (e.g., "distributed_tracing_enabled")
/// @param paramValue - Optional value from code/config
/// @returns Resolved boolean value
#[napi]
pub fn resolve_config_bool(key_name: String, param_value: Option<bool>) -> bool {
    match crate::config::ConfigKey::from_name(&key_name) {
        Some(key) => crate::config::resolve_config_bool(key, param_value),
        None => false,
    }
}

/// Resolve integer configuration value with priority: ENV > param > default.
///
/// @param keyName - Config key (e.g., "http_port", "health_interval")
/// @param paramValue - Optional value from code/config
/// @returns Resolved integer value or null if unknown key
#[napi]
pub fn resolve_config_int(key_name: String, param_value: Option<i64>) -> Option<i64> {
    match crate::config::ConfigKey::from_name(&key_name) {
        Some(key) => crate::config::resolve_config_int(key, param_value),
        None => None,
    }
}

/// Check if distributed tracing is enabled.
///
/// Checks MCP_MESH_DISTRIBUTED_TRACING_ENABLED environment variable.
#[napi]
pub fn is_tracing_enabled() -> bool {
    crate::config::is_tracing_enabled()
}

/// Get Redis URL with fallback to default (redis://localhost:6379).
#[napi]
pub fn get_redis_url() -> String {
    crate::config::get_redis_url()
}

/// Auto-detect external IP address.
///
/// Uses UDP socket trick to find the IP that would route to external networks.
/// Falls back to "localhost" if detection fails.
#[napi]
pub fn auto_detect_ip() -> String {
    crate::config::auto_detect_external_ip()
}

/// Get the default value for a configuration key.
///
/// This allows SDKs to retrieve default values without doing full resolution,
/// useful for documentation, type hints, and avoiding duplicate default definitions.
///
/// @param keyName - Config key (e.g., "registry_url", "namespace", "health_interval")
/// @returns Default value if the key is known and has a default, null otherwise.
#[napi]
pub fn get_default(key_name: String) -> Option<String> {
    crate::config::get_default_by_name(&key_name)
}

/// Get the environment variable name for a configuration key.
///
/// @param keyName - Config key (e.g., "registry_url", "namespace")
/// @returns Environment variable name if the key is known, null otherwise.
#[napi]
pub fn get_env_var(key_name: String) -> Option<String> {
    crate::config::get_env_var_by_name(&key_name)
}

// =============================================================================
// Tracing publish functions
// =============================================================================

/// Initialize the trace publisher.
///
/// Must be called before publishing spans. Checks if tracing is enabled
/// and initializes Redis connection.
///
/// @returns true if tracing is enabled and Redis is available, false otherwise.
#[napi]
pub async fn init_trace_publisher() -> Result<bool> {
    Ok(crate::tracing_publish::init_trace_publisher().await)
}

/// Publish a trace span to Redis.
///
/// Publishes span data to the `mesh:trace` Redis stream.
/// Non-blocking - silently handles failures to never break agent operations.
///
/// @param spanData - Map of span data (all values must be strings)
/// @returns true if published successfully, false otherwise.
#[napi]
pub async fn publish_span(span_data: HashMap<String, String>) -> Result<bool> {
    Ok(crate::tracing_publish::publish_span(span_data).await)
}

/// Check if trace publishing is available.
///
/// @returns true if tracing is enabled and Redis is connected.
#[napi]
pub async fn is_trace_publisher_available() -> Result<bool> {
    Ok(crate::tracing_publish::is_trace_publisher_available().await)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::AgentType;

    #[test]
    fn test_js_spec_conversion() {
        let js_spec = JsAgentSpec {
            name: "test-agent".to_string(),
            version: "1.0.0".to_string(),
            description: "Test agent".to_string(),
            registry_url: "http://localhost:8100".to_string(),
            http_port: 9000,
            http_host: "localhost".to_string(),
            namespace: "default".to_string(),
            agent_type: None, // defaults to mcp_agent
            tools: vec![],
            llm_agents: None,
            heartbeat_interval: 5,
        };

        let rust_spec: RustAgentSpec = js_spec.into();
        assert_eq!(rust_spec.name, "test-agent");
        assert_eq!(rust_spec.http_port, 9000);
        assert_eq!(rust_spec.agent_type, AgentType::McpAgent);
    }

    #[test]
    fn test_js_spec_api_type() {
        let js_spec = JsAgentSpec {
            name: "api-service".to_string(),
            version: "1.0.0".to_string(),
            description: "API service".to_string(),
            registry_url: "http://localhost:8100".to_string(),
            http_port: 0, // port doesn't matter for API
            http_host: "localhost".to_string(),
            namespace: "default".to_string(),
            agent_type: Some("api".to_string()), // API agent type
            tools: vec![],
            llm_agents: None,
            heartbeat_interval: 5,
        };

        let rust_spec: RustAgentSpec = js_spec.into();
        assert_eq!(rust_spec.agent_type, AgentType::Api);
        assert_eq!(rust_spec.http_port, 0);
    }

    #[test]
    fn test_js_llm_agent_spec_conversion() {
        let js_llm_spec = JsLlmAgentSpec {
            function_id: "assist".to_string(),
            provider: r#"{"capability": "llm", "tags": ["+claude"]}"#.to_string(),
            filter: Some(r#"[{"capability": "calculator"}]"#.to_string()),
            filter_mode: "all".to_string(),
            max_iterations: 10,
        };

        let rust_llm_spec: RustLlmAgentSpec = js_llm_spec.into();
        assert_eq!(rust_llm_spec.function_id, "assist");
        assert_eq!(rust_llm_spec.filter_mode, "all");
        assert_eq!(rust_llm_spec.max_iterations, 10);
    }

    #[test]
    fn test_js_spec_with_llm_agents() {
        let js_spec = JsAgentSpec {
            name: "llm-agent".to_string(),
            version: "1.0.0".to_string(),
            description: "LLM agent".to_string(),
            registry_url: "http://localhost:8100".to_string(),
            http_port: 9003,
            http_host: "localhost".to_string(),
            namespace: "default".to_string(),
            agent_type: None,
            tools: vec![JsToolSpec {
                function_name: "assist".to_string(),
                capability: "smart_assistant".to_string(),
                version: "1.0.0".to_string(),
                tags: vec!["llm".to_string()],
                description: "LLM-powered assistant".to_string(),
                dependencies: vec![],
                input_schema: None,
                llm_filter: Some(r#"[{"capability": "calculator"}]"#.to_string()),
                llm_provider: Some(r#"{"capability": "llm"}"#.to_string()),
            }],
            llm_agents: Some(vec![JsLlmAgentSpec {
                function_id: "assist".to_string(),
                provider: r#"{"capability": "llm"}"#.to_string(),
                filter: Some(r#"[{"capability": "calculator"}]"#.to_string()),
                filter_mode: "all".to_string(),
                max_iterations: 10,
            }]),
            heartbeat_interval: 5,
        };

        let rust_spec: RustAgentSpec = js_spec.into();
        assert_eq!(rust_spec.name, "llm-agent");
        assert_eq!(rust_spec.tools.len(), 1);
        assert_eq!(rust_spec.llm_agents.len(), 1);
        assert_eq!(rust_spec.llm_agents[0].function_id, "assist");
    }
}
