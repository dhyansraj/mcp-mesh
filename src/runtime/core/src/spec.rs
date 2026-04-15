//! Agent specification types for MCP Mesh.
//!
//! These types define the configuration passed from language SDKs to the Rust core.

#[cfg(feature = "python")]
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Specification for a dependency required by a tool.
#[cfg_attr(feature = "python", pyclass(get_all, set_all))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencySpec {
    /// Capability name to depend on
    pub capability: String,

    /// Tags for filtering - JSON string to support nested arrays for OR alternatives
    /// e.g., '["addition", ["python", "typescript"]]' means addition AND (python OR typescript)
    pub tags: String,

    /// Version constraint (e.g., ">=2.0.0")
    pub version: Option<String>,
}

#[cfg(feature = "python")]
#[pymethods]
impl DependencySpec {
    #[new]
    #[pyo3(signature = (capability, tags=None, version=None))]
    pub fn py_new(capability: String, tags: Option<String>, version: Option<String>) -> Self {
        Self::new(capability, tags, version)
    }

    fn __repr__(&self) -> String {
        format!("DependencySpec(capability={:?}, tags={:?})", self.capability, self.tags)
    }
}

impl DependencySpec {
    /// Create a new DependencySpec (language-agnostic)
    pub fn new(capability: String, tags: Option<String>, version: Option<String>) -> Self {
        Self {
            capability,
            tags: tags.unwrap_or_else(|| "[]".to_string()),
            version,
        }
    }
}

/// Specification for a tool/capability provided by the agent.
#[cfg_attr(feature = "python", pyclass(get_all, set_all))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
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
    pub dependencies: Vec<DependencySpec>,

    /// JSON Schema for input parameters (MCP format) - serialized JSON string
    pub input_schema: Option<String>,

    /// LLM filter specification (for @mesh.llm decorated functions) - serialized JSON string
    pub llm_filter: Option<String>,

    /// LLM provider specification (for @mesh.llm_provider) - serialized JSON string
    pub llm_provider: Option<String>,

    /// Additional kwargs from decorator - serialized JSON string
    pub kwargs: Option<String>,
}

#[cfg(feature = "python")]
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
    pub fn py_new(
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
        Self::new(
            function_name,
            capability,
            version,
            description,
            tags,
            dependencies,
            input_schema,
            llm_filter,
            llm_provider,
            kwargs,
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "ToolSpec(function_name={:?}, capability={:?})",
            self.function_name, self.capability
        )
    }
}

impl ToolSpec {
    /// Create a new ToolSpec (language-agnostic)
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
}

/// Specification for an LLM agent function.
#[cfg_attr(feature = "python", pyclass(get_all, set_all))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmAgentSpec {
    /// Unique identifier for this LLM function
    pub function_id: String,

    /// Provider selector (capability + tags) - serialized JSON string
    pub provider: String,

    /// Tool filter specification - serialized JSON string
    pub filter: Option<String>,

    /// Filter mode: "all", "best_match", or "*"
    pub filter_mode: String,

    /// Maximum agentic loop iterations
    pub max_iterations: u32,
}

#[cfg(feature = "python")]
#[pymethods]
impl LlmAgentSpec {
    #[new]
    #[pyo3(signature = (function_id, provider, filter=None, filter_mode="all".to_string(), max_iterations=1))]
    pub fn py_new(
        function_id: String,
        provider: String,
        filter: Option<String>,
        filter_mode: String,
        max_iterations: u32,
    ) -> Self {
        Self::new(function_id, provider, filter, filter_mode, max_iterations)
    }

    fn __repr__(&self) -> String {
        format!("LlmAgentSpec(function_id={:?})", self.function_id)
    }
}

impl LlmAgentSpec {
    /// Create a new LlmAgentSpec (language-agnostic)
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
}

/// Agent type for registration with registry.
#[cfg_attr(feature = "python", pyclass(eq, eq_int))]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AgentType {
    /// MCP agent that provides capabilities (tools) to the mesh
    #[default]
    McpAgent = 0,
    /// API service that only consumes capabilities (e.g., FastAPI, Express)
    Api = 1,
}

#[cfg(feature = "python")]
#[pymethods]
impl AgentType {
    /// String representation of the agent type
    fn __str__(&self) -> &'static str {
        self.as_api_str()
    }

    fn __repr__(&self) -> String {
        format!("AgentType.{:?}", self)
    }
}

impl AgentType {
    /// Convert to registry API string format.
    pub fn as_api_str(&self) -> &'static str {
        match self {
            Self::McpAgent => "mcp_agent",
            Self::Api => "api",
        }
    }

    /// Create from string (for Python/TypeScript bindings).
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "api" => Self::Api,
            _ => Self::McpAgent,
        }
    }
}

/// SDK runtime language type.
#[cfg_attr(feature = "python", pyclass(eq, eq_int))]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum RuntimeType {
    /// Python SDK (default for backwards compatibility)
    #[default]
    #[serde(rename = "python")]
    Python = 0,
    /// TypeScript SDK
    #[serde(rename = "typescript")]
    TypeScript = 1,
    /// Java SDK
    #[serde(rename = "java")]
    Java = 2,
}

#[cfg(feature = "python")]
#[pymethods]
impl RuntimeType {
    /// String representation of the runtime type
    fn __str__(&self) -> &'static str {
        self.as_api_str()
    }

    fn __repr__(&self) -> String {
        format!("RuntimeType.{:?}", self)
    }
}

impl RuntimeType {
    /// Convert to registry API string format.
    pub fn as_api_str(&self) -> &'static str {
        match self {
            Self::Python => "python",
            Self::TypeScript => "typescript",
            Self::Java => "java",
        }
    }

    /// Create from string (for Python/TypeScript/Java bindings).
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "typescript" | "ts" => Self::TypeScript,
            "java" => Self::Java,
            _ => Self::Python,
        }
    }
}

/// Complete specification for an MCP Mesh agent.
///
/// This is the primary configuration passed from language SDKs to start the agent runtime.
#[cfg_attr(feature = "python", pyclass(get_all, set_all))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentSpec {
    /// Base agent name (shared across replicas, e.g., "fortuna").
    /// Comes from the decorator/annotation name argument.
    pub name: String,

    /// Unique per-replica agent ID (e.g., "fortuna-abc12345").
    /// Defaults to `name` when not set, preserving backward compatibility.
    #[serde(default)]
    pub agent_id: String,

    /// Agent version (semver)
    pub version: String,

    /// Human-readable description
    pub description: String,

    /// Registry URL (e.g., "http://localhost:8100")
    pub registry_url: String,

    /// HTTP port for this agent (0 = auto-assign)
    pub http_port: u16,

    /// HTTP host announced to registry
    pub http_host: String,

    /// Namespace for isolation
    pub namespace: String,

    /// Agent type: "mcp_agent" (provides capabilities) or "api" (only consumes)
    #[serde(default)]
    pub agent_type: AgentType,

    /// SDK runtime type (python or typescript)
    #[serde(default)]
    pub runtime: RuntimeType,

    /// Tools/capabilities provided by this agent
    pub tools: Vec<ToolSpec>,

    /// LLM agent specifications
    pub llm_agents: Vec<LlmAgentSpec>,

    /// Heartbeat interval in seconds
    pub heartbeat_interval: u64,
}

#[cfg(feature = "python")]
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
        agent_type=None,
        runtime=None,
        tools=None,
        llm_agents=None,
        heartbeat_interval=5,
        agent_id=None
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn py_new(
        name: String,
        registry_url: String,
        version: String,
        description: String,
        http_port: u16,
        http_host: String,
        namespace: String,
        agent_type: Option<String>,
        runtime: Option<String>,
        tools: Option<Vec<ToolSpec>>,
        llm_agents: Option<Vec<LlmAgentSpec>>,
        heartbeat_interval: u64,
        agent_id: Option<String>,
    ) -> Self {
        Self::new(
            name,
            registry_url,
            version,
            description,
            http_port,
            http_host,
            namespace,
            agent_type,
            runtime,
            tools,
            llm_agents,
            heartbeat_interval,
            agent_id,
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "AgentSpec(name={:?}, agent_type={:?}, tools={}, llm_agents={})",
            self.name,
            self.agent_type.as_api_str(),
            self.tools.len(),
            self.llm_agents.len()
        )
    }
}

impl AgentSpec {
    /// Create a new AgentSpec (language-agnostic)
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: String,
        registry_url: String,
        version: String,
        description: String,
        http_port: u16,
        http_host: String,
        namespace: String,
        agent_type: Option<String>,
        runtime: Option<String>,
        tools: Option<Vec<ToolSpec>>,
        llm_agents: Option<Vec<LlmAgentSpec>>,
        heartbeat_interval: u64,
        agent_id: Option<String>,
    ) -> Self {
        // Default agent_id to name if not provided (backward compat).
        let agent_id = agent_id.filter(|s| !s.is_empty()).unwrap_or_else(|| name.clone());
        Self {
            name,
            agent_id,
            version,
            description,
            registry_url,
            http_port,
            http_host,
            namespace,
            agent_type: agent_type
                .map(|s| AgentType::from_str(&s))
                .unwrap_or_default(),
            runtime: runtime
                .map(|s| RuntimeType::from_str(&s))
                .unwrap_or_default(),
            tools: tools.unwrap_or_default(),
            llm_agents: llm_agents.unwrap_or_default(),
            heartbeat_interval,
        }
    }

    /// Get the unique per-replica agent ID.
    ///
    /// The `new()` constructor normalizes an empty/missing `agent_id` to
    /// `name`, but deserialization (via serde) bypasses `new()` and can
    /// produce an empty `agent_id` because of `#[serde(default)]` on the
    /// field. This getter applies the same fallback defensively so callers
    /// always receive a non-empty ID regardless of construction path.
    pub fn agent_id(&self) -> String {
        if self.agent_id.is_empty() {
            self.name.clone()
        } else {
            self.agent_id.clone()
        }
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
            None, // agent_type defaults to mcp_agent
            None, // runtime defaults to python
            None,
            None,
            5,
            None, // agent_id defaults to name
        );

        assert_eq!(spec.name, "test-agent");
        assert_eq!(spec.agent_id(), "test-agent");
        assert!(spec.tools.is_empty());
        assert_eq!(spec.agent_type, AgentType::McpAgent);
        assert_eq!(spec.runtime, RuntimeType::Python);
    }

    #[test]
    fn test_agent_spec_distinct_agent_id() {
        let spec = AgentSpec::new(
            "fortuna".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "".to_string(),
            0,
            "localhost".to_string(),
            "default".to_string(),
            None,
            None,
            None,
            None,
            5,
            Some("fortuna-abc12345".to_string()),
        );

        assert_eq!(spec.name, "fortuna");
        assert_eq!(spec.agent_id(), "fortuna-abc12345");
    }

    #[test]
    fn test_agent_type_api() {
        let spec = AgentSpec::new(
            "api-service".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "API service".to_string(),
            0, // port doesn't matter for API
            "localhost".to_string(),
            "default".to_string(),
            Some("api".to_string()), // API agent type
            Some("typescript".to_string()), // TypeScript runtime
            None,
            None,
            5,
            None,
        );

        assert_eq!(spec.agent_type, AgentType::Api);
        assert_eq!(spec.agent_type.as_api_str(), "api");
        assert_eq!(spec.runtime, RuntimeType::TypeScript);
        assert_eq!(spec.runtime.as_api_str(), "typescript");
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
            None, // runtime
            None,
            None,
            5,
            None,
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
