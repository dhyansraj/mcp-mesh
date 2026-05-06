//! napi-rs bindings for the MeshJob substrate (Phase 1 — TypeScript SDK).
//!
//! Mirror of [`crate::jobs_py`] for Node.js. Exposes the producer-side
//! [`crate::jobs::JobController`] and consumer-side [`crate::jobs::JobProxy`]
//! to TypeScript, plus the [`crate::jobs::submit_job`] entry point and a
//! snapshot accessor for the active [`crate::job_context`].
//!
//! The TypeScript SDK wraps these in an idiomatic surface (`MeshJob` Protocol
//! type + `mesh.tool({ task: true })` option); raw bindings here intentionally
//! stay thin so the Rust core remains the source of truth for state-machine
//! semantics.
//!
//! # Async pattern
//! Methods that block from JavaScript return `Promise`s constructed via
//! napi-rs's `async` feature (`async fn` on `#[napi]` methods). This matches
//! the existing pattern in [`crate::napi`] (e.g. `JsAgentHandle::next_event`).
//!
//! # Caveat — Rust task-local visibility from JavaScript
//! Like the Python equivalent: the Rust `tokio::task_local!` bound by
//! [`crate::job_context::with_job`] is only visible to Rust futures polled
//! within the scope. JS code running on the Node event loop does NOT inherit
//! the task-local across the FFI boundary. The TypeScript SDK compensates by
//! mirroring the context in `AsyncLocalStorage` (see `job-context.ts`),
//! which IS visible to user code and JS-originated outbound calls. The Rust
//! side handles the cancel-registry binding plus header injection on
//! Rust-originated outbound work (e.g. LLM provider `call_tool`).

#![cfg(feature = "typescript")]

use std::sync::Arc;
use std::time::Duration;

use napi::bindgen_prelude::*;
use napi_derive::napi;

use crate::cancel_registry;
use crate::job_context::{self, JobContext};
use crate::jobs::{
    new_coalescing_queue, run_as_job, spawn_batching_tick, submit_job, BatchingConfig,
    BatchingHandle, JobController, JobError, JobProxy, SubmitJobArgs,
};
use crate::task_backend::{
    Job, JobStatus, RegistryHttpBackend, TaskBackend,
};

// =============================================================================
// Helpers
// =============================================================================

/// Build an `Arc<dyn TaskBackend>` from a registry URL. Returns a napi
/// error on transport-construction failure (mirrors `backend_from_url`
/// in `jobs_py.rs`).
fn backend_from_url(registry_url: &str) -> napi::Result<Arc<dyn TaskBackend>> {
    let backend = RegistryHttpBackend::new(registry_url)
        .map_err(|e| Error::from_reason(format!("backend init failed: {}", e)))?;
    Ok(backend.into_arc())
}

/// Map [`JobError`] onto a napi error with reasonable messages so callers
/// can `try/catch` cleanly. We don't have language-level distinct exception
/// types like Python's `TimeoutError`, so we encode the variant name as
/// the leading token; SDK code can string-match if it needs to discriminate.
fn job_error_to_napi(err: JobError) -> Error {
    match err {
        JobError::Timeout(d) => {
            Error::from_reason(format!("timeout: wait timed out after {:?}", d))
        }
        JobError::Cancelled => {
            Error::from_reason("cancelled: job cancelled by enclosing context")
        }
        other => Error::from_reason(other.to_string()),
    }
}

/// Convert a [`Job`] into a JSON value the TS layer can `JSON.parse`-style
/// consume directly. napi-rs's `serde-json` integration converts to a JS
/// object on the boundary so the SDK doesn't need a separate parse step.
fn job_to_json(job: Job) -> serde_json::Value {
    serde_json::json!({
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
    })
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

// =============================================================================
// JsJobController (producer-side)
// =============================================================================

/// Producer-side handle bound to a single job. Application code receives one
/// via DDDI injection (the inbound tool wrapper, next dispatch); the
/// constructor is also exposed for tests and the claim worker dispatch path.
///
/// Each controller owns a per-instance coalescing queue plus a background
/// batching tick that flushes mid-flight progress deltas to the registry on a
/// fixed cadence. The tick is shut down (with a final flush) when the
/// controller is dropped by JS GC.
#[napi(js_name = "JobController")]
pub struct JsJobController {
    inner: JobController,
    /// Background batching tick handle; held so it lives as long as this
    /// controller. Spawned inside napi-rs's Tokio runtime in the
    /// constructor (see `within_runtime_if_available` below) and dropped
    /// (= cancelled with final flush) when JS GC collects the controller.
    /// `Option<...>` is preserved for forward-compat with a possible
    /// noop-feature build where `within_runtime_if_available` may degrade.
    _batching: Option<BatchingHandle>,
}

#[napi]
impl JsJobController {
    /// Construct a controller bound to `(jobId, instanceId)` against the
    /// given `registryUrl`. Spawns a per-controller background batching tick
    /// so mid-flight `updateProgress` calls reach the registry on the
    /// configured cadence (default 2s); the tick is torn down with a final
    /// flush when the controller is dropped.
    #[napi(constructor)]
    pub fn new(job_id: String, instance_id: String, registry_url: String) -> Result<Self> {
        let backend = backend_from_url(&registry_url)?;
        let queue = new_coalescing_queue();
        let inner = JobController::new(
            job_id,
            instance_id.clone(),
            backend.clone(),
            queue.clone(),
        );
        // Spawn the batching tick inside napi-rs's shared Tokio runtime so
        // mid-flight progress deltas actually reach the registry. The
        // `#[napi(constructor)]` is invoked synchronously from JS context
        // with NO ambient Tokio runtime — `Handle::try_current()` would
        // return `Err` and the tick would be silently skipped (mirrors
        // Python's `pyo3_async_runtimes::tokio::get_runtime().enter()`).
        // `within_runtime_if_available` enters napi-rs's `RT` for the
        // duration of the closure so `tokio::spawn` inside
        // `spawn_batching_tick` resolves a valid runtime handle.
        let batching = napi::bindgen_prelude::within_runtime_if_available(|| {
            spawn_batching_tick(
                queue,
                backend,
                instance_id,
                BatchingConfig::default(),
            )
        });
        Ok(Self {
            inner,
            _batching: Some(batching),
        })
    }

    /// The job ID this controller is bound to.
    #[napi(getter)]
    pub fn job_id(&self) -> String {
        self.inner.job_id().to_string()
    }

    /// Enqueue a progress update. Coalesces with any prior pending progress
    /// for this job — only the latest survives the next batch flush.
    #[napi]
    pub async fn update_progress(&self, progress: f64, message: Option<String>) -> Result<()> {
        // f32 on Rust side, f64 on JS side: clamp via cast (JS Number is
        // f64; values outside f32 range round to ±inf which still works
        // as a sentinel — registry will validate range upstream).
        self.inner.update_progress(progress as f32, message).await;
        Ok(())
    }

    /// Mark the job complete with the given result. Flushes immediately.
    /// `result` is any JSON-shaped JS value (object/array/primitive) —
    /// mirrors MCP's "results are JSON" contract.
    #[napi]
    pub async fn complete(&self, result: serde_json::Value) -> Result<()> {
        self.inner
            .complete(result)
            .await
            .map_err(job_error_to_napi)?;
        Ok(())
    }

    /// Mark the job failed with the given error reason. Flushes immediately.
    #[napi]
    pub async fn fail(&self, error: String) -> Result<()> {
        self.inner.fail(error).await.map_err(job_error_to_napi)?;
        Ok(())
    }

    /// Whether `complete` / `fail` has already been called on this
    /// controller. The TS dispatch wrapper uses this to decide whether a
    /// returning user function needs an auto-`complete` — users who already
    /// `await job.complete(...)` closed out the row, so the wrapper must
    /// NOT double-flush.
    ///
    /// Sync from JS's perspective: returns a Promise<boolean> because the
    /// underlying queue read is async, but the call is short.
    #[napi]
    pub async fn is_terminal(&self) -> bool {
        self.inner.is_terminal().await
    }
}

// =============================================================================
// JsJobProxy (consumer-side)
// =============================================================================

/// Consumer-side handle: returned by [`submit_job_napi`] and exposes
/// `wait` / `status` / `cancel` for code that wants to await a remote job.
#[napi(js_name = "JobProxy")]
pub struct JsJobProxy {
    inner: JobProxy,
}

#[napi]
impl JsJobProxy {
    /// Construct a proxy bound to a known `jobId` + `registryUrl`. Normally
    /// callers obtain a proxy via [`submit_job_napi`] / DDDI injection
    /// rather than constructing one directly.
    #[napi(constructor)]
    pub fn new(job_id: String, registry_url: String) -> Result<Self> {
        let backend = backend_from_url(&registry_url)?;
        Ok(Self {
            inner: JobProxy::new(job_id, backend),
        })
    }

    /// The job ID this proxy is bound to.
    #[napi(getter)]
    pub fn job_id(&self) -> String {
        self.inner.job_id().to_string()
    }

    /// Read the latest job state from the registry (single GET).
    /// Returns the full job row as a JSON object.
    #[napi]
    pub async fn status(&self) -> Result<serde_json::Value> {
        let job = self.inner.status().await.map_err(job_error_to_napi)?;
        Ok(job_to_json(job))
    }

    /// Poll until the job reaches a terminal state. Returns the result
    /// payload as a JS value (object/array/primitive) on success;
    /// rejects with a "timeout: ..." error on `timeoutSecs`, or
    /// "cancelled" / other reason on non-success terminal.
    #[napi]
    pub async fn wait(&self, timeout_secs: Option<f64>) -> Result<serde_json::Value> {
        let timeout = timeout_secs.map(Duration::from_secs_f64);
        self.inner
            .wait(timeout)
            .await
            .map_err(job_error_to_napi)
    }

    /// Request cancellation. The registry forwards the signal to the
    /// owner replica when alive. Resolves once the registry has
    /// acknowledged.
    #[napi]
    pub async fn cancel(&self, reason: Option<String>) -> Result<()> {
        self.inner.cancel(reason).await.map_err(job_error_to_napi)?;
        Ok(())
    }
}

// =============================================================================
// Submit-job arguments (TS-shaped object)
// =============================================================================

/// Arguments for [`submit_job_napi`]. Mirrors [`SubmitJobArgs`]
/// field-for-field; `payload` is any JSON-shaped JS value.
///
/// Optional `i64` fields are typed as `Option<i64>` — JavaScript Number
/// safely represents integers up to 2^53; callers passing unix-epoch
/// timestamps stay well inside that range.
#[napi(object, js_name = "SubmitJobArgs")]
pub struct JsSubmitJobArgs {
    pub registry_url: String,
    pub capability: String,
    pub payload: serde_json::Value,
    pub submitted_by: String,
    pub owner_instance_id: Option<String>,
    pub max_duration: Option<u32>,
    pub max_retries: Option<u32>,
    pub total_deadline: Option<i64>,
}

/// Submit a new job via the registry and return a [`JsJobProxy`].
///
/// Mirrors [`SubmitJobArgs`] field-for-field. Single-arg shape matches
/// Python's PyO3 binding.
#[napi(js_name = "submitJob")]
pub async fn submit_job_napi(args: JsSubmitJobArgs) -> Result<JsJobProxy> {
    let backend = backend_from_url(&args.registry_url)?;
    let rust_args = SubmitJobArgs {
        capability: args.capability,
        payload: args.payload,
        submitted_by: args.submitted_by,
        owner_instance_id: args.owner_instance_id,
        max_duration: args.max_duration,
        max_retries: args.max_retries,
        total_deadline: args.total_deadline,
    };
    let (proxy, _resp) = submit_job(backend, rust_args)
        .await
        .map_err(job_error_to_napi)?;
    Ok(JsJobProxy { inner: proxy })
}

// =============================================================================
// Job-context accessors
// =============================================================================

/// Snapshot of the active job context returned by [`current_job_napi`].
/// Mirrors the TS-side `JobContextSnapshot` interface in `job-context.ts`.
#[napi(object, js_name = "JobContextSnapshot")]
pub struct JsJobContextSnapshot {
    pub job_id: String,
    /// `None` if no deadline is set on the active context.
    pub deadline_secs_remaining: Option<u32>,
}

/// Snapshot of the active job context on the current Tokio task, or `null`
/// if no job is in scope.
///
/// Source of truth is the Rust [`crate::job_context`] (set via
/// `with_job` / `run_as_job` by the inbound HTTP wrapper or claim worker).
/// JS code typically reads the AsyncLocalStorage mirror — this binding is
/// for cross-FFI parity / debugging / Rust-originated paths.
#[napi(js_name = "currentJob")]
pub fn current_job_napi() -> Option<JsJobContextSnapshot> {
    job_context::current().map(|ctx| {
        let remaining = ctx.remaining_seconds().map(|s| s as u32);
        JsJobContextSnapshot {
            job_id: ctx.job_id,
            deadline_secs_remaining: remaining,
        }
    })
}

/// Headers injected by [`inject_job_headers_napi`].
///
/// Both fields are optional individually: when an active context has no
/// deadline, `xMeshTimeout` is `None`. When no job context is active at all,
/// the function returns `None` instead of an empty object.
#[napi(object, js_name = "JobHeaders")]
pub struct JsJobHeaders {
    /// `X-Mesh-Job-Id` header value.
    pub x_mesh_job_id: String,
    /// `X-Mesh-Timeout` header value (seconds remaining as decimal string),
    /// or `None` if the active context has no deadline.
    pub x_mesh_timeout: Option<String>,
}

/// Compute the `X-Mesh-Job-Id` / `X-Mesh-Timeout` header values for the
/// active job context, if any.
///
/// Returns `null` when no job context is active on the current task.
/// The TS outbound HTTP layer (e.g. the proxy `createProxy` factory)
/// merges these into the request headers alongside any existing
/// `X-Trace-Id` propagation.
///
/// Header *name shape*: this function returns a plain object the SDK can
/// destructure or spread into a request-headers map. We deliberately do NOT
/// reach across into a JS `Headers` instance here — that's TS-runtime
/// territory (Express/Fetch/undici) and varies between transport stacks.
#[napi(js_name = "injectJobHeaders")]
pub fn inject_job_headers_napi() -> Option<JsJobHeaders> {
    job_context::current().map(|ctx| {
        let timeout = ctx.remaining_seconds().map(|s| s.to_string());
        JsJobHeaders {
            x_mesh_job_id: ctx.job_id,
            x_mesh_timeout: timeout,
        }
    })
}

// =============================================================================
// cancel_active_job
// =============================================================================

/// Fire the cancel token registered for `jobId` in the process-wide
/// cancel registry, if any. Returns `true` iff a token was found and
/// fired (matches [`crate::cancel_registry::cancel_active_job`] semantics).
///
/// Used by the SDK-owned `POST /jobs/{job_id}/cancel` HTTP route — when the
/// registry forwards a cancel to this replica, the route handler calls this
/// to abort the in-flight job. (Route wiring lands in the next dispatch.)
#[napi(js_name = "cancelActiveJob")]
pub fn cancel_active_job_napi(job_id: String) -> bool {
    cancel_registry::cancel_active_job(&job_id)
}

// =============================================================================
// with_job_async
// =============================================================================

/// Run an in-flight JS Promise inside a fresh [`crate::jobs::run_as_job`]
/// scope so the cancel-registry entry under `jobId` is bound for the
/// duration of the await (so the `POST /jobs/{id}/cancel` HTTP route can
/// fire the in-flight cancel token).
///
/// **Important caveat — Rust task-local visibility from JS:** the Rust
/// `tokio::task_local!` bound by `with_job` is NOT visible to JS user
/// code on the Node event loop (different runtimes). The TS SDK MUST
/// set its own `AsyncLocalStorage` (`CURRENT_JOB`) in parallel — that
/// mirror is the source of truth for in-process JS reads and for
/// JS-originated outbound calls. The Rust side handles two things:
///
///   1. cancel-registry binding so `POST /jobs/{id}/cancel` can fire
///      the in-flight cancel token (visible to any Rust futures
///      polled within the scope, including the napi-rs HTTP path of
///      `call_tool`/`submit_job`/etc.);
///   2. header injection for Rust-originated outbound work via
///      [`inject_job_headers_napi`].
///
/// This is the FFI helper the inbound tool wrapper (next dispatch) uses
/// when an `X-Mesh-Job-Id` header arrives on a `tools/call`. It awaits
/// a JS Promise and resolves with whatever the Promise resolves to.
///
/// Arguments:
///   * `jobId` — server-assigned job UUID this call is bound to.
///   * `deadlineSecs` — optional per-attempt deadline in seconds.
///     `null` / `undefined` means no deadline (unlimited per design-doc
///     default).
///   * `body` — in-flight JS Promise resolving to a JSON value. The
///     SDK's TS wrapper typically constructs this with the user
///     function's return value already JSON-serialised.
///
/// NB on lifecycle: napi-rs's `Promise<T>` only completes when the
/// underlying JS Promise settles. The `run_as_job` scope keeps the
/// cancel registry entry alive for that whole window, then drops it
/// (panic-safe via the internal drop guard).
#[napi(js_name = "withJobAsync")]
pub async fn with_job_async_napi(
    job_id: String,
    deadline_secs: Option<f64>,
    body: Promise<serde_json::Value>,
) -> Result<serde_json::Value> {
    let ctx = match deadline_secs {
        Some(secs) if secs > 0.0 => JobContext::with_timeout(job_id, Duration::from_secs_f64(secs)),
        _ => JobContext::new(job_id),
    };
    run_as_job(ctx, async move { body.await }).await
}
