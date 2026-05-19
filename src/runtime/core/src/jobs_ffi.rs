//! C-ABI bindings for the MeshJob substrate (Phase 1 — Java SDK).
//!
//! Mirror of [`crate::jobs_py`] (PyO3) and [`crate::jobs_napi`] (napi-rs)
//! exposed via the C ABI so JNR-FFI consumers (Java, Kotlin, etc.) can drive
//! the producer-side [`crate::jobs::JobController`] and consumer-side
//! [`crate::jobs::JobProxy`] from `libmcp_mesh_core.{dylib,so,dll}`.
//!
//! # Async pattern
//! The C ABI cannot return Promises / Futures, so blocking-from-Java methods
//! bridge through a process-wide [`tokio::runtime::Runtime`] (initialized
//! lazily in [`jobs_runtime`]) and `block_on` the underlying async API.
//! Java callers wrap these in `CompletableFuture` on their side if they
//! want async ergonomics.
//!
//! # Error handling
//! Functions return `i32` status codes (`0` = success, non-zero = error)
//! and stash a thread-local error message in [`crate::ffi::set_last_error`]
//! that callers fetch via `mesh_last_error`. String outputs are passed via
//! `*mut *mut c_char` out-parameters; the caller frees with `mesh_free_string`.
//!
//! # Caveat — task-local visibility from Java
//! Like the Python / TS bindings: the Rust `tokio::task_local!` bound by
//! [`crate::job_context::with_job`] is only visible to Rust futures polled
//! within the scope. Java threads do NOT inherit the task-local across the
//! JNR-FFI boundary. The Java SDK MUST mirror the context in its own
//! `ThreadLocal` (see `JobContext.java`) for visibility to user code and
//! to Java-originated outbound calls. The Rust side handles two things:
//!
//!   1. cancel-registry binding so `POST /jobs/{id}/cancel` can fire the
//!      in-flight cancel token (visible to any Rust futures polled within
//!      the scope, including the `mesh_call_tool` outbound HTTP path);
//!   2. header injection on Rust-originated outbound work via
//!      [`mesh_inject_job_headers`].

#![cfg(feature = "ffi")]

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_void};
use std::ptr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;

use tokio::runtime::Runtime;

use crate::cancel_registry;
use crate::ffi::{set_last_error, take_last_error};
use crate::job_context::{self, JobContext};
use crate::jobs::{
    new_coalescing_queue, run_as_job, spawn_batching_tick, submit_job, BatchingConfig,
    BatchingHandle, JobController, JobError, JobProxy, SubmitJobArgs,
};
use crate::task_backend::{
    Job, JobEvent, JobEventReceipt, JobStatus, RegistryHttpBackend, TaskBackend,
};

// =============================================================================
// Process-wide blocking runtime
// =============================================================================

/// Lazily-initialized multi-thread tokio runtime used by the FFI layer to
/// `block_on` async core APIs (the C ABI cannot expose async). One runtime
/// per process keeps the resource cost down — JNR-FFI consumers don't pay
/// per-call overhead for runtime construction.
fn jobs_runtime() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| {
        Runtime::new().expect("failed to construct jobs FFI tokio runtime")
    })
}

// =============================================================================
// Helpers
// =============================================================================

/// Read a possibly-null `*const c_char` as `Option<&str>`. Returns `None`
/// for null pointers; returns `Err` for invalid UTF-8 (with the error
/// stashed in the thread-local last-error slot).
unsafe fn opt_cstr<'a>(ptr: *const c_char, name: &str) -> Result<Option<&'a str>, ()> {
    if ptr.is_null() {
        return Ok(None);
    }
    match CStr::from_ptr(ptr).to_str() {
        Ok(s) => Ok(Some(s)),
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in {}: {}", name, e));
            Err(())
        }
    }
}

/// Read a non-null `*const c_char` as `&str`. Sets last-error and returns
/// `Err` for null or invalid UTF-8.
unsafe fn req_cstr<'a>(ptr: *const c_char, name: &str) -> Result<&'a str, ()> {
    if ptr.is_null() {
        set_last_error(format!("{} is null", name));
        return Err(());
    }
    match CStr::from_ptr(ptr).to_str() {
        Ok(s) => Ok(s),
        Err(e) => {
            set_last_error(format!("Invalid UTF-8 in {}: {}", name, e));
            Err(())
        }
    }
}

/// Allocate a C string from a Rust string and write it to `out`. Returns
/// 0 on success, -1 on allocation failure (with last-error set).
unsafe fn write_out_string(out: *mut *mut c_char, value: String) -> i32 {
    if out.is_null() {
        set_last_error("output pointer is null");
        return -1;
    }
    match CString::new(value) {
        Ok(c) => {
            *out = c.into_raw();
            0
        }
        Err(e) => {
            set_last_error(format!("Failed to create C string (interior NUL): {}", e));
            -1
        }
    }
}

/// Build an `Arc<dyn TaskBackend>` from a registry URL. Sets last-error and
/// returns `None` on transport-construction failure.
fn backend_from_url(registry_url: &str) -> Option<Arc<dyn TaskBackend>> {
    match RegistryHttpBackend::new(registry_url) {
        Ok(b) => Some(b.into_arc()),
        Err(e) => {
            set_last_error(format!("backend init failed: {}", e));
            None
        }
    }
}

/// Stash a [`JobError`] into the thread-local last-error slot. Returns the
/// error code -1 so callers can `return jobs_set_err(e);` directly.
fn jobs_set_err(err: JobError) -> i32 {
    set_last_error(err.to_string());
    -1
}

fn job_status_to_str(s: JobStatus) -> &'static str {
    match s {
        JobStatus::Working => "working",
        JobStatus::InputRequired => "input_required",
        JobStatus::Completed => "completed",
        JobStatus::Failed => "failed",
        JobStatus::Cancelled => "cancelled",
    }
}

// Stricter timeout-policy than mesh_job_proxy_wait's predicate (which
// silently aliases NaN/Inf to "no timeout" for back-compat). New FFI
// surfaces should adopt this form: surface callers' invalid inputs as
// errors rather than aliasing — matches the napi/pyo3 `parse_timeout_secs`
// helpers in jobs_napi.rs / jobs_py.rs. The two policies coexist
// intentionally; do not unify without coordinating a deprecation cycle
// for mesh_job_proxy_wait.
/// Parse an FFI-supplied `timeout_secs` f64 into an `Option<Duration>`,
/// using the negative-sentinel convention to bridge `Option<Duration>` over
/// the C ABI (which cannot pass `null` doubles).
///
/// Policy (matches `parse_timeout_secs` in `jobs_napi.rs` / `jobs_py.rs`):
/// - `secs < 0.0` → `Ok(None)` (no timeout — Java passes `-1.0` to express
///   `Optional<Duration>::empty()`)
/// - `secs.is_nan() || secs.is_infinite()` → `Err(...)` — these are likely
///   bugs in the caller; surfacing a clean error beats silent "no timeout"
/// - finite `>= 0` but overflows `Duration::from_secs_f64` (e.g. `f64::MAX`)
///   → `Err(...)` via `try_from_secs_f64` (the panicking constructor
///   `from_secs_f64` would have aborted the host process)
/// - finite `>= 0` and convertible → `Ok(Some(Duration::...))`
fn parse_ffi_timeout_secs(secs: f64) -> Result<Option<Duration>, String> {
    if secs.is_nan() {
        return Err(format!("timeout_secs must be a finite number, got NaN"));
    }
    if secs.is_infinite() {
        return Err(format!(
            "timeout_secs must be a finite number, got {}",
            secs
        ));
    }
    if secs < 0.0 {
        return Ok(None);
    }
    Duration::try_from_secs_f64(secs)
        .map(Some)
        .map_err(|e| format!("timeout_secs out of range: {} (got {})", e, secs))
}

/// Convert a [`JobEvent`] to a JSON string matching the wire shape that
/// the Python (`job_event_to_pydict`) and TS (`job_event_to_json`) bindings
/// expose. Java callers parse this with Jackson on their side.
fn job_event_to_json_string(ev: JobEvent) -> String {
    serde_json::json!({
        "job_id": ev.job_id,
        "seq": ev.seq,
        "type": ev.event_type,
        "payload": ev.payload.unwrap_or(serde_json::Value::Null),
        "trace_context": ev.trace_context.unwrap_or(serde_json::Value::Null),
        "posted_by": ev.posted_by,
        "created_at": ev.created_at,
    })
    .to_string()
}

/// Convert a [`JobEventReceipt`] to a JSON string matching the wire shape
/// Python/TS bindings expose.
fn job_event_receipt_to_json_string(receipt: JobEventReceipt) -> String {
    serde_json::json!({
        "job_id": receipt.job_id,
        "seq": receipt.seq,
        "created_at": receipt.created_at,
    })
    .to_string()
}

/// Serialize a [`Job`] row to JSON matching the wire shape Python/TS bindings
/// expose (and the registry's `Job` schema). Java callers parse this with
/// Jackson on their side.
fn job_to_json_string(job: Job) -> String {
    let value = serde_json::json!({
        "id": job.id,
        "capability": job.capability,
        "owner_instance_id": job.owner_instance_id,
        "status": job_status_to_str(job.status),
        "progress": job.progress,
        "progress_message": job.progress_message,
        "result": job.result.unwrap_or(serde_json::Value::Null),
        "error": job.error,
        "submitted_payload": job.submitted_payload,
        "attempt_count": job.attempt_count,
        "max_retries": job.max_retries,
        "max_duration": job.max_duration,
        "total_deadline": job.total_deadline,
        "lease_expires_at": job.lease_expires_at,
        "last_heartbeat_at": job.last_heartbeat_at,
        "submitted_at": job.submitted_at,
        "submitted_by": job.submitted_by,
    });
    value.to_string()
}

// =============================================================================
// Opaque handles (C-visible structs)
// =============================================================================

/// Opaque handle wrapping a [`JobController`] plus its background batching
/// tick. The tick is held alongside the controller so it lives until the
/// caller invokes [`mesh_job_controller_free`] (mirrors PyJobController /
/// JsJobController which both keep a `BatchingHandle` field).
///
/// Not `#[repr(C)]` — internals stay opaque to C consumers.
pub struct JobControllerHandle {
    inner: JobController,
    /// Per-controller batching tick — same per-instance pattern as the
    /// Python/TS bindings. Dropped (= cancelled with final flush) when the
    /// caller frees the handle. Optional so future feature flags can degrade
    /// gracefully (terminal flushes work without it).
    _batching: Option<BatchingHandle>,
}

/// Opaque handle wrapping a [`JobProxy`].
pub struct JobProxyHandle {
    inner: JobProxy,
}

// =============================================================================
// JobController: producer-side C ABI
// =============================================================================

/// Construct a [`JobController`] bound to `(job_id, instance_id)` against the
/// given `registry_url`. Spawns a per-controller background batching tick so
/// mid-flight `update_progress` calls reach the registry on the configured
/// cadence (default 2s — see [`BatchingConfig::default`]); the tick is torn
/// down with a final flush when the handle is freed.
///
/// # Returns
/// 0 on success (handle written to `*out_handle`), non-zero on error
/// (check `mesh_last_error`).
///
/// # Safety
/// All input strings must be valid null-terminated UTF-8. `out_handle`
/// must point to writable memory for one `*mut JobControllerHandle`.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_new(
    job_id: *const c_char,
    instance_id: *const c_char,
    registry_url: *const c_char,
    out_handle: *mut *mut JobControllerHandle,
) -> i32 {
    take_last_error();
    if out_handle.is_null() {
        set_last_error("out_handle is null");
        return -1;
    }
    let job_id = match req_cstr(job_id, "job_id") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };
    let instance_id = match req_cstr(instance_id, "instance_id") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };
    let registry_url = match req_cstr(registry_url, "registry_url") {
        Ok(s) => s,
        Err(()) => return -1,
    };
    let backend = match backend_from_url(registry_url) {
        Some(b) => b,
        None => return -1,
    };

    let queue = new_coalescing_queue();
    let inner = JobController::new(
        job_id,
        instance_id.clone(),
        backend.clone(),
        queue.clone(),
    );

    // Spawn the batching tick inside the FFI tokio runtime so mid-flight
    // progress deltas actually reach the registry. Mirrors the Python /
    // napi pattern of entering the runtime context for `tokio::spawn` to
    // resolve a valid handle.
    let batching = {
        let _guard = jobs_runtime().enter();
        spawn_batching_tick(queue, backend, instance_id, BatchingConfig::default())
    };

    let handle = Box::new(JobControllerHandle {
        inner,
        _batching: Some(batching),
    });
    *out_handle = Box::into_raw(handle);
    0
}

/// Enqueue a progress update. Coalesces with any prior pending progress
/// for this job — only the latest survives the next batch flush.
///
/// `message` may be NULL (no message).
///
/// # Safety
/// `handle` must come from [`mesh_job_controller_new`] and must not yet
/// have been freed.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_update_progress(
    handle: *mut JobControllerHandle,
    progress: f64,
    message: *const c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let message = match opt_cstr(message, "message") {
        Ok(s) => s.map(str::to_string),
        Err(()) => return -1,
    };
    let inner = handle.inner.clone();
    let progress = progress as f32;
    jobs_runtime().block_on(async move {
        inner.update_progress(progress, message).await;
    });
    0
}

/// Mark the job complete with the given result (JSON-encoded). Flushes
/// immediately.
///
/// # Safety
/// `result_json` must be a valid JSON string (UTF-8). Invalid JSON
/// returns -1 with last-error set.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_complete(
    handle: *mut JobControllerHandle,
    result_json: *const c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let result_str = match req_cstr(result_json, "result_json") {
        Ok(s) => s,
        Err(()) => return -1,
    };
    let value: serde_json::Value = match serde_json::from_str(result_str) {
        Ok(v) => v,
        Err(e) => {
            set_last_error(format!("invalid result_json: {}", e));
            return -1;
        }
    };
    let inner = handle.inner.clone();
    jobs_runtime().block_on(async move { inner.complete(value).await })
        .map(|_| 0)
        .unwrap_or_else(jobs_set_err)
}

/// Mark the job failed with the given error reason. Flushes immediately.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_fail(
    handle: *mut JobControllerHandle,
    error: *const c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let error_str = match req_cstr(error, "error") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };
    let inner = handle.inner.clone();
    jobs_runtime().block_on(async move { inner.fail(error_str).await })
        .map(|_| 0)
        .unwrap_or_else(jobs_set_err)
}

/// Voluntarily release the lease so a peer replica can re-claim and
/// retry. Used by the Java SDK dispatch wrapper when a handler raises
/// a retryOn-matched exception (#895). `reason` may be NULL for
/// "no reason given"; an empty string is passed through as `Some("")`
/// for parity with `mesh_job_proxy_cancel`.
///
/// See [`crate::jobs::JobController::release_lease`] for full semantics.
/// Note: release does NOT increment `attempt_count` — the claim that
/// picked the row up already counted this attempt; the next claim will
/// count the next attempt.
///
/// Marks the controller terminal locally before the backend call so
/// racing `update_progress` from this defunct attempt is fenced (mirror
/// of Python's / TS's release_lease contract).
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_release_lease(
    handle: *mut JobControllerHandle,
    reason: *const c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    // `reason` is optional — NULL means "no reason given". Empty string
    // is passed through as `Some("")` for parity with `mesh_job_proxy_cancel`.
    let reason_opt: Option<String> = match opt_cstr(reason, "reason") {
        Ok(opt) => opt.map(str::to_string),
        Err(()) => return -1,
    };
    let inner = handle.inner.clone();
    jobs_runtime()
        .block_on(async move { inner.release_lease(reason_opt).await })
        .map(|_| 0)
        .unwrap_or_else(jobs_set_err)
}

/// Whether `complete` / `fail` has already been called on this controller.
///
/// # Returns
/// `1` if terminal, `0` if not, `-1` on error.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_is_terminal(
    handle: *const JobControllerHandle,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let inner = handle.inner.clone();
    let terminal = jobs_runtime().block_on(async move { inner.is_terminal().await });
    if terminal {
        1
    } else {
        0
    }
}

/// Whether the cancel token bound to this controller's job in the
/// process-wide cancel registry has been fired. Returns `0` (not cancelled)
/// when the job is not currently registered (no [`mesh_run_as_job`] scope
/// active). Used by per-language SDKs whose blocking primitives cannot be
/// interrupted by a Tokio cancel token firing — e.g. the Java fixture's
/// `runs_overlong` polls this between `Thread.sleep` intervals so a
/// mid-flight cancel can break out of the loop instead of running to
/// natural completion. Distinct from [`mesh_job_controller_is_terminal`]:
/// terminal reflects local complete/fail/release intent; cancelled
/// reflects an external cancel signal (HTTP route, deadline trip, etc.).
///
/// # Returns
/// `1` if cancel token fired, `0` if not (or job not registered),
/// `-1` on error.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_is_cancelled(
    handle: *const JobControllerHandle,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let inner = handle.inner.clone();
    let cancelled = jobs_runtime().block_on(async move { inner.is_cancelled().await });
    if cancelled {
        1
    } else {
        0
    }
}

/// Wait for the next event posted to this job's event channel.
///
/// Mirrors [`JobController::recv_event`]. Returns the event as a JSON
/// string written to `*out_event_json`, or a null pointer when the
/// timeout elapses without a matching event. Cursor is per-controller-
/// instance (shared across `clone`s); a fresh controller for the same
/// `job_id` replays from seq=0.
///
/// # Arguments
/// - `types_json`: optional UTF-8 NUL-terminated JSON string encoding an
///   array of event-type tags. `NULL` (or a JSON `null`) means "receive
///   all types". Invalid JSON or non-array shape returns -1 with the
///   last-error slot populated.
/// - `timeout_secs`: f64 timeout in seconds. The C ABI cannot pass
///   `Option<f64>`, so the convention is: pass a negative value (e.g.
///   `-1.0`) to express "no timeout" (mirrors `Optional<Duration>::empty()`
///   on the Java side). NaN / ±Infinity reject with -1. Finite-but-
///   overflowing values (e.g. `f64::MAX`) reject with -1 via
///   [`Duration::try_from_secs_f64`] — see `parse_ffi_timeout_secs`.
/// - `out_event_json`: receives `*mut c_char` JSON string of the event
///   on arrival, or a NULL pointer on clean timeout (in which case the
///   return code is still 0). Caller frees via `mesh_free_string` when
///   the pointer is non-null.
///
/// # Returns
/// - `0` on success (event delivered OR clean timeout — caller checks
///   if `*out_event_json` is null to distinguish)
/// - `-1` on invalid args (null handle, malformed types_json, invalid
///   timeout)
/// - `-2` on JobNotFound (registry doesn't know the job — typically
///   "404 Not Found" from `GET /jobs/{id}/events`). Distinct from the
///   generic -3 so the Java SDK can map to a typed
///   `JobNotFoundException`.
/// - `-3` on other backend errors (5xx after retries, network failure,
///   etc.). See `mesh_last_error` for details.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_recv_event(
    handle: *mut JobControllerHandle,
    types_json: *const c_char,
    timeout_secs: f64,
    out_event_json: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    if out_event_json.is_null() {
        set_last_error("out_event_json is null");
        return -1;
    }
    // Default to empty so the success-path null-write is unambiguous
    // (callers can treat a null out-pointer as "timeout elapsed").
    *out_event_json = ptr::null_mut();
    let handle = &*handle;

    // Parse optional types filter — NULL → None (receive all); JSON array
    // → Some(Vec<String>); anything else rejects.
    let types_opt: Option<Vec<String>> = match opt_cstr(types_json, "types_json") {
        Ok(None) => None,
        Ok(Some(s)) => match serde_json::from_str::<serde_json::Value>(s) {
            Ok(serde_json::Value::Null) => None,
            Ok(serde_json::Value::Array(arr)) => {
                let mut out = Vec::with_capacity(arr.len());
                for v in arr {
                    match v {
                        serde_json::Value::String(s) => out.push(s),
                        other => {
                            set_last_error(format!(
                                "types_json must be an array of strings, got element: {}",
                                other
                            ));
                            return -1;
                        }
                    }
                }
                Some(out)
            }
            Ok(other) => {
                set_last_error(format!(
                    "types_json must be a JSON array or null, got: {}",
                    other
                ));
                return -1;
            }
            Err(e) => {
                set_last_error(format!("invalid types_json: {}", e));
                return -1;
            }
        },
        Err(()) => return -1,
    };

    let timeout = match parse_ffi_timeout_secs(timeout_secs) {
        Ok(t) => t,
        Err(msg) => {
            set_last_error(msg);
            return -1;
        }
    };

    let inner = handle.inner.clone();
    let result = jobs_runtime().block_on(async move { inner.recv_event(types_opt, timeout).await });
    match result {
        Ok(None) => {
            // Clean timeout — leave out-pointer as null and return 0.
            // Caller distinguishes "event arrived" from "timeout" by
            // checking the out-pointer.
            0
        }
        Ok(Some(ev)) => write_out_string(out_event_json, job_event_to_json_string(ev)),
        Err(JobError::Backend(crate::task_backend::BackendError::NotFound(msg))) => {
            set_last_error(format!("job not found: {}", msg));
            -2
        }
        Err(e) => {
            set_last_error(e.to_string());
            -3
        }
    }
}

/// Read the job ID this controller is bound to. Caller frees the returned
/// string via `mesh_free_string`.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_job_id(
    handle: *const JobControllerHandle,
    out_job_id: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    write_out_string(out_job_id, handle.inner.job_id().to_string())
}

/// Free a [`JobControllerHandle`] returned by [`mesh_job_controller_new`].
///
/// Drops the inner controller AND the background batching tick (which
/// triggers a final flush of any pending deltas before the tick stops).
///
/// # Safety
/// `handle` must come from [`mesh_job_controller_new`] or be NULL. After
/// this call, `handle` is invalid and must not be used.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_controller_free(handle: *mut JobControllerHandle) {
    if handle.is_null() {
        return;
    }
    drop(Box::from_raw(handle));
}

// =============================================================================
// JobProxy: consumer-side C ABI
// =============================================================================

/// Submit a new job via the registry and return a [`JobProxyHandle`].
///
/// `args_json` must encode a JSON object with these fields (mirroring
/// [`SubmitJobArgs`] field-for-field):
///
/// ```json
/// {
///   "registry_url": "http://...",
///   "capability": "...",
///   "payload": { ... },
///   "submitted_by": "...",
///   "owner_instance_id": "..." | null,
///   "max_duration": 120 | null,
///   "max_retries": 1 | null,
///   "total_deadline": 1700000000 | null
/// }
/// ```
///
/// JSON-shaped (rather than positional) args mirror the napi-rs
/// `JsSubmitJobArgs` object — keeps the C ABI signature stable as fields
/// are added.
#[no_mangle]
pub unsafe extern "C" fn mesh_submit_job(
    args_json: *const c_char,
    out_handle: *mut *mut JobProxyHandle,
) -> i32 {
    take_last_error();
    if out_handle.is_null() {
        set_last_error("out_handle is null");
        return -1;
    }
    let args_str = match req_cstr(args_json, "args_json") {
        Ok(s) => s,
        Err(()) => return -1,
    };

    // Parse with a permissive shape so missing optional fields default to
    // None. Required fields (registry_url, capability, payload, submitted_by)
    // surface a clean error if absent.
    #[derive(serde::Deserialize)]
    struct SubmitArgsWire {
        registry_url: String,
        capability: String,
        payload: serde_json::Value,
        submitted_by: String,
        #[serde(default)]
        owner_instance_id: Option<String>,
        #[serde(default)]
        max_duration: Option<u32>,
        #[serde(default)]
        max_retries: Option<u32>,
        #[serde(default)]
        total_deadline: Option<i64>,
    }
    let wire: SubmitArgsWire = match serde_json::from_str(args_str) {
        Ok(w) => w,
        Err(e) => {
            set_last_error(format!("invalid args_json: {}", e));
            return -1;
        }
    };

    let backend = match backend_from_url(&wire.registry_url) {
        Some(b) => b,
        None => return -1,
    };
    let args = SubmitJobArgs {
        capability: wire.capability,
        payload: wire.payload,
        submitted_by: wire.submitted_by,
        owner_instance_id: wire.owner_instance_id,
        max_duration: wire.max_duration,
        max_retries: wire.max_retries,
        total_deadline: wire.total_deadline,
    };

    let result = jobs_runtime().block_on(async move { submit_job(backend, args).await });
    match result {
        Ok((proxy, _resp)) => {
            let handle = Box::new(JobProxyHandle { inner: proxy });
            *out_handle = Box::into_raw(handle);
            0
        }
        Err(e) => jobs_set_err(e),
    }
}

/// Construct a [`JobProxyHandle`] bound to a known job id + registry URL.
/// Normally callers obtain a proxy via [`mesh_submit_job`] / DDDI injection
/// rather than constructing one directly.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_new(
    job_id: *const c_char,
    registry_url: *const c_char,
    out_handle: *mut *mut JobProxyHandle,
) -> i32 {
    take_last_error();
    if out_handle.is_null() {
        set_last_error("out_handle is null");
        return -1;
    }
    let job_id = match req_cstr(job_id, "job_id") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };
    let registry_url = match req_cstr(registry_url, "registry_url") {
        Ok(s) => s,
        Err(()) => return -1,
    };
    let backend = match backend_from_url(registry_url) {
        Some(b) => b,
        None => return -1,
    };
    let handle = Box::new(JobProxyHandle {
        inner: JobProxy::new(job_id, backend),
    });
    *out_handle = Box::into_raw(handle);
    0
}

/// Read the job id this proxy is bound to. Caller frees via `mesh_free_string`.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_job_id(
    handle: *const JobProxyHandle,
    out_job_id: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    write_out_string(out_job_id, handle.inner.job_id().to_string())
}

/// Read the latest job state from the registry (single GET). The full Job
/// row is serialized as JSON and written to `*out_job_json`; caller frees
/// via `mesh_free_string`.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_status(
    handle: *mut JobProxyHandle,
    out_job_json: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let inner = handle.inner.clone();
    let result = jobs_runtime().block_on(async move { inner.status().await });
    match result {
        Ok(job) => write_out_string(out_job_json, job_to_json_string(job)),
        Err(e) => jobs_set_err(e),
    }
}

/// Poll until the job reaches a terminal state. On success writes the job
/// `result` (JSON-encoded) to `*out_result_json`; caller frees via
/// `mesh_free_string`.
///
/// `timeout_secs`: wall-clock timeout. Any value `<= 0.0` (including
/// `-0.0` and negatives such as `-1`) means "no timeout"; non-finite
/// values (NaN, ±Inf) also fall back to "no timeout". Matches the
/// Python / napi-rs `Optional<f64>` shape and keeps the same policy
/// as [`mesh_run_as_job`] for consistency.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_wait(
    handle: *mut JobProxyHandle,
    timeout_secs: f64,
    out_result_json: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    // Uniform "no timeout" policy with mesh_run_as_job: `secs <= 0.0`
    // (covers -0.0 which `< 0.0` would miss in IEEE-754) or non-finite.
    // Use try_from_secs_f64 — `from_secs_f64` panics on overflow (e.g.
    // `f64::MAX`); we surface the failure cleanly via the last-error
    // slot so a buggy caller can't crash the host process. (PR #891 review.)
    let timeout = if !timeout_secs.is_finite() || timeout_secs <= 0.0 {
        None
    } else {
        match Duration::try_from_secs_f64(timeout_secs) {
            Ok(d) => Some(d),
            Err(e) => {
                set_last_error(format!(
                    "mesh_job_proxy_wait: invalid timeout_secs ({}): {}",
                    timeout_secs, e
                ));
                return -1;
            }
        }
    };
    let inner = handle.inner.clone();
    let result = jobs_runtime().block_on(async move { inner.wait(timeout).await });
    match result {
        Ok(value) => write_out_string(out_result_json, value.to_string()),
        Err(e) => jobs_set_err(e),
    }
}

/// Request cancellation. The registry forwards the signal to the owner
/// replica when alive. `reason` may be NULL.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_cancel(
    handle: *mut JobProxyHandle,
    reason: *const c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    let handle = &*handle;
    let reason = match opt_cstr(reason, "reason") {
        Ok(s) => s.map(str::to_string),
        Err(()) => return -1,
    };
    let inner = handle.inner.clone();
    jobs_runtime().block_on(async move { inner.cancel(reason).await })
        .map(|_| 0)
        .unwrap_or_else(jobs_set_err)
}

/// Post an event into this job's event channel.
///
/// Mirrors [`JobProxy::send_event`]. The running handler (inside a
/// `task=true` job) will see the event on its next `recv_event` call —
/// or wake immediately if it's currently long-polling.
///
/// # Arguments
/// - `event_type`: UTF-8 NUL-terminated event-type tag (e.g. `"signal"`,
///   `"user_input"`).
/// - `payload_json`: optional UTF-8 NUL-terminated JSON string encoding
///   the event payload. May be `NULL` to send an empty payload (the
///   Rust core treats null/missing as an empty JSON object — matching
///   the Python/TS `payload=None` shape).
/// - `out_receipt_json`: receives `*mut c_char` JSON string of the
///   receipt (`{job_id, seq, created_at}`). Caller frees via
///   `mesh_free_string`.
///
/// # Returns
/// - `0` on success
/// - `-1` on invalid args (null handle, malformed payload_json)
/// - `-2` on JobNotFound (registry doesn't know the job — 404 from
///   `POST /jobs/{id}/events`). Mapped by the Java SDK to
///   `JobNotFoundException`.
/// - `-3` on JobTerminal (job already completed/failed/cancelled — 409
///   from the registry, surfaced as [`JobError::JobTerminal`]). Mapped
///   by the Java SDK to `JobTerminalException`. Distinct from -2 so
///   callers can branch on terminal-state vs. unknown-job.
/// - `-4` on other backend errors (transport failure, 5xx after
///   retries, etc.). See `mesh_last_error` for details.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_send_event(
    handle: *mut JobProxyHandle,
    event_type: *const c_char,
    payload_json: *const c_char,
    out_receipt_json: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    if out_receipt_json.is_null() {
        set_last_error("out_receipt_json is null");
        return -1;
    }
    let handle = &*handle;

    let event_type = match req_cstr(event_type, "event_type") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };

    // NULL payload → empty object (matches Python's `payload=None` →
    // `{}` normalization in `mesh.jobs.post_event`).
    let payload: serde_json::Value = match opt_cstr(payload_json, "payload_json") {
        Ok(None) => serde_json::Value::Object(serde_json::Map::new()),
        Ok(Some(s)) => match serde_json::from_str(s) {
            Ok(v) => v,
            Err(e) => {
                set_last_error(format!("invalid payload_json: {}", e));
                return -1;
            }
        },
        Err(()) => return -1,
    };

    let inner = handle.inner.clone();
    let result = jobs_runtime().block_on(async move { inner.send_event(event_type, payload).await });
    match result {
        Ok(receipt) => write_out_string(out_receipt_json, job_event_receipt_to_json_string(receipt)),
        Err(JobError::JobTerminal(msg)) => {
            set_last_error(format!("job is terminal: {}", msg));
            -3
        }
        Err(JobError::Backend(crate::task_backend::BackendError::NotFound(msg))) => {
            set_last_error(format!("job not found: {}", msg));
            -2
        }
        Err(e) => {
            set_last_error(e.to_string());
            -4
        }
    }
}

/// Fetch a single batch of events from this job's event log with
/// `seq > after`, optionally filtered by `types`. The Java SDK's
/// `MeshJobs.subscribeEvents` blocking iterator is built on top of
/// this primitive — callers manage their own cursor between calls.
///
/// Mirrors [`JobProxy::list_events`] one-for-one. Returns the events
/// AND the registry-supplied `next_after` watermark in a JSON envelope
/// `{"events": [...], "next_after": N}` written to
/// `*out_envelope_json`. Caller frees via `mesh_free_string`.
///
/// # Arguments
/// - `after`: cursor — only events with `seq > after` are returned.
///   Pass `0` for "from the beginning of the event log".
/// - `types_json`: optional UTF-8 NUL-terminated JSON string encoding an
///   array of event-type tags (e.g. `["work","progress"]`). `NULL` (or
///   a JSON `null`) means "all types". Invalid JSON or non-array shape
///   returns -1 with the last-error slot populated.
/// - `timeout_secs`: f64 long-poll budget in seconds. Same negative-
///   sentinel convention as [`mesh_job_controller_recv_event`]:
///   pass a negative value (e.g. `-1.0`) to express "no timeout"
///   (single immediate read; rarely needed). NaN / ±Infinity reject
///   with -1; finite-but-overflowing values reject via
///   [`Duration::try_from_secs_f64`] (see `parse_ffi_timeout_secs`).
/// - `out_envelope_json`: receives `*mut c_char` JSON envelope
///   `{"events":[...],"next_after":N}`. Empty `events` array means
///   "no events arrived within the wait window" — the caller advances
///   the cursor to `next_after` (which may be `> after` when the
///   registry scanned events hidden by a server-side `types` filter)
///   and polls again. Caller frees via `mesh_free_string`.
///
/// # Returns
/// - `0` on success (envelope written; events list may be empty).
/// - `-1` on invalid args (null handle, null out-pointer, malformed
///   types_json, invalid timeout).
/// - `-2` on JobNotFound (registry doesn't know the job — 404 from
///   `GET /jobs/{id}/events`). Mapped by the Java SDK to
///   `JobNotFoundException`.
/// - `-3` on other backend errors (transport failure, 5xx after
///   retries, decode failure, etc.). See `mesh_last_error` for details.
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_list_events(
    handle: *mut JobProxyHandle,
    after: i64,
    types_json: *const c_char,
    timeout_secs: f64,
    out_envelope_json: *mut *mut c_char,
) -> i32 {
    take_last_error();
    if handle.is_null() {
        set_last_error("handle is null");
        return -1;
    }
    if out_envelope_json.is_null() {
        set_last_error("out_envelope_json is null");
        return -1;
    }
    *out_envelope_json = ptr::null_mut();
    let handle = &*handle;

    // Parse optional types filter — NULL → None (all types); JSON array
    // → Some(Vec<String>); anything else rejects. Same shape as
    // mesh_job_controller_recv_event.
    let types_opt: Option<Vec<String>> = match opt_cstr(types_json, "types_json") {
        Ok(None) => None,
        Ok(Some(s)) => match serde_json::from_str::<serde_json::Value>(s) {
            Ok(serde_json::Value::Null) => None,
            Ok(serde_json::Value::Array(arr)) => {
                let mut out = Vec::with_capacity(arr.len());
                for v in arr {
                    match v {
                        serde_json::Value::String(s) => out.push(s),
                        other => {
                            set_last_error(format!(
                                "types_json must be an array of strings, got element: {}",
                                other
                            ));
                            return -1;
                        }
                    }
                }
                Some(out)
            }
            Ok(other) => {
                set_last_error(format!(
                    "types_json must be a JSON array or null, got: {}",
                    other
                ));
                return -1;
            }
            Err(e) => {
                set_last_error(format!("invalid types_json: {}", e));
                return -1;
            }
        },
        Err(()) => return -1,
    };

    let wait = match parse_ffi_timeout_secs(timeout_secs) {
        Ok(t) => t,
        Err(msg) => {
            set_last_error(msg);
            return -1;
        }
    };

    let inner = handle.inner.clone();
    let result = jobs_runtime()
        .block_on(async move { inner.list_events(after, types_opt, wait).await });
    match result {
        Ok((events, next_after)) => {
            // Build the envelope shape consumed by Java's
            // EventSubscription. snake_case `next_after` keeps the wire
            // shape consistent with the registry response.
            let events_values: Vec<serde_json::Value> = events
                .into_iter()
                .map(|ev| serde_json::json!({
                    "job_id": ev.job_id,
                    "seq": ev.seq,
                    "type": ev.event_type,
                    "payload": ev.payload.unwrap_or(serde_json::Value::Null),
                    "trace_context": ev.trace_context.unwrap_or(serde_json::Value::Null),
                    "posted_by": ev.posted_by,
                    "created_at": ev.created_at,
                }))
                .collect();
            let envelope = serde_json::json!({
                "events": events_values,
                "next_after": next_after,
            });
            write_out_string(out_envelope_json, envelope.to_string())
        }
        Err(JobError::Backend(crate::task_backend::BackendError::NotFound(msg))) => {
            set_last_error(format!("job not found: {}", msg));
            -2
        }
        Err(e) => {
            set_last_error(e.to_string());
            -3
        }
    }
}

/// Free a [`JobProxyHandle`] returned by [`mesh_submit_job`] /
/// [`mesh_job_proxy_new`].
#[no_mangle]
pub unsafe extern "C" fn mesh_job_proxy_free(handle: *mut JobProxyHandle) {
    if handle.is_null() {
        return;
    }
    drop(Box::from_raw(handle));
}

// =============================================================================
// Context + cancel registry C ABI
// =============================================================================

/// Snapshot of the active job context on the current Rust task, or NULL
/// if no job is in scope.
///
/// Writes a JSON object of shape `{"job_id": str, "deadline_secs_remaining":
/// int|null}` to `*out_snapshot_json`. If no context is active, writes NULL
/// (same convention as Python's `current_job` returning `None`).
///
/// Caller frees the JSON string via `mesh_free_string` if it is non-NULL.
#[no_mangle]
pub unsafe extern "C" fn mesh_current_job(out_snapshot_json: *mut *mut c_char) -> i32 {
    take_last_error();
    if out_snapshot_json.is_null() {
        set_last_error("out_snapshot_json is null");
        return -1;
    }
    match job_context::current() {
        None => {
            *out_snapshot_json = ptr::null_mut();
            0
        }
        Some(ctx) => {
            let value = serde_json::json!({
                "job_id": ctx.job_id,
                "deadline_secs_remaining": ctx.remaining_seconds(),
            });
            write_out_string(out_snapshot_json, value.to_string())
        }
    }
}

/// Compute the `X-Mesh-Job-Id` / `X-Mesh-Timeout` header values for the
/// active job context, if any.
///
/// Writes a JSON object `{"X-Mesh-Job-Id": "...", "X-Mesh-Timeout":
/// "<secs>"}` (with `X-Mesh-Timeout` omitted when no deadline is set) to
/// `*out_headers_json`. If no context is active, writes NULL.
///
/// Caller frees the JSON string via `mesh_free_string` if it is non-NULL.
#[no_mangle]
pub unsafe extern "C" fn mesh_inject_job_headers(out_headers_json: *mut *mut c_char) -> i32 {
    take_last_error();
    if out_headers_json.is_null() {
        set_last_error("out_headers_json is null");
        return -1;
    }
    match job_context::current() {
        None => {
            *out_headers_json = ptr::null_mut();
            0
        }
        Some(ctx) => {
            let remaining = ctx.remaining_seconds();
            let mut map = serde_json::Map::new();
            map.insert(
                "X-Mesh-Job-Id".to_string(),
                serde_json::Value::String(ctx.job_id),
            );
            if let Some(secs) = remaining {
                map.insert(
                    "X-Mesh-Timeout".to_string(),
                    serde_json::Value::String(secs.to_string()),
                );
            }
            write_out_string(
                out_headers_json,
                serde_json::Value::Object(map).to_string(),
            )
        }
    }
}

/// Fire the cancel token registered for `job_id` in the process-wide
/// cancel registry, if any.
///
/// # Returns
/// `1` if a token was found and fired, `0` if no active job for that id,
/// `-1` on error (null/invalid `job_id`).
#[no_mangle]
pub unsafe extern "C" fn mesh_cancel_active_job(job_id: *const c_char) -> i32 {
    take_last_error();
    let job_id = match req_cstr(job_id, "job_id") {
        Ok(s) => s,
        Err(()) => return -1,
    };
    if cancel_registry::cancel_active_job(job_id) {
        1
    } else {
        0
    }
}

/// Block until the cancel token bound for `job_id` in the process-wide
/// cancel registry fires (explicit cancel via `mesh_cancel_active_job`)
/// OR the job is unregistered naturally (ended without cancel — see
/// `cancel_registry::JobCancelState::ended`). Resolves immediately if
/// the job is not currently registered (already terminal / never claimed).
///
/// Returns 0 on success (token resolved or unregistered), -1 on a NULL
/// `job_id_ptr` or invalid UTF-8.
///
/// Java SDK uses this from a watcher thread (wrapped in a
/// `CompletableFuture.runAsync`) to abort outbound OkHttp `Call`s when
/// the producer's job is cancelled. The `ended` arm prevents the
/// watcher from leaking when the call completes naturally without
/// cancel. Mirror of the napi `awaitJobCancel(jobId)` shipped in TS PR
/// #897, but blocking instead of async because JNR-FFI doesn't expose
/// async return types.
///
/// # Safety
/// `job_id_ptr` must be a valid C string for the duration of this call.
#[no_mangle]
pub unsafe extern "C" fn mesh_await_job_cancel(job_id_ptr: *const c_char) -> i32 {
    take_last_error();
    let job_id = match req_cstr(job_id_ptr, "job_id") {
        Ok(s) => s.to_string(),
        Err(()) => return -1,
    };
    // Snapshot both tokens once. None means "not registered" — resolve
    // immediately so callers don't hang on stale jobs.
    let Some((cancel, ended)) = cancel_registry::get_state(&job_id) else {
        return 0;
    };
    jobs_runtime().block_on(async move {
        tokio::select! {
            _ = cancel.cancelled() => {},
            _ = ended.cancelled() => {},
        }
    });
    0
}

// =============================================================================
// run_as_job — callback-based scope binding
// =============================================================================

/// Run a Java-provided callback inside a fresh [`crate::jobs::run_as_job`]
/// scope so the cancel-registry entry under the snapshot's `job_id` is
/// bound for the duration of the callback (allowing
/// `POST /jobs/{id}/cancel` to fire the in-flight cancel token).
///
/// `snapshot_json` must encode a JSON object of shape
/// `{"job_id": "...", "deadline_secs": <number>|null}` mirroring the
/// payload Java SDK constructs from inbound `X-Mesh-Job-Id` / `X-Mesh-Timeout`
/// headers. `deadline_secs` is the per-attempt deadline (relative); null /
/// missing / non-positive ≡ no deadline.
///
/// `callback` is invoked synchronously from the runtime's `block_on`,
/// wrapped in [`tokio::task::block_in_place`] so it is legal for the
/// callback to issue further blocking FFI calls (e.g.
/// `mesh_job_controller_complete` / `_fail` / `_update_progress`) that
/// internally re-enter `jobs_runtime().block_on(...)` — without
/// `block_in_place` such nested `block_on` calls would panic with
/// "Cannot start a runtime from within a runtime". This requires
/// `jobs_runtime()` to be a multi-threaded runtime, which it is
/// (`Runtime::new()` defaults to `multi_thread`). The callback receives
/// the opaque `user_data` pointer the caller passed in. The callback's
/// `i32` return value is propagated as this function's return value
/// (0 = success, non-zero = caller-defined error).
///
/// # Safety
/// `callback` must be a valid C function pointer for the entire duration
/// of this call. `user_data` is passed through opaquely — Rust does not
/// dereference it. If the callback panics across the FFI boundary the
/// behaviour is undefined; Java callers must catch all checked / unchecked
/// exceptions in their bridge function.
///
/// # Caveat
/// The Rust `tokio::task_local!` bound by `with_job` is only visible to
/// Rust futures polled within the scope. Java code in the callback will
/// NOT see the task-local — it must read its own `ThreadLocal` mirror.
/// The Rust side handles two things here:
///   1. cancel-registry binding so a `POST /jobs/{id}/cancel` arriving
///      mid-flight fires the in-flight token (the Java SDK reads this via
///      `mesh_cancel_active_job` from its cancel HTTP route);
///   2. header injection on Rust-originated outbound work (the cancel
///      token + `X-Mesh-*` headers are visible to `mesh_call_tool` and
///      friends polled inside the scope).
#[no_mangle]
pub unsafe extern "C" fn mesh_run_as_job(
    snapshot_json: *const c_char,
    callback: extern "C" fn(*mut c_void) -> i32,
    user_data: *mut c_void,
) -> i32 {
    take_last_error();
    let snap_str = match req_cstr(snapshot_json, "snapshot_json") {
        Ok(s) => s,
        Err(()) => return -1,
    };

    #[derive(serde::Deserialize)]
    struct SnapshotWire {
        job_id: String,
        #[serde(default)]
        deadline_secs: Option<f64>,
    }
    let wire: SnapshotWire = match serde_json::from_str(snap_str) {
        Ok(w) => w,
        Err(e) => {
            set_last_error(format!("invalid snapshot_json: {}", e));
            return -1;
        }
    };

    // Reject non-finite deadlines explicitly (NaN / ±Inf indicate an
    // upstream bug — silently aliasing them to "no deadline" would
    // paper over it). Any finite value `<= 0.0` (including -0.0 and
    // negatives) is treated as "no deadline" for uniformity with
    // [`mesh_job_proxy_wait`]. The two functions previously diverged
    // on -0.0 handling (`is_sign_negative` vs `< 0.0`); a single
    // policy avoids future drift.
    if let Some(secs) = wire.deadline_secs {
        if !secs.is_finite() {
            set_last_error(format!(
                "mesh_run_as_job: invalid deadline_secs ({}) for job {} — must be a finite number or null",
                secs, wire.job_id
            ));
            return -1;
        }
    }

    // `try_from_secs_f64` rather than `from_secs_f64` — the latter panics
    // for very-large finite values (e.g. `f64::MAX`); a buggy caller
    // shouldn't be able to abort the host process. (PR #891 review.)
    let ctx = match wire.deadline_secs {
        Some(secs) if secs > 0.0 => match Duration::try_from_secs_f64(secs) {
            Ok(d) => JobContext::with_timeout(wire.job_id, d),
            Err(e) => {
                set_last_error(format!(
                    "mesh_run_as_job: invalid deadline_secs ({}) for job {}: {}",
                    secs, wire.job_id, e
                ));
                return -1;
            }
        },
        _ => JobContext::new(wire.job_id),
    };

    // Wrap the user pointer so we can move it into the async block without
    // raw-pointer Send/Sync issues. The C contract is: `user_data` is
    // opaque; Rust never derefs it, just hands it back to the callback.
    struct UserDataPtr(*mut c_void);
    unsafe impl Send for UserDataPtr {}
    let ud = UserDataPtr(user_data);

    jobs_runtime().block_on(async move {
        run_as_job(ctx, async move {
            // `block_in_place` tells the multi-threaded Tokio runtime
            // "this call may block; move me off the worker thread so
            // other tasks can progress." This makes nested `block_on`
            // calls inside the callback legal — which matters because
            // the Java SDK's controller methods (mesh_job_controller_*)
            // each do their own `jobs_runtime().block_on(...)`
            // internally. Without `block_in_place`, a callback that
            // calls `controller.complete()` would panic with "Cannot
            // start a runtime from within a runtime."
            //
            // Requires `jobs_runtime()` to be multi-threaded — it is
            // (`Runtime::new()` defaults to `multi_thread`).
            let UserDataPtr(ptr) = ud;
            tokio::task::block_in_place(|| callback(ptr))
        })
        .await
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;
    use std::sync::atomic::{AtomicI32, Ordering};

    /// Smoke test for the [`opt_cstr`] / [`req_cstr`] helpers — they are
    /// unsafe internally but the safe inputs below cover the happy path
    /// and the null-pointer guard without requiring native callers.
    #[test]
    fn req_cstr_rejects_null() {
        let res = unsafe { req_cstr(ptr::null(), "x") };
        assert!(res.is_err());
    }

    #[test]
    fn opt_cstr_returns_none_for_null() {
        let res = unsafe { opt_cstr(ptr::null(), "x") };
        assert_eq!(res.unwrap(), None);
    }

    #[test]
    fn opt_cstr_returns_some_for_value() {
        let s = CString::new("hello").unwrap();
        let res = unsafe { opt_cstr(s.as_ptr(), "x") };
        assert_eq!(res.unwrap(), Some("hello"));
    }

    /// `mesh_current_job` must write NULL when no context is active —
    /// matches Python's `current_job_py` returning `None` and TS's
    /// `currentJob` returning `null`. Java callers branch on the null
    /// pointer rather than parsing an empty object.
    #[test]
    fn current_job_writes_null_outside_scope() {
        let mut out: *mut c_char = ptr::null_mut();
        let rc = unsafe { mesh_current_job(&mut out as *mut _) };
        assert_eq!(rc, 0);
        assert!(out.is_null(), "expected NULL when no active context");
    }

    /// `mesh_inject_job_headers` outside-of-scope must also be NULL — same
    /// "no headers" semantics as the napi `injectJobHeaders() -> null`.
    #[test]
    fn inject_job_headers_writes_null_outside_scope() {
        let mut out: *mut c_char = ptr::null_mut();
        let rc = unsafe { mesh_inject_job_headers(&mut out as *mut _) };
        assert_eq!(rc, 0);
        assert!(out.is_null());
    }

    /// `mesh_cancel_active_job` returns 0 when no active job — same
    /// false-on-miss semantics as `cancel_registry::cancel_active_job`.
    #[test]
    fn cancel_active_job_returns_zero_when_unknown() {
        let id = CString::new("does-not-exist-ffi-test").unwrap();
        let rc = unsafe { mesh_cancel_active_job(id.as_ptr()) };
        assert_eq!(rc, 0);
    }

    /// `mesh_await_job_cancel` must resolve immediately (return 0) when
    /// the job is not currently registered — mirrors the napi
    /// `awaitJobCancel` `None`-branch resolve-immediately semantic so
    /// Java watchers don't hang on stale jobs.
    #[test]
    fn await_job_cancel_resolves_immediately_when_unregistered() {
        let id = CString::new("await-cancel-not-registered").unwrap();
        let rc = unsafe { mesh_await_job_cancel(id.as_ptr()) };
        assert_eq!(rc, 0);
    }

    /// Null pointer must be rejected via the last-error slot rather
    /// than panicking — same pattern as the other req_cstr-guarded
    /// entry points.
    #[test]
    fn await_job_cancel_rejects_null() {
        let rc = unsafe { mesh_await_job_cancel(ptr::null()) };
        assert_eq!(rc, -1);
    }

    /// `mesh_await_job_cancel` must wake on the registry's `ended`
    /// token when a job is unregistered without explicit cancel — this
    /// is the no-leak path: the Java watcher thread reclaims itself
    /// when the surrounding `mesh_run_as_job` scope ends naturally.
    #[test]
    fn await_job_cancel_wakes_on_natural_unregister() {
        use std::thread;
        use std::time::Duration;
        use tokio_util::sync::CancellationToken;

        let job_id = format!(
            "await-cancel-natural-{}",
            uuid::Uuid::new_v4().simple()
        );
        cancel_registry::register_active_job(&job_id, CancellationToken::new());

        let job_id_for_thread = job_id.clone();
        let unregisterer = thread::spawn(move || {
            thread::sleep(Duration::from_millis(50));
            cancel_registry::unregister_active_job(&job_id_for_thread);
        });

        let id_c = CString::new(job_id).unwrap();
        let rc = unsafe { mesh_await_job_cancel(id_c.as_ptr()) };
        assert_eq!(rc, 0);
        unregisterer.join().expect("unregister thread panicked");
    }

    /// `mesh_run_as_job` must reject malformed JSON cleanly via the
    /// last-error slot rather than panicking. Matches the pattern used by
    /// `mesh_submit_job` for the wire-args parse failure.
    #[test]
    fn run_as_job_rejects_invalid_snapshot_json() {
        extern "C" fn cb(_: *mut c_void) -> i32 { 0 }
        let bad = CString::new("not-json").unwrap();
        let rc = unsafe { mesh_run_as_job(bad.as_ptr(), cb, ptr::null_mut()) };
        assert_eq!(rc, -1);
    }

    /// Non-finite deadline (NaN / +Inf) rejection — these indicate a real
    /// upstream bug, so we surface a clean error rather than silently
    /// aliasing to "no deadline". Negative + zero values are NOT
    /// rejected; they are treated as "no deadline" for uniformity with
    /// `mesh_job_proxy_wait` (see `wait_treats_zero_and_negative_as_no_timeout`).
    #[test]
    fn run_as_job_rejects_non_finite_deadline() {
        extern "C" fn cb(_: *mut c_void) -> i32 { 0 }
        // NaN and +Inf both rejected — JSON does not encode these as
        // numbers, but if a buggy caller stringifies them as "NaN" /
        // "Infinity" the snapshot parse will already fail; the
        // is_finite branch is the defence-in-depth check for futures
        // where the wire encoding gains support.
        let bad = CString::new(r#"{"job_id":"j-nan","deadline_secs":1e400}"#).unwrap();
        let rc = unsafe { mesh_run_as_job(bad.as_ptr(), cb, ptr::null_mut()) };
        assert_eq!(rc, -1, "+Inf deadline must be rejected");
    }

    /// Boundary policy for `mesh_run_as_job`: zero, -0.0, and finite
    /// negative deadlines all collapse to "no deadline" and the callback
    /// runs successfully. Mirrors the same policy in
    /// `mesh_job_proxy_wait` so future maintainers don't have to choose
    /// between two operators.
    #[test]
    fn run_as_job_treats_zero_and_negative_deadline_as_no_deadline() {
        extern "C" fn cb(_: *mut c_void) -> i32 { 0 }
        for snap_json in [
            r#"{"job_id":"j-zero","deadline_secs":0.0}"#,
            r#"{"job_id":"j-negzero","deadline_secs":-0.0}"#,
            r#"{"job_id":"j-neg","deadline_secs":-5.0}"#,
        ] {
            let snap = CString::new(snap_json).unwrap();
            let rc = unsafe { mesh_run_as_job(snap.as_ptr(), cb, ptr::null_mut()) };
            assert_eq!(rc, 0, "expected no-deadline policy for {}", snap_json);
        }
    }

    /// Boundary policy for `mesh_job_proxy_wait`'s timeout argument:
    /// zero, -0.0, and negative values all map to "no timeout"
    /// (Option::None passed to the inner wait), and non-finite values
    /// (NaN, ±Inf) map to "no timeout" too. We can't easily call the
    /// wait FFI without a real handle here, so we exercise the same
    /// predicate the FFI uses.
    #[test]
    fn wait_treats_zero_and_negative_as_no_timeout() {
        fn would_be_no_timeout(secs: f64) -> bool {
            !secs.is_finite() || secs <= 0.0
        }
        assert!(would_be_no_timeout(0.0));
        assert!(would_be_no_timeout(-0.0));
        assert!(would_be_no_timeout(-1.0));
        assert!(would_be_no_timeout(f64::NAN));
        assert!(would_be_no_timeout(f64::INFINITY));
        assert!(would_be_no_timeout(f64::NEG_INFINITY));
        assert!(!would_be_no_timeout(0.001));
        assert!(!would_be_no_timeout(60.0));
    }

    /// `f64::MAX` deadline must NOT panic — `Duration::from_secs_f64`
    /// panics on values that overflow `u64` seconds; we now use the
    /// fallible `try_from_secs_f64` and surface the failure via the
    /// last-error slot. (PR #891 review.)
    #[test]
    fn run_as_job_rejects_overflowing_deadline() {
        extern "C" fn cb(_: *mut c_void) -> i32 { 0 }
        // `f64::MAX` is finite, positive, and overflows u64-seconds —
        // exactly the case that previously panicked. Wrap the FFI call
        // in `catch_unwind` to prove the absence of a panic regression
        // even if the fix is reverted.
        let payload = format!(
            r#"{{"job_id":"j-overflow","deadline_secs":{}}}"#,
            f64::MAX
        );
        let snap = CString::new(payload).unwrap();
        let res = std::panic::catch_unwind(|| unsafe {
            mesh_run_as_job(snap.as_ptr(), cb, ptr::null_mut())
        });
        assert!(res.is_ok(), "f64::MAX deadline must not panic");
        assert_eq!(res.unwrap(), -1, "f64::MAX deadline must surface as error");
        // last-error slot should carry the diagnostic.
        let err = take_last_error();
        assert!(err.is_some(), "expected last_error to be populated");
    }

    /// `parse_ffi_timeout_secs` mirrors `parse_timeout_secs` in napi /
    /// pyo3 bindings — same NaN/Inf/overflow rejection. The Java/FFI
    /// twist is the negative-sentinel "no timeout" convention since C
    /// ABI cannot pass a nullable double.
    #[test]
    fn parse_ffi_timeout_secs_negative_means_no_timeout() {
        assert_eq!(parse_ffi_timeout_secs(-1.0).unwrap(), None);
        assert_eq!(parse_ffi_timeout_secs(-0.5).unwrap(), None);
        assert_eq!(parse_ffi_timeout_secs(f64::MIN).unwrap(), None);
    }

    #[test]
    fn parse_ffi_timeout_secs_accepts_zero_and_positive() {
        assert_eq!(
            parse_ffi_timeout_secs(0.0).unwrap(),
            Some(Duration::from_secs(0))
        );
        assert_eq!(
            parse_ffi_timeout_secs(1.5).unwrap(),
            Some(Duration::from_secs_f64(1.5))
        );
    }

    #[test]
    fn parse_ffi_timeout_secs_rejects_nan_and_infinity() {
        assert!(parse_ffi_timeout_secs(f64::NAN).is_err());
        assert!(parse_ffi_timeout_secs(f64::INFINITY).is_err());
        assert!(parse_ffi_timeout_secs(f64::NEG_INFINITY).is_err());
    }

    #[test]
    fn parse_ffi_timeout_secs_rejects_overflow() {
        let err = parse_ffi_timeout_secs(f64::MAX).expect_err("overflow must reject");
        assert!(err.contains("out of range"), "got: {err}");
    }

    /// `mesh_job_controller_recv_event` must reject null handle / null
    /// out-ptr cleanly via the last-error slot rather than crashing.
    #[test]
    fn recv_event_rejects_null_handle() {
        let mut out: *mut c_char = ptr::null_mut();
        let rc = unsafe {
            mesh_job_controller_recv_event(
                ptr::null_mut(),
                ptr::null(),
                -1.0,
                &mut out as *mut _,
            )
        };
        assert_eq!(rc, -1);
    }

    /// `mesh_job_proxy_list_events` must reject null handle / null
    /// out-ptr cleanly via the last-error slot rather than crashing.
    /// Mirrors `recv_event_rejects_null_handle` / `send_event_rejects_null_handle`.
    #[test]
    fn list_events_rejects_null_handle() {
        let mut out: *mut c_char = ptr::null_mut();
        let rc = unsafe {
            mesh_job_proxy_list_events(
                ptr::null_mut(),
                0,
                ptr::null(),
                -1.0,
                &mut out as *mut _,
            )
        };
        assert_eq!(rc, -1);
    }

    /// `mesh_job_proxy_send_event` must reject null handle / null
    /// out-ptr cleanly via the last-error slot rather than crashing.
    #[test]
    fn send_event_rejects_null_handle() {
        let mut out: *mut c_char = ptr::null_mut();
        let event_type = CString::new("signal").unwrap();
        let rc = unsafe {
            mesh_job_proxy_send_event(
                ptr::null_mut(),
                event_type.as_ptr(),
                ptr::null(),
                &mut out as *mut _,
            )
        };
        assert_eq!(rc, -1);
    }

    /// `mesh_job_proxy_wait` with an overflowing finite timeout must
    /// also surface as -1 rather than panic. We can't easily exercise
    /// the FFI without a live handle, so we cover the `try_from_secs_f64`
    /// behaviour directly to lock the contract in.
    #[test]
    fn proxy_wait_overflowing_timeout_does_not_panic() {
        // `from_secs_f64` would have panicked here.
        let res = Duration::try_from_secs_f64(f64::MAX);
        assert!(res.is_err(), "f64::MAX must fail try_from_secs_f64");
    }

    /// Happy-path: snapshot with no deadline, callback returns 0.
    /// Verifies the callback is actually invoked AND its return value
    /// propagates as the FFI return value.
    #[test]
    fn run_as_job_invokes_callback_and_propagates_return() {
        static SEEN: AtomicI32 = AtomicI32::new(0);
        extern "C" fn cb(_: *mut c_void) -> i32 {
            SEEN.fetch_add(1, Ordering::SeqCst);
            42
        }
        let snap = CString::new(r#"{"job_id":"j-cb"}"#).unwrap();
        let rc = unsafe { mesh_run_as_job(snap.as_ptr(), cb, ptr::null_mut()) };
        assert_eq!(rc, 42, "callback return value must propagate");
        assert_eq!(SEEN.load(Ordering::SeqCst), 1, "callback should run exactly once");
    }
}
