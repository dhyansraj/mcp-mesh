//! Node.js/TypeScript bindings via napi-rs.
//!
//! This module provides bindings for the TypeScript SDK (@mcpmesh/sdk).
//! It mirrors the Python bindings but uses napi-rs instead of PyO3.

use napi::bindgen_prelude::*;
use napi_derive::napi;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::events::{EventType, HealthStatus, LlmToolInfo, MeshEvent};
use crate::handle::AgentHandle as RustAgentHandle;
use crate::spec::{AgentSpec as RustAgentSpec, DependencySpec as RustDependencySpec, ToolSpec as RustToolSpec};
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
            None, // llm_filter - not used in Phase 1
            None, // llm_provider - not used in Phase 1
            None, // kwargs
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
    /// Tools/capabilities provided by this agent
    pub tools: Vec<JsToolSpec>,
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
            Some(js.tools.into_iter().map(|t| t.into()).collect()),
            None, // llm_agents - not used in Phase 1
            js.heartbeat_interval as u64,
        )
    }
}

/// Mesh event for TypeScript.
#[napi(object)]
pub struct JsMeshEvent {
    /// Event type (e.g., "dependency_available", "agent_registered")
    pub event_type: String,
    /// Capability name (for dependency events)
    pub capability: Option<String>,
    /// Endpoint URL (for dependency_available)
    pub endpoint: Option<String>,
    /// Function name to call (for dependency_available)
    pub function_name: Option<String>,
    /// Agent ID (for dependency events)
    pub agent_id: Option<String>,
    /// Function ID of the LLM agent (for llm_tools_updated)
    pub function_id: Option<String>,
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
            function_id: event.function_id,
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
    /// Returns null when the runtime has shut down.
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

#[cfg(test)]
mod tests {
    use super::*;

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
            tools: vec![],
            heartbeat_interval: 5,
        };

        let rust_spec: RustAgentSpec = js_spec.into();
        assert_eq!(rust_spec.name, "test-agent");
        assert_eq!(rust_spec.http_port, 9000);
    }
}
