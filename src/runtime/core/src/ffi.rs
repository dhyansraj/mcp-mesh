//! C-compatible FFI bindings for MCP Mesh Core.
//!
//! This module provides a minimal C API for multi-language SDK support.
//! Data is exchanged as JSON strings for universal compatibility.
//!
//! # Safety
//!
//! All functions are designed to be safe to call from any thread.
//! Strings returned by `mesh_*` functions must be freed with `mesh_free_string`.
//! Handles returned by `mesh_start_agent` must be freed with `mesh_free_handle`.

use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::ptr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};

use crate::events::MeshEvent;
use crate::handle::HandleState;
use crate::runtime::{AgentRuntime, RuntimeConfig};
use crate::spec::AgentSpec;

// Thread-local last error storage
thread_local! {
    static LAST_ERROR: std::cell::RefCell<Option<String>> = const { std::cell::RefCell::new(None) };
}

/// Set the last error message for the current thread.
fn set_last_error(err: impl Into<String>) {
    LAST_ERROR.with(|e| *e.borrow_mut() = Some(err.into()));
}

/// Take and clear the last error message for the current thread.
fn take_last_error() -> Option<String> {
    LAST_ERROR.with(|e| e.borrow_mut().take())
}

/// Opaque handle to a running MCP Mesh agent.
///
/// This struct holds all resources needed to interact with the agent runtime.
/// It must be freed with `mesh_free_handle` when no longer needed.
///
/// Note: This struct is intentionally NOT `#[repr(C)]` to keep its internals
/// opaque to C consumers. The FFI functions work with raw pointers.
pub struct MeshAgentHandle {
    /// Channel to receive events from the runtime
    event_rx: mpsc::Receiver<MeshEvent>,
    /// Channel to signal shutdown to the runtime
    shutdown_tx: mpsc::Sender<()>,
    /// Tokio runtime running the agent
    runtime: tokio::runtime::Runtime,
    /// Whether the agent is still running
    is_running: AtomicBool,
    /// Agent ID once registered
    agent_id: Option<String>,
    /// Shared state with runtime (for health status updates)
    shared_state: Arc<tokio::sync::RwLock<HandleState>>,
}

impl MeshAgentHandle {
    /// Check if the agent is still running.
    pub fn is_running(&self) -> bool {
        self.is_running.load(Ordering::SeqCst)
    }

    /// Mark the agent as stopped.
    pub fn mark_stopped(&self) {
        self.is_running.store(false, Ordering::SeqCst);
    }
}

/// Library version string.
const VERSION: &str = env!("CARGO_PKG_VERSION");

// =============================================================================
// Lifecycle Functions
// =============================================================================

/// Start an agent from JSON specification.
///
/// # Arguments
/// * `spec_json` - JSON string containing AgentSpec
///
/// # Returns
/// Handle to agent, or NULL on error (check `mesh_last_error`)
///
/// # Safety
/// * `spec_json` must be a valid null-terminated C string
/// * The returned handle must be freed with `mesh_free_handle`
#[no_mangle]
pub unsafe extern "C" fn mesh_start_agent(spec_json: *const c_char) -> *mut MeshAgentHandle {
    // Clear any previous error
    take_last_error();

    // Validate input
    if spec_json.is_null() {
        set_last_error("spec_json is null");
        return ptr::null_mut();
    }

    // Parse the C string
    let spec_str = match CStr::from_ptr(spec_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in spec_json: {}", e));
            return ptr::null_mut();
        }
    };

    // Parse JSON into AgentSpec
    let spec: AgentSpec = match serde_json::from_str(spec_str) {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Failed to parse AgentSpec JSON: {}", e));
            return ptr::null_mut();
        }
    };

    info!("FFI: Starting agent '{}' from JSON spec", spec.name);

    // Create tokio runtime for this agent
    let runtime = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => {
            set_last_error(format!("Failed to create tokio runtime: {}", e));
            return ptr::null_mut();
        }
    };

    // Create channels
    let (event_tx, event_rx) = mpsc::channel(100);
    let (shutdown_tx, shutdown_rx) = mpsc::channel(1);
    let shared_state = Arc::new(tokio::sync::RwLock::new(HandleState::default()));

    // Create runtime config
    let config = RuntimeConfig {
        heartbeat: crate::heartbeat::HeartbeatConfig {
            interval: Duration::from_secs(spec.heartbeat_interval),
            ..Default::default()
        },
        ..Default::default()
    };

    // Create AgentRuntime synchronously to propagate initialization errors
    let spec_clone = spec.clone();
    let shared_state_clone = shared_state.clone();
    let agent_runtime = match runtime.block_on(async {
        AgentRuntime::new(spec_clone, config, event_tx, shared_state_clone, shutdown_rx)
    }) {
        Ok(rt) => rt,
        Err(e) => {
            set_last_error(format!("Failed to create agent runtime: {}", e));
            return ptr::null_mut();
        }
    };

    // Spawn the run loop in a background task (runtime created successfully)
    runtime.spawn(async move {
        agent_runtime.run().await;
    });

    // Create the handle
    let handle = Box::new(MeshAgentHandle {
        event_rx,
        shutdown_tx,
        runtime,
        is_running: AtomicBool::new(true),
        agent_id: None,
        shared_state,
    });

    info!("FFI: Agent '{}' started successfully", spec.name);

    Box::into_raw(handle)
}

/// Request graceful shutdown of agent.
///
/// Sends unregister to registry, stops heartbeat loop.
/// Non-blocking - use `mesh_next_event` to wait for shutdown event.
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
#[no_mangle]
pub unsafe extern "C" fn mesh_shutdown(handle: *mut MeshAgentHandle) {
    if handle.is_null() {
        return;
    }

    let handle = &*handle;

    if !handle.is_running() {
        debug!("FFI: Agent already shut down");
        return;
    }

    info!("FFI: Requesting agent shutdown");

    // Send shutdown signal (non-blocking)
    let _ = handle.shutdown_tx.try_send(());
}

/// Free agent handle and associated resources.
///
/// Call after shutdown completes or on error.
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent` or NULL
/// * After this call, `handle` is invalid and must not be used
#[no_mangle]
pub unsafe extern "C" fn mesh_free_handle(handle: *mut MeshAgentHandle) {
    if handle.is_null() {
        return;
    }

    info!("FFI: Freeing agent handle");

    // Take ownership and drop
    let handle = Box::from_raw(handle);

    // Mark as stopped
    handle.mark_stopped();

    // The runtime and channels will be dropped automatically
    drop(handle);
}

// =============================================================================
// Event Functions
// =============================================================================

/// Get next event from agent runtime.
///
/// Blocks until event available or timeout.
///
/// # Arguments
/// * `handle` - Agent handle
/// * `timeout_ms` - Timeout in milliseconds (-1 for infinite, 0 for non-blocking)
///
/// # Returns
/// JSON string (caller must free with `mesh_free_string`), or NULL on timeout/shutdown
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
/// * The returned string must be freed with `mesh_free_string`
#[no_mangle]
pub unsafe extern "C" fn mesh_next_event(
    handle: *mut MeshAgentHandle,
    timeout_ms: i64,
) -> *mut c_char {
    if handle.is_null() {
        set_last_error("handle is null");
        return ptr::null_mut();
    }

    let handle = &mut *handle;

    if !handle.is_running() {
        return ptr::null_mut();
    }

    // Receive event with timeout
    let event = handle.runtime.block_on(async {
        if timeout_ms < 0 {
            // Infinite wait
            handle.event_rx.recv().await
        } else if timeout_ms == 0 {
            // Non-blocking
            match handle.event_rx.try_recv() {
                Ok(event) => Some(event),
                Err(_) => None,
            }
        } else {
            // Timeout
            let duration = Duration::from_millis(timeout_ms as u64);
            tokio::time::timeout(duration, handle.event_rx.recv())
                .await
                .ok()
                .flatten()
        }
    });

    match event {
        Some(event) => {
            // Check for shutdown event
            if event.event_type == crate::events::EventType::Shutdown {
                handle.mark_stopped();
            }

            // Serialize to JSON
            match serde_json::to_string(&event) {
                Ok(json) => match CString::new(json) {
                    Ok(c_str) => c_str.into_raw(),
                    Err(e) => {
                        set_last_error(format!("Failed to create C string: {}", e));
                        ptr::null_mut()
                    }
                },
                Err(e) => {
                    set_last_error(format!("Failed to serialize event: {}", e));
                    ptr::null_mut()
                }
            }
        }
        None => {
            // Channel closed or timeout
            ptr::null_mut()
        }
    }
}

/// Check if agent is still running.
///
/// # Arguments
/// * `handle` - Agent handle
///
/// # Returns
/// 1 if running, 0 if shutdown/error
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
#[no_mangle]
pub unsafe extern "C" fn mesh_is_running(handle: *const MeshAgentHandle) -> i32 {
    if handle.is_null() {
        return 0;
    }

    let handle = &*handle;
    if handle.is_running() {
        1
    } else {
        0
    }
}

// =============================================================================
// Health Reporting
// =============================================================================

/// Report agent health status.
///
/// # Arguments
/// * `handle` - Agent handle
/// * `status` - Health status: "healthy", "degraded", or "unhealthy"
///
/// # Returns
/// 0 on success, -1 on error
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
/// * `status` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_report_health(
    handle: *mut MeshAgentHandle,
    status: *const c_char,
) -> i32 {
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }

    if status.is_null() {
        set_last_error("status is null");
        return -1;
    }

    let status_str = match CStr::from_ptr(status).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in status: {}", e));
            return -1;
        }
    };

    let health_status = match status_str {
        "healthy" => crate::events::HealthStatus::Healthy,
        "degraded" => crate::events::HealthStatus::Degraded,
        "unhealthy" => crate::events::HealthStatus::Unhealthy,
        _ => {
            set_last_error(format!(
                "Invalid health status '{}', expected: healthy, degraded, or unhealthy",
                status_str
            ));
            return -1;
        }
    };

    // Update health status in shared state
    let handle = &*handle;
    handle.runtime.block_on(async {
        let mut state = handle.shared_state.write().await;
        state.health_status = health_status;
    });

    info!("FFI: Health status updated to: {}", status_str);

    0
}

// =============================================================================
// Utility Functions
// =============================================================================

/// Get last error message.
///
/// Thread-local, cleared on next `mesh_*` call.
///
/// # Returns
/// Error message (caller must free with `mesh_free_string`), or NULL if no error
///
/// # Safety
/// * The returned string must be freed with `mesh_free_string`
#[no_mangle]
pub extern "C" fn mesh_last_error() -> *mut c_char {
    match take_last_error() {
        Some(error) => match CString::new(error) {
            Ok(c_str) => c_str.into_raw(),
            Err(_) => ptr::null_mut(),
        },
        None => ptr::null_mut(),
    }
}

/// Free string returned by `mesh_*` functions.
///
/// # Safety
/// * `s` must be a string returned by a `mesh_*` function or NULL
/// * After this call, `s` is invalid and must not be used
#[no_mangle]
pub unsafe extern "C" fn mesh_free_string(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

/// Get library version string.
///
/// # Returns
/// Version string (do not free)
#[no_mangle]
pub extern "C" fn mesh_version() -> *const c_char {
    // Use a static CString to ensure the pointer remains valid
    static VERSION_CSTR: std::sync::OnceLock<CString> = std::sync::OnceLock::new();
    VERSION_CSTR
        .get_or_init(|| CString::new(VERSION).unwrap())
        .as_ptr()
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version() {
        let version = mesh_version();
        assert!(!version.is_null());
        unsafe {
            let version_str = CStr::from_ptr(version).to_str().unwrap();
            assert!(!version_str.is_empty());
        }
    }

    #[test]
    fn test_last_error() {
        // Initially no error
        let err = mesh_last_error();
        assert!(err.is_null());

        // Set an error
        set_last_error("test error");
        let err = mesh_last_error();
        assert!(!err.is_null());

        unsafe {
            let err_str = CStr::from_ptr(err).to_str().unwrap();
            assert_eq!(err_str, "test error");
            mesh_free_string(err);
        }

        // Error should be cleared
        let err = mesh_last_error();
        assert!(err.is_null());
    }

    #[test]
    fn test_start_agent_null_spec() {
        unsafe {
            let handle = mesh_start_agent(ptr::null());
            assert!(handle.is_null());

            let err = mesh_last_error();
            assert!(!err.is_null());
            let err_str = CStr::from_ptr(err).to_str().unwrap();
            assert!(err_str.contains("null"));
            mesh_free_string(err);
        }
    }

    #[test]
    fn test_start_agent_invalid_json() {
        unsafe {
            let invalid_json = CString::new("not valid json").unwrap();
            let handle = mesh_start_agent(invalid_json.as_ptr());
            assert!(handle.is_null());

            let err = mesh_last_error();
            assert!(!err.is_null());
            let err_str = CStr::from_ptr(err).to_str().unwrap();
            assert!(err_str.contains("JSON") || err_str.contains("parse"));
            mesh_free_string(err);
        }
    }

    #[test]
    fn test_free_null_handle() {
        // Should not panic
        unsafe {
            mesh_free_handle(ptr::null_mut());
        }
    }

    #[test]
    fn test_free_null_string() {
        // Should not panic
        unsafe {
            mesh_free_string(ptr::null_mut());
        }
    }
}
