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
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{mpsc, Mutex};
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
pub(crate) fn set_last_error(err: impl Into<String>) {
    LAST_ERROR.with(|e| *e.borrow_mut() = Some(err.into()));
}

/// Take and clear the last error message for the current thread.
pub(crate) fn take_last_error() -> Option<String> {
    LAST_ERROR.with(|e| e.borrow_mut().take())
}

/// Opaque handle to a running MCP Mesh agent.
///
/// This struct holds all resources needed to interact with the agent runtime.
/// It must be freed with `mesh_free_handle` when no longer needed.
///
/// Lifetime: the raw pointer handed to C is `Arc`-managed
/// (`Arc::into_raw` in `mesh_start_agent`). Every accessor takes a
/// temporary strong reference for the duration of the call (see
/// `handle_guard`), and `mesh_free_handle` releases the creation
/// reference — so freeing while another thread is still inside
/// `mesh_next_event` / `mesh_report_health` / etc. defers the actual
/// drop until the last in-flight call returns instead of yanking the
/// memory out from under it (use-after-free under the "safe from any
/// thread" contract).
///
/// Note: This struct is intentionally NOT `#[repr(C)]` to keep its internals
/// opaque to C consumers. The FFI functions work with raw pointers.
pub struct MeshAgentHandle {
    /// Channel to receive events from the runtime. Behind a tokio Mutex
    /// (like the Python/napi handles) so `mesh_next_event` can take
    /// `*const` like every other accessor — the previous `&mut *handle`
    /// could overlap with concurrent `&*handle` borrows from
    /// `mesh_report_health` / `mesh_shutdown` / `mesh_is_running` under
    /// the "safe from any thread" contract, which is formal aliasing UB
    /// (issue #1166 LOW).
    event_rx: Mutex<mpsc::Receiver<MeshEvent>>,
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

/// Take a temporary strong reference to the handle for the duration of
/// one FFI call.
///
/// The returned `Arc` keeps the handle (and its tokio runtime) alive even
/// if `mesh_free_handle` runs concurrently on another thread — the memory
/// is released only when the last in-flight call drops its guard.
///
/// # Safety
/// `ptr` must be a non-null pointer obtained from `mesh_start_agent` that
/// has not yet been passed to `mesh_free_handle`. (Calls that *start*
/// after free are still undefined behavior — the contract is unchanged;
/// this guard only protects calls already in flight when free happens.)
unsafe fn handle_guard(ptr: *const MeshAgentHandle) -> Arc<MeshAgentHandle> {
    Arc::increment_strong_count(ptr);
    Arc::from_raw(ptr)
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
        AgentRuntime::new(spec_clone, config, event_tx, shared_state_clone, shutdown_rx, command_rx).await
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

    // Create the handle. Arc-managed (not Box) so concurrent in-flight
    // accessors each hold a strong reference via `handle_guard` and
    // `mesh_free_handle` cannot free the memory out from under them.
    let handle = Arc::new(MeshAgentHandle {
        event_rx: Mutex::new(event_rx),
        shutdown_tx,
        command_tx,
        runtime,
        is_running: AtomicBool::new(true),
        agent_id: None,
        shared_state,
    });

    info!("FFI: Agent '{}' started successfully", spec.name);

    Arc::into_raw(handle) as *mut MeshAgentHandle
}

/// Request graceful shutdown of agent.
///
/// Sends unregister to registry, stops heartbeat loop.
/// Non-blocking - use `mesh_next_event` to wait for shutdown event.
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
#[no_mangle]
pub unsafe extern "C" fn mesh_shutdown(handle: *const MeshAgentHandle) {
    if handle.is_null() {
        return;
    }

    let handle = handle_guard(handle);

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
/// Also drains queued trace spans (up to 2 seconds, equivalent to
/// `mesh_flush_spans(2000)`) so spans published during the agent's final
/// moments are not lost.
///
/// Safe to call while other threads are still inside `mesh_*` accessors
/// on the same handle (including a `mesh_next_event` parked on an
/// infinite timeout): the handle is reference-counted, so this releases
/// the creation reference and the underlying resources are dropped when
/// the last in-flight call returns. A parked infinite `mesh_next_event`
/// unparks on its own — the graceful shutdown triggered here makes the
/// runtime emit the shutdown event and then exit, closing the event
/// channel, so the parked caller observes the shutdown event (or channel
/// close → NULL) and returns. Only if the runtime is wedged and never
/// processes the shutdown signal does a parked infinite wait keep the
/// resources alive (a leak, not a crash).
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent` or NULL
/// * After this call, `handle` is invalid and must not be passed to any
///   `mesh_*` function (calls already in flight are safe; new calls are
///   not)
#[no_mangle]
pub unsafe extern "C" fn mesh_free_handle(handle: *mut MeshAgentHandle) {
    if handle.is_null() {
        return;
    }

    info!("FFI: Freeing agent handle");

    // Take back the creation reference from mesh_start_agent. In-flight
    // accessors hold their own strong counts (handle_guard), so dropping
    // this one frees the memory only when no call is mid-execution.
    let handle = Arc::from_raw(handle as *const MeshAgentHandle);

    // If still running, trigger graceful shutdown and wait (bounded) for
    // the runtime to finish unregistering before dropping it.
    if handle.is_running() {
        warn!("FFI: Agent still running during free, triggering graceful shutdown");

        // Send shutdown signal
        let _ = handle.shutdown_tx.try_send(());

        // Wait up to 2 seconds for the shutdown event. The runtime's run
        // loop sends the registry DELETE (unregister) BEFORE emitting the
        // shutdown event, so observing the event means the unregister
        // attempt completed — dropping the tokio runtime earlier would
        // abort the in-flight DELETE and leave a stale registry entry
        // until the heartbeat timeout (issue #1166 LOW).
        let waited = handle.runtime.block_on(async {
            tokio::time::timeout(Duration::from_secs(2), async {
                let mut rx = handle.event_rx.lock().await;
                loop {
                    match rx.recv().await {
                        Some(event)
                            if event.event_type == crate::events::EventType::Shutdown =>
                        {
                            break;
                        }
                        // Drain unrelated events queued before shutdown.
                        Some(_) => continue,
                        // Channel closed: the runtime task is already gone.
                        None => break,
                    }
                }
            })
            .await
        });
        if waited.is_err() {
            warn!("FFI: graceful shutdown did not complete within 2s; dropping runtime");
        }
    }

    // Drain queued trace spans (bounded). The span queue is process-global
    // and outlives this handle, but for the common one-agent-per-process
    // embedder this is the last mesh_* call before exit — without a drain
    // here, spans queued via mesh_publish_span during the agent's final
    // moments (often the diagnostically critical ones) would be silently
    // lost when the process exits. No-op if the publisher was never
    // initialized. Embedders can also call mesh_flush_spans directly.
    if !flush_span_queue(Duration::from_secs(2)) {
        warn!("FFI: trace span queue did not drain within 2s; some spans may be lost");
    }

    // Mark as stopped
    handle.mark_stopped();

    // Release the creation reference. The runtime and channels drop here
    // if no accessor is in flight, otherwise when the last guard drops.
    drop(handle);
}

// =============================================================================
// Event Functions
// =============================================================================

/// Get next event from agent runtime.
///
/// Blocks until event available or timeout. The timeout covers the FULL
/// wait, including acquisition of the internal receiver lock — a
/// `timeout_ms = 0` (non-blocking) or finite-timeout call returns within
/// its budget even while another thread is parked in an infinite
/// `mesh_next_event` wait on the same handle.
///
/// Each event is delivered to exactly ONE caller: the receiver is a
/// shared single-consumer queue, not a broadcast. With multiple
/// concurrent callers, an event goes to whichever caller dequeues it
/// first.
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
    handle: *const MeshAgentHandle,
    timeout_ms: i64,
) -> *mut c_char {
    if handle.is_null() {
        set_last_error("handle is null");
        return ptr::null_mut();
    }

    let handle = handle_guard(handle);

    if !handle.is_running() {
        return ptr::null_mut();
    }

    // Receive event with timeout. The receiver lives behind a tokio Mutex
    // so this function can share the handle (`&*handle`) with concurrent
    // accessors instead of taking `&mut` (aliasing UB under the
    // "safe from any thread" contract).
    //
    // The lock acquisition MUST sit inside the timeout: another caller may
    // hold the receiver in an infinite recv(), and wrapping only recv()
    // would turn a bounded call into an unbounded one (it would park on
    // `.lock()` first).
    let event = if timeout_ms == 0 {
        // Non-blocking: if the receiver is held by another caller, no
        // event is available to *this* caller right now — report
        // timeout instead of waiting for the lock.
        match handle.event_rx.try_lock() {
            Ok(mut event_rx) => event_rx.try_recv().ok(),
            Err(_) => None,
        }
    } else if timeout_ms < 0 {
        // Infinite wait
        handle.runtime.block_on(async {
            let mut event_rx = handle.event_rx.lock().await;
            event_rx.recv().await
        })
    } else {
        // Bounded wait covering lock + recv
        let duration = Duration::from_millis(timeout_ms as u64);
        handle.runtime.block_on(async {
            tokio::time::timeout(duration, async {
                let mut event_rx = handle.event_rx.lock().await;
                event_rx.recv().await
            })
            .await
            .ok()
            .flatten()
        })
    };

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

    let handle = handle_guard(handle);
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
    handle: *const MeshAgentHandle,
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
    let handle = handle_guard(handle);
    handle.runtime.block_on(async {
        let mut state = handle.shared_state.write().await;
        state.health_status = health_status;
    });

    info!("FFI: Health status updated to: {}", status_str);

    0
}

/// Update the HTTP port after auto-detection.
///
/// Call this after the HTTP server starts with port=0 to update
/// the registry with the actual assigned port. Triggers a full
/// heartbeat to re-register with the correct endpoint.
///
/// # Arguments
/// * `handle` - Agent handle
/// * `port` - The actual port the HTTP server is listening on
///
/// # Returns
/// 0 on success, -1 on error
///
/// # Safety
/// * `handle` must be a valid handle from `mesh_start_agent`
#[no_mangle]
pub unsafe extern "C" fn mesh_update_port(
    handle: *const MeshAgentHandle,
    port: i32,
) -> i32 {
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }

    if port < 0 || port > 65535 {
        set_last_error(format!("Invalid port: {}", port));
        return -1;
    }

    let handle = handle_guard(handle);

    match handle.command_tx.try_send(crate::runtime::RuntimeCommand::UpdatePort(port as u16)) {
        Ok(_) => {
            info!("FFI: Port updated to {}", port);
            0
        }
        Err(e) => {
            set_last_error(format!("Failed to send port update: {}", e));
            -1
        }
    }
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
        .get_or_init(|| CString::new(VERSION).expect("VERSION constant must not contain null bytes"))
        .as_ptr()
}

/// Get TLS configuration resolved from environment variables.
///
/// Returns a JSON string with the TLS config:
/// ```json
/// {
///   "enabled": true,
///   "mode": "auto",
///   "cert_path": "/path/to/cert.pem",
///   "key_path": "/path/to/key.pem",
///   "ca_path": "/path/to/ca.pem"
/// }
/// ```
///
/// When TLS is off, returns:
/// ```json
/// {"enabled": false, "mode": "off", "cert_path": null, "key_path": null, "ca_path": null}
/// ```
///
/// # Returns
/// * JSON string (caller must free with `mesh_free_string`)
/// * NULL on error (check `mesh_last_error`)
#[no_mangle]
pub extern "C" fn mesh_get_tls_config() -> *mut c_char {
    let config = crate::tls::TlsConfig::get_resolved_or_env();

    let mode_str = match config.mode {
        crate::tls::TlsMode::Off => "off",
        crate::tls::TlsMode::Auto => "auto",
        crate::tls::TlsMode::Strict => "strict",
    };

    let json = serde_json::json!({
        "enabled": config.is_enabled(),
        "mode": mode_str,
        "provider": config.provider,
        "cert_path": config.cert_path,
        "key_path": config.key_path,
        "ca_path": config.ca_path,
    });

    match CString::new(json.to_string()) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Prepare TLS credentials (fetch from provider, write secure temp files).
///
/// Must be called early in agent startup, before HTTP server starts.
/// Results are cached globally -- subsequent calls to `mesh_get_tls_config()`
/// will return the resolved config with temp file paths.
///
/// # Arguments
/// * `agent_name` - Agent name for certificate CN (e.g., "greeter-abc123")
///
/// # Returns
/// * JSON string with TLS config (caller must free with `mesh_free_string`)
/// * NULL on error (check `mesh_last_error`)
///
/// # Safety
/// * `agent_name` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_prepare_tls(agent_name: *const c_char) -> *mut c_char {
    if agent_name.is_null() {
        set_last_error("agent_name is null");
        return ptr::null_mut();
    }

    let name = match CStr::from_ptr(agent_name).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in agent_name: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::tls::TlsConfig::prepare_blocking(name) {
        Ok(config) => {
            let mode_str = match config.mode {
                crate::tls::TlsMode::Off => "off",
                crate::tls::TlsMode::Auto => "auto",
                crate::tls::TlsMode::Strict => "strict",
            };
            let json = serde_json::json!({
                "enabled": config.is_enabled(),
                "mode": mode_str,
                "provider": config.provider,
                "cert_path": config.cert_path,
                "key_path": config.key_path,
                "ca_path": config.ca_path,
            });
            match CString::new(json.to_string()) {
                Ok(c_str) => c_str.into_raw(),
                Err(e) => {
                    set_last_error(format!("Failed to create C string: {}", e));
                    ptr::null_mut()
                }
            }
        }
        Err(e) => {
            set_last_error(format!("Failed to prepare TLS: {}", e));
            ptr::null_mut()
        }
    }
}

/// Clean up temporary TLS credential files.
///
/// Call during agent shutdown. Safe to call multiple times.
#[no_mangle]
pub extern "C" fn mesh_cleanup_tls() {
    crate::tls::TlsConfig::cleanup_tls_files();
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

/// Bounded queue between `mesh_publish_span` (caller thread) and the
/// tracing runtime's drain task. Sized for bursts; on overflow spans are
/// dropped with a counter (tracing must never block or break agent
/// operations).
const SPAN_QUEUE_CAPACITY: usize = 1024;

/// Message on the span queue: a span to publish, or a flush marker whose
/// ack fires once every message enqueued before it has been processed
/// (the drain task consumes the queue in FIFO order).
enum SpanQueueMsg {
    Span(std::collections::HashMap<String, String>),
    Flush(tokio::sync::oneshot::Sender<()>),
}

/// Sender side of the span queue. Initialized by
/// `mesh_init_trace_publisher` on success; `None` (unset) means the
/// publisher was never initialized and `mesh_publish_span` returns 0.
static SPAN_QUEUE: std::sync::OnceLock<mpsc::Sender<SpanQueueMsg>> = std::sync::OnceLock::new();

/// Spans dropped because the queue was full. Logged periodically from
/// the enqueue path.
static DROPPED_SPANS: AtomicU64 = AtomicU64::new(0);

/// Initialize the span queue and spawn its drain task on the tracing
/// runtime. Idempotent — subsequent calls return the existing sender.
fn ensure_span_queue() -> &'static mpsc::Sender<SpanQueueMsg> {
    SPAN_QUEUE.get_or_init(|| {
        let (tx, mut rx) = mpsc::channel::<SpanQueueMsg>(SPAN_QUEUE_CAPACITY);
        get_tracing_runtime().spawn(async move {
            while let Some(msg) = rx.recv().await {
                match msg {
                    SpanQueueMsg::Span(span) => {
                        // Failures are already logged (debug) inside
                        // publish_span; never break the drain loop on a
                        // bad span.
                        let _ = tracing_publish::publish_span(span).await;
                    }
                    SpanQueueMsg::Flush(ack) => {
                        // FIFO: everything enqueued before this marker has
                        // been processed — wake the flusher (receiver may
                        // have given up on timeout; ignore send errors).
                        let _ = ack.send(());
                    }
                }
            }
        });
        tx
    })
}

/// Drain the span queue: block until every span enqueued via
/// `mesh_publish_span` before this call has been handed to Redis (or
/// failed), or until `timeout` elapses.
///
/// Returns true if the queue fully drained (or was never armed — nothing
/// queued means nothing to lose), false on timeout.
fn flush_span_queue(timeout: Duration) -> bool {
    let Some(queue) = SPAN_QUEUE.get() else {
        // Publisher never initialized: the queue doesn't exist, so no
        // span can be pending. Don't arm it just to flush nothing.
        return true;
    };

    let (ack_tx, ack_rx) = tokio::sync::oneshot::channel();
    get_tracing_runtime().block_on(async {
        tokio::time::timeout(timeout, async {
            if queue.send(SpanQueueMsg::Flush(ack_tx)).await.is_err() {
                // Drain task gone (runtime tearing down) — nothing more
                // can be flushed; treat as drained-as-far-as-possible.
                return;
            }
            let _ = ack_rx.await;
        })
        .await
        .is_ok()
    })
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

    // Arm the non-blocking publish path (queue + drain task) whenever tracing
    // is enabled, even if the initial connect failed: the background re-prober
    // (issue #1364) may bring Redis up later, and the drain task calls
    // publish_span which short-circuits instantly while unavailable. Without
    // arming here a Redis-down-at-startup Java agent could never publish spans
    // after recovery.
    if is_tracing_enabled() {
        let _ = ensure_span_queue();
    }

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
/// Non-blocking (from the caller's perspective) - returns after queuing the span
/// onto a bounded in-process queue drained by the tracing runtime, which
/// performs the actual Redis XADD asynchronously. Silently handles failures
/// to never break agent operations; on queue overflow the span is dropped
/// (counted, logged periodically).
///
/// # Arguments
/// * `span_json` - JSON string containing span data (all values should be strings)
///
/// # Returns
/// 1 on success (queued), 0 on failure (not initialized, invalid input,
/// or queue full)
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

    // Enqueue for the tracing runtime's drain task. The queue only exists
    // after a successful mesh_init_trace_publisher — without it there's
    // nothing to publish to, so fail fast (matches the previous behavior
    // of publish_span returning false when uninitialized).
    let Some(queue) = SPAN_QUEUE.get() else {
        debug!("FFI: mesh_publish_span called before mesh_init_trace_publisher");
        return 0;
    };

    match queue.try_send(SpanQueueMsg::Span(span_data)) {
        Ok(()) => 1,
        Err(mpsc::error::TrySendError::Full(_)) => {
            let dropped = DROPPED_SPANS.fetch_add(1, Ordering::Relaxed) + 1;
            // Log periodically rather than per drop — overflow happens in
            // bursts and per-span logging would amplify the load.
            // (`u64::is_multiple_of` needs Rust >= 1.87 — see
            // `rust-version` in Cargo.toml.)
            if dropped == 1 || dropped.is_multiple_of(100) {
                warn!(
                    "FFI: trace span queue full; dropped {} spans so far",
                    dropped
                );
            }
            0
        }
        Err(mpsc::error::TrySendError::Closed(_)) => {
            debug!("FFI: trace span queue closed");
            0
        }
    }
}

/// Flush queued trace spans.
///
/// Blocks until every span queued via `mesh_publish_span` before this
/// call has been published to Redis (or dropped on a publish error), or
/// until `timeout_ms` elapses. `mesh_free_handle` calls this
/// automatically with a 2-second budget so an agent's final spans are not
/// lost at teardown; embedders that need a different budget (or that
/// publish spans after freeing the handle) can call it directly.
///
/// # Arguments
/// * `timeout_ms` - Maximum time to wait in milliseconds; negative values
///   are treated as 0
///
/// # Returns
/// 1 if the queue fully drained (or the publisher was never initialized),
/// 0 on timeout
#[no_mangle]
pub extern "C" fn mesh_flush_spans(timeout_ms: i64) -> i32 {
    let timeout = Duration::from_millis(timeout_ms.max(0) as u64);
    if flush_span_queue(timeout) {
        1
    } else {
        0
    }
}

// =============================================================================
// Response Parsing Functions
// =============================================================================

/// Extract JSON from LLM response text.
///
/// Strategies (in order):
/// 1. Find ```json...``` code blocks
/// 2. Progressive JSON object extraction
/// 3. Progressive JSON array extraction
///
/// # Arguments
/// * `text` - Raw LLM response text
///
/// # Returns
/// Extracted JSON string (caller must free with `mesh_free_string`), or NULL if no JSON found
///
/// # Safety
/// * `text` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_extract_json(text: *const c_char) -> *mut c_char {
    if text.is_null() {
        set_last_error("text is null");
        return ptr::null_mut();
    }

    let text_str = match CStr::from_ptr(text).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in text: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::response_parser::extract_json(text_str) {
        Some(json) => match CString::new(json) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        None => ptr::null_mut(),
    }
}

/// Strip markdown code fences from content.
///
/// # Arguments
/// * `text` - Text with potential code fences
///
/// # Returns
/// Text with fences removed (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `text` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_strip_code_fences(text: *const c_char) -> *mut c_char {
    if text.is_null() {
        set_last_error("text is null");
        return ptr::null_mut();
    }

    let text_str = match CStr::from_ptr(text).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in text: {}", e));
            return ptr::null_mut();
        }
    };

    let result = crate::response_parser::strip_code_fences(text_str);
    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

// =============================================================================
// Schema Normalization Functions
// =============================================================================

/// Make a JSON schema strict for structured output.
///
/// Adds additionalProperties: false to all object types and optionally
/// sets required to include all property keys.
///
/// # Arguments
/// * `schema_json` - JSON schema string
/// * `add_all_required` - 1 to add all properties to required, 0 to skip
///
/// # Returns
/// Modified schema JSON (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `schema_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_make_schema_strict(
    schema_json: *const c_char,
    add_all_required: i32,
) -> *mut c_char {
    if schema_json.is_null() {
        set_last_error("schema_json is null");
        return ptr::null_mut();
    }

    let json_str = match CStr::from_ptr(schema_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in schema_json: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::schema::make_schema_strict(json_str, add_all_required != 0) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Sanitize a JSON schema by removing unsupported validation keywords.
///
/// # Arguments
/// * `schema_json` - JSON schema string
///
/// # Returns
/// Sanitized schema JSON (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `schema_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_sanitize_schema(schema_json: *const c_char) -> *mut c_char {
    if schema_json.is_null() {
        set_last_error("schema_json is null");
        return ptr::null_mut();
    }

    let json_str = match CStr::from_ptr(schema_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in schema_json: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::schema::sanitize_schema(json_str) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Check if any tool schema property contains x-media-type.
///
/// # Arguments
/// * `schema_json` - JSON schema string (OpenAI tool format or bare schema)
///
/// # Returns
/// 1 if media params found, 0 otherwise
///
/// # Safety
/// * `schema_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_detect_media_params(schema_json: *const c_char) -> i32 {
    if schema_json.is_null() {
        return 0;
    }

    let json_str = match CStr::from_ptr(schema_json).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };

    if crate::schema::detect_media_params(json_str) { 1 } else { 0 }
}

/// Check if a JSON schema is simple enough for hint mode.
///
/// # Arguments
/// * `schema_json` - JSON schema string
///
/// # Returns
/// 1 if simple, 0 otherwise
///
/// # Safety
/// * `schema_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_is_simple_schema(schema_json: *const c_char) -> i32 {
    if schema_json.is_null() {
        return 0;
    }

    let json_str = match CStr::from_ptr(schema_json).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };

    if crate::schema::is_simple_schema(json_str) { 1 } else { 0 }
}

/// Normalize a raw JSON Schema and return a JSON envelope with
/// `{canonical, hash, verdict, warnings}`.
///
/// This is the C FFI wrapper around `schema_normalize::normalize_schema`
/// (issue #547). Mirrors the Python (`normalize_schema_py`) and napi
/// (`normalize_schema`) bindings so Java SDKs can produce identical
/// canonical forms and hashes for cross-runtime capability matching.
///
/// # Arguments
/// * `raw_json` - Raw JSON Schema string
/// * `origin` - Origin runtime hint: "python", "typescript", "java", or unknown.
///   May be NULL.
///
/// # Returns
/// JSON string with fields `canonical`, `hash`, `verdict`, `warnings`
/// (caller must free with `mesh_free_string`). On error returns a JSON
/// envelope with `verdict="BLOCK"` rather than NULL so callers can always
/// parse the response.
///
/// # Safety
/// * `raw_json` must be a valid null-terminated C string
/// * `origin` may be NULL or a valid null-terminated C string
/// * The returned string must be freed with `mesh_free_string`
#[no_mangle]
pub unsafe extern "C" fn mesh_normalize_schema(
    raw_json: *const c_char,
    origin: *const c_char,
) -> *mut c_char {
    use crate::schema_normalize::{self, SchemaOrigin};

    fn block_envelope(reason: &str) -> *mut c_char {
        let envelope = serde_json::json!({
            "canonical": serde_json::Value::Null,
            "hash": "",
            "verdict": "BLOCK",
            "warnings": [reason],
        });
        let s = serde_json::to_string(&envelope)
            .unwrap_or_else(|_| r#"{"verdict":"BLOCK"}"#.to_string());
        match CString::new(s) {
            Ok(c) => c.into_raw(),
            Err(_) => ptr::null_mut(),
        }
    }

    if raw_json.is_null() {
        return block_envelope("null raw_json pointer");
    }

    let raw_str = match CStr::from_ptr(raw_json).to_str() {
        Ok(s) => s,
        Err(e) => return block_envelope(&format!("Invalid UTF-8 in raw_json: {}", e)),
    };

    let origin_str = if origin.is_null() {
        "unknown"
    } else {
        match CStr::from_ptr(origin).to_str() {
            Ok(s) => s,
            Err(_) => "unknown",
        }
    };

    let origin_enum = match origin_str {
        "python" => SchemaOrigin::Python,
        "typescript" => SchemaOrigin::TypeScript,
        "java" => SchemaOrigin::Java,
        _ => SchemaOrigin::Unknown,
    };

    let result = schema_normalize::normalize_schema(raw_str, origin_enum);
    let envelope = serde_json::json!({
        "canonical": result.canonical,
        "hash": result.hash,
        "verdict": result.verdict,
        "warnings": result.warnings,
    });
    let serialized = match serde_json::to_string(&envelope) {
        Ok(s) => s,
        Err(e) => return block_envelope(&format!("serialize failed: {}", e)),
    };

    match CString::new(serialized) {
        Ok(c) => c.into_raw(),
        Err(e) => block_envelope(&format!("CString conversion failed: {}", e)),
    }
}

// =============================================================================
// Trace Context Functions
// =============================================================================

/// Generate OpenTelemetry-compliant trace ID (32-char hex, 128-bit).
///
/// # Returns
/// Trace ID string (caller must free with `mesh_free_string`), or NULL on error
#[no_mangle]
pub extern "C" fn mesh_generate_trace_id() -> *mut c_char {
    let id = crate::trace_context::generate_trace_id();
    match CString::new(id) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Generate OpenTelemetry-compliant span ID (16-char hex, 64-bit).
///
/// # Returns
/// Span ID string (caller must free with `mesh_free_string`), or NULL on error
#[no_mangle]
pub extern "C" fn mesh_generate_span_id() -> *mut c_char {
    let id = crate::trace_context::generate_span_id();
    match CString::new(id) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Inject trace context into JSON-RPC arguments.
///
/// # Arguments
/// * `args_json` - JSON object string with existing arguments
/// * `trace_id` - Trace ID to inject
/// * `span_id` - Span ID to inject as _parent_span
/// * `propagated_headers_json` - Optional JSON object of headers to propagate (may be NULL)
///
/// # Returns
/// Modified JSON string (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `args_json`, `trace_id`, and `span_id` must be valid null-terminated C strings
/// * `propagated_headers_json` may be NULL
#[no_mangle]
pub unsafe extern "C" fn mesh_inject_trace_context(
    args_json: *const c_char,
    trace_id: *const c_char,
    span_id: *const c_char,
    propagated_headers_json: *const c_char,
) -> *mut c_char {
    if args_json.is_null() {
        set_last_error("args_json is null");
        return ptr::null_mut();
    }
    if trace_id.is_null() {
        set_last_error("trace_id is null");
        return ptr::null_mut();
    }
    if span_id.is_null() {
        set_last_error("span_id is null");
        return ptr::null_mut();
    }

    let args_str = match CStr::from_ptr(args_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in args_json: {}", e));
            return ptr::null_mut();
        }
    };
    let trace_str = match CStr::from_ptr(trace_id).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in trace_id: {}", e));
            return ptr::null_mut();
        }
    };
    let span_str = match CStr::from_ptr(span_id).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in span_id: {}", e));
            return ptr::null_mut();
        }
    };

    let headers_opt = if propagated_headers_json.is_null() {
        None
    } else {
        match CStr::from_ptr(propagated_headers_json).to_str() {
            Ok(s) => Some(s),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in propagated_headers_json: {}", e));
                return ptr::null_mut();
            }
        }
    };

    match crate::trace_context::inject_trace_context(args_str, trace_str, span_str, headers_opt) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Extract trace context from HTTP headers with body fallback.
///
/// # Arguments
/// * `headers_json` - JSON object of HTTP headers
/// * `body_json` - Optional JSON-RPC body (may be NULL)
///
/// # Returns
/// JSON string with trace_id and parent_span (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `headers_json` must be a valid null-terminated C string
/// * `body_json` may be NULL
#[no_mangle]
pub unsafe extern "C" fn mesh_extract_trace_context(
    headers_json: *const c_char,
    body_json: *const c_char,
) -> *mut c_char {
    if headers_json.is_null() {
        set_last_error("headers_json is null");
        return ptr::null_mut();
    }

    let headers_str = match CStr::from_ptr(headers_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in headers_json: {}", e));
            return ptr::null_mut();
        }
    };

    let body_opt = if body_json.is_null() {
        None
    } else {
        match CStr::from_ptr(body_json).to_str() {
            Ok(s) => Some(s),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in body_json: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let result = crate::trace_context::extract_trace_context(headers_str, body_opt);
    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Filter headers by propagation allowlist with prefix matching.
///
/// # Arguments
/// * `headers_json` - JSON object of HTTP headers
/// * `allowlist_csv` - Comma-separated list of header prefixes
///
/// # Returns
/// JSON string of matching headers (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * Both parameters must be valid null-terminated C strings
#[no_mangle]
pub unsafe extern "C" fn mesh_filter_propagation_headers(
    headers_json: *const c_char,
    allowlist_csv: *const c_char,
) -> *mut c_char {
    if headers_json.is_null() {
        set_last_error("headers_json is null");
        return ptr::null_mut();
    }
    if allowlist_csv.is_null() {
        set_last_error("allowlist_csv is null");
        return ptr::null_mut();
    }

    let headers_str = match CStr::from_ptr(headers_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in headers_json: {}", e));
            return ptr::null_mut();
        }
    };
    let allowlist_str = match CStr::from_ptr(allowlist_csv).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in allowlist_csv: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::trace_context::filter_propagation_headers(headers_str, allowlist_str) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Check if a header matches the propagation allowlist.
///
/// # Arguments
/// * `header_name` - Header name to check
/// * `allowlist_csv` - Comma-separated list of header prefixes
///
/// # Returns
/// 1 if matches, 0 otherwise
///
/// # Safety
/// * Both parameters must be valid null-terminated C strings
#[no_mangle]
pub unsafe extern "C" fn mesh_matches_propagate_header(
    header_name: *const c_char,
    allowlist_csv: *const c_char,
) -> i32 {
    if header_name.is_null() || allowlist_csv.is_null() {
        return 0;
    }

    let name_str = match CStr::from_ptr(header_name).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let allowlist_str = match CStr::from_ptr(allowlist_csv).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };

    if crate::trace_context::matches_propagate_header(name_str, allowlist_str) {
        1
    } else {
        0
    }
}

// =============================================================================
// MCP Client Functions
// =============================================================================

/// Global tokio runtime for MCP client operations.
/// Lazily initialized on first call_tool invocation.
static MCP_RUNTIME: std::sync::OnceLock<tokio::runtime::Runtime> = std::sync::OnceLock::new();

fn get_mcp_runtime() -> &'static tokio::runtime::Runtime {
    MCP_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("mesh-mcp")
            .enable_all()
            .build()
            .expect("Failed to create MCP runtime")
    })
}

/// Build a JSON-RPC 2.0 request envelope.
///
/// # Arguments
/// * `method` - JSON-RPC method name
/// * `params_json` - JSON string for params
/// * `request_id` - Unique request identifier
///
/// # Returns
/// JSON-RPC request string (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * All parameters must be valid null-terminated C strings
#[no_mangle]
pub unsafe extern "C" fn mesh_build_jsonrpc_request(
    method: *const c_char,
    params_json: *const c_char,
    request_id: *const c_char,
) -> *mut c_char {
    if method.is_null() {
        set_last_error("method is null");
        return ptr::null_mut();
    }
    if params_json.is_null() {
        set_last_error("params_json is null");
        return ptr::null_mut();
    }
    if request_id.is_null() {
        set_last_error("request_id is null");
        return ptr::null_mut();
    }

    let method_str = match CStr::from_ptr(method).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in method: {}", e));
            return ptr::null_mut();
        }
    };
    let params_str = match CStr::from_ptr(params_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in params_json: {}", e));
            return ptr::null_mut();
        }
    };
    let id_str = match CStr::from_ptr(request_id).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in request_id: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::mcp_client::build_jsonrpc_request(method_str, params_str, id_str) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Generate a unique request ID.
///
/// # Returns
/// Request ID string (caller must free with `mesh_free_string`)
#[no_mangle]
pub extern "C" fn mesh_generate_request_id() -> *mut c_char {
    let id = crate::mcp_client::generate_request_id();
    match CString::new(id) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Parse SSE or plain JSON response.
///
/// # Arguments
/// * `response_text` - Raw response body
///
/// # Returns
/// Extracted JSON string (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `response_text` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_parse_sse_response(response_text: *const c_char) -> *mut c_char {
    if response_text.is_null() {
        set_last_error("response_text is null");
        return ptr::null_mut();
    }

    let text_str = match CStr::from_ptr(response_text).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in response_text: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::mcp_client::parse_sse_response(text_str) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Extract text content from MCP CallToolResult.
///
/// # Arguments
/// * `result_json` - JSON string of the MCP result
///
/// # Returns
/// Extracted content string (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `result_json` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_extract_content(result_json: *const c_char) -> *mut c_char {
    if result_json.is_null() {
        set_last_error("result_json is null");
        return ptr::null_mut();
    }

    let json_str = match CStr::from_ptr(result_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in result_json: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::mcp_client::extract_content(json_str) {
        Ok(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

/// Call a remote MCP tool via HTTP POST with retry.
///
/// # Arguments
/// * `endpoint` - MCP endpoint URL
/// * `tool_name` - Name of the tool to call
/// * `args_json` - Optional JSON string of tool arguments (may be NULL)
/// * `headers_json` - Optional JSON object of extra headers (may be NULL)
/// * `timeout_ms` - Request timeout in milliseconds
/// * `max_retries` - Maximum number of retries on network error
///
/// # Returns
/// Result string (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `endpoint` and `tool_name` must be valid null-terminated C strings
/// * `args_json` and `headers_json` may be NULL
#[no_mangle]
pub unsafe extern "C" fn mesh_call_tool(
    endpoint: *const c_char,
    tool_name: *const c_char,
    args_json: *const c_char,
    headers_json: *const c_char,
    timeout_ms: i64,
    max_retries: i32,
) -> *mut c_char {
    if endpoint.is_null() {
        set_last_error("endpoint is null");
        return ptr::null_mut();
    }
    if tool_name.is_null() {
        set_last_error("tool_name is null");
        return ptr::null_mut();
    }

    let endpoint_str = match CStr::from_ptr(endpoint).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in endpoint: {}", e));
            return ptr::null_mut();
        }
    };
    let tool_str = match CStr::from_ptr(tool_name).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in tool_name: {}", e));
            return ptr::null_mut();
        }
    };

    let args_opt = if args_json.is_null() {
        None
    } else {
        match CStr::from_ptr(args_json).to_str() {
            Ok(s) => Some(s.to_string()),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in args_json: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let headers_opt = if headers_json.is_null() {
        None
    } else {
        match CStr::from_ptr(headers_json).to_str() {
            Ok(s) => Some(s.to_string()),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in headers_json: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let timeout = if timeout_ms > 0 { timeout_ms as u64 } else { 30000 };
    let retries = if max_retries >= 0 { max_retries as u32 } else { 1 };

    let rt = get_mcp_runtime();
    let result = rt.block_on(async {
        crate::mcp_client::call_tool(
            endpoint_str,
            tool_str,
            args_opt.as_deref(),
            headers_opt.as_deref(),
            timeout,
            retries,
        ).await
    });

    match result {
        Ok(content) => match CString::new(content) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e);
            ptr::null_mut()
        }
    }
}

// =============================================================================
// Provider Functions
// =============================================================================

/// Determine output mode for a vendor given the context.
///
/// # Arguments
/// * `provider` - Vendor name (e.g., "anthropic", "openai", "gemini")
/// * `is_string_type` - 1 if the output schema is a plain string type
/// * `has_tools` - 1 if tools are present in the request
/// * `override_mode` - Optional override mode (may be NULL)
///
/// # Returns
/// Output mode string: "text", "hint", or "strict" (caller must free with `mesh_free_string`)
///
/// # Safety
/// * `provider` must be a valid null-terminated C string
/// * `override_mode` may be NULL
#[no_mangle]
pub unsafe extern "C" fn mesh_determine_output_mode(
    provider: *const c_char,
    is_string_type: i32,
    has_tools: i32,
    override_mode: *const c_char,
) -> *mut c_char {
    if provider.is_null() {
        set_last_error("provider is null");
        return ptr::null_mut();
    }

    let provider_str = match CStr::from_ptr(provider).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in provider: {}", e));
            return ptr::null_mut();
        }
    };

    let override_opt = if override_mode.is_null() {
        None
    } else {
        match CStr::from_ptr(override_mode).to_str() {
            Ok(s) if !s.is_empty() => Some(s),
            Ok(_) => None,
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in override_mode: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let result = crate::provider::determine_output_mode(
        provider_str,
        is_string_type != 0,
        has_tools != 0,
        override_opt,
    );

    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Build the complete system prompt with vendor-specific additions.
///
/// # Arguments
/// * `provider` - Vendor name
/// * `base_prompt` - Base system prompt text
/// * `has_tools` - 1 if tools are present
/// * `has_media_params` - 1 if media parameters are present
/// * `schema_json` - Optional JSON schema string (may be NULL)
/// * `schema_name` - Optional schema name (may be NULL)
/// * `output_mode` - Output mode: "text", "hint", or "strict"
///
/// # Returns
/// Complete system prompt (caller must free with `mesh_free_string`), or NULL on error
///
/// # Safety
/// * `provider`, `base_prompt`, and `output_mode` must be valid null-terminated C strings
/// * `schema_json` and `schema_name` may be NULL
#[no_mangle]
pub unsafe extern "C" fn mesh_format_system_prompt(
    provider: *const c_char,
    base_prompt: *const c_char,
    has_tools: i32,
    has_media_params: i32,
    schema_json: *const c_char,
    schema_name: *const c_char,
    output_mode: *const c_char,
) -> *mut c_char {
    if provider.is_null() {
        set_last_error("provider is null");
        return ptr::null_mut();
    }
    if base_prompt.is_null() {
        set_last_error("base_prompt is null");
        return ptr::null_mut();
    }
    if output_mode.is_null() {
        set_last_error("output_mode is null");
        return ptr::null_mut();
    }

    let provider_str = match CStr::from_ptr(provider).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in provider: {}", e));
            return ptr::null_mut();
        }
    };
    let base_str = match CStr::from_ptr(base_prompt).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in base_prompt: {}", e));
            return ptr::null_mut();
        }
    };
    let mode_str = match CStr::from_ptr(output_mode).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in output_mode: {}", e));
            return ptr::null_mut();
        }
    };

    let schema_opt = if schema_json.is_null() {
        None
    } else {
        match CStr::from_ptr(schema_json).to_str() {
            Ok(s) => Some(s),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in schema_json: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let name_opt = if schema_name.is_null() {
        None
    } else {
        match CStr::from_ptr(schema_name).to_str() {
            Ok(s) => Some(s),
            Err(e) => {
                set_last_error(format!("Invalid UTF-8 in schema_name: {}", e));
                return ptr::null_mut();
            }
        }
    };

    let result = crate::provider::format_system_prompt(
        provider_str,
        base_str,
        has_tools != 0,
        has_media_params != 0,
        schema_opt,
        name_opt,
        mode_str,
    );

    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
    }
}

/// Build the `response_format` JSON object for vendors that support it.
///
/// # Arguments
/// * `provider` - Vendor name
/// * `schema_json` - JSON schema string
/// * `schema_name` - Schema name for the response_format
/// * `has_tools` - 1 if tools are present
///
/// # Returns
/// JSON string with response_format (caller must free with `mesh_free_string`),
/// or NULL if vendor does not support response_format for this scenario
///
/// # Safety
/// * All parameters must be valid null-terminated C strings
#[no_mangle]
pub unsafe extern "C" fn mesh_build_response_format(
    provider: *const c_char,
    schema_json: *const c_char,
    schema_name: *const c_char,
    has_tools: i32,
) -> *mut c_char {
    if provider.is_null() {
        set_last_error("provider is null");
        return ptr::null_mut();
    }
    if schema_json.is_null() {
        set_last_error("schema_json is null");
        return ptr::null_mut();
    }
    if schema_name.is_null() {
        set_last_error("schema_name is null");
        return ptr::null_mut();
    }

    let provider_str = match CStr::from_ptr(provider).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in provider: {}", e));
            return ptr::null_mut();
        }
    };
    let schema_str = match CStr::from_ptr(schema_json).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in schema_json: {}", e));
            return ptr::null_mut();
        }
    };
    let name_str = match CStr::from_ptr(schema_name).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in schema_name: {}", e));
            return ptr::null_mut();
        }
    };

    match crate::provider::build_response_format(provider_str, schema_str, name_str, has_tools != 0) {
        Some(result) => match CString::new(result) {
            Ok(c_str) => c_str.into_raw(),
            Err(e) => {
                set_last_error(format!("Failed to create C string: {}", e));
                ptr::null_mut()
            }
        },
        None => ptr::null_mut(),
    }
}

/// Get vendor capabilities as JSON.
///
/// # Arguments
/// * `provider` - Vendor name
///
/// # Returns
/// JSON string with vendor capabilities (caller must free with `mesh_free_string`),
/// or NULL on error
///
/// # Safety
/// * `provider` must be a valid null-terminated C string
#[no_mangle]
pub unsafe extern "C" fn mesh_get_vendor_capabilities(provider: *const c_char) -> *mut c_char {
    if provider.is_null() {
        set_last_error("provider is null");
        return ptr::null_mut();
    }

    let provider_str = match CStr::from_ptr(provider).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in provider: {}", e));
            return ptr::null_mut();
        }
    };

    let result = crate::provider::get_vendor_capabilities(provider_str);

    match CString::new(result) {
        Ok(c_str) => c_str.into_raw(),
        Err(e) => {
            set_last_error(format!("Failed to create C string: {}", e));
            ptr::null_mut()
        }
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

    /// Issue #1166 MED-3 + span-drain follow-up: ONE lifecycle test for
    /// the process-global span queue. SPAN_QUEUE / TRACING_RUNTIME / the
    /// tracing_publish PUBLISHER singleton are all process-wide, and a
    /// OnceLock'd queue can never be unarmed again — so every assertion
    /// that touches the queue lives in this single test fn (splitting
    /// them up would create order-dependent tests). No other test in this
    /// crate depends on the queue being UNarmed: the other
    /// mesh_publish_span tests fail on null/invalid JSON before reaching
    /// the queue.
    ///
    /// Covers:
    /// * `mesh_publish_span` enqueues and returns 1 immediately — the
    ///   Redis XADD happens on the tracing runtime's drain task;
    /// * `mesh_flush_spans` blocks until previously queued spans reached
    ///   the (fake) Redis server;
    /// * `mesh_free_handle` drains the queue, so spans published right
    ///   before teardown are not lost.
    ///
    /// NB: mutates process env (REDIS_URL, tracing flag); the suite runs
    /// with --test-threads=1 like the other env-mutating tests.
    #[test]
    fn test_mesh_span_queue_lifecycle_publish_flush_free() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        // Fake RESP server that records every byte it reads and answers
        // each command with "+PONG" (parses as the reply to everything
        // this test triggers: PING, CLIENT SETINFO, XADD-as-String — see
        // the sibling test in tracing_publish.rs for the pipelining
        // details).
        let server_rt = tokio::runtime::Runtime::new().unwrap();
        let received: Arc<std::sync::Mutex<Vec<u8>>> =
            Arc::new(std::sync::Mutex::new(Vec::new()));
        let received_srv = received.clone();
        let addr = server_rt.block_on(async {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
                .await
                .expect("bind fake redis");
            let addr = listener.local_addr().unwrap();
            tokio::spawn(async move {
                loop {
                    let Ok((mut sock, _)) = listener.accept().await else {
                        break;
                    };
                    let received = received_srv.clone();
                    tokio::spawn(async move {
                        let mut buf = [0u8; 8192];
                        loop {
                            match sock.read(&mut buf).await {
                                Ok(0) | Err(_) => break,
                                Ok(n) => {
                                    received.lock().unwrap().extend_from_slice(&buf[..n]);
                                    let req = String::from_utf8_lossy(&buf[..n]);
                                    let ncmds = req
                                        .split("\r\n")
                                        .filter(|line| line.starts_with('*'))
                                        .count()
                                        .max(1);
                                    let resp = "+PONG\r\n".repeat(ncmds);
                                    if sock.write_all(resp.as_bytes()).await.is_err() {
                                        break;
                                    }
                                }
                            }
                        }
                    });
                }
            });
            addr
        });

        // publish_span awaits the XADD reply before completing, and the
        // flush ack fires only after all prior queue entries completed —
        // so once a flush returns, the server has read every span.
        let count_xadds = || {
            let buf = received.lock().unwrap();
            String::from_utf8_lossy(&buf).matches("XADD").count()
        };

        std::env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        std::env::set_var("REDIS_URL", format!("redis://{}", addr));

        assert_eq!(
            mesh_init_trace_publisher(),
            1,
            "init must succeed against the fake server"
        );

        // Non-blocking enqueue path: valid spans are accepted (1) right
        // away; Redis I/O happens on the drain task.
        for i in 0..3 {
            let span =
                CString::new(format!(r#"{{"span_id":"s{}","name":"test"}}"#, i)).unwrap();
            assert_eq!(
                unsafe { mesh_publish_span(span.as_ptr()) },
                1,
                "span {} must be queued without blocking",
                i
            );
        }

        assert_eq!(mesh_flush_spans(5_000), 1, "flush must drain within budget");
        assert_eq!(count_xadds(), 3, "server must have all pre-flush spans");

        // Spans queued just before teardown must survive mesh_free_handle
        // (the final spans of an agent's life are exactly what an
        // embedder loses without the teardown drain).
        for i in 3..5 {
            let span =
                CString::new(format!(r#"{{"span_id":"s{}","name":"test"}}"#, i)).unwrap();
            assert_eq!(unsafe { mesh_publish_span(span.as_ptr()) }, 1);
        }

        let runtime = tokio::runtime::Runtime::new().unwrap();
        let (_event_tx, event_rx) = mpsc::channel::<MeshEvent>(4);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, _command_rx) = mpsc::channel(1);
        // Arc (not Box): mesh_free_handle reclaims via Arc::from_raw,
        // matching what mesh_start_agent hands out.
        let handle = Arc::new(MeshAgentHandle {
            event_rx: Mutex::new(event_rx),
            shutdown_tx,
            command_tx,
            runtime,
            // Already stopped: free skips the graceful-shutdown wait and
            // exercises exactly the teardown drain.
            is_running: AtomicBool::new(false),
            agent_id: None,
            shared_state: Arc::new(tokio::sync::RwLock::new(HandleState::default())),
        });
        unsafe { mesh_free_handle(Arc::into_raw(handle) as *mut MeshAgentHandle) };
        assert_eq!(
            count_xadds(),
            5,
            "mesh_free_handle must drain spans queued before teardown"
        );

        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        std::env::remove_var("REDIS_URL");
    }

    /// Freeing the handle while another thread sits parked in an
    /// infinite-timeout `mesh_next_event` must not crash (the
    /// use-after-free this would have been with a Box-owned handle), and
    /// the parked caller must unpark cleanly once the event channel
    /// closes. With a wedged runtime (no shutdown event ever emitted —
    /// the test holds the event sender), free's bounded 2s wait times
    /// out, free returns, and the parked caller returns NULL when the
    /// sender finally drops.
    #[test]
    fn test_free_handle_while_next_event_parked() {
        let runtime = tokio::runtime::Runtime::new().unwrap();
        let (event_tx, event_rx) = mpsc::channel::<MeshEvent>(4);
        let (shutdown_tx, _shutdown_rx) = mpsc::channel(1);
        let (command_tx, _command_rx) = mpsc::channel(1);
        let handle = Arc::new(MeshAgentHandle {
            event_rx: Mutex::new(event_rx),
            shutdown_tx,
            command_tx,
            runtime,
            is_running: AtomicBool::new(true),
            agent_id: None,
            shared_state: Arc::new(tokio::sync::RwLock::new(HandleState::default())),
        });
        let ptr = Arc::into_raw(handle) as *mut MeshAgentHandle;

        // Park a caller in an infinite wait. Its handle_guard keeps the
        // handle alive across the concurrent free below.
        let ptr_addr = ptr as usize;
        let parked = std::thread::spawn(move || {
            let result =
                unsafe { mesh_next_event(ptr_addr as *const MeshAgentHandle, -1) };
            result.is_null()
        });

        // Give the thread time to actually park inside recv().
        std::thread::sleep(Duration::from_millis(200));
        assert!(!parked.is_finished(), "caller must be parked before free");

        // Free while parked. The graceful-shutdown wait can't get the
        // receiver lock (the parked caller holds it) and no shutdown
        // event ever arrives, so this returns after its 2s budget —
        // dropping the creation reference but NOT the memory.
        unsafe { mesh_free_handle(ptr) };

        // The parked caller is still alive and still parked; dropping the
        // last sender closes the channel and unparks it with None → NULL.
        assert!(!parked.is_finished(), "parked caller must survive free");
        drop(event_tx);
        let got_null = parked.join().expect("parked mesh_next_event must not crash");
        assert!(got_null, "parked caller must observe channel close as NULL");
    }

    #[test]
    fn test_update_port_null_handle() {
        unsafe {
            let result = mesh_update_port(ptr::null_mut(), 8080);
            assert_eq!(result, -1);
            let err = mesh_last_error();
            assert!(!err.is_null());
            mesh_free_string(err);
        }
    }

    #[test]
    fn test_update_port_invalid() {
        unsafe {
            // Negative port
            let result = mesh_update_port(ptr::null_mut(), -1);
            assert_eq!(result, -1);
            // Port too high
            let result = mesh_update_port(ptr::null_mut(), 70000);
            assert_eq!(result, -1);
        }
    }

    #[test]
    fn test_prepare_tls_null_agent_name() {
        unsafe {
            let result = mesh_prepare_tls(ptr::null());
            assert!(result.is_null());
            let err = mesh_last_error();
            assert!(!err.is_null());
            let err_str = CStr::from_ptr(err).to_str().unwrap();
            assert!(err_str.contains("null"));
            mesh_free_string(err);
        }
    }

    #[test]
    fn test_prepare_tls_off_mode() {
        // With TLS off (default), prepare_tls should return valid JSON
        std::env::remove_var("MCP_MESH_TLS_MODE");
        unsafe {
            let name = CString::new("test-agent").unwrap();
            let result = mesh_prepare_tls(name.as_ptr());
            // May be non-null (TLS off config) or null depending on OnceLock state
            // from other tests. Just verify no crash.
            if !result.is_null() {
                let json_str = CStr::from_ptr(result).to_str().unwrap();
                assert!(json_str.contains("\"enabled\""));
                mesh_free_string(result);
            }
        }
    }

    #[test]
    fn test_cleanup_tls_no_panic() {
        // Should not panic even when no TLS config has been resolved
        mesh_cleanup_tls();
    }
}
