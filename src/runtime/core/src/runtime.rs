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

use crate::events::{LlmToolInfo, MeshEvent};
use crate::handle::HandleState;
use crate::heartbeat::{HeartbeatAction, HeartbeatConfig, HeartbeatStateMachine};
use crate::registry::{HeartbeatRequest, HeartbeatResponse, RegistryClient};
use crate::spec::AgentSpec;

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
    }

    /// Process dependency resolution changes and emit events.
    async fn process_dependency_changes(
        &mut self,
        resolved: &HashMap<String, Vec<crate::registry::ResolvedDependency>>,
    ) {
        let mut new_deps = HashMap::new();

        // The registry returns dependencies keyed by the function that NEEDS them,
        // but each provider has the actual capability name we need to emit
        for (_requesting_func, providers) in resolved {
            // Take the first available/healthy provider
            if let Some(provider) = providers.iter().find(|p| p.status == "available" || p.status == "healthy") {
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

        // Find removed dependencies
        let old_caps: Vec<String> = self.topology.dependencies.keys().cloned().collect();
        for cap in old_caps {
            if !new_deps.contains_key(&cap) {
                info!("Dependency '{}' removed", cap);

                // Update shared state
                {
                    let mut state = self.shared_state.write().await;
                    state.dependencies.remove(&cap);
                }

                // Emit event
                let _ = self
                    .event_tx
                    .send(MeshEvent::dependency_unavailable(cap.clone()))
                    .await;

                self.topology.dependencies.remove(&cap);
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

                // Update shared state
                {
                    let mut state = self.shared_state.write().await;
                    state.dependencies.insert(cap.clone(), endpoint.clone());
                }

                // Emit event
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
                    .insert(cap.clone(), (endpoint.clone(), func_name.clone(), agent_id.clone()));
            }
        }
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

            // Check if changed
            let changed = match self.topology.llm_tools.get(function_id) {
                Some(old_tools) => old_tools.len() != tool_infos.len(), // Simple check, could be more thorough
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
}

/// Start an agent runtime in a background task.
///
/// Returns the event receiver and shared state handle.
pub fn spawn_runtime(
    spec: AgentSpec,
    config: RuntimeConfig,
) -> Result<
    (
        mpsc::Receiver<MeshEvent>,
        Arc<RwLock<HandleState>>,
        mpsc::Sender<()>,
    ),
    crate::registry::RegistryError,
> {
    let (event_tx, event_rx) = mpsc::channel(config.event_buffer_size);
    let (shutdown_tx, shutdown_rx) = mpsc::channel(1);
    let shared_state = Arc::new(RwLock::new(HandleState::default()));

    let runtime = AgentRuntime::new(
        spec,
        config,
        event_tx,
        shared_state.clone(),
        shutdown_rx,
    )?;

    // Spawn the runtime in a background task
    tokio::spawn(async move {
        runtime.run().await;
    });

    Ok((event_rx, shared_state, shutdown_tx))
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
