//! Event types for communication between Rust core and language SDKs.
//!
//! Events are pushed from the Rust runtime to language SDKs via an async channel.
//! Language SDKs consume these events and update their internal state (e.g., dependency proxies).

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Health status of an agent.
#[pyclass(eq, eq_int)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HealthStatus {
    /// Agent is fully operational
    Healthy,
    /// Agent has reduced functionality
    Degraded,
    /// Agent is not operational
    Unhealthy,
}

#[pymethods]
impl HealthStatus {
    fn __repr__(&self) -> String {
        match self {
            HealthStatus::Healthy => "HealthStatus.Healthy".to_string(),
            HealthStatus::Degraded => "HealthStatus.Degraded".to_string(),
            HealthStatus::Unhealthy => "HealthStatus.Unhealthy".to_string(),
        }
    }

    fn __str__(&self) -> String {
        match self {
            HealthStatus::Healthy => "healthy".to_string(),
            HealthStatus::Degraded => "degraded".to_string(),
            HealthStatus::Unhealthy => "unhealthy".to_string(),
        }
    }

    /// Convert to registry API status string
    pub fn as_api_str(&self) -> &'static str {
        match self {
            HealthStatus::Healthy => "healthy",
            HealthStatus::Degraded => "degraded",
            HealthStatus::Unhealthy => "unhealthy",
        }
    }
}

impl Default for HealthStatus {
    fn default() -> Self {
        Self::Healthy
    }
}

/// Provider specification for LLM provider resolution event.
/// Note: Not using #[pyclass] to avoid GIL issues in tokio thread.
/// The fields are accessed directly in Python via MeshEvent.provider_info
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmProviderInfo {
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

/// Tool specification for LLM tools update event.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmToolInfo {
    /// Function name of the tool
    #[pyo3(get)]
    pub function_name: String,

    /// Capability name
    #[pyo3(get)]
    pub capability: String,

    /// Endpoint URL to call
    #[pyo3(get)]
    pub endpoint: String,

    /// Agent ID providing this tool
    #[pyo3(get)]
    pub agent_id: String,

    /// Input schema (serialized JSON string)
    #[pyo3(get)]
    pub input_schema: Option<String>,
}

#[pymethods]
impl LlmToolInfo {
    fn __repr__(&self) -> String {
        format!(
            "LlmToolInfo(function_name={:?}, capability={:?})",
            self.function_name, self.capability
        )
    }
}

/// Events emitted by the Rust core to language SDKs.
///
/// Language SDKs consume these events to update their internal state.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshEvent {
    /// Event type identifier
    #[pyo3(get)]
    pub event_type: String,

    // Fields for dependency events
    /// Capability name (for dependency events)
    #[pyo3(get)]
    pub capability: Option<String>,

    /// Endpoint URL (for dependency_available)
    #[pyo3(get)]
    pub endpoint: Option<String>,

    /// Function name to call (for dependency_available)
    #[pyo3(get)]
    pub function_name: Option<String>,

    /// Agent ID (for dependency events)
    #[pyo3(get)]
    pub agent_id: Option<String>,

    // Fields for LLM tools events
    /// Function ID of the LLM agent (for llm_tools_updated)
    #[pyo3(get)]
    pub function_id: Option<String>,

    /// List of available tools (for llm_tools_updated)
    #[pyo3(get)]
    pub tools: Option<Vec<LlmToolInfo>>,

    // Fields for LLM provider events
    /// Provider info (for llm_provider_available) - not exposed via #[pyo3(get)]
    /// because LlmProviderInfo is not a pyclass. Use get_provider_info() method instead.
    pub provider_info: Option<LlmProviderInfo>,

    // Fields for error/status events
    /// Error message (for error events)
    #[pyo3(get)]
    pub error: Option<String>,

    /// Health status (for health events)
    #[pyo3(get)]
    pub status: Option<HealthStatus>,

    /// Reason for event (for disconnect events)
    #[pyo3(get)]
    pub reason: Option<String>,
}

#[pymethods]
impl MeshEvent {
    fn __repr__(&self) -> String {
        format!("MeshEvent(event_type={:?})", self.event_type)
    }

    /// Get provider_info as a Python object with attributes.
    /// Returns None if no provider info, otherwise returns an object with
    /// function_id, agent_id, endpoint, function_name, and model attributes.
    #[getter]
    fn provider_info(&self, py: Python<'_>) -> PyResult<Option<PyObject>> {
        match &self.provider_info {
            Some(info) => {
                // Create a simple namespace-like object
                let provider_class = py.import("types")?.getattr("SimpleNamespace")?;
                let kwargs = pyo3::types::PyDict::new(py);
                kwargs.set_item("function_id", &info.function_id)?;
                kwargs.set_item("agent_id", &info.agent_id)?;
                kwargs.set_item("endpoint", &info.endpoint)?;
                kwargs.set_item("function_name", &info.function_name)?;
                kwargs.set_item("model", &info.model)?;
                let obj = provider_class.call((), Some(&kwargs))?;
                Ok(Some(obj.into()))
            }
            None => Ok(None),
        }
    }
}

impl MeshEvent {
    /// Create an "agent_registered" event
    pub fn agent_registered(agent_id: String) -> Self {
        Self {
            event_type: "agent_registered".to_string(),
            agent_id: Some(agent_id),
            capability: None,
            endpoint: None,
            function_name: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "registration_failed" event
    pub fn registration_failed(error: String) -> Self {
        Self {
            event_type: "registration_failed".to_string(),
            error: Some(error),
            agent_id: None,
            capability: None,
            endpoint: None,
            function_name: None,
            function_id: None,
            tools: None,
            provider_info: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "dependency_available" event
    pub fn dependency_available(
        capability: String,
        endpoint: String,
        function_name: String,
        agent_id: String,
    ) -> Self {
        Self {
            event_type: "dependency_available".to_string(),
            capability: Some(capability),
            endpoint: Some(endpoint),
            function_name: Some(function_name),
            agent_id: Some(agent_id),
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "dependency_unavailable" event
    pub fn dependency_unavailable(capability: String) -> Self {
        Self {
            event_type: "dependency_unavailable".to_string(),
            capability: Some(capability),
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "dependency_changed" event (endpoint or function changed)
    pub fn dependency_changed(
        capability: String,
        endpoint: String,
        function_name: String,
        agent_id: String,
    ) -> Self {
        Self {
            event_type: "dependency_changed".to_string(),
            capability: Some(capability),
            endpoint: Some(endpoint),
            function_name: Some(function_name),
            agent_id: Some(agent_id),
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create an "llm_tools_updated" event
    pub fn llm_tools_updated(function_id: String, tools: Vec<LlmToolInfo>) -> Self {
        Self {
            event_type: "llm_tools_updated".to_string(),
            function_id: Some(function_id),
            tools: Some(tools),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "health_check_due" event
    pub fn health_check_due() -> Self {
        Self {
            event_type: "health_check_due".to_string(),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "health_status_changed" event
    pub fn health_status_changed(status: HealthStatus) -> Self {
        Self {
            event_type: "health_status_changed".to_string(),
            status: Some(status),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            reason: None,
        }
    }

    /// Create a "registry_connected" event
    pub fn registry_connected() -> Self {
        Self {
            event_type: "registry_connected".to_string(),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create a "registry_disconnected" event
    pub fn registry_disconnected(reason: String) -> Self {
        Self {
            event_type: "registry_disconnected".to_string(),
            reason: Some(reason),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
        }
    }

    /// Create a "shutdown" event
    pub fn shutdown() -> Self {
        Self {
            event_type: "shutdown".to_string(),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            provider_info: None,
            error: None,
            status: None,
            reason: None,
        }
    }

    /// Create an "llm_provider_available" event
    pub fn llm_provider_available(provider_info: LlmProviderInfo) -> Self {
        Self {
            event_type: "llm_provider_available".to_string(),
            provider_info: Some(provider_info),
            capability: None,
            endpoint: None,
            function_name: None,
            agent_id: None,
            function_id: None,
            tools: None,
            error: None,
            status: None,
            reason: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dependency_available_event() {
        let event = MeshEvent::dependency_available(
            "date-service".to_string(),
            "http://localhost:9001".to_string(),
            "get_date".to_string(),
            "date-service-abc123".to_string(),
        );

        assert_eq!(event.event_type, "dependency_available");
        assert_eq!(event.capability, Some("date-service".to_string()));
        assert_eq!(event.endpoint, Some("http://localhost:9001".to_string()));
    }

    #[test]
    fn test_health_status_string() {
        assert_eq!(HealthStatus::Healthy.as_api_str(), "healthy");
        assert_eq!(HealthStatus::Degraded.as_api_str(), "degraded");
        assert_eq!(HealthStatus::Unhealthy.as_api_str(), "unhealthy");
    }
}
