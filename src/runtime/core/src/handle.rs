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
use tokio::sync::{mpsc, Mutex, RwLock};

use crate::events::{HealthStatus, MeshEvent};

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
}

impl AgentHandle {
    /// Create a new handle with the given channels.
    pub fn new(
        event_rx: mpsc::Receiver<MeshEvent>,
        state: Arc<RwLock<HandleState>>,
        shutdown_tx: mpsc::Sender<()>,
    ) -> Self {
        Self {
            event_rx: Arc::new(Mutex::new(event_rx)),
            state,
            shutdown_tx,
        }
    }

    /// Get a reference to the shared state.
    pub fn state(&self) -> Arc<RwLock<HandleState>> {
        self.state.clone()
    }
}

/// Python-specific methods for AgentHandle
#[cfg(feature = "python")]
#[pymethods]
impl AgentHandle {
    /// Wait for and return the next mesh event.
    ///
    /// This is an async method that blocks until an event is available.
    /// Returns None when the runtime has shut down.
    ///
    /// # Example (Python)
    /// ```python
    /// event = await handle.next_event()
    /// if event.event_type == "dependency_available":
    ///     print(f"Dependency {event.capability} at {event.endpoint}")
    /// ```
    fn next_event<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let event_rx = self.event_rx.clone();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut rx = event_rx.lock().await;
            match rx.recv().await {
                Some(event) => Ok(event),
                None => {
                    // Channel closed, return shutdown event
                    Ok(MeshEvent::shutdown())
                }
            }
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
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_handle_state() {
        let (event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let _handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx);

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
            ))
            .await
            .unwrap();

        drop(event_tx);
    }

    #[test]
    fn test_handle_shutdown() {
        let (_event_tx, event_rx) = mpsc::channel(10);
        let (shutdown_tx, mut shutdown_rx) = mpsc::channel(1);
        let state = Arc::new(RwLock::new(HandleState::default()));

        let handle = AgentHandle::new(event_rx, state.clone(), shutdown_tx);

        // Request shutdown (using internal method for tests)
        handle.shutdown_internal();

        // Check flag is set
        assert!(handle.is_shutdown_requested_internal());

        // Check signal was sent
        assert!(shutdown_rx.try_recv().is_ok());
    }
}
