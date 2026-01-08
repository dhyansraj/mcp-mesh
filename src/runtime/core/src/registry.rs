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
use crate::spec::AgentSpec;

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
#[derive(Debug, Clone, Deserialize)]
pub struct ResolvedDependency {
    pub agent_id: String,
    pub endpoint: String,
    pub function_name: String,
    pub capability: String,
    pub status: String,
    #[serde(default)]
    pub ttl: u64,
}

/// Tool information for LLM agents.
#[derive(Debug, Clone, Deserialize)]
pub struct LlmToolInfo {
    /// Registry returns "name" field for function name
    #[serde(rename = "name")]
    pub function_name: String,
    pub capability: String,
    pub endpoint: String,
    #[serde(default)]
    pub agent_id: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: Option<serde_json::Value>,
}

/// Resolved LLM provider information.
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_filter: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_provider: Option<serde_json::Value>,
}

/// Dependency registration for heartbeat request.
#[derive(Debug, Clone, Serialize)]
pub struct DependencyRegistration {
    pub capability: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
}

/// Full heartbeat request body.
#[derive(Debug, Clone, Serialize)]
pub struct HeartbeatRequest {
    pub agent_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub version: String,
    pub http_host: String,
    pub http_port: u16,
    pub namespace: String,
    pub status: String,
    pub tools: Vec<ToolRegistration>,
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
                        tags: d.tags.clone(),
                        version: d.version.clone(),
                    })
                    .collect(),
                input_schema: t.input_schema.as_ref().and_then(|s| serde_json::from_str(s).ok()),
                llm_filter: t.llm_filter.as_ref().and_then(|f| serde_json::from_str(f).ok()),
                llm_provider: t.llm_provider.as_ref().and_then(|p| serde_json::from_str(p).ok()),
            })
            .collect();

        Self {
            agent_id: spec.agent_id(),
            name: Some(spec.name.clone()),
            version: spec.version.clone(),
            http_host: spec.http_host.clone(),
            http_port: spec.http_port,
            namespace: spec.namespace.clone(),
            status: health_status.as_api_str().to_string(),
            tools,
        }
    }
}

/// Client for communicating with MCP Mesh Registry.
pub struct RegistryClient {
    client: Client,
    base_url: String,
}

impl RegistryClient {
    /// Create a new registry client.
    pub fn new(registry_url: &str) -> Result<Self, RegistryError> {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .connect_timeout(Duration::from_secs(10))
            .build()?;

        // Normalize URL (remove trailing slash)
        let base_url = registry_url.trim_end_matches('/').to_string();

        Ok(Self { client, base_url })
    }

    /// Perform a fast heartbeat check (HEAD request).
    ///
    /// Returns the status indicating whether full heartbeat is needed.
    pub async fn fast_heartbeat_check(&self, agent_id: &str) -> FastHeartbeatStatus {
        let url = format!("{}/heartbeat/{}", self.base_url, agent_id);

        trace!("Sending fast heartbeat HEAD request to {}", url);

        match self.client.head(&url).send().await {
            Ok(response) => {
                let status = FastHeartbeatStatus::from_status_code(response.status().as_u16());
                debug!(
                    "Fast heartbeat for agent '{}': HTTP {} -> {:?}",
                    agent_id,
                    response.status().as_u16(),
                    status
                );
                status
            }
            Err(e) => {
                warn!("Fast heartbeat failed for agent '{}': {}", agent_id, e);
                FastHeartbeatStatus::NetworkError
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
            )]),
            None,
            5,
        );

        let request = HeartbeatRequest::from_spec(&spec, HealthStatus::Healthy);

        assert_eq!(request.agent_id, "test-agent");
        assert_eq!(request.tools.len(), 1);
        assert_eq!(request.tools[0].function_name, "greet");
        assert_eq!(request.tools[0].capability, "greeting");
    }
}
