//! Agent runtime - the main background task that manages heartbeats and topology.
//!
//! The runtime:
//! - Runs in a background tokio task
//! - Manages the heartbeat state machine
//! - Sends events to the Python SDK via channels
//! - Tracks topology changes and emits dependency events

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, RwLock};
use tokio::time::sleep;
use tracing::{info, trace, warn};

use crate::events::{LlmProviderInfo, LlmToolInfo, MeshEvent};
use crate::handle::HandleState;
use crate::heartbeat::{HeartbeatAction, HeartbeatConfig, HeartbeatStateMachine};
use crate::registry::{HeartbeatRequest, HeartbeatResponse, RegistryClient};
use crate::spec::AgentSpec;

/// Internal provider tracking (non-PyO3 to avoid GIL issues in tokio thread)
#[derive(Debug, Clone)]
struct TrackedProvider {
    function_id: String,
    agent_id: String,
    endpoint: String,
    function_name: String,
    model: Option<String>,
}

/// Configuration for the agent runtime.
#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    /// Heartbeat configuration
    pub heartbeat: HeartbeatConfig,
    /// Event channel buffer size
    pub event_buffer_size: usize,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            heartbeat: HeartbeatConfig::default(),
            event_buffer_size: 100,
        }
    }
}

/// Topology state - tracks current dependency endpoints.
#[derive(Debug, Default)]
struct TopologyState {
    /// Current dependencies (capability -> (endpoint, function_name, agent_id))
    dependencies: HashMap<String, (String, String, String)>,
    /// LLM tools (function_id -> tools)
    llm_tools: HashMap<String, Vec<LlmToolInfo>>,
    /// LLM providers (function_id -> provider info) - using internal struct to avoid GIL issues
    llm_providers: HashMap<String, TrackedProvider>,
}

/// The agent runtime that runs in the background.
pub struct AgentRuntime {
    spec: AgentSpec,
    config: RuntimeConfig,
    registry_client: RegistryClient,
    state_machine: HeartbeatStateMachine,
    topology: TopologyState,
    event_tx: mpsc::Sender<MeshEvent>,
    shared_state: Arc<RwLock<HandleState>>,
    shutdown_rx: mpsc::Receiver<()>,
}

impl AgentRuntime {
    /// Create a new agent runtime.
    pub fn new(
        spec: AgentSpec,
        config: RuntimeConfig,
        event_tx: mpsc::Sender<MeshEvent>,
        shared_state: Arc<RwLock<HandleState>>,
        shutdown_rx: mpsc::Receiver<()>,
    ) -> Result<Self, crate::registry::RegistryError> {
        let registry_client = RegistryClient::new(&spec.registry_url)?;
        let heartbeat_config = HeartbeatConfig {
            interval: Duration::from_secs(spec.heartbeat_interval),
            ..config.heartbeat.clone()
        };
        let state_machine = HeartbeatStateMachine::new(heartbeat_config);

        Ok(Self {
            spec,
            config,
            registry_client,
            state_machine,
            topology: TopologyState::default(),
            event_tx,
            shared_state,
            shutdown_rx,
        })
    }

    /// Run the agent runtime loop.
    ///
    /// This is the main entry point that runs until shutdown is requested.
    pub async fn run(mut self) {
        info!("Starting agent runtime for '{}'", self.spec.name);

        loop {
            // Check for shutdown signal (non-blocking)
            if self.shutdown_rx.try_recv().is_ok() {
                info!("Shutdown signal received");
                self.state_machine.shutdown();
            }

            if self.state_machine.is_shutting_down() {
                // Gracefully unregister from registry before stopping
                self.unregister_from_registry().await;
                break;
            }

            // Determine next action
            let action = self.state_machine.next_action();
            trace!("Next action: {:?}", action);

            match action {
                HeartbeatAction::SendFull => {
                    self.send_full_heartbeat().await;
                }
                HeartbeatAction::SendFast => {
                    self.send_fast_heartbeat().await;
                }
                HeartbeatAction::Wait(duration) => {
                    trace!("Waiting {:?} until next heartbeat", duration);
                    tokio::select! {
                        _ = sleep(duration) => {}
                        _ = self.shutdown_rx.recv() => {
                            info!("Shutdown signal received during wait");
                            self.state_machine.shutdown();
                        }
                    }
                }
                HeartbeatAction::Retry { attempt, backoff } => {
                    warn!("Retry attempt {} with backoff {:?}", attempt, backoff);
                    tokio::select! {
                        _ = sleep(backoff) => {}
                        _ = self.shutdown_rx.recv() => {
                            info!("Shutdown signal received during backoff");
                            self.state_machine.shutdown();
                        }
                    }
                    // After backoff, try full registration
                    self.send_full_heartbeat().await;
                }
                HeartbeatAction::None => {
                    break;
                }
            }
        }

        // Send shutdown event
        let _ = self.event_tx.send(MeshEvent::shutdown()).await;
        info!("Agent runtime for '{}' stopped", self.spec.name);
    }

    /// Unregister the agent from the registry during shutdown.
    ///
    /// This ensures immediate topology update for dependent agents
    /// instead of waiting for the heartbeat timeout.
    async fn unregister_from_registry(&self) {
        let agent_id = self.spec.agent_id();
        info!("Unregistering agent '{}' from registry", agent_id);

        match self.registry_client.unregister_agent(&agent_id).await {
            Ok(()) => {
                info!("Agent '{}' unregistered successfully", agent_id);
            }
            Err(e) => {
                // Log but don't fail shutdown - network issues shouldn't block shutdown
                warn!(
                    "Failed to unregister agent '{}' (continuing shutdown): {}",
                    agent_id, e
                );
            }
        }
    }

    /// Send a fast heartbeat check (HEAD request).
    async fn send_fast_heartbeat(&mut self) {
        let agent_id = self.spec.agent_id();
        let status = self.registry_client.fast_heartbeat_check(&agent_id).await;

        let action = self.state_machine.on_fast_heartbeat_result(status);

        // If we need a full heartbeat, do it now
        if action == HeartbeatAction::SendFull {
            self.send_full_heartbeat().await;
        }
    }

    /// Send a full heartbeat (POST request).
    async fn send_full_heartbeat(&mut self) {
        let request = HeartbeatRequest::from_spec(&self.spec, self.state_machine.health_status());

        match self.registry_client.send_heartbeat(&request).await {
            Ok(response) => {
                self.state_machine.on_full_heartbeat_success();

                // Update shared state with agent ID
                {
                    let mut state = self.shared_state.write().await;
                    state.agent_id = Some(response.agent_id.clone());
                }

                // Process topology changes
                self.process_heartbeat_response(response).await;

                // Send registration event if this was first successful registration
                if self.state_machine.heartbeat_count() == 1 {
                    let _ = self
                        .event_tx
                        .send(MeshEvent::agent_registered(self.spec.agent_id()))
                        .await;
                }
            }
            Err(e) => {
                self.state_machine.on_full_heartbeat_failure(&e.to_string());

                // Send error event
                let _ = self
                    .event_tx
                    .send(MeshEvent::registration_failed(e.to_string()))
                    .await;
            }
        }
    }

    /// Process a heartbeat response and emit topology change events.
    async fn process_heartbeat_response(&mut self, response: HeartbeatResponse) {
        // Process dependency changes
        self.process_dependency_changes(&response.dependencies_resolved)
            .await;

        // Process LLM tools changes
        self.process_llm_tools_changes(&response.llm_tools).await;

        // Process LLM provider changes
        self.process_llm_providers_changes(&response.llm_providers)
            .await;
    }

    /// Process dependency resolution changes and emit events.
    ///
    /// This method batches state updates to minimize lock contention.
    async fn process_dependency_changes(
        &mut self,
        resolved: &HashMap<String, Vec<crate::registry::ResolvedDependency>>,
    ) {
        let mut new_deps = HashMap::new();

        // The registry returns dependencies keyed by the function that NEEDS them,
        // but each provider has the actual capability name we need to emit.
        // A function can depend on MULTIPLE capabilities (e.g., math_greeting needs add AND multiply).
        for (_requesting_func, providers) in resolved {
            // Process ALL available/healthy providers, not just the first one
            for provider in providers.iter().filter(|p| p.status == "available" || p.status == "healthy") {
                // Use the actual capability from the provider, not the key
                new_deps.insert(
                    provider.capability.clone(),
                    (
                        provider.endpoint.clone(),
                        provider.function_name.clone(),
                        provider.agent_id.clone(),
                    ),
                );
            }
        }

        // Collect all changes first (before acquiring any locks)
        let mut removed_caps: Vec<String> = Vec::new();
        let mut added_or_changed: Vec<(String, String, String, String, bool)> = Vec::new(); // (cap, endpoint, func_name, agent_id, is_new)

        // Find removed dependencies
        let old_caps: Vec<String> = self.topology.dependencies.keys().cloned().collect();
        for cap in old_caps {
            if !new_deps.contains_key(&cap) {
                info!("Dependency '{}' removed", cap);
                removed_caps.push(cap);
            }
        }

        // Find new or changed dependencies
        for (cap, (endpoint, func_name, agent_id)) in &new_deps {
            let changed = match self.topology.dependencies.get(cap) {
                Some((old_ep, old_fn, _)) => old_ep != endpoint || old_fn != func_name,
                None => true,
            };

            if changed {
                let is_new = !self.topology.dependencies.contains_key(cap);
                if is_new {
                    info!(
                        "Dependency '{}' available at {} ({})",
                        cap, endpoint, func_name
                    );
                } else {
                    info!(
                        "Dependency '{}' changed to {} ({})",
                        cap, endpoint, func_name
                    );
                }
                added_or_changed.push((
                    cap.clone(),
                    endpoint.clone(),
                    func_name.clone(),
                    agent_id.clone(),
                    is_new,
                ));
            }
        }

        // Batch update shared state (single lock acquisition)
        if !removed_caps.is_empty() || !added_or_changed.is_empty() {
            let mut state = self.shared_state.write().await;
            for cap in &removed_caps {
                state.dependencies.remove(cap);
            }
            for (cap, endpoint, _, _, _) in &added_or_changed {
                state.dependencies.insert(cap.clone(), endpoint.clone());
            }
        }

        // Update local topology and emit events (no lock needed)
        for cap in removed_caps {
            let _ = self
                .event_tx
                .send(MeshEvent::dependency_unavailable(cap.clone()))
                .await;
            self.topology.dependencies.remove(&cap);
        }

        for (cap, endpoint, func_name, agent_id, is_new) in added_or_changed {
            let event = if is_new {
                MeshEvent::dependency_available(
                    cap.clone(),
                    endpoint.clone(),
                    func_name.clone(),
                    agent_id.clone(),
                )
            } else {
                MeshEvent::dependency_changed(
                    cap.clone(),
                    endpoint.clone(),
                    func_name.clone(),
                    agent_id.clone(),
                )
            };
            let _ = self.event_tx.send(event).await;

            self.topology
                .dependencies
                .insert(cap, (endpoint, func_name, agent_id));
        }
    }

    /// Check if two LlmToolInfo lists are equivalent.
    fn tools_are_equal(old: &[LlmToolInfo], new: &[LlmToolInfo]) -> bool {
        if old.len() != new.len() {
            return false;
        }

        // Check each tool - order matters for simplicity, but we compare all fields
        for (old_tool, new_tool) in old.iter().zip(new.iter()) {
            if old_tool.function_name != new_tool.function_name
                || old_tool.capability != new_tool.capability
                || old_tool.endpoint != new_tool.endpoint
                || old_tool.agent_id != new_tool.agent_id
                || old_tool.input_schema != new_tool.input_schema
            {
                return false;
            }
        }
        true
    }

    /// Process LLM tools changes and emit events.
    async fn process_llm_tools_changes(
        &mut self,
        llm_tools: &HashMap<String, Vec<crate::registry::LlmToolInfo>>,
    ) {
        for (function_id, tools) in llm_tools {
            // Convert to our event type
            let tool_infos: Vec<LlmToolInfo> = tools
                .iter()
                .map(|t| LlmToolInfo {
                    function_name: t.function_name.clone(),
                    capability: t.capability.clone(),
                    endpoint: t.endpoint.clone(),
                    agent_id: t.agent_id.clone(),
                    input_schema: t
                        .input_schema
                        .as_ref()
                        .and_then(|s| serde_json::to_string(s).ok()),
                })
                .collect();

            // Check if changed - compare all fields, not just length
            let changed = match self.topology.llm_tools.get(function_id) {
                Some(old_tools) => !Self::tools_are_equal(old_tools, &tool_infos),
                None => true,
            };

            if changed {
                info!(
                    "LLM tools updated for function '{}': {} tools",
                    function_id,
                    tool_infos.len()
                );

                // Emit event
                let _ = self
                    .event_tx
                    .send(MeshEvent::llm_tools_updated(
                        function_id.clone(),
                        tool_infos.clone(),
                    ))
                    .await;

                self.topology
                    .llm_tools
                    .insert(function_id.clone(), tool_infos);
            }
        }
    }

    /// Process LLM provider changes and emit events.
    async fn process_llm_providers_changes(
        &mut self,
        llm_providers: &HashMap<String, crate::registry::ResolvedLlmProvider>,
    ) {
        for (function_id, provider) in llm_providers {
            // Use internal tracking struct to avoid GIL issues
            let tracked = TrackedProvider {
                function_id: function_id.clone(),
                agent_id: provider.agent_id.clone(),
                endpoint: provider.endpoint.clone(),
                function_name: provider.function_name.clone(),
                model: provider.model.clone(),
            };

            // Check if changed
            let changed = match self.topology.llm_providers.get(function_id) {
                Some(old_provider) => {
                    old_provider.endpoint != tracked.endpoint
                        || old_provider.function_name != tracked.function_name
                }
                None => true,
            };

            if changed {
                info!(
                    "LLM provider resolved for function '{}': {} at {}",
                    function_id, tracked.function_name, tracked.endpoint
                );

                // Store the tracking info first (no PyO3 involvement)
                self.topology
                    .llm_providers
                    .insert(function_id.clone(), tracked.clone());

                // Create LlmProviderInfo and send event
                let provider_info = LlmProviderInfo {
                    function_id: function_id.clone(),
                    agent_id: provider.agent_id.clone(),
                    endpoint: provider.endpoint.clone(),
                    function_name: provider.function_name.clone(),
                    model: provider.model.clone(),
                };
                let _ = self
                    .event_tx
                    .send(MeshEvent::llm_provider_available(provider_info))
                    .await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_runtime_config_default() {
        let config = RuntimeConfig::default();
        assert_eq!(config.event_buffer_size, 100);
        assert_eq!(config.heartbeat.interval, Duration::from_secs(5));
    }
}
