//! Agent handle for controlling the runtime and receiving events.
//!
//! The AgentHandle is returned when starting an agent and provides:
//! - Async event stream for topology updates
//! - Current state queries
//! - Shutdown control

#[cfg(feature = "python")]
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, Mutex, RwLock};

use crate::events::{HealthStatus, MeshEvent};
use crate::runtime::RuntimeCommand;
use crate::spec::ToolSpec;

/// Internal state shared between handle and runtime.
pub struct HandleState {
    /// Current dependency endpoints (capability -> endpoint)
    pub dependencies: HashMap<String, String>,

    /// Current health status
    pub health_status: HealthStatus,

    /// Whether shutdown has been requested
    pub shutdown_requested: bool,

    /// Agent ID assigned by registry
    pub agent_id: Option<String>,
}

impl Default for HandleState {
    fn default() -> Self {
        Self {
            dependencies: HashMap::new(),
            health_status: HealthStatus::Healthy,
            shutdown_requested: false,
            agent_id: None,
        }
    }
}

/// Handle to a running agent runtime.
///
/// This is the primary interface for language SDKs to interact with the Rust core.
/// It provides async event streaming and state queries.
#[cfg_attr(feature = "python", pyclass)]
pub struct AgentHandle {
    /// Event receiver (from runtime)
    event_rx: Arc<Mutex<mpsc::Receiver<MeshEvent>>>,

    /// Shared state
    state: Arc<RwLock<HandleState>>,

    /// Shutdown signal sender
    shutdown_tx: mpsc::Sender<()>,

    /// Command sender for runtime commands (e.g., update tools)
    command_tx: mpsc::Sender<RuntimeCommand>,
}

impl AgentHandle {
    /// Create a new handle with the given channels.
    pub fn new(
        event_rx: mpsc::Receiver<MeshEvent>,
        state: Arc<RwLock<HandleState>>,
        shutdown_tx: mpsc::Sender<()>,
        command_tx: mpsc::Sender<RuntimeCommand>,
    ) -> Self {
        Self {
            event_rx: Arc::new(Mutex::new(event_rx)),
            state,
            shutdown_tx,
            command_tx,
        }
    }

    /// Get a reference to the shared state.
    pub fn state(&self) -> Arc<RwLock<HandleState>> {
        self.state.clone()
    }

    /// Get a reference to the event receiver (for language bindings).
    pub fn event_rx(&self) -> Arc<Mutex<mpsc::Receiver<MeshEvent>>> {
        self.event_rx.clone()
    }

    /// Cancel-safe pull of the next mesh event, with an internal liveness
    /// timeout.
    ///
    /// Returns:
    /// - `Some(event)` when an event is available;
    /// - `Some(MeshEvent::shutdown())` when the runtime channel has closed;
    /// - `None` when `timeout` elapsed with no event (a loop-liveness tick so
    ///   callers can re-check their own shutdown flag).
    ///
    /// # Cancel-safety invariant
    /// This function never removes a message from the channel that it does not
    /// return. `mpsc::Receiver::recv` is cancel-safe, and `tokio::time::timeout`
    /// only drops the `recv` future when the timer wins the race — at which
    /// point `recv` has not yet dequeued anything. This is the whole point of
    /// pushing the timeout *inside* the future (issue #1256): the previous
    /// design wrapped `next_event()` in an external `asyncio.wait_for(...)`,
    /// whose cancellation could fire in the window *after* `recv` dequeued a
    /// message but *before* it crossed the pyo3→asyncio boundary, silently
    /// dropping that event and permanently stalling a dependency edge. With
    /// the timeout internal, callers loop on plain `.await`s and no event is
    /// ever cancelled mid-delivery.
    pub async fn pull_next_event(
        event_rx: Arc<Mutex<mpsc::Receiver<MeshEvent>>>,
        timeout: Duration,
    ) -> Option<MeshEvent> {
        let mut rx = event_rx.lock().await;
        match tokio::time::timeout(timeout, rx.recv()).await {
            Ok(Some(event)) => Some(event),
            // Channel closed — surface the shutdown sentinel so the caller
            // can break its loop, matching the pre-existing contract.
            Ok(None) => Some(MeshEvent::shutdown()),
            // Timer won the race; recv did not dequeue anything (cancel-safe).
            Err(_) => None,
        }
    }
}

/// Python-specific methods for AgentHandle
#[cfg(feature = "python")]
#[pymethods]
impl AgentHandle {
    /// Wait for and return the next mesh event.
    ///
    /// This is an async method that resolves either with the next event or,
    /// after a short internal liveness timeout, with `None`. `None` means "no
    /// event yet" — the caller should loop and re-check its own shutdown flag,
    /// then call `next_event()` again. A `shutdown` event is returned when the
    /// runtime channel closes.
    ///
    /// # Cancel-safety (issue #1256)
    /// The timeout lives *inside* this future (see [`Self::pull_next_event`]),
    /// so callers MUST NOT wrap this in an external `asyncio.wait_for(...)`
    /// cancellation: doing so can drop a dequeued event in the window between
    /// the mpsc pop and delivery to Python, permanently stalling a dependency
    /// edge. Loop on plain `await handle.next_event()` and branch on `None`.
    ///
    /// # Example (Python)
    /// ```python
    /// event = await handle.next_event()
    /// if event is None:
    ///     continue  # liveness tick; re-check shutdown and loop
    /// if event.event_type == "dependency_available":
    ///     print(f"Dependency {event.capability} at {event.endpoint}")
    /// ```
    fn next_event<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let event_rx = self.event_rx.clone();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Ok(AgentHandle::pull_next_event(event_rx, Duration::from_secs(1)).await)
        })
    }

    /// Get current dependency endpoints.
    ///
    /// Returns a dict mapping capability names to endpoint URLs.
    /// This is a snapshot of the current state.
    fn get_dependencies(&self) -> PyResult<HashMap<String, String>> {
        Ok(self.get_dependencies_internal())
    }

    /// Get current agent health status.
    fn get_status(&self) -> PyResult<HealthStatus> {
        Ok(self.get_status_internal())
    }

    /// Get the agent ID assigned by the registry.
    ///
    /// Returns None if not yet registered.
    fn get_agent_id(&self) -> PyResult<Option<String>> {
        Ok(self.get_agent_id_internal())
    }

    /// Check if shutdown has been requested.
    fn is_shutdown_requested(&self) -> PyResult<bool> {
        Ok(self.is_shutdown_requested_internal())
    }

    /// Request graceful shutdown of the agent runtime.
    ///
    /// This signals the runtime to stop heartbeats and clean up.
    /// The next call to `next_event()` will return a shutdown event.
    fn shutdown(&self) -> PyResult<()> {
        self.shutdown_internal();
        Ok(())
    }

    /// Update the HTTP port after auto-detection.
    ///
    /// Call this after the server starts with port=0 to update
    /// the registry with the actual assigned port.
    ///
    /// Returns True if the update was sent successfully.
    #[pyo3(name = "update_port")]
    fn update_port_py(&self, port: u16) -> PyResult<bool> {
        Ok(self.command_tx.try_send(RuntimeCommand::UpdatePort(port)).is_ok())
    }

    fn __repr__(&self) -> String {
        let state = self.state.blocking_read();
        format!(
            "AgentHandle(agent_id={:?}, dependencies={}, status={:?})",
            state.agent_id,
            state.dependencies.len(),
            state.health_status
        )
    }
}

/// Language-agnostic methods for AgentHandle (used by both Python and FFI)
impl AgentHandle {
    /// Get current dependency endpoints.
    pub fn get_dependencies_internal(&self) -> HashMap<String, String> {
        let state = self.state.blocking_read();
        state.dependencies.clone()
    }

    /// Get current agent health status.
    pub fn get_status_internal(&self) -> HealthStatus {
        let state = self.state.blocking_read();
        state.health_status
    }

    /// Get the agent ID assigned by the registry.
    pub fn get_agent_id_internal(&self) -> Option<String> {
        let state = self.state.blocking_read();
        state.agent_id.clone()
    }

    /// Check if shutdown has been requested.
    pub fn is_shutdown_requested_internal(&self) -> bool {
        let state = self.state.blocking_read();
        state.shutdown_requested
    }

    /// Get current dependency endpoints (async version).
    ///
    /// Use this — not the `*_internal` variant — when calling from an
    /// async context (e.g. napi-rs async methods): `blocking_read()`
    /// panics when invoked within an async execution context. Mirrors
    /// the `shutdown_async` / `update_tools_async` pattern.
    pub async fn get_dependencies_async(&self) -> HashMap<String, String> {
        let state = self.state.read().await;
        state.dependencies.clone()
    }

    /// Get current agent health status (async version).
    /// See [`Self::get_dependencies_async`] for when to use this.
    pub async fn get_status_async(&self) -> HealthStatus {
        let state = self.state.read().await;
        state.health_status
    }

    /// Get the agent ID assigned by the registry (async version).
    /// See [`Self::get_dependencies_async`] for when to use this.
    pub async fn get_agent_id_async(&self) -> Option<String> {
        let state = self.state.read().await;
        state.agent_id.clone()
    }

    /// Check if shutdown has been requested (async version).
    /// See [`Self::get_dependencies_async`] for when to use this.
    pub async fn is_shutdown_requested_async(&self) -> bool {
        let state = self.state.read().await;
        state.shutdown_requested
    }

    /// Request graceful shutdown of the agent runtime.
    pub fn shutdown_internal(&self) {
        // Set shutdown flag
        {
            let mut state = self.state.blocking_write();
            state.shutdown_requested = true;
        }

        // Send shutdown signal (non-blocking, ignore if full)
        let _ = self.shutdown_tx.try_send(());
    }

    /// Request graceful shutdown of the agent runtime (async version).
    /// Use this when calling from an async context (e.g., napi-rs).
    pub async fn shutdown_async(&self) {
        // Set shutdown flag
        {
            let mut state = self.state.write().await;
            state.shutdown_requested = true;
        }

        // Send shutdown signal (non-blocking, ignore if full)
        let _ = self.shutdown_tx.try_send(());
    }

    /// Update the tools/routes registered with the registry.
    /// Uses smart diffing - only triggers a heartbeat if tools have changed.
    pub fn update_tools(&self, tools: Vec<ToolSpec>) -> bool {
        self.command_tx
            .try_send(RuntimeCommand::UpdateTools(tools))
            .is_ok()
    }

    /// Update the tools/routes registered with the registry (async version).
    /// Uses smart diffing - only triggers a heartbeat if tools have changed.
    pub async fn update_tools_async(&self, tools: Vec<ToolSpec>) -> bool {
        self.command_tx
            .send(RuntimeCommand::UpdateTools(tools))
            .await
            .is_ok()
    }

    /// Update the HTTP port (e.g., after auto-detection).
    pub fn update_port(&self, port: u16) -> bool {
        self.command_tx
            .try_send(RuntimeCommand::UpdatePort(port))
            .is_ok()
    }

    /// Update the HTTP port (e.g., after auto-detection) - async version.
    pub async fn update_port_async(&self, port: u16) -> bool {
        self.command_tx
            .send(RuntimeCommand::UpdatePort(port))
            .await
            .is_ok()
    }

    /// Update the A2A surfaces and agent_type registered with the registry
    /// (issue #938). Uses smart diffing — only triggers a heartbeat if the
    /// payload actually changed. Call this from the SDK after each
    /// `mesh.a2a.mount(...)` (or unmount, when supported) so deferred mounts
    /// are reflected in the next heartbeat envelope rather than silently
    /// dropped.
    ///
    /// Mirrors Python's per-heartbeat `_build_a2a_surfaces` semantics
    /// (`heartbeat_preparation.py:371-389`) without paying the per-tick FFI
    /// cost: TS recomputes locally and pushes only on change.
    pub fn update_surfaces(&self, agent_type: String, surfaces: Option<String>) -> bool {
        self.command_tx
            .try_send(RuntimeCommand::UpdateSurfaces { agent_type, surfaces })
            .is_ok()
    }

    /// Update the A2A surfaces and agent_type — async version. Use this
    /// when calling from an async context (e.g., napi-rs).
    pub async fn update_surfaces_async(
        &self,
        agent_type: String,
        surfaces: Option<String>,
    ) -> bool {
        self.command_tx
            .send(RuntimeCommand::UpdateSurfaces { agent_type, surfaces })
            .await
            .is_ok()
    }

    /// Get a reference to the command sender (for language bindings that need direct access).
    pub fn command_tx(&self) -> mpsc::Sender<RuntimeCommand> {
        self.command_tx.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_handle_state() {
        let (event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, _command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let _handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        // Update state
        {
            let mut s = state.write().await;
            s.agent_id = Some("test-agent".to_string());
            s.dependencies.insert("date-service".to_string(), "http://localhost:9001".to_string());
        }

        // Query state directly (avoid blocking_read in async context)
        {
            let s = state.read().await;
            assert_eq!(s.agent_id, Some("test-agent".to_string()));
            assert_eq!(s.dependencies.len(), 1);
        }

        // Send an event
        event_tx
            .send(MeshEvent::dependency_available(
                "weather".to_string(),
                "http://localhost:9002".to_string(),
                "get_weather".to_string(),
                "weather-agent".to_string(),
                "test-tool".to_string(),
                0,
                None,
            ))
            .await
            .unwrap();

        drop(event_tx);
    }

    /// Issue #1166 MED-2: the async accessors must be callable from
    /// within a tokio runtime. The `*_internal` variants use
    /// `blocking_read()`, which panics in an async execution context —
    /// these `.await`-based variants are what async bindings (napi)
    /// must call.
    #[tokio::test]
    async fn test_async_accessors_work_in_async_context() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, _command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        {
            let mut s = state.write().await;
            s.agent_id = Some("async-agent".to_string());
            s.dependencies
                .insert("date-service".to_string(), "http://localhost:9001".to_string());
            s.health_status = HealthStatus::Degraded;
        }

        assert_eq!(
            handle.get_agent_id_async().await,
            Some("async-agent".to_string())
        );
        let deps = handle.get_dependencies_async().await;
        assert_eq!(deps.len(), 1);
        assert_eq!(
            deps.get("date-service").map(String::as_str),
            Some("http://localhost:9001")
        );
        assert_eq!(handle.get_status_async().await, HealthStatus::Degraded);
        assert!(!handle.is_shutdown_requested_async().await);

        handle.shutdown_async().await;
        assert!(handle.is_shutdown_requested_async().await);
    }

    /// Issue #1256: the event pull must be cancel-safe across its internal
    /// liveness timeout. A slow consumer that lets many timeout ticks elapse
    /// between events must still observe EVERY event — none may be dropped in
    /// the recv→deliver window. Uses a 1ms timeout so the consumer takes many
    /// `None` ticks between the producer's events.
    #[tokio::test]
    async fn test_next_event_pull_is_cancel_safe_across_timeout_ticks() {
        use crate::events::EventType;

        let (event_tx, event_rx) = mpsc::channel(100);
        let event_rx = Arc::new(Mutex::new(event_rx));

        let n = 25u32;
        let producer = tokio::spawn(async move {
            for i in 0..n {
                // Delay straddles the pull timeout so the consumer sees many
                // `None` ticks between deliveries.
                tokio::time::sleep(Duration::from_millis(3)).await;
                event_tx
                    .send(MeshEvent::dependency_available(
                        format!("cap-{i}"),
                        "http://endpoint".to_string(),
                        "func".to_string(),
                        "agent".to_string(),
                        "requesting_fn".to_string(),
                        0,
                        None,
                    ))
                    .await
                    .unwrap();
            }
            // Dropping the sender closes the channel; recv drains buffered
            // messages first, then yields the shutdown sentinel.
        });

        let mut got = 0u32;
        loop {
            match AgentHandle::pull_next_event(event_rx.clone(), Duration::from_millis(1)).await {
                Some(ev) if ev.event_type == EventType::Shutdown => break,
                Some(_) => got += 1,
                None => {} // liveness tick — keep looping
            }
        }

        producer.await.unwrap();
        assert_eq!(
            got, n,
            "no event may be lost across internal timeout ticks (cancel-safety)"
        );
    }

    /// A pull against an idle channel must resolve to `None` (a liveness tick)
    /// once the internal timeout elapses — not block forever.
    #[tokio::test]
    async fn test_next_event_pull_times_out_to_none_when_idle() {
        let (_event_tx, event_rx) = mpsc::channel::<MeshEvent>(4);
        let event_rx = Arc::new(Mutex::new(event_rx));

        let result = AgentHandle::pull_next_event(event_rx, Duration::from_millis(20)).await;
        assert!(result.is_none(), "idle channel must yield a None liveness tick");
    }

    /// When the channel closes, the pull must surface the shutdown sentinel
    /// (not `None`) so the caller breaks its loop.
    #[tokio::test]
    async fn test_next_event_pull_returns_shutdown_on_close() {
        use crate::events::EventType;

        let (event_tx, event_rx) = mpsc::channel::<MeshEvent>(4);
        let event_rx = Arc::new(Mutex::new(event_rx));
        drop(event_tx);

        let result = AgentHandle::pull_next_event(event_rx, Duration::from_secs(5)).await;
        match result {
            Some(ev) => assert_eq!(ev.event_type, EventType::Shutdown),
            None => panic!("closed channel must yield a shutdown event, not a timeout tick"),
        }
    }

    #[test]
    fn test_handle_shutdown() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, mut shutdown_rx) = mpsc::channel(1);
        let (command_tx, _command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        // Request shutdown (using internal method for tests)
        handle.shutdown_internal();

        // Check flag is set
        assert!(handle.is_shutdown_requested_internal());

        // Check signal was sent
        assert!(shutdown_rx.try_recv().is_ok());
    }

    #[tokio::test]
    async fn test_handle_update_tools() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, mut command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        // Send update tools command
        let tools = vec![ToolSpec::new(
            "GET:/time".to_string(),
            "".to_string(),
            "1.0.0".to_string(),
            "".to_string(),
            None,
            Some(vec![crate::spec::DependencySpec::new("time_service".to_string(), None, None, None, None, None, false)]),
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
        )];

        assert!(handle.update_tools(tools));

        // Verify command was received
        let cmd = command_rx.try_recv().unwrap();
        match cmd {
            RuntimeCommand::UpdateTools(received_tools) => {
                assert_eq!(received_tools.len(), 1);
                assert_eq!(received_tools[0].function_name, "GET:/time");
            }
            _ => panic!("Expected UpdateTools command"),
        }
    }

    #[tokio::test]
    async fn test_handle_update_surfaces() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, mut command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        let surfaces_json = r#"[{"path":"/agents/date","skill_id":"get-date"}]"#.to_string();
        assert!(handle.update_surfaces("a2a".to_string(), Some(surfaces_json.clone())));

        let cmd = command_rx.try_recv().unwrap();
        match cmd {
            RuntimeCommand::UpdateSurfaces { agent_type, surfaces } => {
                assert_eq!(agent_type, "a2a");
                assert_eq!(surfaces, Some(surfaces_json));
            }
            _ => panic!("Expected UpdateSurfaces command"),
        }
    }

    #[tokio::test]
    async fn test_handle_update_surfaces_clear() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, mut command_rx) = mpsc::channel(10);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx, command_tx);

        // Clearing surfaces should still propagate as a command — the
        // runtime's smart-diff inside handle_update_surfaces decides
        // whether to fire a heartbeat. The handle just enqueues.
        assert!(handle.update_surfaces("api".to_string(), None));

        let cmd = command_rx.try_recv().unwrap();
        match cmd {
            RuntimeCommand::UpdateSurfaces { agent_type, surfaces } => {
                assert_eq!(agent_type, "api");
                assert_eq!(surfaces, None);
            }
            _ => panic!("Expected UpdateSurfaces command"),
        }
    }
}
