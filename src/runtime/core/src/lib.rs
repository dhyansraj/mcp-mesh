//! MCP Mesh Core - Rust runtime for MCP Mesh agents.
//!
//! This crate provides the core runtime functionality for MCP Mesh agents:
//! - Agent startup and registration
//! - Heartbeat loop (fast HEAD + conditional POST)
//! - Topology management and change detection
//! - Event streaming to language SDKs
//!
//! # Architecture
//!
//! ```text
//! Python SDK                     Rust Core
//! ───────────────────────────────────────────
//! Decorators          →
//! Metadata collection →          AgentSpec
//!                                ↓
//!                               start_agent()
//!                                ↓
//!                               AgentRuntime
//!                                ├─ HeartbeatLoop
//!                                ├─ RegistryClient
//!                                └─ TopologyManager
//!                                ↓
//! Event listener      ←         EventStream
//! DI updates          ←         MeshEvent
//! ```

pub mod events;
pub mod handle;
pub mod heartbeat;
pub mod registry;
pub mod runtime;
pub mod spec;

use pyo3::prelude::*;
use std::sync::Arc;
use std::thread;
use tokio::sync::RwLock;
use tracing::info;
use tracing_subscriber::EnvFilter;

use events::{HealthStatus, LlmToolInfo, MeshEvent};
use handle::{AgentHandle, HandleState};
use runtime::RuntimeConfig;
use spec::{AgentSpec, DependencySpec, LlmAgentSpec, ToolSpec};

/// Initialize logging with tracing.
fn init_logging() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("mcp_mesh_core=debug".parse().unwrap()))
        .try_init();
}

/// Start an agent runtime with the given specification.
///
/// This spawns a background Tokio runtime that handles:
/// - Registration with the mesh registry
/// - Periodic heartbeats
/// - Topology change detection
/// - Event streaming
///
/// # Arguments
/// * `spec` - Agent specification including name, capabilities, dependencies
///
/// # Returns
/// Handle to the running agent runtime
///
/// # Raises
/// * `RuntimeError` - If agent startup fails
#[pyfunction]
#[pyo3(signature = (spec))]
fn start_agent(py: Python<'_>, spec: AgentSpec) -> PyResult<AgentHandle> {
    init_logging();

    info!("Starting agent '{}' with Rust core", spec.name);

    // Create runtime config from spec
    let config = RuntimeConfig {
        heartbeat: heartbeat::HeartbeatConfig {
            interval: std::time::Duration::from_secs(spec.heartbeat_interval),
            ..Default::default()
        },
        ..Default::default()
    };

    // We need to spawn a tokio runtime in a background thread
    // because Python's asyncio and tokio don't mix well in the same thread
    let (event_rx, shared_state, shutdown_tx) = {
        // Create channels that will be used by both the spawned thread and the handle
        let (event_tx, event_rx) = tokio::sync::mpsc::channel(config.event_buffer_size);
        let (shutdown_tx, shutdown_rx) = tokio::sync::mpsc::channel(1);
        let shared_state = Arc::new(RwLock::new(HandleState::default()));

        let spec_clone = spec.clone();
        let config_clone = config.clone();
        let event_tx_clone = event_tx;
        let shared_state_clone = shared_state.clone();

        // Spawn background thread with tokio runtime
        thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
            rt.block_on(async {
                match runtime::AgentRuntime::new(
                    spec_clone,
                    config_clone,
                    event_tx_clone,
                    shared_state_clone,
                    shutdown_rx,
                ) {
                    Ok(agent_runtime) => {
                        agent_runtime.run().await;
                    }
                    Err(e) => {
                        tracing::error!("Failed to create agent runtime: {}", e);
                    }
                }
            });
        });

        (event_rx, shared_state, shutdown_tx)
    };

    // Create the handle
    let handle = AgentHandle::new(event_rx, shared_state, shutdown_tx);

    Ok(handle)
}

/// MCP Mesh Core Python module.
#[pymodule]
fn mcp_mesh_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Initialize logging on module import
    init_logging();

    // Register types
    m.add_class::<AgentSpec>()?;
    m.add_class::<ToolSpec>()?;
    m.add_class::<DependencySpec>()?;
    m.add_class::<LlmAgentSpec>()?;
    m.add_class::<AgentHandle>()?;
    m.add_class::<MeshEvent>()?;
    m.add_class::<LlmToolInfo>()?;
    m.add_class::<HealthStatus>()?;

    // Register functions
    m.add_function(wrap_pyfunction!(start_agent, m)?)?;

    Ok(())
}
