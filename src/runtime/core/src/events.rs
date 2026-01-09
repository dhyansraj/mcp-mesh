//! Event types for communication between Rust core and language SDKs.
//!
//! Events are pushed from the Rust runtime to language SDKs via an async channel.
//! Language SDKs consume these events and update their internal state (e.g., dependency proxies).

#[cfg(feature = "python")]
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Type of mesh event.
///
/// This enum provides type-safe event identification.
/// Serializes to snake_case strings for backwards compatibility with language SDKs.
#[cfg_attr(feature = "python", pyclass(eq, eq_int))]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    /// Agent successfully registered with the mesh registry
    AgentRegistered,
    /// Agent registration failed
    RegistrationFailed,
    /// A dependency became available
    DependencyAvailable,
    /// A dependency became unavailable
    DependencyUnavailable,
    /// A dependency's endpoint or function changed
    DependencyChanged,
    /// LLM tools list was updated
    LlmToolsUpdated,
    /// Health check is due (SDK should run health checks)
    HealthCheckDue,
    /// Agent health status changed
    HealthStatusChanged,
    /// Connected to registry
    RegistryConnected,
    /// Disconnected from registry
    RegistryDisconnected,
    /// Agent runtime is shutting down
    #[default]
    Shutdown,
    /// LLM provider became available
    LlmProviderAvailable,
}

#[cfg_attr(feature = "python", pymethods)]
impl EventType {
    fn __repr__(&self) -> String {
        format!("EventType.{:?}", self)
    }

    fn __str__(&self) -> String {
        self.as_str().to_string()
    }
}

impl EventType {
    /// Convert to the string representation used in serialization.
    pub fn as_str(&self) -> &'static str {
        match self {
            EventType::AgentRegistered => "agent_registered",
            EventType::RegistrationFailed => "registration_failed",
            EventType::DependencyAvailable => "dependency_available",
            EventType::DependencyUnavailable => "dependency_unavailable",
            EventType::DependencyChanged => "dependency_changed",
            EventType::LlmToolsUpdated => "llm_tools_updated",
            EventType::HealthCheckDue => "health_check_due",
            EventType::HealthStatusChanged => "health_status_changed",
            EventType::RegistryConnected => "registry_connected",
            EventType::RegistryDisconnected => "registry_disconnected",
            EventType::Shutdown => "shutdown",
            EventType::LlmProviderAvailable => "llm_provider_available",
        }
    }
}

/// Health status of an agent.
#[cfg_attr(feature = "python", pyclass(eq, eq_int))]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HealthStatus {
    /// Agent is fully operational
    Healthy,
    /// Agent has reduced functionality
    Degraded,
    /// Agent is not operational
    Unhealthy,
}

#[cfg_attr(feature = "python", pymethods)]
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
#[cfg_attr(feature = "python", pyclass(get_all))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmToolInfo {
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

#[cfg(feature = "python")]
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
/// Note: Using manual getters instead of get_all because provider_info needs custom handling.
#[cfg_attr(feature = "python", pyclass)]
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MeshEvent {
    /// Event type identifier
    pub event_type: EventType,

    // Fields for dependency events
    /// Capability name (for dependency events)
    pub capability: Option<String>,

    /// Endpoint URL (for dependency_available)
    pub endpoint: Option<String>,

    /// Function name to call (for dependency_available)
    pub function_name: Option<String>,

    /// Agent ID (for dependency events)
    pub agent_id: Option<String>,

    // Fields for LLM tools events
    /// Function ID of the LLM agent (for llm_tools_updated)
    pub function_id: Option<String>,

    /// List of available tools (for llm_tools_updated)
    pub tools: Option<Vec<LlmToolInfo>>,

    // Fields for LLM provider events
    /// Provider info (for llm_provider_available) - accessed via get_provider_info() in Python
    pub provider_info: Option<LlmProviderInfo>,

    // Fields for error/status events
    /// Error message (for error events)
    pub error: Option<String>,

    /// Health status (for health events)
    pub status: Option<HealthStatus>,

    /// Reason for event (for disconnect events)
    pub reason: Option<String>,
}

#[cfg(feature = "python")]
#[pymethods]
impl MeshEvent {
    fn __repr__(&self) -> String {
        format!("MeshEvent(event_type={:?})", self.event_type)
    }

    // Manual getters for Python (can't use get_all due to provider_info needing custom handling)
    #[getter]
    fn event_type(&self) -> String {
        // Return string representation for backwards compatibility with Python SDK
        self.event_type.as_str().to_string()
    }

    #[getter]
    fn capability(&self) -> Option<String> {
        self.capability.clone()
    }

    #[getter]
    fn endpoint(&self) -> Option<String> {
        self.endpoint.clone()
    }

    #[getter]
    fn function_name(&self) -> Option<String> {
        self.function_name.clone()
    }

    #[getter]
    fn agent_id(&self) -> Option<String> {
        self.agent_id.clone()
    }

    #[getter]
    fn function_id(&self) -> Option<String> {
        self.function_id.clone()
    }

    #[getter]
    fn tools(&self) -> Option<Vec<LlmToolInfo>> {
        self.tools.clone()
    }

    #[getter]
    fn error(&self) -> Option<String> {
        self.error.clone()
    }

    #[getter]
    fn status(&self) -> Option<HealthStatus> {
        self.status
    }

    #[getter]
    fn reason(&self) -> Option<String> {
        self.reason.clone()
    }

    /// Get provider_info as a Python object with attributes.
    /// Returns None if no provider info, otherwise returns an object with
    /// function_id, agent_id, endpoint, function_name, and model attributes.
    #[getter]
    fn provider_info(&self, py: Python<'_>) -> PyResult<Option<pyo3::Py<pyo3::PyAny>>> {
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
            event_type: EventType::AgentRegistered,
            agent_id: Some(agent_id),
            ..Default::default()
        }
    }

    /// Create a "registration_failed" event
    pub fn registration_failed(error: String) -> Self {
        Self {
            event_type: EventType::RegistrationFailed,
            error: Some(error),
            ..Default::default()
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
            event_type: EventType::DependencyAvailable,
            capability: Some(capability),
            endpoint: Some(endpoint),
            function_name: Some(function_name),
            agent_id: Some(agent_id),
            ..Default::default()
        }
    }

    /// Create a "dependency_unavailable" event
    pub fn dependency_unavailable(capability: String) -> Self {
        Self {
            event_type: EventType::DependencyUnavailable,
            capability: Some(capability),
            ..Default::default()
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
            event_type: EventType::DependencyChanged,
            capability: Some(capability),
            endpoint: Some(endpoint),
            function_name: Some(function_name),
            agent_id: Some(agent_id),
            ..Default::default()
        }
    }

    /// Create an "llm_tools_updated" event
    pub fn llm_tools_updated(function_id: String, tools: Vec<LlmToolInfo>) -> Self {
        Self {
            event_type: EventType::LlmToolsUpdated,
            function_id: Some(function_id),
            tools: Some(tools),
            ..Default::default()
        }
    }

    /// Create a "health_check_due" event
    pub fn health_check_due() -> Self {
        Self {
            event_type: EventType::HealthCheckDue,
            ..Default::default()
        }
    }

    /// Create a "health_status_changed" event
    pub fn health_status_changed(status: HealthStatus) -> Self {
        Self {
            event_type: EventType::HealthStatusChanged,
            status: Some(status),
            ..Default::default()
        }
    }

    /// Create a "registry_connected" event
    pub fn registry_connected() -> Self {
        Self {
            event_type: EventType::RegistryConnected,
            ..Default::default()
        }
    }

    /// Create a "registry_disconnected" event
    pub fn registry_disconnected(reason: String) -> Self {
        Self {
            event_type: EventType::RegistryDisconnected,
            reason: Some(reason),
            ..Default::default()
        }
    }

    /// Create a "shutdown" event
    pub fn shutdown() -> Self {
        Self {
            event_type: EventType::Shutdown,
            ..Default::default()
        }
    }

    /// Create an "llm_provider_available" event
    pub fn llm_provider_available(provider_info: LlmProviderInfo) -> Self {
        Self {
            event_type: EventType::LlmProviderAvailable,
            provider_info: Some(provider_info),
            ..Default::default()
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

        assert_eq!(event.event_type, EventType::DependencyAvailable);
        assert_eq!(event.event_type.as_str(), "dependency_available");
        assert_eq!(event.capability, Some("date-service".to_string()));
        assert_eq!(event.endpoint, Some("http://localhost:9001".to_string()));
    }

    #[test]
    fn test_event_type_serialization() {
        // Test that EventType serializes to snake_case strings
        let json = serde_json::to_string(&EventType::DependencyAvailable).unwrap();
        assert_eq!(json, "\"dependency_available\"");

        let json = serde_json::to_string(&EventType::LlmToolsUpdated).unwrap();
        assert_eq!(json, "\"llm_tools_updated\"");

        // Test deserialization
        let event_type: EventType = serde_json::from_str("\"agent_registered\"").unwrap();
        assert_eq!(event_type, EventType::AgentRegistered);
    }

    #[test]
    fn test_event_type_as_str() {
        assert_eq!(EventType::AgentRegistered.as_str(), "agent_registered");
        assert_eq!(EventType::DependencyChanged.as_str(), "dependency_changed");
        assert_eq!(EventType::LlmProviderAvailable.as_str(), "llm_provider_available");
        assert_eq!(EventType::Shutdown.as_str(), "shutdown");
    }

    #[test]
    fn test_health_status_string() {
        assert_eq!(HealthStatus::Healthy.as_api_str(), "healthy");
        assert_eq!(HealthStatus::Degraded.as_api_str(), "degraded");
        assert_eq!(HealthStatus::Unhealthy.as_api_str(), "unhealthy");
    }
}
