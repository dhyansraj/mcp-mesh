//! Agent specification types for MCP Mesh.
//!
//! These types define the configuration passed from language SDKs to the Rust core.

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Specification for a dependency required by a tool.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencySpec {
    /// Capability name to depend on
    #[pyo3(get, set)]
    pub capability: String,

    /// Tags for filtering (e.g., ["+fast", "-deprecated"])
    #[pyo3(get, set)]
    pub tags: Vec<String>,

    /// Version constraint (e.g., ">=2.0.0")
    #[pyo3(get, set)]
    pub version: Option<String>,
}

#[pymethods]
impl DependencySpec {
    #[new]
    #[pyo3(signature = (capability, tags=None, version=None))]
    pub fn new(capability: String, tags: Option<Vec<String>>, version: Option<String>) -> Self {
        Self {
            capability,
            tags: tags.unwrap_or_default(),
            version,
        }
    }

    fn __repr__(&self) -> String {
        format!("DependencySpec(capability={:?}, tags={:?})", self.capability, self.tags)
    }
}

/// Specification for a tool/capability provided by the agent.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
    /// Function name in the code
    #[pyo3(get, set)]
    pub function_name: String,

    /// Capability name for discovery
    #[pyo3(get, set)]
    pub capability: String,

    /// Version of this capability
    #[pyo3(get, set)]
    pub version: String,

    /// Tags for filtering
    #[pyo3(get, set)]
    pub tags: Vec<String>,

    /// Human-readable description
    #[pyo3(get, set)]
    pub description: String,

    /// Dependencies required by this tool
    #[pyo3(get, set)]
    pub dependencies: Vec<DependencySpec>,

    /// JSON Schema for input parameters (MCP format) - serialized JSON string
    #[pyo3(get, set)]
    pub input_schema: Option<String>,

    /// LLM filter specification (for @mesh.llm decorated functions) - serialized JSON string
    #[pyo3(get, set)]
    pub llm_filter: Option<String>,

    /// LLM provider specification (for @mesh.llm_provider) - serialized JSON string
    #[pyo3(get, set)]
    pub llm_provider: Option<String>,

    /// Additional kwargs from decorator - serialized JSON string
    #[pyo3(get, set)]
    pub kwargs: Option<String>,
}

#[pymethods]
impl ToolSpec {
    #[new]
    #[pyo3(signature = (
        function_name,
        capability,
        version="1.0.0".to_string(),
        description="".to_string(),
        tags=None,
        dependencies=None,
        input_schema=None,
        llm_filter=None,
        llm_provider=None,
        kwargs=None
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        function_name: String,
        capability: String,
        version: String,
        description: String,
        tags: Option<Vec<String>>,
        dependencies: Option<Vec<DependencySpec>>,
        input_schema: Option<String>,
        llm_filter: Option<String>,
        llm_provider: Option<String>,
        kwargs: Option<String>,
    ) -> Self {
        Self {
            function_name,
            capability,
            version,
            description,
            tags: tags.unwrap_or_default(),
            dependencies: dependencies.unwrap_or_default(),
            input_schema,
            llm_filter,
            llm_provider,
            kwargs,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "ToolSpec(function_name={:?}, capability={:?})",
            self.function_name, self.capability
        )
    }
}

/// Specification for an LLM agent function.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmAgentSpec {
    /// Unique identifier for this LLM function
    #[pyo3(get, set)]
    pub function_id: String,

    /// Provider selector (capability + tags) - serialized JSON string
    #[pyo3(get, set)]
    pub provider: String,

    /// Tool filter specification - serialized JSON string
    #[pyo3(get, set)]
    pub filter: Option<String>,

    /// Filter mode: "all", "best_match", or "*"
    #[pyo3(get, set)]
    pub filter_mode: String,

    /// Maximum agentic loop iterations
    #[pyo3(get, set)]
    pub max_iterations: u32,
}

#[pymethods]
impl LlmAgentSpec {
    #[new]
    #[pyo3(signature = (function_id, provider, filter=None, filter_mode="all".to_string(), max_iterations=1))]
    pub fn new(
        function_id: String,
        provider: String,
        filter: Option<String>,
        filter_mode: String,
        max_iterations: u32,
    ) -> Self {
        Self {
            function_id,
            provider,
            filter,
            filter_mode,
            max_iterations,
        }
    }

    fn __repr__(&self) -> String {
        format!("LlmAgentSpec(function_id={:?})", self.function_id)
    }
}

/// Complete specification for an MCP Mesh agent.
///
/// This is the primary configuration passed from language SDKs to start the agent runtime.
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentSpec {
    /// Unique agent name/identifier
    #[pyo3(get, set)]
    pub name: String,

    /// Agent version (semver)
    #[pyo3(get, set)]
    pub version: String,

    /// Human-readable description
    #[pyo3(get, set)]
    pub description: String,

    /// Registry URL (e.g., "http://localhost:8100")
    #[pyo3(get, set)]
    pub registry_url: String,

    /// HTTP port for this agent (0 = auto-assign)
    #[pyo3(get, set)]
    pub http_port: u16,

    /// HTTP host announced to registry
    #[pyo3(get, set)]
    pub http_host: String,

    /// Namespace for isolation
    #[pyo3(get, set)]
    pub namespace: String,

    /// Tools/capabilities provided by this agent
    #[pyo3(get, set)]
    pub tools: Vec<ToolSpec>,

    /// LLM agent specifications
    #[pyo3(get, set)]
    pub llm_agents: Vec<LlmAgentSpec>,

    /// Heartbeat interval in seconds
    #[pyo3(get, set)]
    pub heartbeat_interval: u64,
}

#[pymethods]
impl AgentSpec {
    #[new]
    #[pyo3(signature = (
        name,
        registry_url,
        version="1.0.0".to_string(),
        description="".to_string(),
        http_port=0,
        http_host="localhost".to_string(),
        namespace="default".to_string(),
        tools=None,
        llm_agents=None,
        heartbeat_interval=5
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: String,
        registry_url: String,
        version: String,
        description: String,
        http_port: u16,
        http_host: String,
        namespace: String,
        tools: Option<Vec<ToolSpec>>,
        llm_agents: Option<Vec<LlmAgentSpec>>,
        heartbeat_interval: u64,
    ) -> Self {
        Self {
            name,
            version,
            description,
            registry_url,
            http_port,
            http_host,
            namespace,
            tools: tools.unwrap_or_default(),
            llm_agents: llm_agents.unwrap_or_default(),
            heartbeat_interval,
        }
    }

    /// Get the agent ID (name with optional suffix for uniqueness)
    pub fn agent_id(&self) -> String {
        // For now, just use the name. Could add UUID suffix later.
        self.name.clone()
    }

    /// Get all dependency capabilities required by this agent's tools
    pub fn all_dependencies(&self) -> Vec<String> {
        let mut deps: Vec<String> = self
            .tools
            .iter()
            .flat_map(|t| t.dependencies.iter().map(|d| d.capability.clone()))
            .collect();
        deps.sort();
        deps.dedup();
        deps
    }

    fn __repr__(&self) -> String {
        format!(
            "AgentSpec(name={:?}, tools={}, llm_agents={})",
            self.name,
            self.tools.len(),
            self.llm_agents.len()
        )
    }
}

/// Resolved dependency information from registry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolvedDependency {
    /// Capability name
    pub capability: String,

    /// Agent ID providing this capability
    pub agent_id: String,

    /// Endpoint URL (e.g., "http://localhost:9001")
    pub endpoint: String,

    /// Function name to call
    pub function_name: String,

    /// Agent health status
    pub status: String,

    /// TTL in seconds
    pub ttl: u64,
}

/// Resolved LLM tools for an LLM agent function.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolvedLlmTools {
    /// Function ID of the LLM agent
    pub function_id: String,

    /// List of available tools
    pub tools: Vec<ResolvedTool>,
}

/// A resolved tool available to an LLM agent.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolvedTool {
    /// Function name
    pub function_name: String,

    /// Capability name
    pub capability: String,

    /// Endpoint URL
    pub endpoint: String,

    /// Input schema for the tool
    pub input_schema: Option<serde_json::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_agent_spec_creation() {
        let spec = AgentSpec::new(
            "test-agent".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "Test agent".to_string(),
            9000,
            "localhost".to_string(),
            "default".to_string(),
            None,
            None,
            5,
        );

        assert_eq!(spec.name, "test-agent");
        assert_eq!(spec.agent_id(), "test-agent");
        assert!(spec.tools.is_empty());
    }

    #[test]
    fn test_all_dependencies() {
        let mut spec = AgentSpec::new(
            "test-agent".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "".to_string(),
            0,
            "localhost".to_string(),
            "default".to_string(),
            None,
            None,
            5,
        );

        spec.tools = vec![
            ToolSpec::new(
                "func1".to_string(),
                "cap1".to_string(),
                "1.0.0".to_string(),
                "".to_string(),
                None,
                Some(vec![
                    DependencySpec::new("date-service".to_string(), None, None),
                    DependencySpec::new("weather-service".to_string(), None, None),
                ]),
                None,
                None,
                None,
                None,
            ),
            ToolSpec::new(
                "func2".to_string(),
                "cap2".to_string(),
                "1.0.0".to_string(),
                "".to_string(),
                None,
                Some(vec![DependencySpec::new("date-service".to_string(), None, None)]),
                None,
                None,
                None,
                None,
            ),
        ];

        let deps = spec.all_dependencies();
        assert_eq!(deps, vec!["date-service", "weather-service"]);
    }
}
