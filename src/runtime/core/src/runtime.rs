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
use tokio::sync::{mpsc, watch, RwLock};
use tokio::time::sleep;
use tracing::{info, trace, warn};

use crate::events::{LlmProviderInfo, LlmToolInfo, MeshEvent};
use crate::handle::HandleState;
use crate::heartbeat::{HeartbeatAction, HeartbeatConfig, HeartbeatStateMachine};
use crate::registry::{HeartbeatRequest, HeartbeatResponse, RegistryClient};
use crate::spec::{AgentSpec, ToolSpec};
use crate::tls::TlsConfig;

/// Commands that can be sent to the runtime to modify its state.
#[derive(Debug)]
pub enum RuntimeCommand {
    /// Update the tools/routes registered with the registry.
    /// Triggers a full heartbeat if tools have changed.
    UpdateTools(Vec<ToolSpec>),
    /// Update the HTTP port (e.g., after auto-detection).
    UpdatePort(u16),
    /// Update the A2A surfaces and agent_type registered with the registry
    /// (issue #938 — mid-flight `mesh.a2a.mount(...)` parity with Python's
    /// per-heartbeat `_build_a2a_surfaces`). Triggers a full heartbeat when
    /// either field actually changes; no-op otherwise so re-mounting the
    /// same surface doesn't generate redundant POSTs.
    ///
    /// Carries a JSON-encoded surfaces payload (matches `AgentSpec.surfaces`
    /// shape) and the new `agent_type` (`"a2a"`, `"api"`, or `"mcp_agent"`).
    /// `surfaces=None` means clear the field; an empty-string payload is
    /// treated as `None` so callers don't have to special-case the wire.
    UpdateSurfaces {
        agent_type: String,
        surfaces: Option<String>,
    },
}

/// Internal provider tracking (non-PyO3 to avoid GIL issues in tokio thread).
///
/// `kwargs` is the provider tool's @mesh.tool kwargs serialized as JSON so it
/// can travel through the FFI boundary. SDKs decode it to configure the
/// provider proxy.
#[derive(Debug, Clone)]
struct TrackedProvider {
    function_id: String,
    agent_id: String,
    endpoint: String,
    function_name: String,
    model: Option<String>,
    kwargs: Option<String>,
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

/// Key for tracking dependencies by position.
/// Combines the requesting function and the dependency index within that function.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct DepKey {
    /// The function that requested this dependency
    requesting_function: String,
    /// The index of the dependency in the function's dependencies array
    dep_index: u32,
}

/// Resolved dependency value with all details.
///
/// `kwargs` carries the producer's @mesh.tool kwargs as a JSON string so it
/// can travel through the FFI boundary without GIL acquisition. SDKs decode
/// it on receipt to configure the consumer-side proxy.
#[derive(Debug, Clone, PartialEq, Eq)]
struct DepValue {
    /// The capability name
    capability: String,
    /// The endpoint URL
    endpoint: String,
    /// The function name to call
    function_name: String,
    /// The agent providing this dependency
    agent_id: String,
    /// Producer's @mesh.tool kwargs serialized as JSON; None if absent.
    kwargs: Option<String>,
}

/// Topology state - tracks current dependency endpoints.
#[derive(Debug, Default)]
struct TopologyState {
    /// Current dependencies keyed by (requesting_function, dep_index)
    /// This allows multiple dependencies on the same capability with different tags
    dependencies: HashMap<DepKey, DepValue>,
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
    /// Channel for receiving commands from the SDK (e.g., update tools)
    command_rx: mpsc::Receiver<RuntimeCommand>,
    /// Flag to force a full heartbeat on next iteration
    force_full_heartbeat: bool,
    /// Producer side of the pending-jobs hint published on every fast
    /// heartbeat response. The claim worker (per-language SDK) holds the
    /// `watch::Receiver` and wakes when this transitions to `Some(n>0)`.
    /// Initialized to `None` (no pending work known).
    pending_jobs_tx: watch::Sender<Option<u32>>,
}

impl AgentRuntime {
    /// Create a new agent runtime.
    pub async fn new(
        spec: AgentSpec,
        config: RuntimeConfig,
        event_tx: mpsc::Sender<MeshEvent>,
        shared_state: Arc<RwLock<HandleState>>,
        shutdown_rx: mpsc::Receiver<()>,
        command_rx: mpsc::Receiver<RuntimeCommand>,
    ) -> Result<Self, crate::registry::RegistryError> {
        // Reuse cached config from prepare_tls() if available, otherwise resolve fresh.
        // Use the unique per-replica agent_id so TLS credential temp dirs don't collide
        // when multiple replicas of the same base agent run on the same host.
        let tls_config = match TlsConfig::get_resolved_config() {
            Some(config) => config,
            None => TlsConfig::resolve(&spec.agent_id()).await?,
        };
        let registry_client = RegistryClient::new(&spec.registry_url, &tls_config)?;
        let heartbeat_config = HeartbeatConfig {
            interval: Duration::from_secs(spec.heartbeat_interval),
            ..config.heartbeat.clone()
        };
        let state_machine = HeartbeatStateMachine::new(heartbeat_config);
        let (pending_jobs_tx, _) = watch::channel::<Option<u32>>(None);

        Ok(Self {
            spec,
            config,
            registry_client,
            state_machine,
            topology: TopologyState::default(),
            event_tx,
            shared_state,
            shutdown_rx,
            command_rx,
            force_full_heartbeat: false,
            pending_jobs_tx,
        })
    }

    /// Subscribe to the pending-jobs hint. The returned receiver yields
    /// the latest `X-Mesh-Pending-Jobs` count from each fast heartbeat
    /// (or `None` when the header is absent / zero / pre-populated).
    ///
    /// Consumed by the claim worker (per-language SDK plumbs this in
    /// during agent startup). Multiple subscribers are safe — `watch`
    /// channels broadcast.
    pub fn subscribe_pending_jobs(&self) -> watch::Receiver<Option<u32>> {
        self.pending_jobs_tx.subscribe()
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

            // Process any pending commands (non-blocking)
            self.process_pending_commands();

            if self.state_machine.is_shutting_down() {
                // Gracefully unregister from registry before stopping
                self.unregister_from_registry().await;
                break;
            }

            // Check if we need to force a full heartbeat (e.g., after tools update)
            if self.force_full_heartbeat {
                self.force_full_heartbeat = false;
                self.send_full_heartbeat().await;
                continue;
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
                        cmd = self.command_rx.recv() => {
                            if let Some(cmd) = cmd {
                                self.handle_command(cmd);
                            }
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
                        cmd = self.command_rx.recv() => {
                            if let Some(cmd) = cmd {
                                self.handle_command(cmd);
                            }
                        }
                    }
                    // A shutdown that arrived during the backoff consumed
                    // the one-shot signal from the capacity-1 channel — the
                    // next iteration's try_recv would find nothing. Skip the
                    // heartbeat so the loop-top is_shutting_down() check runs
                    // the normal shutdown path (unregister + shutdown event)
                    // instead of re-registering (issue #1166 MED-1). The
                    // Wait arm doesn't need this: it does no state-mutating
                    // work after its select.
                    if self.state_machine.is_shutting_down() {
                        continue;
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

    /// Process any pending commands without blocking.
    fn process_pending_commands(&mut self) {
        while let Ok(cmd) = self.command_rx.try_recv() {
            self.handle_command(cmd);
        }
    }

    /// Handle a runtime command.
    fn handle_command(&mut self, cmd: RuntimeCommand) {
        match cmd {
            RuntimeCommand::UpdateTools(new_tools) => {
                self.handle_update_tools(new_tools);
            }
            RuntimeCommand::UpdatePort(port) => {
                if self.spec.http_port != port {
                    info!("Updating HTTP port from {} to {}", self.spec.http_port, port);
                    self.spec.http_port = port;
                    self.force_full_heartbeat = true;
                }
            }
            RuntimeCommand::UpdateSurfaces { agent_type, surfaces } => {
                self.handle_update_surfaces(agent_type, surfaces);
            }
        }
    }

    /// Handle an A2A surfaces update (issue #938). Smart-diffs the incoming
    /// payload against the current spec — only forces a full heartbeat when
    /// either `agent_type` or the serialized `surfaces` JSON actually
    /// changes. Empty-string payloads are normalized to `None` so the wire
    /// stays clean (matches `AgentSpec::py_new`'s `filter(|s| !s.trim().is_empty())`).
    fn handle_update_surfaces(&mut self, agent_type: String, surfaces: Option<String>) {
        use crate::spec::AgentType;
        // Normalize empty/whitespace-only surfaces JSON to None so the wire
        // stays clean (registry's `surfaces` is omitted via skip_serializing_if).
        let new_surfaces = surfaces.filter(|s| !s.trim().is_empty());
        // Surface unknown agent_type strings (typos, future variants) before
        // they're silently coerced to `McpAgent` by `AgentType::from_str`'s
        // catch-all branch. We preserve the existing behavior (still proceed
        // with the coerced value) so the wire contract is unchanged — this
        // is observability-only. Known variants match the catch list in
        // `AgentType::from_str` (`spec.rs`); keep both in sync.
        match agent_type.to_lowercase().as_str() {
            "api" | "a2a" | "mcp_agent" => {}
            other => {
                warn!(
                    "Unknown agent_type '{}' in UpdateSurfaces — coercing to 'mcp_agent'. \
                     This is likely a typo or a newer SDK pushing a future variant.",
                    other
                );
            }
        }
        let new_agent_type = AgentType::from_str(&agent_type);

        let surfaces_changed = self.spec.surfaces != new_surfaces;
        let agent_type_changed = self.spec.agent_type != new_agent_type;

        if !surfaces_changed && !agent_type_changed {
            trace!("Surfaces unchanged, skipping heartbeat");
            return;
        }

        if agent_type_changed {
            info!(
                "Updating agent_type from '{}' to '{}'",
                self.spec.agent_type.as_api_str(),
                new_agent_type.as_api_str()
            );
            self.spec.agent_type = new_agent_type;
        }
        if surfaces_changed {
            let count = new_surfaces
                .as_deref()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok())
                .as_ref()
                .and_then(|v| v.as_array().map(|a| a.len()))
                .unwrap_or(0);
            info!("Updating A2A surfaces ({} entries)", count);
            self.spec.surfaces = new_surfaces;
        }
        self.force_full_heartbeat = true;
    }

    /// Handle tools update with smart diffing.
    /// Only triggers a full heartbeat if tools have actually changed.
    fn handle_update_tools(&mut self, new_tools: Vec<ToolSpec>) {
        // Smart diff: compare new tools with existing ones
        if self.tools_are_different(&new_tools) {
            info!(
                "Tools updated: {} tools (was {} tools)",
                new_tools.len(),
                self.spec.tools.len()
            );
            self.spec.tools = new_tools;
            self.force_full_heartbeat = true;
        } else {
            trace!("Tools unchanged, skipping heartbeat");
        }
    }

    /// Compare tools for equality (smart diffing).
    /// Returns true if the new tools are different from the current spec.
    fn tools_are_different(&self, new_tools: &[ToolSpec]) -> bool {
        if self.spec.tools.len() != new_tools.len() {
            return true;
        }

        for (old, new) in self.spec.tools.iter().zip(new_tools.iter()) {
            // Compare key fields that affect registration
            if old.function_name != new.function_name
                || old.capability != new.capability
                || old.version != new.version
                || old.dependencies.len() != new.dependencies.len()
            {
                return true;
            }

            // Compare dependencies
            for (old_dep, new_dep) in old.dependencies.iter().zip(new.dependencies.iter()) {
                if old_dep.capability != new_dep.capability
                    || old_dep.tags != new_dep.tags
                    || old_dep.version != new_dep.version
                {
                    return true;
                }
            }
        }

        false
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
        let response = self.registry_client.fast_heartbeat_check(&agent_id).await;

        // Publish the pending-jobs hint so the claim worker (per-SDK) can
        // wake. `send_replace` (vs `send`) so we keep emitting even when
        // the value didn't change — claim workers may want every tick as
        // a liveness signal.
        let _ = self.pending_jobs_tx.send_replace(response.pending_jobs);

        let action = self.state_machine.on_fast_heartbeat_result(response);

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
    /// The registry returns dependencies keyed by requesting function name,
    /// with an ordered Vec of resolved dependencies matching the order in which
    /// they were declared. This preserves position information so that duplicate
    /// capabilities with different tags can be correctly injected.
    ///
    /// This method batches state updates to minimize lock contention.
    async fn process_dependency_changes(
        &mut self,
        resolved: &HashMap<String, Vec<crate::registry::ResolvedDependency>>,
    ) {
        // Build new dependency map keyed by (requesting_function, dep_index)
        let mut new_deps: HashMap<DepKey, DepValue> = HashMap::new();

        // The registry returns dependencies keyed by the function that NEEDS them,
        // with the Vec preserving the declaration order (index = position in dependencies array).
        for (requesting_func, providers) in resolved {
            for (dep_index, provider) in providers.iter().enumerate() {
                // Only process available/healthy providers
                if provider.status != "available" && provider.status != "healthy" {
                    continue;
                }

                let key = DepKey {
                    requesting_function: requesting_func.clone(),
                    dep_index: dep_index as u32,
                };

                let value = DepValue {
                    capability: provider.capability.clone(),
                    endpoint: provider.endpoint.clone(),
                    function_name: provider.function_name.clone(),
                    agent_id: provider.agent_id.clone(),
                    kwargs: provider
                        .kwargs
                        .as_ref()
                        .and_then(|v| serde_json::to_string(v).ok()),
                };

                new_deps.insert(key, value);
            }
        }

        // Collect all changes first (before acquiring any locks)
        let mut removed: Vec<(DepKey, DepValue)> = Vec::new();
        let mut added_or_changed: Vec<(DepKey, DepValue, bool)> = Vec::new(); // (key, value, is_new)

        // Find removed dependencies
        let old_keys: Vec<DepKey> = self.topology.dependencies.keys().cloned().collect();
        for key in old_keys {
            if !new_deps.contains_key(&key) {
                if let Some(old_value) = self.topology.dependencies.get(&key) {
                    info!(
                        "Dependency '{}' at {}:{} removed",
                        old_value.capability, key.requesting_function, key.dep_index
                    );
                    removed.push((key, old_value.clone()));
                }
            }
        }

        // Find new or changed dependencies
        for (key, value) in &new_deps {
            let (changed, is_new) = match self.topology.dependencies.get(key) {
                Some(old_value) => (
                    old_value.endpoint != value.endpoint
                        || old_value.function_name != value.function_name
                        || old_value.kwargs != value.kwargs,
                    false,
                ),
                None => (true, true),
            };

            if changed {
                if is_new {
                    info!(
                        "Dependency '{}' at {}:{} available at {} ({})",
                        value.capability,
                        key.requesting_function,
                        key.dep_index,
                        value.endpoint,
                        value.function_name
                    );
                } else {
                    info!(
                        "Dependency '{}' at {}:{} changed to {} ({})",
                        value.capability,
                        key.requesting_function,
                        key.dep_index,
                        value.endpoint,
                        value.function_name
                    );
                }
                added_or_changed.push((key.clone(), value.clone(), is_new));
            }
        }

        // Batch update shared state (single lock acquisition)
        // Note: shared state still uses capability as key for backward compatibility
        // with other parts of the system that lookup by capability
        if !removed.is_empty() || !added_or_changed.is_empty() {
            let mut state = self.shared_state.write().await;
            for (_, value) in &removed {
                state.dependencies.remove(&value.capability);
            }
            for (_, value, _) in &added_or_changed {
                state
                    .dependencies
                    .insert(value.capability.clone(), value.endpoint.clone());
            }
        }

        // Update local topology and emit events (no lock needed).
        //
        // Send each event BEFORE recording the change in the topology map.
        // If the send fails (channel dropped/full receiver gone), leaving
        // the topology unchanged means the diff gate re-detects the change
        // on the next heartbeat and re-emits (self-healing) — recording it
        // anyway would permanently suppress re-emission (a lost
        // DEPENDENCY_AVAILABLE would leave the consumer proxy unbound
        // forever). Mirrors `process_llm_providers_changes`.
        for (key, value) in removed {
            if let Err(e) = self
                .event_tx
                .send(MeshEvent::dependency_unavailable(
                    value.capability.clone(),
                    key.requesting_function.clone(),
                    key.dep_index,
                ))
                .await
            {
                warn!(
                    "Failed to emit DEPENDENCY_UNAVAILABLE for '{}' at {}:{}: {}; \
                     will retry on next heartbeat",
                    value.capability, key.requesting_function, key.dep_index, e
                );
                continue;
            }
            self.topology.dependencies.remove(&key);
        }

        for (key, value, is_new) in added_or_changed {
            let event = if is_new {
                MeshEvent::dependency_available(
                    value.capability.clone(),
                    value.endpoint.clone(),
                    value.function_name.clone(),
                    value.agent_id.clone(),
                    key.requesting_function.clone(),
                    key.dep_index,
                    value.kwargs.clone(),
                )
            } else {
                MeshEvent::dependency_changed(
                    value.capability.clone(),
                    value.endpoint.clone(),
                    value.function_name.clone(),
                    value.agent_id.clone(),
                    key.requesting_function.clone(),
                    key.dep_index,
                    value.kwargs.clone(),
                )
            };
            if let Err(e) = self.event_tx.send(event).await {
                warn!(
                    "Failed to emit dependency event for '{}' at {}:{}: {}; \
                     will retry on next heartbeat",
                    value.capability, key.requesting_function, key.dep_index, e
                );
                continue;
            }

            self.topology.dependencies.insert(key, value);
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
                || old_tool.description != new_tool.description
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
                    description: t.description.clone(),
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

                // Send the event BEFORE recording it in topology — same
                // self-healing pattern as `process_llm_providers_changes`
                // and `process_dependency_changes`: a failed send leaves
                // the diff gate primed to re-emit on the next heartbeat.
                if let Err(e) = self
                    .event_tx
                    .send(MeshEvent::llm_tools_updated(
                        function_id.clone(),
                        tool_infos.clone(),
                    ))
                    .await
                {
                    warn!(
                        "Failed to emit LLM_TOOLS_UPDATED for function '{}': {}; \
                         will retry on next heartbeat",
                        function_id, e
                    );
                    continue;
                }

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
            // Serialize kwargs once so the same JSON string is used for both the
            // tracking struct (for change detection) and the emitted event.
            let kwargs_json = provider
                .kwargs
                .as_ref()
                .and_then(|v| serde_json::to_string(v).ok());

            // Use internal tracking struct to avoid GIL issues
            let tracked = TrackedProvider {
                function_id: function_id.clone(),
                agent_id: provider.agent_id.clone(),
                endpoint: provider.endpoint.clone(),
                function_name: provider.function_name.clone(),
                model: provider.model.clone(),
                kwargs: kwargs_json.clone(),
            };

            // Check if changed (kwargs/agent_id/model included so any field
            // change emits a fresh event — mirrors process_dependency_changes).
            // Note: `vendor` lives on LlmProviderInfo (the emitted event) but
            // not on TrackedProvider; vendor changes will be picked up via the
            // model field, which always changes when the LiteLLM model string
            // (vendor/model) changes.
            let changed = match self.topology.llm_providers.get(function_id) {
                Some(old_provider) => {
                    old_provider.agent_id != tracked.agent_id
                        || old_provider.endpoint != tracked.endpoint
                        || old_provider.function_name != tracked.function_name
                        || old_provider.model != tracked.model
                        || old_provider.kwargs != tracked.kwargs
                }
                None => true,
            };

            if changed {
                info!(
                    "LLM provider resolved for function '{}': {} at {}",
                    function_id, tracked.function_name, tracked.endpoint
                );

                // Create LlmProviderInfo and send event
                let provider_info = LlmProviderInfo {
                    function_id: function_id.clone(),
                    agent_id: provider.agent_id.clone(),
                    endpoint: provider.endpoint.clone(),
                    function_name: provider.function_name.clone(),
                    model: provider.model.clone(),
                    vendor: provider.vendor.clone(),
                    kwargs: kwargs_json,
                };

                // Send the event BEFORE recording it in topology. If the send
                // fails (channel dropped), we leave the function_id out of
                // `llm_providers` so the diff gate re-emits on the next
                // heartbeat (self-healing) instead of permanently suppressing
                // re-emission and leaving the @MeshLlm proxy unbound.
                if let Err(e) = self
                    .event_tx
                    .send(MeshEvent::llm_provider_available(provider_info))
                    .await
                {
                    warn!(
                        "Failed to emit LLM_PROVIDER_AVAILABLE for function '{}': {}; \
                         will retry on next heartbeat",
                        function_id, e
                    );
                    continue;
                }

                // Store the tracking info only after a successful send so the
                // diff gate treats this provider as "seen".
                self.topology
                    .llm_providers
                    .insert(function_id.clone(), tracked.clone());
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

    /// Issue #1166 MED-1 regression: a shutdown that arrives during the
    /// Retry arm's backoff must terminate the runtime — even when the
    /// registry recovers at exactly that heartbeat. Before the fix, the
    /// Retry arm consumed the one-shot shutdown signal, then sent the
    /// heartbeat anyway; the success overwrote ShuttingDown with Healthy
    /// and the agent re-registered and ran forever.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn shutdown_during_retry_backoff_is_not_swallowed() {
        use crate::events::EventType;
        use crate::spec::AgentSpec;

        let mut server = mockito::Server::new_async().await;

        // First full heartbeat fails -> with missed_threshold=1 the state
        // machine enters Reconnecting and the run loop hits the Retry arm.
        let fail = server
            .mock("POST", "/heartbeat")
            .with_status(500)
            .expect(1)
            .create_async()
            .await;
        // Registry "recovers": any subsequent heartbeat would succeed.
        // It must never be hit — the shutdown arrives during the backoff.
        let recover = server
            .mock("POST", "/heartbeat")
            .with_status(200)
            .with_header("content-type", "application/json")
            .with_body(r#"{"status":"success","message":"ok","agent_id":"shutdown-retry-agent"}"#)
            .create_async()
            .await;
        // Graceful unregister during shutdown.
        let unregister = server
            .mock("DELETE", "/agents/shutdown-retry-agent")
            .with_status(204)
            .create_async()
            .await;

        let spec = AgentSpec::new(
            "shutdown-retry-agent".to_string(),
            server.url(),
            "1.0.0".to_string(),
            "".to_string(),
            8080,
            "localhost".to_string(),
            "default".to_string(),
            None,
            None,
            None,
            None,
            1, // heartbeat_interval (secs)
            None,
        );
        let config = RuntimeConfig {
            heartbeat: HeartbeatConfig {
                interval: Duration::from_secs(1),
                max_retries: 5,
                // After one failure retry_attempt=1 -> capped at
                // max_backoff=2s, equal jitter floors at 1s. The shutdown
                // below lands ~300ms in, well inside the backoff window.
                base_backoff: Duration::from_secs(2),
                max_backoff: Duration::from_secs(2),
                missed_threshold: 1,
            },
            event_buffer_size: 100,
        };

        let (event_tx, mut event_rx) = mpsc::channel(100);
        let (shutdown_tx, shutdown_rx) = mpsc::channel(1);
        let (_command_tx, command_rx) = mpsc::channel(10);
        let shared_state = Arc::new(RwLock::new(HandleState::default()));

        let runtime = AgentRuntime::new(
            spec,
            config,
            event_tx,
            shared_state,
            shutdown_rx,
            command_rx,
        )
        .await
        .expect("runtime construction should succeed");

        let join = tokio::spawn(runtime.run());

        // Let the first heartbeat fail and the Retry backoff begin, then
        // request shutdown mid-backoff.
        sleep(Duration::from_millis(300)).await;
        shutdown_tx.send(()).await.expect("shutdown signal");

        // The runtime must exit promptly (backoff floor is 1s; allow 5s).
        tokio::time::timeout(Duration::from_secs(5), join)
            .await
            .expect("runtime did not exit after shutdown during retry backoff")
            .expect("runtime task panicked");

        // Collect emitted events: must include shutdown, must NOT include
        // a (re-)registration.
        let mut saw_shutdown = false;
        while let Ok(event) = event_rx.try_recv() {
            assert_ne!(
                event.event_type,
                EventType::AgentRegistered,
                "agent must not re-register after shutdown was requested"
            );
            if event.event_type == EventType::Shutdown {
                saw_shutdown = true;
            }
        }
        assert!(saw_shutdown, "shutdown event must be emitted to the caller");

        fail.assert_async().await;
        assert!(
            !recover.matched_async().await,
            "no heartbeat may be sent after shutdown arrived during backoff"
        );
        unregister.assert_async().await;
    }
}
