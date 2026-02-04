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

use crate::config::is_tracing_enabled;
use crate::events::MeshEvent;
use crate::handle::HandleState;
use crate::runtime::{AgentRuntime, RuntimeConfig};
use crate::spec::AgentSpec;
use crate::tracing_publish;

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
    /// Channel to send commands to the runtime (e.g., update tools)
    command_tx: mpsc::Sender<crate::runtime::RuntimeCommand>,
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
    let (command_tx, command_rx) = mpsc::channel::<crate::runtime::RuntimeCommand>(10);
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
        AgentRuntime::new(spec_clone, config, event_tx, shared_state_clone, shutdown_rx, command_rx)
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
        command_tx,
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
/// If the agent is still running, this will trigger graceful shutdown
/// and wait briefly (up to 2 seconds) for the agent to unregister from
/// the registry before dropping resources.
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

    // Take ownership
    let handle = Box::from_raw(handle);

    // If still running, trigger graceful shutdown and wait briefly
    if handle.is_running() {
        warn!("FFI: Agent still running during free, triggering graceful shutdown");

        // Send shutdown signal
        let _ = handle.shutdown_tx.try_send(());

        // Wait briefly for graceful termination (up to 2 seconds)
        handle.runtime.block_on(async {
            tokio::time::sleep(Duration::from_millis(100)).await;
        });
    }

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

// =============================================================================
// Config Resolution Functions
// =============================================================================

/// Resolve configuration value with priority: ENV > param > default.
///
/// For http_host, auto-detects external IP if no value provided.
///
/// # Arguments
/// * `key_name` - Config key (e.g., "http_host", "registry_url", "namespace")
/// * `param_value` - Optional value from code/config (NULL for none)
///
/// # Returns
/// Resolved value (caller must free with `mesh_free_string`), or NULL if unknown key
///
/// # Safety
/// * `key_name` must be a valid null-terminated C string
/// * `param_value` may be NULL or a valid null-terminated C string
/// * The returned string must be freed with `mesh_free_string`
#[no_mangle]
pub unsafe extern "C" fn mesh_resolve_config(
    key_name: *const c_char,
    param_value: *const c_char,
) -> *mut c_char {
    if key_name.is_null() {
        set_last_error("key_name is null");
        return ptr::null_mut();
    }

    let key = match CStr::from_ptr(key_name).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in key_name: {}", e));
            return ptr::null_mut();
        }
    };

    let param = if param_value.is_null() {
        None
    } else {
        match CStr::from_ptr(param_value).to_str() {
            Ok(s) if !s.is_empty() => Some(s),
            Ok(_) => None, // Empty string treated as no value
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in param_value: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let result = crate::config::resolve_config_by_name(key, param);

    if result.is_empty() {
        // Unknown key or no value available
        return ptr::null_mut();
    }

    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Resolve integer configuration value with priority: ENV > param > default.
///
/// # Arguments
/// * `key_name` - Config key (e.g., "http_port", "health_interval")
/// * `param_value` - Value from code/config (-1 for none)
///
/// # Returns
/// Resolved value, or -1 if unknown key or no value available
///
/// # Safety
/// * `key_name` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_resolve_config_int(
    key_name: *const c_char,
    param_value: i64,
) -> i64 {
    if key_name.is_null() {
        set_last_error("key_name is null");
        return -1;
    }

    let key = match CStr::from_ptr(key_name).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in key_name: {}", e));
            return -1;
        }
    };

    let param = if param_value < 0 { None } else { Some(param_value) };

    match crate::config::ConfigKey::from_name(key) {
        Some(k) => crate::config::resolve_config_int(k, param).unwrap_or(-1),
        None => {
            set_last_error(format!("Unknown config key: {}", key));
            -1
        }
    }
}

/// Auto-detect external IP address.
///
/// Uses UDP socket trick to find IP that routes to external networks.
/// Falls back to "localhost" if detection fails.
///
/// # Returns
/// IP address string (caller must free with `mesh_free_string`)
///
/// # Safety
/// * The returned string must be freed with `mesh_free_string`
#[no_mangle]
pub extern "C" fn mesh_auto_detect_ip() -> *mut c_char {
    let ip = crate::config::auto_detect_external_ip();

    match CString::new(ip) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
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
// Tracing Functions
// =============================================================================

/// Global tokio runtime for tracing operations.
/// Lazily initialized on first tracing call.
static TRACING_RUNTIME: std::sync::OnceLock<tokio::runtime::Runtime> = std::sync::OnceLock::new();

fn get_tracing_runtime() -> &'static tokio::runtime::Runtime {
    TRACING_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .thread_name("mesh-trace")
            .enable_all()
            .build()
            .expect("Failed to create tracing runtime")
    })
}

/// Check if distributed tracing is enabled.
///
/// Checks MCP_MESH_DISTRIBUTED_TRACING_ENABLED environment variable.
///
/// # Returns
/// 1 if tracing is enabled, 0 otherwise
#[no_mangle]
pub extern "C" fn mesh_is_tracing_enabled() -> i32 {
    if is_tracing_enabled() { 1 } else { 0 }
}

/// Initialize the trace publisher.
///
/// Must be called before `mesh_publish_span`. Connects to Redis.
///
/// # Returns
/// 1 on success (Redis connected), 0 on failure
#[no_mangle]
pub extern "C" fn mesh_init_trace_publisher() -> i32 {
    let rt = get_tracing_runtime();
    let result = rt.block_on(async {
        tracing_publish::init_trace_publisher().await
    });

    if result {
        info!("FFI: Trace publisher initialized successfully");
        1
    } else {
        debug!("FFI: Trace publisher initialization failed (tracing disabled or Redis unavailable)");
        0
    }
}

/// Check if trace publisher is available.
///
/// # Returns
/// 1 if publisher is initialized and ready, 0 otherwise
#[no_mangle]
pub extern "C" fn mesh_is_trace_publisher_available() -> i32 {
    let rt = get_tracing_runtime();
    let result = rt.block_on(async {
        tracing_publish::is_trace_publisher_available().await
    });

    if result { 1 } else { 0 }
}

/// Publish a trace span to Redis.
///
/// Non-blocking (from the caller's perspective) - returns after queuing the span.
/// Silently handles failures to never break agent operations.
///
/// # Arguments
/// * `span_json` - JSON string containing span data (all values should be strings)
///
/// # Returns
/// 1 on success (queued), 0 on failure
///
/// # Safety
/// * `span_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_publish_span(span_json: *const c_char) -> i32 {
    if span_json.is_null() {
        debug!("FFI: mesh_publish_span called with null span_json");
        return 0;
    }

    let json_str = match CStr::from_ptr(span_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            debug!("FFI: Invalid UTF-8 in span_json: {}", e);
            return 0;
        }
    };

    // Parse JSON into HashMap
    let span_data: std::collections::HashMap<String, String> = match serde_json::from_str(json_str) {
        Ok(data) => data,
        Err(e) => {
            debug!("FFI: Failed to parse span JSON: {}", e);
            return 0;
        }
    };

    // Publish to Redis
    let rt = get_tracing_runtime();
    let result = rt.block_on(async {
        tracing_publish::publish_span(span_data).await
    });

    if result {
        debug!("FFI: Trace span published successfully");
        1
    } else {
        debug!("FFI: Failed to publish trace span");
        0
    }
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

    #[test]
    fn test_resolve_config_namespace() {
        unsafe {
            let key = CString::new("namespace").unwrap();
            let result = mesh_resolve_config(key.as_ptr(), ptr::null());
            assert!(!result.is_null());
            let value = CStr::from_ptr(result).to_str().unwrap();
            // Default namespace is "default"
            assert_eq!(value, "default");
            mesh_free_string(result);
        }
    }

    #[test]
    fn test_resolve_config_with_param() {
        unsafe {
            let key = CString::new("namespace").unwrap();
            let param = CString::new("production").unwrap();
            let result = mesh_resolve_config(key.as_ptr(), param.as_ptr());
            assert!(!result.is_null());
            let value = CStr::from_ptr(result).to_str().unwrap();
            assert_eq!(value, "production");
            mesh_free_string(result);
        }
    }

    #[test]
    fn test_resolve_config_unknown_key() {
        unsafe {
            let key = CString::new("unknown_key").unwrap();
            let result = mesh_resolve_config(key.as_ptr(), ptr::null());
            assert!(result.is_null());
        }
    }

    #[test]
    fn test_resolve_config_null_key() {
        unsafe {
            let result = mesh_resolve_config(ptr::null(), ptr::null());
            assert!(result.is_null());
            let err = mesh_last_error();
            assert!(!err.is_null());
            mesh_free_string(err);
        }
    }

    #[test]
    fn test_resolve_config_int() {
        unsafe {
            let key = CString::new("health_interval").unwrap();
            // Default is 5
            let result = mesh_resolve_config_int(key.as_ptr(), -1);
            assert_eq!(result, 5);
        }
    }

    #[test]
    fn test_resolve_config_int_with_param() {
        unsafe {
            let key = CString::new("health_interval").unwrap();
            let result = mesh_resolve_config_int(key.as_ptr(), 10);
            assert_eq!(result, 10);
        }
    }

    #[test]
    fn test_resolve_config_int_unknown_key() {
        unsafe {
            let key = CString::new("unknown_key").unwrap();
            let result = mesh_resolve_config_int(key.as_ptr(), -1);
            assert_eq!(result, -1);
        }
    }

    #[test]
    fn test_auto_detect_ip() {
        let result = mesh_auto_detect_ip();
        assert!(!result.is_null());
        unsafe {
            let ip = CStr::from_ptr(result).to_str().unwrap();
            // Should return something (either real IP or localhost)
            assert!(!ip.is_empty());
            mesh_free_string(result);
        }
    }

    #[test]
    fn test_resolve_config_http_host_auto_detect() {
        unsafe {
            let key = CString::new("http_host").unwrap();
            let result = mesh_resolve_config(key.as_ptr(), ptr::null());
            assert!(!result.is_null());
            let value = CStr::from_ptr(result).to_str().unwrap();
            // Should return auto-detected IP (not empty)
            assert!(!value.is_empty());
            mesh_free_string(result);
        }
    }

    #[test]
    fn test_mesh_is_tracing_enabled_default() {
        // Without env var set, should return 0
        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        assert_eq!(mesh_is_tracing_enabled(), 0);
    }

    #[test]
    fn test_mesh_is_tracing_enabled_with_env() {
        std::env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        assert_eq!(mesh_is_tracing_enabled(), 1);
        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
    }

    #[test]
    fn test_mesh_publish_span_null_json() {
        unsafe {
            // Should return 0 for null input
            assert_eq!(mesh_publish_span(ptr::null()), 0);
        }
    }

    #[test]
    fn test_mesh_publish_span_invalid_json() {
        unsafe {
            let invalid = CString::new("not valid json").unwrap();
            // Should return 0 for invalid JSON
            assert_eq!(mesh_publish_span(invalid.as_ptr()), 0);
        }
    }
}
