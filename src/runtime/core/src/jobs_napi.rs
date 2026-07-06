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
    Job, JobEvent, JobEventReceipt, RegistryHttpBackend, TaskBackend,
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

/// Validate and convert a JS-supplied `timeoutSecs` (`Option<f64>`) into
/// an `Option<Duration>`. `Duration::from_secs_f64` panics on negative,
/// NaN, infinite, or out-of-range inputs; this helper traps those at the
/// JS boundary and surfaces a clean `Error` instead so a typo'd literal
/// in user code can't crash the Rust runtime. Uses the fallible
/// `try_from_secs_f64` for the final conversion so even finite-but-huge
/// values (e.g. `f64::MAX`) reject cleanly instead of panicking. Mirrors
/// `parse_timeout_secs` in `jobs_py.rs`.
fn parse_timeout_secs(secs: Option<f64>) -> napi::Result<Option<Duration>> {
    match secs {
        None => Ok(None),
        Some(s) => crate::task_backend::validate_secs_to_duration(s, false)
            .map_err(Error::from_reason),
    }
}

/// Map [`JobError`] onto a napi error with reasonable messages so callers
/// can `try/catch` cleanly. We don't have language-level distinct exception
/// types like Python's `TimeoutError`, so we encode the variant name as
/// the leading token; SDK code can string-match if it needs to discriminate.
///
/// `JobError::JobTerminal` and the `NotFound` backend error carry the
/// distinct "job is terminal" / "job not found" prefixes that the TS SDK
/// re-classifies into `JobTerminalError` / `JobNotFoundError` typed
/// exceptions — matching the Python SDK's string-based dispatch in
/// `mesh/jobs.py::_translate_job_error`.
fn job_error_to_napi(err: JobError) -> Error {
    match err {
        JobError::Timeout(d) => {
            Error::from_reason(format!("timeout: wait timed out after {:?}", d))
        }
        JobError::Cancelled => {
            Error::from_reason("cancelled: job cancelled by enclosing context")
        }
        // `JobTerminal` surfaces the exact "job is terminal" prefix the
        // TS SDK's `JobTerminalError` re-classification keys on (mirror
        // of Python's `mesh/jobs.py::_translate_job_error`). Keep the
        // string stable — it is part of the SDK contract.
        JobError::JobTerminal(msg) => {
            Error::from_reason(format!("job is terminal: {}", msg))
        }
        other => Error::from_reason(other.to_string()),
    }
}

/// Convert a [`JobEvent`] into a JSON value the TS layer consumes as a
/// plain JS object via napi-rs's `serde-json` integration. Field shape
/// mirrors the OpenAPI `JobEvent` schema and the Python `job_event_to_pydict`
/// helper field-for-field so cross-runtime test fixtures can read either.
fn job_event_to_json(ev: JobEvent) -> serde_json::Value {
    serde_json::to_value(&ev).unwrap_or(serde_json::Value::Null)
}

/// Convert a [`JobEventReceipt`] into a JSON value the TS layer consumes
/// as a plain JS object. Mirrors `JobEventPostResponse` field-for-field
/// (= Python's `job_event_receipt_to_pydict`).
fn job_event_receipt_to_json(receipt: JobEventReceipt) -> serde_json::Value {
    serde_json::to_value(&receipt).unwrap_or(serde_json::Value::Null)
}

/// Convert a [`Job`] into a JSON value the TS layer can `JSON.parse`-style
/// consume directly. napi-rs's `serde-json` integration converts to a JS
/// object on the boundary so the SDK doesn't need a separate parse step.
fn job_to_json(job: Job) -> serde_json::Value {
    serde_json::to_value(&job).unwrap_or(serde_json::Value::Null)
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
    pub fn new(
        job_id: String,
        instance_id: String,
        registry_url: String,
        claim_epoch: Option<i64>,
    ) -> Result<Self> {
        let backend = backend_from_url(&registry_url)?;
        let queue = new_coalescing_queue();
        // `claim_epoch=None` (push-mode inbound job / old registry) ⇒ legacy
        // owner-only behavior; on the claim path the SDK passes the epoch
        // from the `/jobs/claim` response so this execution is fenced (#1252).
        let inner = JobController::new_with_epoch(
            job_id,
            instance_id.clone(),
            claim_epoch,
            backend.clone(),
            queue.clone(),
            // No seeded resume cursor at this binding surface (issue #1277
            // runtime resume gating is a later wave).
            None,
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

    /// The claim generation this controller executes under, or ``null`` for
    /// a push-mode inbound job / an old registry (issue #1252).
    #[napi(getter)]
    pub fn claim_epoch(&self) -> Option<i64> {
        self.inner.claim_epoch()
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

    /// Voluntarily release the lease so a peer replica can re-claim and
    /// retry. Used by the TS dispatch wrapper when a handler raises a
    /// retryOn-matched exception (issue #894): instead of marking the row
    /// terminal=failed, the SDK calls `releaseLease` so the registry resets
    /// `owner_instance_id` and a peer replica picks up the row within ~5s
    /// via the HEAD-heartbeat path. Note: release does NOT increment
    /// `attempt_count` — the claim that picked the row up already counted
    /// this attempt; the next claim will count the next attempt.
    ///
    /// Marks terminal locally before the backend call to fence racing
    /// progress updates from the now-defunct attempt (mirror of
    /// `JobController::release_lease` in Rust core).
    #[napi]
    pub async fn release_lease(&self, reason: Option<String>) -> Result<()> {
        self.inner
            .release_lease(reason)
            .await
            .map_err(job_error_to_napi)?;
        Ok(())
    }

    /// Transition the job to `input_required`, signalling the consumer
    /// that the handler is blocked awaiting an external answer. STATUS-ONLY
    /// primitive: it posts the `input_required` delta (with `prompt`
    /// carried on the existing `progress_message` field) and resolves once
    /// posted — it does NOT await the answer. Compose it with the existing
    /// event primitives for a full request-and-await: call
    /// `await job.requestInput(prompt)`, then park on
    /// `await job.recvEvent(["answer"])`; an external party answers via
    /// `proxy.sendEvent("answer", ...)`; the handler resumes and
    /// `await job.complete(...)`s.
    ///
    /// Flushes IMMEDIATELY (not via the coalescing batch tick) because the
    /// consumer is blocked on this control-plane transition. NON-terminal:
    /// the handler keeps running and may still call `updateProgress` /
    /// `complete` / `fail` afterwards. `complete` / `fail` exit
    /// `input_required` (the registry confirms the transition).
    #[napi]
    pub async fn request_input(&self, prompt: Option<String>) -> Result<()> {
        self.inner
            .request_input(prompt)
            .await
            .map_err(job_error_to_napi)?;
        Ok(())
    }

    /// Wait for the next event posted into this job's event log.
    ///
    /// Mirrors [`JobController::recv_event`]. Returns the event as a JS
    /// object on arrival, `null` on timeout. Cursor is
    /// per-controller-instance (shared across `clone`s); a fresh
    /// controller for the same `jobId` replays from seq=0.
    ///
    /// `timeoutSecs` is validated for NaN/Infinity/negative via
    /// [`parse_timeout_secs`] — invalid inputs reject with a clear
    /// `Error("timeoutSecs must be non-negative and finite")` rather than
    /// crashing the Rust runtime via `Duration::from_secs_f64`'s panic
    /// (mirror of the Python `PyValueError` path in `jobs_py.rs`).
    #[napi]
    pub async fn recv_event(
        &self,
        types: Option<Vec<String>>,
        timeout_secs: Option<f64>,
    ) -> Result<Option<serde_json::Value>> {
        let timeout = parse_timeout_secs(timeout_secs)?;
        let result = self
            .inner
            .recv_event(types, timeout)
            .await
            .map_err(job_error_to_napi)?;
        Ok(result.map(job_event_to_json))
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
    ///
    /// `timeoutSecs` is validated via [`parse_timeout_secs`] — NaN /
    /// Infinity / negative inputs reject with a clear `Error` rather
    /// than panicking inside `Duration::from_secs_f64`.
    #[napi]
    pub async fn wait(&self, timeout_secs: Option<f64>) -> Result<serde_json::Value> {
        let timeout = parse_timeout_secs(timeout_secs)?;
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

    /// Post an event into this job's event log. The running handler
    /// (inside the `task: true` job) will see it on its next
    /// `recvEvent` call — or wake immediately if it's currently
    /// long-polling.
    ///
    /// `payload` is any JSON-shaped JS value (object/array/primitive).
    /// The receipt object carries `{ job_id, seq, created_at }` so
    /// callers can stitch a follow-up `recvEvent` to it via `after`.
    ///
    /// Throws on:
    ///   - job-not-found (registry doesn't know the job) — the SDK
    ///     re-classifies "job not found" into `JobNotFoundError`
    ///   - job-terminal (job already completed/failed/cancelled) — the
    ///     SDK re-classifies "job is terminal" into `JobTerminalError`
    ///   - other transport / backend errors.
    #[napi]
    pub async fn send_event(
        &self,
        event_type: String,
        payload: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let receipt = self
            .inner
            .send_event(event_type, payload)
            .await
            .map_err(job_error_to_napi)?;
        Ok(job_event_receipt_to_json(receipt))
    }

    /// Fetch a single batch of events from this job's event log with
    /// `seq > after`, optionally filtered by `types`. The TS SDK's
    /// `mesh.jobs.subscribeEvents` async iterator is built on top of
    /// this primitive — callers manage their own cursor between calls.
    ///
    /// `timeoutSecs`: long-poll budget. `null`/`undefined` ≡ single
    /// immediate read; a number long-polls up to that many seconds
    /// (capped at 60s by the registry). An empty `events` array means
    /// "no events arrived within the wait window" — the caller
    /// continues with the same cursor (or advances to `nextAfter` if
    /// the registry returned a higher watermark, which happens when
    /// server-side `types` filtering hides events in the scanned range).
    ///
    /// Returns a `ListEventsResult { events, nextAfter }` object:
    /// `events` is the list of event objects (same shape as
    /// `recvEvent`'s single-event object); `nextAfter` is the
    /// registry-supplied watermark the caller should feed back as
    /// `after` on the next call so empty pages caused by server-side
    /// `types` filtering still advance the cursor.
    #[napi]
    pub async fn list_events(
        &self,
        after: i64,
        types: Option<Vec<String>>,
        timeout_secs: Option<f64>,
    ) -> Result<ListEventsResult> {
        let wait = parse_timeout_secs(timeout_secs)?;
        let (events, next_after) = self
            .inner
            .list_events(after, types, wait)
            .await
            .map_err(job_error_to_napi)?;
        let events_json = events.into_iter().map(job_event_to_json).collect();
        Ok(ListEventsResult {
            events: events_json,
            next_after,
        })
    }
}

/// Result of [`JsJobProxy::list_events`]. Wrapped struct rather than a
/// bare `(Vec<X>, i64)` tuple because napi-rs's auto-serialisation does
/// not emit a tuple shape on the JS side — wrapping in a `#[napi(object)]`
/// gives us a stable `{ events, nextAfter }` object the TS SDK consumes
/// directly.
///
/// Note: the Rust struct intentionally drops the `Js` prefix used by
/// sibling types in this module (`JsJobProxy`, `JsSubmitJobArgs`, …)
/// because napi-rs's codegen emits the Rust struct name verbatim for
/// method return types (it honours `js_name` for top-level function
/// returns but not for `#[napi] impl` method returns). Keeping the Rust
/// name aligned with the JS name avoids a dangling `JsListEventsResult`
/// reference in the generated `index.d.ts`.
#[napi(object)]
pub struct ListEventsResult {
    /// The list of events returned by the registry. Same shape as
    /// `recvEvent`'s single-event object.
    pub events: Vec<serde_json::Value>,
    /// Registry-supplied cursor watermark to feed back as `after` on
    /// the next call. Larger than `after` whenever the registry scanned
    /// events that were hidden by a server-side `types` filter — the
    /// caller advances past the filtered range without re-scanning.
    pub next_after: i64,
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
    /// Claim generation this attempt executes under, or `None` for a
    /// push-mode inbound job / an old registry (issue #1252).
    pub claim_epoch: Option<i64>,
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
            claim_epoch: ctx.claim_epoch,
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
// await_job_cancel
// =============================================================================

/// Await the cancel token registered for `jobId` in the process-wide
/// cancel registry. Resolves when the token fires (i.e.
/// [`cancel_active_job_napi`] was called for this `jobId`), or
/// immediately if no token is currently registered (already terminal /
/// never claimed) — callers don't hang on stale jobs.
///
/// Used by the TS proxy to wire outbound `AbortController`s to the
/// active job's cancel token: when the registry's
/// `POST /jobs/{job_id}/cancel` route fires the token, the proxy aborts
/// in-flight outbound `fetch()` requests so cancel propagates to
/// downstream calls instead of stalling on socket reads. Without this,
/// the producer-side cancel only flips `JobController.is_terminal()`
/// after the outer await returns — outbound HTTP work the handler
/// kicked off keeps running in the background.
///
/// napi-rs maps `pub async fn -> ()` to `Promise<void>` on the JS side.
///
/// Resolves on EITHER explicit cancel OR the registry's natural-end
/// signal. Without the latter, futures awaiting a job that finishes
/// without an explicit cancel would hang forever (the snapshot Arc
/// keeps the cancel token alive past `unregister_active_job`), leaking
/// one Rust task + one JS Promise per outbound call. With the `ended`
/// signal, awaiters wake when the registry tears down the entry.
#[napi(js_name = "awaitJobCancel")]
pub async fn await_job_cancel_napi(job_id: String) {
    // Snapshot both tokens under the registry lock once. If the job is
    // not registered (already terminal / never claimed), resolve
    // immediately so callers don't hang on stale jobs.
    let Some((cancel, ended)) = cancel_registry::get_state(&job_id) else {
        return;
    };
    tokio::select! {
        _ = cancel.cancelled() => {},
        _ = ended.cancelled() => {},
    }
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
/// Validate `deadline_secs` for [`with_job_async_napi`]. Returns the
/// [`napi::Error`] message that would be propagated to JS, or `None`
/// when the input is acceptable. Extracted from `with_job_async_napi`
/// so it can be unit-tested without the napi `Promise<T>` boundary.
fn validate_deadline_secs(deadline_secs: Option<f64>, job_id: &str) -> Option<String> {
    match deadline_secs {
        Some(secs) if !secs.is_finite() || secs < 0.0 => Some(format!(
            "withJobAsync: invalid deadline_secs ({}) for job {} — must be a non-negative finite number or null",
            secs, job_id,
        )),
        _ => None,
    }
}

#[napi(js_name = "withJobAsync")]
pub async fn with_job_async_napi(
    job_id: String,
    deadline_secs: Option<f64>,
    body: Promise<serde_json::Value>,
    claim_epoch: Option<i64>,
) -> Result<serde_json::Value> {
    // Reject negative / NaN / Inf deadlines explicitly: silently aliasing
    // them to "no deadline" (the previous behaviour) papers over upstream
    // bugs where a caller arithmetic'd a negative remaining-time or
    // produced NaN through a buggy clock computation.
    if let Some(msg) = validate_deadline_secs(deadline_secs, &job_id) {
        return Err(Error::from_reason(msg));
    }
    let ctx = match deadline_secs {
        Some(secs) if secs > 0.0 => {
            // `validate_deadline_secs` already rejects NaN / Inf / negative,
            // but a finite-but-huge `secs` (e.g. `f64::MAX`) would still
            // panic in `Duration::from_secs_f64`. Use the fallible variant
            // and surface a clean napi error instead.
            let dur = Duration::try_from_secs_f64(secs).map_err(|e| {
                Error::from_reason(format!(
                    "withJobAsync: deadline_secs ({}) out of range for job {} — {}",
                    secs, job_id, e
                ))
            })?;
            JobContext::with_timeout(job_id, dur)
        }
        _ => JobContext::new(job_id),
    };
    // Carry the claim generation so `currentJob()` exposes it (issue #1252).
    let ctx = ctx.with_claim_epoch(claim_epoch);
    run_as_job(ctx, async move { body.await }).await
}

#[cfg(test)]
mod tests {
    use super::{parse_timeout_secs, validate_deadline_secs};

    #[test]
    fn parse_timeout_secs_accepts_none_and_valid() {
        assert_eq!(parse_timeout_secs(None).unwrap(), None);
        assert_eq!(
            parse_timeout_secs(Some(0.0)).unwrap(),
            Some(std::time::Duration::from_secs(0))
        );
        assert_eq!(
            parse_timeout_secs(Some(1.5)).unwrap(),
            Some(std::time::Duration::from_millis(1500))
        );
    }

    #[test]
    fn parse_timeout_secs_rejects_nan_inf_negative() {
        assert!(parse_timeout_secs(Some(f64::NAN)).is_err());
        assert!(parse_timeout_secs(Some(f64::INFINITY)).is_err());
        assert!(parse_timeout_secs(Some(f64::NEG_INFINITY)).is_err());
        assert!(parse_timeout_secs(Some(-1.0)).is_err());
    }

    #[test]
    fn parse_timeout_secs_rejects_overflow_finite() {
        // `f64::MAX` is finite but vastly exceeds `Duration`'s range
        // (`u64::MAX` seconds). The pre-fix `Duration::from_secs_f64`
        // would panic here; the fix uses `try_from_secs_f64` and surfaces
        // a clean napi error instead. Regression test for the panic path.
        let err = parse_timeout_secs(Some(f64::MAX)).expect_err("should reject overflow");
        let msg = err.reason.as_str();
        assert!(
            msg.contains("out of range"),
            "expected 'out of range' in error, got: {msg}"
        );
    }


    #[test]
    fn validate_deadline_secs_accepts_none_and_zero_and_positive() {
        assert!(validate_deadline_secs(None, "j-1").is_none());
        assert!(validate_deadline_secs(Some(0.0), "j-1").is_none());
        assert!(validate_deadline_secs(Some(1.5), "j-1").is_none());
        assert!(validate_deadline_secs(Some(60.0), "j-1").is_none());
    }

    #[test]
    fn validate_deadline_secs_rejects_negative() {
        let msg = validate_deadline_secs(Some(-0.001), "j-neg").expect("should reject");
        assert!(msg.contains("invalid deadline_secs"));
        assert!(msg.contains("j-neg"));
        assert!(msg.contains("-0.001"));

        let msg = validate_deadline_secs(Some(-30.0), "abc").expect("should reject");
        assert!(msg.contains("-30"));
        assert!(msg.contains("abc"));
    }

    #[test]
    fn validate_deadline_secs_rejects_nan_and_inf() {
        assert!(validate_deadline_secs(Some(f64::NAN), "j-nan").is_some());
        assert!(validate_deadline_secs(Some(f64::INFINITY), "j-inf").is_some());
        assert!(validate_deadline_secs(Some(f64::NEG_INFINITY), "j-ninf").is_some());
    }
}
