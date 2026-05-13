//! Registry client for communicating with MCP Mesh Registry.
//!
//! Handles:
//! - Fast heartbeat checks (HEAD requests)
//! - Full heartbeat/registration (POST requests)
//! - Response parsing for topology updates

use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use thiserror::Error;
use tracing::{debug, info, trace, warn};

use crate::events::HealthStatus;
use crate::spec::{AgentSpec, AgentType};
use crate::tls::TlsConfig;

/// Errors that can occur during registry communication.
#[derive(Debug, Error)]
pub enum RegistryError {
    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),

    #[error("Invalid URL: {0}")]
    InvalidUrl(String),

    #[error("JSON serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("Registry returned error: {status} - {message}")]
    RegistryError { status: u16, message: String },

    #[error("Unexpected response: {0}")]
    UnexpectedResponse(String),

    #[error("TLS configuration error: {0}")]
    TlsError(String),
}

impl From<crate::tls::TlsError> for RegistryError {
    fn from(e: crate::tls::TlsError) -> Self {
        RegistryError::TlsError(e.to_string())
    }
}

/// Result of a fast heartbeat check (HEAD request).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FastHeartbeatStatus {
    /// 200 OK - No topology changes
    NoChanges,
    /// 202 Accepted - Topology changed, need full heartbeat
    TopologyChanged,
    /// 410 Gone - Agent unknown, need to re-register
    AgentUnknown,
    /// 503 Service Unavailable - Registry error
    RegistryError,
    /// Network/connection error
    NetworkError,
}

/// Combined result of a fast heartbeat HEAD: status + optional pending-jobs
/// hint parsed from the `X-Mesh-Pending-Jobs` response header.
///
/// `pending_jobs` is the count of unclaimed jobs across this agent's
/// declared capabilities (registry-side computation, capped per the
/// design doc — see "Pending-jobs scoping: per-agent capability set"). The
/// header is opportunistic: it can ride either the 200 or 202 response,
/// and is omitted entirely when there is no work to claim.
///
/// Treated as `None` when:
/// - The header is absent (registry version pre-jobs, or no pending work).
/// - The header is present but parses as `0` (treat 0 as absent — same
///   "no work to claim" signal so claim worker stays asleep).
/// - The header value cannot be parsed as `u32`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FastHeartbeatResponse {
    pub status: FastHeartbeatStatus,
    pub pending_jobs: Option<u32>,
}

/// Header name for the pending-jobs hint. Defined here so registry-side
/// integration tests / fixtures can reference the same constant.
pub const PENDING_JOBS_HEADER: &str = "X-Mesh-Pending-Jobs";

/// Parse the `X-Mesh-Pending-Jobs` header value into an optional count.
///
/// Per [`FastHeartbeatResponse`] docs: missing, `0`, and unparseable
/// values all collapse to `None`. Anything > 0 returns `Some(n)`.
///
/// A malformed header (non-numeric / >u32::MAX) is logged at warn
/// level so version-skew between the agent runtime and the registry
/// surfaces in operator logs — silently dropping the value would mask
/// the protocol mismatch and leave job claims stuck.
fn parse_pending_jobs_header(headers: &reqwest::header::HeaderMap) -> Option<u32> {
    let header_val = headers.get(PENDING_JOBS_HEADER)?;
    let raw = match header_val.to_str() {
        Ok(s) => s,
        Err(e) => {
            warn!(
                "ignoring non-ASCII {} header value: {} (likely registry/runtime version skew)",
                PENDING_JOBS_HEADER, e
            );
            return None;
        }
    };
    let trimmed = raw.trim();
    match trimmed.parse::<u32>() {
        Ok(0) => None,
        Ok(n) => Some(n),
        Err(e) => {
            warn!(
                "ignoring malformed {} header value {:?}: {} (likely registry/runtime version skew)",
                PENDING_JOBS_HEADER, trimmed, e
            );
            None
        }
    }
}

impl FastHeartbeatStatus {
    /// Create status from HTTP status code.
    pub fn from_status_code(code: u16) -> Self {
        match code {
            200 => Self::NoChanges,
            202 => Self::TopologyChanged,
            410 => Self::AgentUnknown,
            503 => Self::RegistryError,
            _ => Self::NetworkError,
        }
    }

    /// Check if full heartbeat is required.
    pub fn requires_full_heartbeat(&self) -> bool {
        matches!(self, Self::TopologyChanged | Self::AgentUnknown)
    }

    /// Check if we should skip for resilience (error states).
    pub fn should_skip_for_resilience(&self) -> bool {
        matches!(self, Self::RegistryError | Self::NetworkError)
    }

    /// Check if we can skip (optimization - no changes).
    pub fn should_skip_for_optimization(&self) -> bool {
        matches!(self, Self::NoChanges)
    }
}

/// Resolved dependency information from registry response.
///
/// `kwargs` carries the producer's @mesh.tool kwargs (e.g. `stream_type`,
/// `timeout`) so the consumer's proxy can configure itself from the
/// producer's advertised behavior. Issue #645 bug 2.
#[derive(Debug, Clone, Deserialize)]
pub struct ResolvedDependency {
    pub agent_id: String,
    pub endpoint: String,
    pub function_name: String,
    pub capability: String,
    pub status: String,
    #[serde(default)]
    pub ttl: u64,
    #[serde(default)]
    pub kwargs: Option<serde_json::Value>,
}

/// Tool information for LLM agents.
#[derive(Debug, Clone, Deserialize)]
pub struct LlmToolInfo {
    /// Registry returns "name" field for function name
    #[serde(rename = "name")]
    pub function_name: String,
    pub capability: String,
    /// Tool description for LLM prompting
    #[serde(default)]
    pub description: Option<String>,
    pub endpoint: String,
    #[serde(default)]
    pub agent_id: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: Option<serde_json::Value>,
}

/// Resolved LLM provider information.
///
/// `kwargs` carries the provider tool's @mesh.tool kwargs (e.g. `stream_type`)
/// so the consumer's provider proxy can configure itself from the producer's
/// advertised behavior. Mirrors `ResolvedDependency.kwargs`.
#[derive(Debug, Clone, Deserialize)]
pub struct ResolvedLlmProvider {
    pub agent_id: String,
    pub endpoint: String,
    /// Registry returns "name" field for function name
    #[serde(rename = "name")]
    pub function_name: String,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub capability: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub vendor: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub kwargs: Option<serde_json::Value>,
}

/// Full heartbeat response from registry.
#[derive(Debug, Clone, Deserialize)]
pub struct HeartbeatResponse {
    pub status: String,
    pub message: String,
    pub agent_id: String,
    #[serde(default)]
    pub dependencies_resolved: HashMap<String, Vec<ResolvedDependency>>,
    #[serde(default)]
    pub llm_tools: HashMap<String, Vec<LlmToolInfo>>,
    #[serde(default)]
    pub llm_providers: HashMap<String, ResolvedLlmProvider>,
}

/// Tool registration for heartbeat request.
#[derive(Debug, Clone, Serialize)]
pub struct ToolRegistration {
    pub function_name: String,
    pub capability: String,
    pub version: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub dependencies: Vec<DependencyRegistration>,
    #[serde(rename = "inputSchema", skip_serializing_if = "Option::is_none")]
    pub input_schema: Option<serde_json::Value>,
    #[serde(rename = "outputSchema", skip_serializing_if = "Option::is_none")]
    pub output_schema: Option<serde_json::Value>,
    #[serde(rename = "inputSchemaCanonical", skip_serializing_if = "Option::is_none")]
    pub input_schema_canonical: Option<serde_json::Value>,
    #[serde(rename = "inputSchemaHash", skip_serializing_if = "Option::is_none")]
    pub input_schema_hash: Option<String>,
    #[serde(rename = "outputSchemaCanonical", skip_serializing_if = "Option::is_none")]
    pub output_schema_canonical: Option<serde_json::Value>,
    #[serde(rename = "outputSchemaHash", skip_serializing_if = "Option::is_none")]
    pub output_schema_hash: Option<String>,
    #[serde(rename = "schemaWarnings", skip_serializing_if = "Option::is_none")]
    pub schema_warnings: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_filter: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_provider: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kwargs: Option<serde_json::Value>,
}

/// Dependency registration for heartbeat request.
#[derive(Debug, Clone, Serialize)]
pub struct DependencyRegistration {
    pub capability: String,
    /// Tags can be nested arrays for OR alternatives: ["addition", ["python", "typescript"]]
    #[serde(skip_serializing_if = "is_empty_tags")]
    pub tags: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(rename = "expectedSchemaCanonical", skip_serializing_if = "Option::is_none")]
    pub expected_schema_canonical: Option<serde_json::Value>,
    #[serde(rename = "expectedSchemaHash", skip_serializing_if = "Option::is_none")]
    pub expected_schema_hash: Option<String>,
    #[serde(rename = "matchMode", skip_serializing_if = "Option::is_none")]
    pub match_mode: Option<String>,
}

/// Helper to check if tags array is empty
fn is_empty_tags(v: &serde_json::Value) -> bool {
    v.as_array().map_or(true, |a| a.is_empty())
}

/// LLM agent registration for heartbeat request.
#[derive(Debug, Clone, Serialize)]
pub struct LlmAgentRegistration {
    pub function_id: String,
    pub provider: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<serde_json::Value>,
    pub filter_mode: String,
    pub max_iterations: u32,
}

/// Full heartbeat request body.
#[derive(Debug, Clone, Serialize)]
pub struct HeartbeatRequest {
    pub agent_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub agent_type: String,
    pub version: String,
    /// Free-form agent description (issue #969). Forwarded verbatim to the
    /// registry, which strips whitespace and truncates at 256 chars before
    /// persisting. Skipped on the wire when empty/absent so older SDKs that
    /// never set a description don't add a noisy `"description":""` field.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub http_host: String,
    pub http_port: u16,
    pub namespace: String,
    pub status: String,
    /// SDK runtime type: "python" or "typescript"
    pub runtime: String,
    pub tools: Vec<ToolRegistration>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub llm_agents: Vec<LlmAgentRegistration>,
    /// A2A surfaces (issue #903 / A2A_SURFACE_DESIGN.org). Optional —
    /// populated only when the agent has at least one `@mesh.a2a` decorator.
    /// Forwarded as a JSON value so the Rust core doesn't need to model the
    /// surface schema; the registry's `MeshAgentRegistration` deserializer
    /// reshapes this into typed `A2ASurface` entries.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub surfaces: Option<serde_json::Value>,
}

impl HeartbeatRequest {
    /// Create a heartbeat request from an AgentSpec.
    pub fn from_spec(spec: &AgentSpec, health_status: HealthStatus) -> Self {
        let tools: Vec<ToolRegistration> = spec
            .tools
            .iter()
            .map(|t| ToolRegistration {
                function_name: t.function_name.clone(),
                capability: t.capability.clone(),
                version: t.version.clone(),
                tags: t.tags.clone(),
                description: if t.description.is_empty() {
                    None
                } else {
                    Some(t.description.clone())
                },
                dependencies: t
                    .dependencies
                    .iter()
                    .map(|d| DependencyRegistration {
                        capability: d.capability.clone(),
                        // Parse tags JSON string to Value for nested array support
                        tags: serde_json::from_str(&d.tags).unwrap_or(serde_json::Value::Array(vec![])),
                        version: d.version.clone(),
                        expected_schema_canonical: d.expected_schema_canonical.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                        expected_schema_hash: d.expected_schema_hash.clone(),
                        match_mode: d.match_mode.clone(),
                    })
                    .collect(),
                input_schema: t.input_schema.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                output_schema: t.output_schema.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                input_schema_canonical: t.input_schema_canonical.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                input_schema_hash: t.input_schema_hash.clone(),
                output_schema_canonical: t.output_schema_canonical.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                output_schema_hash: t.output_schema_hash.clone(),
                schema_warnings: t.schema_warnings.clone(),
                llm_filter: t.llm_filter.as_ref().and_then(|f| serde_json::from_str(f).ok()),
                llm_provider: t.llm_provider.as_ref().and_then(|p| serde_json::from_str(p).ok()),
                kwargs: t.kwargs.as_ref().and_then(|k| serde_json::from_str(k).ok()),
            })
            .collect();

        // Build LLM agent registrations
        let llm_agents: Vec<LlmAgentRegistration> = spec
            .llm_agents
            .iter()
            .map(|a| {
                let provider = match serde_json::from_str(&a.provider) {
                    Ok(v) => v,
                    Err(e) => {
                        warn!(
                            "Failed to parse provider JSON for LLM agent '{}': {}. Using null.",
                            a.function_id, e
                        );
                        serde_json::Value::Null
                    }
                };
                let filter = match a.filter.as_ref() {
                    Some(f) => match serde_json::from_str(f) {
                        Ok(v) => Some(v),
                        Err(e) => {
                            warn!(
                                "Failed to parse filter JSON for LLM agent '{}': {}. Skipping filter.",
                                a.function_id, e
                            );
                            None
                        }
                    },
                    None => None,
                };
                LlmAgentRegistration {
                    function_id: a.function_id.clone(),
                    provider,
                    filter,
                    filter_mode: a.filter_mode.clone(),
                    max_iterations: a.max_iterations,
                }
            })
            .collect();

        Self {
            agent_id: spec.agent_id(),
            name: Some(spec.name.clone()),
            agent_type: spec.agent_type.as_api_str().to_string(),
            version: spec.version.clone(),
            // Issue #969: forward the optional description. Empty strings
            // are treated as absent so we don't pollute the wire with a
            // `"description":""` payload for agents that never set one.
            description: if spec.description.is_empty() {
                None
            } else {
                Some(spec.description.clone())
            },
            http_host: spec.http_host.clone(),
            http_port: spec.http_port,
            namespace: spec.namespace.clone(),
            status: health_status.as_api_str().to_string(),
            runtime: spec.runtime.as_api_str().to_string(),
            tools,
            llm_agents,
            // Issue #903 Phase 1B: forward A2A surfaces verbatim so the
            // registry can persist them and stamp FQDNs. The SDK passes
            // a JSON string from Python (because pyclass(get_all, set_all)
            // can't host a `serde_json::Value` field directly); parse it
            // here before sending so the wire shape matches the registry's
            // typed `MeshAgentRegistration.surfaces` deserializer.
            surfaces: spec
                .surfaces
                .as_ref()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok()),
        }
    }
}

/// Client for communicating with MCP Mesh Registry.
pub struct RegistryClient {
    client: Client,
    base_url: String,
}

impl RegistryClient {
    /// Create a new registry client with optional TLS configuration.
    pub fn new(registry_url: &str, tls_config: &TlsConfig) -> Result<Self, RegistryError> {
        let mut builder = Client::builder()
            .timeout(Duration::from_secs(30))
            .connect_timeout(Duration::from_secs(10));

        if tls_config.is_enabled() {
            // Add client identity (cert + key) for mTLS
            if let Some(identity) = tls_config
                .build_identity()?
            {
                builder = builder.identity(identity);
            }

            // Add custom CA for verifying registry's cert
            if let Some(ca) = tls_config
                .build_ca_cert()?
            {
                builder = builder.add_root_certificate(ca);
            }

            // SPIFFE/SPIRE certs use URI SANs (spiffe://...), not DNS/IP SANs.
            // Skip hostname verification but keep cert chain validation against
            // the trust bundle. This matches the Go registry proxy's behavior
            // (InsecureSkipVerify + VerifyConnection chain check).
            if tls_config.provider == "spire" {
                builder = builder.danger_accept_invalid_hostnames(true);
                info!("SPIFFE TLS: hostname verification disabled (URI SAN-based identity)");
            }
        }

        let client = builder.build()?;

        if tls_config.is_enabled() {
            info!("Registry client configured with mTLS (provider: {})", tls_config.provider);
        } else {
            debug!("Registry client using plain HTTP");
        }

        // Normalize URL (remove trailing slash)
        let base_url = registry_url.trim_end_matches('/').to_string();

        Ok(Self { client, base_url })
    }

    /// Perform a fast heartbeat check (HEAD request).
    ///
    /// Returns the status indicating whether full heartbeat is needed,
    /// plus an optional `pending_jobs` count parsed from the
    /// `X-Mesh-Pending-Jobs` response header (see [`FastHeartbeatResponse`]).
    pub async fn fast_heartbeat_check(&self, agent_id: &str) -> FastHeartbeatResponse {
        let url = format!("{}/heartbeat/{}", self.base_url, agent_id);

        trace!("Sending fast heartbeat HEAD request to {}", url);

        match self.client.head(&url).send().await {
            Ok(response) => {
                let status_code = response.status().as_u16();
                let status = FastHeartbeatStatus::from_status_code(status_code);
                let pending_jobs = parse_pending_jobs_header(response.headers());
                debug!(
                    "Fast heartbeat for agent '{}': HTTP {} -> {:?} pending_jobs={:?}",
                    agent_id, status_code, status, pending_jobs
                );
                FastHeartbeatResponse {
                    status,
                    pending_jobs,
                }
            }
            Err(e) => {
                warn!("Fast heartbeat failed for agent '{}': {}", agent_id, e);
                FastHeartbeatResponse {
                    status: FastHeartbeatStatus::NetworkError,
                    pending_jobs: None,
                }
            }
        }
    }

    /// Send a full heartbeat (POST request).
    ///
    /// Returns the response with resolved dependencies and LLM tools.
    pub async fn send_heartbeat(
        &self,
        request: &HeartbeatRequest,
    ) -> Result<HeartbeatResponse, RegistryError> {
        let url = format!("{}/heartbeat", self.base_url);

        debug!("Sending full heartbeat for agent '{}'", request.agent_id);

        // Log the actual JSON being sent for debugging
        if let Ok(json_str) = serde_json::to_string_pretty(request) {
            info!("Heartbeat request JSON:\n{}", json_str);
        }
        trace!("Heartbeat request: {:?}", request);

        let response = self
            .client
            .post(&url)
            .json(request)
            .send()
            .await?;

        let status = response.status();

        if status.is_success() {
            let body = response.text().await?;
            info!("Heartbeat response body:\n{}", body);

            let parsed: HeartbeatResponse = serde_json::from_str(&body)?;

            // Log detailed tool info
            for (func_id, tools) in &parsed.llm_tools {
                info!(
                    "LLM tools for '{}': {} tools - {:?}",
                    func_id,
                    tools.len(),
                    tools.iter().map(|t| &t.function_name).collect::<Vec<_>>()
                );
            }

            info!(
                "Heartbeat successful for agent '{}': {} dependencies, {} LLM tools, {} LLM providers",
                request.agent_id,
                parsed.dependencies_resolved.len(),
                parsed.llm_tools.len(),
                parsed.llm_providers.len()
            );

            Ok(parsed)
        } else {
            let body = response.text().await.unwrap_or_default();
            Err(RegistryError::RegistryError {
                status: status.as_u16(),
                message: body,
            })
        }
    }

    /// Send initial registration (same as heartbeat but first time).
    pub async fn register(
        &self,
        spec: &AgentSpec,
        health_status: HealthStatus,
    ) -> Result<HeartbeatResponse, RegistryError> {
        let request = HeartbeatRequest::from_spec(spec, health_status);
        self.send_heartbeat(&request).await
    }

    /// Unregister an agent from the registry (DELETE request).
    ///
    /// Called during graceful shutdown to immediately remove the agent
    /// from the registry. This triggers topology change events for
    /// dependent agents.
    pub async fn unregister_agent(&self, agent_id: &str) -> Result<(), RegistryError> {
        let url = format!("{}/agents/{}", self.base_url, agent_id);

        info!("Unregistering agent '{}' from registry", agent_id);

        match self.client.delete(&url).send().await {
            Ok(response) => {
                let status = response.status();
                if status.is_success() || status.as_u16() == 404 {
                    // 200/204 = success, 404 = already gone (both are fine)
                    info!(
                        "Agent '{}' unregistered successfully (HTTP {})",
                        agent_id,
                        status.as_u16()
                    );
                    Ok(())
                } else {
                    let body = response.text().await.unwrap_or_default();
                    warn!(
                        "Failed to unregister agent '{}': HTTP {} - {}",
                        agent_id,
                        status.as_u16(),
                        body
                    );
                    Err(RegistryError::RegistryError {
                        status: status.as_u16(),
                        message: body,
                    })
                }
            }
            Err(e) => {
                warn!("Network error unregistering agent '{}': {}", agent_id, e);
                // Don't fail shutdown due to network error
                Err(RegistryError::Network(e))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::ToolSpec;
    use crate::tls::TlsMode;

    /// Build a TLS-off config for tests that need a `RegistryClient`.
    fn test_tls_off() -> TlsConfig {
        TlsConfig {
            mode: TlsMode::Off,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "file".to_string(),
            credentials: None,
        }
    }

    #[test]
    fn test_fast_heartbeat_status_from_code() {
        assert_eq!(
            FastHeartbeatStatus::from_status_code(200),
            FastHeartbeatStatus::NoChanges
        );
        assert_eq!(
            FastHeartbeatStatus::from_status_code(202),
            FastHeartbeatStatus::TopologyChanged
        );
        assert_eq!(
            FastHeartbeatStatus::from_status_code(410),
            FastHeartbeatStatus::AgentUnknown
        );
        assert_eq!(
            FastHeartbeatStatus::from_status_code(503),
            FastHeartbeatStatus::RegistryError
        );
        assert_eq!(
            FastHeartbeatStatus::from_status_code(500),
            FastHeartbeatStatus::NetworkError
        );
    }

    #[test]
    fn test_fast_heartbeat_status_decisions() {
        assert!(FastHeartbeatStatus::NoChanges.should_skip_for_optimization());
        assert!(!FastHeartbeatStatus::NoChanges.requires_full_heartbeat());

        assert!(FastHeartbeatStatus::TopologyChanged.requires_full_heartbeat());
        assert!(!FastHeartbeatStatus::TopologyChanged.should_skip_for_optimization());

        assert!(FastHeartbeatStatus::NetworkError.should_skip_for_resilience());
        assert!(FastHeartbeatStatus::RegistryError.should_skip_for_resilience());
    }

    #[test]
    fn test_heartbeat_request_from_spec() {
        let spec = AgentSpec::new(
            "test-agent".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "Test".to_string(),
            9000,
            "localhost".to_string(),
            "default".to_string(),
            None, // agent_type defaults to mcp_agent
            None, // runtime defaults to python
            Some(vec![ToolSpec::new(
                "greet".to_string(),
                "greeting".to_string(),
                "1.0.0".to_string(),
                "Greeting tool".to_string(),
                Some(vec!["utility".to_string()]),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )]),
            None,
            5,
            None,
        );

        let request = HeartbeatRequest::from_spec(&spec, HealthStatus::Healthy);

        assert_eq!(request.agent_id, "test-agent");
        assert_eq!(request.agent_type, "mcp_agent");
        assert_eq!(request.tools.len(), 1);
        assert_eq!(request.tools[0].function_name, "greet");
        assert_eq!(request.tools[0].capability, "greeting");
        // Issue #969: description was set on the spec — the request should
        // forward it as Some(...) (see test_heartbeat_request_description_round_trip
        // below for the empty-string → None case).
        assert_eq!(request.description.as_deref(), Some("Test"));
    }

    #[test]
    fn test_heartbeat_request_description_round_trip() {
        // Issue #969: when the spec carries a description, HeartbeatRequest
        // forwards it as Some(value). Empty string maps to None so we don't
        // pollute the wire for agents that never set a description.
        let mut spec = AgentSpec::new(
            "described-agent".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "Hello from the mesh".to_string(),
            9000,
            "localhost".to_string(),
            "default".to_string(),
            None,
            None,
            None,
            None,
            5,
            None,
        );
        let with_desc = HeartbeatRequest::from_spec(&spec, HealthStatus::Healthy);
        assert_eq!(with_desc.description.as_deref(), Some("Hello from the mesh"));

        spec.description = String::new();
        let empty_desc = HeartbeatRequest::from_spec(&spec, HealthStatus::Healthy);
        assert_eq!(empty_desc.description, None,
            "empty description should serialize as None (skip_serializing_if)");
    }

    #[test]
    fn parse_pending_jobs_header_present_nonzero() {
        let mut h = reqwest::header::HeaderMap::new();
        h.insert(PENDING_JOBS_HEADER, "5".parse().unwrap());
        assert_eq!(parse_pending_jobs_header(&h), Some(5));
    }

    #[test]
    fn parse_pending_jobs_header_absent() {
        let h = reqwest::header::HeaderMap::new();
        assert_eq!(parse_pending_jobs_header(&h), None);
    }

    #[test]
    fn parse_pending_jobs_header_zero_treated_as_absent() {
        let mut h = reqwest::header::HeaderMap::new();
        h.insert(PENDING_JOBS_HEADER, "0".parse().unwrap());
        assert_eq!(parse_pending_jobs_header(&h), None);
    }

    #[test]
    fn parse_pending_jobs_header_unparseable_is_none() {
        let mut h = reqwest::header::HeaderMap::new();
        h.insert(PENDING_JOBS_HEADER, "abc".parse().unwrap());
        assert_eq!(parse_pending_jobs_header(&h), None);
    }

    /// Build a tiny HEAD-only HTTP mock server that returns the given
    /// status code and optional pending-jobs header. Returns the bound
    /// port. The server handles exactly one request and then exits.
    async fn spawn_head_mock(status_code: u16, pending: Option<&'static str>) -> u16 {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 4096];
            let _ = sock.read(&mut buf).await.unwrap();
            let status_line = match status_code {
                200 => "HTTP/1.1 200 OK\r\n",
                202 => "HTTP/1.1 202 Accepted\r\n",
                410 => "HTTP/1.1 410 Gone\r\n",
                _ => "HTTP/1.1 500 Internal Server Error\r\n",
            };
            let mut resp = String::from(status_line);
            resp.push_str("Content-Length: 0\r\n");
            if let Some(p) = pending {
                resp.push_str(&format!("{}: {}\r\n", PENDING_JOBS_HEADER, p));
            }
            resp.push_str("\r\n");
            sock.write_all(resp.as_bytes()).await.unwrap();
        });
        port
    }

    #[tokio::test]
    async fn fast_heartbeat_check_parses_pending_jobs_on_200() {
        let port = spawn_head_mock(200, Some("3")).await;
        let url = format!("http://127.0.0.1:{}", port);
        let client = RegistryClient::new(&url, &test_tls_off()).unwrap();
        let r = client.fast_heartbeat_check("agent-x").await;
        assert_eq!(r.status, FastHeartbeatStatus::NoChanges);
        assert_eq!(r.pending_jobs, Some(3));
    }

    #[tokio::test]
    async fn fast_heartbeat_check_no_header_yields_none() {
        let port = spawn_head_mock(200, None).await;
        let url = format!("http://127.0.0.1:{}", port);
        let client = RegistryClient::new(&url, &test_tls_off()).unwrap();
        let r = client.fast_heartbeat_check("agent-x").await;
        assert_eq!(r.status, FastHeartbeatStatus::NoChanges);
        assert_eq!(r.pending_jobs, None);
    }

    #[tokio::test]
    async fn fast_heartbeat_check_zero_treated_as_none() {
        let port = spawn_head_mock(200, Some("0")).await;
        let url = format!("http://127.0.0.1:{}", port);
        let client = RegistryClient::new(&url, &test_tls_off()).unwrap();
        let r = client.fast_heartbeat_check("agent-x").await;
        assert_eq!(r.pending_jobs, None);
    }

    #[tokio::test]
    async fn fast_heartbeat_check_pending_jobs_rides_202() {
        let port = spawn_head_mock(202, Some("4")).await;
        let url = format!("http://127.0.0.1:{}", port);
        let client = RegistryClient::new(&url, &test_tls_off()).unwrap();
        let r = client.fast_heartbeat_check("agent-x").await;
        assert_eq!(r.status, FastHeartbeatStatus::TopologyChanged);
        assert_eq!(r.pending_jobs, Some(4));
    }

    #[test]
    fn test_heartbeat_request_api_type() {
        let spec = AgentSpec::new(
            "api-service".to_string(),
            "http://localhost:8100".to_string(),
            "1.0.0".to_string(),
            "API".to_string(),
            0, // port doesn't matter for API
            "localhost".to_string(),
            "default".to_string(),
            Some("api".to_string()), // API agent type
            None, // runtime defaults to python
            None,
            None,
            5,
            None,
        );

        let request = HeartbeatRequest::from_spec(&spec, HealthStatus::Healthy);

        assert_eq!(request.agent_type, "api");
        assert_eq!(request.http_port, 0);
    }
}
