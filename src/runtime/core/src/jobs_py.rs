//! PyO3 bindings for the MeshJob substrate (Phase 1 — Python SDK).
//!
//! Exposes the producer-side [`crate::jobs::JobController`] and consumer-side
//! [`crate::jobs::JobProxy`] to Python, plus the [`crate::jobs::submit_job`]
//! entry point and a snapshot accessor for the active [`crate::job_context`].
//!
//! The Python SDK wraps these in a Pythonic surface (`mesh.MeshJob`,
//! `@mesh.tool(task=True)`); raw bindings here intentionally stay thin so
//! the Rust core remains the source of truth for state-machine semantics.
//!
//! # Async pattern
//! Every blocking-from-Python method bridges through
//! `pyo3_async_runtimes::tokio::future_into_py` (matches
//! [`crate::handle::AgentHandle::next_event`]), so callers `await` the
//! returned coroutine on Python's asyncio event loop.

#![cfg(feature = "python")]

use std::sync::Arc;
use std::time::Duration;

use pyo3::exceptions::{PyRuntimeError, PyTimeoutError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

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

/// Validate and convert a Python-supplied `timeout_secs` (`Option<f64>`) into
/// an `Option<Duration>`. `Duration::from_secs_f64` panics on negative, NaN,
/// infinite, or out-of-range inputs; this helper traps those at the Python
/// boundary and surfaces a clean `ValueError` instead so the runtime can't
/// be crashed by a typo'd timeout literal in user code. Uses the fallible
/// `try_from_secs_f64` for the final conversion so even finite-but-huge
/// values (e.g. `sys.float_info.max`) reject cleanly instead of panicking.
fn parse_timeout_secs(secs: Option<f64>) -> PyResult<Option<Duration>> {
    match secs {
        None => Ok(None),
        Some(s) => crate::task_backend::validate_secs_to_duration(s, false)
            .map_err(PyValueError::new_err),
    }
}

/// Build an `Arc<dyn TaskBackend>` from a registry URL. Returns a Python
/// exception on transport-construction failure (mirrors the pattern in
/// `lib.rs::call_tool_py`).
fn backend_from_url(registry_url: &str) -> PyResult<Arc<dyn TaskBackend>> {
    let backend = RegistryHttpBackend::new(registry_url)
        .map_err(|e| PyRuntimeError::new_err(format!("backend init failed: {}", e)))?;
    Ok(backend.into_arc())
}

/// Convert a [`JobError`] into the closest matching Python exception so
/// callers can `try/except` cleanly without inspecting strings.
fn job_error_to_py(err: JobError) -> PyErr {
    match err {
        JobError::Timeout(d) => PyTimeoutError::new_err(format!(
            "wait timed out after {:?}",
            d
        )),
        JobError::Cancelled => PyRuntimeError::new_err("job cancelled by enclosing context"),
        // `JobTerminal` is a distinct Rust variant but currently surfaces
        // as a generic RuntimeError on the Python side. When the Python
        // SDK adopts a dedicated `JobTerminalError` exception (Phase C)
        // we can swap this for `JobTerminalError::new_err(...)` without
        // touching the Rust core.
        JobError::JobTerminal(msg) => PyRuntimeError::new_err(format!("job is terminal: {}", msg)),
        other => PyRuntimeError::new_err(other.to_string()),
    }
}

/// Convert a [`Job`] to a Python `dict`. Mirrors the Go registry's `Job`
/// schema field-for-field so application code can index by the same keys it
/// would see on the wire.
fn job_to_pydict(py: Python<'_>, job: Job) -> PyResult<Py<PyAny>> {
    let value = serde_json::to_value(&job)
        .map_err(|e| PyValueError::new_err(format!("failed to serialize Job: {e}")))?;
    crate::json_value_to_pyobject(py, &value)
}

/// Convert a Python object (dict / list / primitive) to a
/// `serde_json::Value`. The runtime accepts whatever JSON-shaped Python
/// values application code chooses to pass; we serialize via Python's
/// stdlib `json.dumps` to keep the surface tiny and avoid reimplementing
/// container traversal here.
fn pyany_to_json(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<serde_json::Value> {
    let json_mod = py.import("json")?;
    let dumps = json_mod.getattr("dumps")?;
    let s: String = dumps.call1((obj,))?.extract()?;
    serde_json::from_str(&s)
        .map_err(|e| PyValueError::new_err(format!("invalid JSON-shaped value: {}", e)))
}

/// Convert a [`JobEvent`] to a Python `dict`. Field-for-field mirror of
/// the OpenAPI `JobEvent` schema so application code can index by the
/// same keys it would see on the wire.
fn job_event_to_pydict(py: Python<'_>, ev: JobEvent) -> PyResult<Py<PyAny>> {
    let value = serde_json::to_value(&ev)
        .map_err(|e| PyValueError::new_err(format!("failed to serialize JobEvent: {e}")))?;
    crate::json_value_to_pyobject(py, &value)
}

/// Convert a [`JobEventReceipt`] to a Python `dict`. Mirrors the
/// `JobEventPostResponse` schema field-for-field.
fn job_event_receipt_to_pydict(py: Python<'_>, receipt: JobEventReceipt) -> PyResult<Py<PyAny>> {
    let value = serde_json::to_value(&receipt)
        .map_err(|e| PyValueError::new_err(format!("failed to serialize JobEventReceipt: {e}")))?;
    crate::json_value_to_pyobject(py, &value)
}

// =============================================================================
// PyJobController (producer-side)
// =============================================================================

/// Producer-side handle bound to a single job. Application code typically
/// receives one via `MeshJob` DDDI injection (next dispatch wires the
/// inbound binding); the constructor is also exposed for tests and for the
/// claim worker dispatch path.
///
/// Each controller owns a per-instance coalescing queue plus a background
/// batching tick that flushes mid-flight progress deltas to the registry on
/// a fixed cadence (default 2s — see [`BatchingConfig::default`]). The tick
/// is shut down when the controller is dropped (Python GC), with a final
/// flush on the way out so no pending delta is lost.
///
/// Terminal calls (`complete` / `fail`) still flush immediately via
/// [`JobController::flush_terminal`]; the tick only matters for the
/// progress-update path between submission and completion.
///
/// Per-controller (rather than per-agent shared) tick is intentional for
/// the Python integration: PyO3 binding constraints make per-call
/// construction the path of least resistance, and one extra 2-second timer
/// per active job is negligible. The shared-queue model documented in the
/// design doc remains the long-term target — see TODO in
/// `MESHJOB_DESIGN.org`.
#[pyclass(name = "JobController", module = "mcp_mesh_core")]
pub struct PyJobController {
    inner: JobController,
    /// Background batching tick handle; held so it lives as long as this
    /// controller. Dropped (= cancelled with final flush) when the
    /// controller is collected. Optional because we degrade gracefully if
    /// the tick can't be spawned (e.g. no Tokio runtime available at
    /// construction time — terminal flushes still work).
    _batching: Option<BatchingHandle>,
}

#[pymethods]
impl PyJobController {
    /// Construct a controller bound to `(job_id, instance_id)` against the
    /// given `registry_url`. Spawns a per-controller background batching
    /// tick so mid-flight `update_progress` calls reach the registry on the
    /// configured cadence (default 2s); the tick is torn down with a final
    /// flush when the controller is dropped.
    #[new]
    #[pyo3(signature = (job_id, instance_id, registry_url, claim_epoch=None))]
    fn new(
        job_id: String,
        instance_id: String,
        registry_url: &str,
        claim_epoch: Option<i64>,
    ) -> PyResult<Self> {
        let backend = backend_from_url(registry_url)?;
        let queue = new_coalescing_queue();
        // `claim_epoch=None` (push-mode inbound job, or an old registry that
        // predates epochs) ⇒ legacy owner-only behavior. On the claim path
        // the SDK passes the epoch from the `/jobs/claim` response so this
        // execution is fenced (issue #1252).
        let inner = JobController::new_with_epoch(
            job_id,
            instance_id.clone(),
            claim_epoch,
            backend.clone(),
            queue.clone(),
        );
        // Spawn the batching tick on the shared PyO3 Tokio runtime so
        // mid-flight progress deltas actually reach the registry. We
        // enter the runtime context so the `tokio::spawn` inside
        // `spawn_batching_tick` finds a runtime; this is the same handle
        // every other PyO3 async helper in this crate uses.
        let runtime = pyo3_async_runtimes::tokio::get_runtime();
        let _guard = runtime.enter();
        let batching = spawn_batching_tick(
            queue,
            backend,
            instance_id,
            BatchingConfig::default(),
        );
        Ok(Self {
            inner,
            _batching: Some(batching),
        })
    }

    /// The job ID this controller is bound to.
    #[getter]
    fn job_id(&self) -> String {
        self.inner.job_id().to_string()
    }

    /// The claim generation this controller executes under, or ``None`` for
    /// a push-mode inbound job / an old registry. Additive read accessor
    /// (issue #1252) so handlers can stamp side effects for dedupe.
    #[getter]
    fn claim_epoch(&self) -> Option<i64> {
        self.inner.claim_epoch()
    }

    /// Enqueue a progress update. Coalesces with any prior pending progress
    /// for this job — only the latest survives the next batch flush.
    #[pyo3(signature = (progress, message=None))]
    fn update_progress<'py>(
        &self,
        py: Python<'py>,
        progress: f32,
        message: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.update_progress(progress, message).await;
            Ok(())
        })
    }

    /// Mark the job complete with the given result. Flushes immediately.
    /// `result` must be a JSON-serialisable Python value (dict / list /
    /// primitive) — mirrors MCP's "results are JSON" contract.
    fn complete<'py>(
        &self,
        py: Python<'py>,
        result: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value = pyany_to_json(py, &result)?;
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.complete(value).await.map_err(job_error_to_py)?;
            Ok(())
        })
    }

    /// Mark the job failed with the given error reason. Flushes immediately.
    fn fail<'py>(&self, py: Python<'py>, error: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.fail(error).await.map_err(job_error_to_py)?;
            Ok(())
        })
    }

    /// Voluntarily release the lease so a peer replica can re-claim and
    /// retry. Used when a handler raised a ``retry_on``-matched exception
    /// (issue #879): instead of marking the row terminal=failed, the SDK
    /// calls ``release_lease`` so the registry resets ``owner_instance_id``
    /// and a peer replica picks up the row within ~5s via the
    /// HEAD-heartbeat path. Note: release does NOT increment
    /// ``attempt_count`` — the claim that picked the row up already
    /// counted this attempt; the next claim will count the next attempt.
    ///
    /// Returns ``None`` (not the response object) — the SDK only needs to
    /// know that the call succeeded; the per-attempt state is the registry's
    /// concern. Status stays ``working`` when there's retry budget left,
    /// or transitions to ``failed`` (terminal, with
    /// ``error="exhausted (release): <reason>"``) when the row's existing
    /// ``attempt_count`` is already past ``max_retries`` — i.e. the
    /// handler raised on the row's final allowed attempt. The consumer's
    /// wait loop sees the exhaustion via the next poll.
    #[pyo3(signature = (reason=None))]
    fn release_lease<'py>(
        &self,
        py: Python<'py>,
        reason: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.release_lease(reason).await.map_err(job_error_to_py)?;
            Ok(())
        })
    }

    /// Transition the job to ``input_required``, signalling the consumer
    /// that the handler is blocked awaiting an external answer. STATUS-ONLY
    /// primitive: it posts the ``input_required`` delta (with ``prompt``
    /// carried on the existing ``progress_message`` field) and returns once
    /// posted — it does NOT await the answer. Compose it with the existing
    /// event primitives for a full request-and-await: call
    /// ``await job.request_input(prompt)``, then park on
    /// ``await job.recv_event(types=["answer"])``; an external party answers
    /// via ``proxy.send_event("answer", ...)``; the handler resumes and
    /// ``await job.complete(...)``s.
    ///
    /// Flushes IMMEDIATELY (not via the coalescing batch tick) because the
    /// consumer is blocked on this control-plane transition. NON-terminal:
    /// the handler keeps running and may still call ``update_progress`` /
    /// ``complete`` / ``fail`` afterwards. ``complete`` / ``fail`` exit
    /// ``input_required`` (the registry confirms the transition).
    ///
    /// Signature: ``request_input(prompt: Optional[str] = None) -> None``
    #[pyo3(signature = (prompt=None))]
    fn request_input<'py>(
        &self,
        py: Python<'py>,
        prompt: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.request_input(prompt).await.map_err(job_error_to_py)?;
            Ok(())
        })
    }

    /// Whether ``complete`` / ``fail`` has already been called on this
    /// controller. The Python dispatch wrapper uses this to decide
    /// whether a returning user function needs an auto-``complete`` —
    /// users who explicitly called ``await job.complete(...)`` already
    /// closed out the row, so the wrapper must NOT double-flush.
    fn is_terminal<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Ok(inner.is_terminal().await)
        })
    }

    /// Wait for the next event posted into this job's event log.
    ///
    /// Mirrors [`JobController::recv_event`]. Returns the event as a
    /// Python ``dict`` on arrival, ``None`` on timeout. Cursor is
    /// per-controller-instance (shared across ``clone``s); a fresh
    /// controller for the same ``job_id`` replays from seq=0.
    ///
    /// Signature: ``recv_event(types: Optional[List[str]] = None, timeout_secs: Optional[float] = None) -> Optional[dict]``
    #[pyo3(signature = (types=None, timeout_secs=None))]
    fn recv_event<'py>(
        &self,
        py: Python<'py>,
        types: Option<Vec<String>>,
        timeout_secs: Option<f64>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let timeout = parse_timeout_secs(timeout_secs)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = inner.recv_event(types, timeout).await.map_err(job_error_to_py)?;
            Python::with_gil(|py| match result {
                None => Ok::<Py<PyAny>, PyErr>(py.None()),
                Some(ev) => job_event_to_pydict(py, ev),
            })
        })
    }

    fn __repr__(&self) -> String {
        format!("JobController(job_id={:?})", self.inner.job_id())
    }
}

// =============================================================================
// PyJobProxy (consumer-side)
// =============================================================================

/// Consumer-side handle: returned by [`submit_job_py`] and exposes
/// `wait` / `status` / `cancel` for code that wants to await a remote job.
#[pyclass(name = "JobProxy", module = "mcp_mesh_core")]
pub struct PyJobProxy {
    inner: JobProxy,
}

#[pymethods]
impl PyJobProxy {
    /// Construct a proxy bound to a known `job_id` + `registry_url`. Normally
    /// callers obtain a proxy via [`submit_job_py`] / DDDI injection rather
    /// than constructing one directly.
    #[new]
    fn new(job_id: String, registry_url: &str) -> PyResult<Self> {
        let backend = backend_from_url(registry_url)?;
        Ok(Self {
            inner: JobProxy::new(job_id, backend),
        })
    }

    /// The job id this proxy is bound to.
    #[getter]
    fn job_id(&self) -> String {
        self.inner.job_id().to_string()
    }

    /// Read the latest job state from the registry (single GET).
    fn status<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let job = inner.status().await.map_err(job_error_to_py)?;
            Python::with_gil(|py| job_to_pydict(py, job))
        })
    }

    /// Poll until the job reaches a terminal state. Returns the result
    /// payload as a Python value (dict / list / primitive) on success;
    /// raises `TimeoutError` on `timeout_secs`, `RuntimeError` on
    /// non-success terminal or cancellation.
    #[pyo3(signature = (timeout_secs=None))]
    fn wait<'py>(
        &self,
        py: Python<'py>,
        timeout_secs: Option<f64>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let timeout = parse_timeout_secs(timeout_secs)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let value = inner.wait(timeout).await.map_err(job_error_to_py)?;
            Python::with_gil(|py| crate::json_value_to_pyobject(py, &value))
        })
    }

    /// Request cancellation. The registry forwards the signal to the owner
    /// replica when alive. Returns once the registry has acknowledged.
    #[pyo3(signature = (reason=None))]
    fn cancel<'py>(
        &self,
        py: Python<'py>,
        reason: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            inner.cancel(reason).await.map_err(job_error_to_py)?;
            Ok(())
        })
    }

    /// Post an event into this job's event log. The running handler will
    /// see it on its next ``recv_event`` call (or wake from a long-poll).
    ///
    /// ``payload`` may be any JSON-shaped Python value (``dict``/``list``/
    /// primitive). The receipt dict carries ``job_id`` / ``seq`` /
    /// ``created_at`` so callers can stitch a follow-up ``recv_event``
    /// to it via ``after``.
    ///
    /// Signature: ``send_event(event_type: str, payload: Any) -> dict``
    fn send_event<'py>(
        &self,
        py: Python<'py>,
        event_type: String,
        payload: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let payload_json = pyany_to_json(py, &payload)?;
        let inner = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let receipt = inner
                .send_event(event_type, payload_json)
                .await
                .map_err(job_error_to_py)?;
            Python::with_gil(|py| job_event_receipt_to_pydict(py, receipt))
        })
    }

    /// Fetch a single batch of events from this job's event log with
    /// ``seq > after``, optionally filtered by ``types``. The Python SDK's
    /// ``mesh.jobs.subscribe_events`` async iterator is built on top of
    /// this primitive — callers manage their own cursor between calls.
    ///
    /// ``timeout_secs``: long-poll budget. ``None`` ≡ single immediate
    /// read; ``Some(secs)`` long-polls up to that many seconds (capped
    /// at 60s by the registry). An empty result means "no events arrived
    /// within the wait window" — the caller continues with the same
    /// cursor.
    ///
    /// Returns a ``(events, next_after)`` tuple: ``events`` is the list
    /// of event dicts (same shape as ``recv_event``'s single-event dict);
    /// ``next_after`` is the registry-supplied watermark that the caller
    /// should feed back as ``after`` on the next call so empty pages
    /// caused by server-side ``types`` filtering still advance the cursor.
    ///
    /// Signature: ``list_events(after: int = 0, types: Optional[List[str]] = None, timeout_secs: Optional[float] = None) -> Tuple[List[dict], int]``
    #[pyo3(signature = (after=0, types=None, timeout_secs=None))]
    fn list_events<'py>(
        &self,
        py: Python<'py>,
        after: i64,
        types: Option<Vec<String>>,
        timeout_secs: Option<f64>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        let wait = parse_timeout_secs(timeout_secs)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let (events, next_after) = inner
                .list_events(after, types, wait)
                .await
                .map_err(job_error_to_py)?;
            Python::with_gil(|py| {
                let list = PyList::empty(py);
                for ev in events {
                    list.append(job_event_to_pydict(py, ev)?)?;
                }
                let tuple = (list, next_after).into_pyobject(py)?;
                Ok::<Py<PyAny>, PyErr>(tuple.into_any().unbind())
            })
        })
    }

    fn __repr__(&self) -> String {
        format!("JobProxy(job_id={:?})", self.inner.job_id())
    }
}

// =============================================================================
// submit_job + current_job entry points
// =============================================================================

/// Submit a new job via the registry and return a [`PyJobProxy`].
///
/// Mirrors [`crate::jobs::SubmitJobArgs`] field-for-field. `payload` is any
/// JSON-shaped Python value.
#[pyfunction(name = "submit_job")]
#[pyo3(signature = (
    registry_url,
    capability,
    payload,
    submitted_by,
    owner_instance_id=None,
    max_duration=None,
    max_retries=None,
    total_deadline=None,
))]
#[allow(clippy::too_many_arguments)]
pub fn submit_job_py<'py>(
    py: Python<'py>,
    registry_url: &str,
    capability: String,
    payload: Bound<'py, PyAny>,
    submitted_by: String,
    owner_instance_id: Option<String>,
    max_duration: Option<u32>,
    max_retries: Option<u32>,
    total_deadline: Option<i64>,
) -> PyResult<Bound<'py, PyAny>> {
    let backend = backend_from_url(registry_url)?;
    let payload_json = pyany_to_json(py, &payload)?;
    let args = SubmitJobArgs {
        capability,
        payload: payload_json,
        submitted_by,
        owner_instance_id,
        max_duration,
        max_retries,
        total_deadline,
    };
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let (proxy, _resp) = submit_job(backend, args).await.map_err(job_error_to_py)?;
        Ok(PyJobProxy { inner: proxy })
    })
}

/// Fire the cancel token registered for `job_id` in the process-wide
/// cancel registry, if any. Returns `True` iff a token was found and
/// fired (matches [`crate::cancel_registry::cancel_active_job`] semantics).
///
/// Used by the SDK-owned `POST /jobs/{job_id}/cancel` HTTP route — when
/// the registry forwards a cancel to this replica, the route handler
/// calls this to abort the in-flight job.
#[pyfunction(name = "cancel_active_job")]
pub fn cancel_active_job_py(job_id: &str) -> bool {
    cancel_registry::cancel_active_job(job_id)
}

/// Await the cancel token bound for `job_id` in the process-wide
/// cancel registry. Resolves when EITHER the token fires (explicit
/// cancel via [`cancel_active_job_py`]) OR the registry unregisters
/// the job naturally (ended without cancel — see
/// [`crate::cancel_registry::JobCancelState::ended`]). Resolves
/// immediately if the job is not currently registered (already
/// terminal / never claimed).
///
/// Used by the SDK's job_dispatch wrapper to race the user's
/// coroutine against cancel-token-fire — when cancel arrives, the
/// dispatch wrapper cancels the user's asyncio task so
/// `await asyncio.sleep` and similar propagate CancelledError
/// naturally. Mirror of the TypeScript SDK's `awaitJobCancel(jobId)`
/// napi and the C ABI `mesh_await_job_cancel`.
///
/// Returns a Python coroutine; callers `await` it on asyncio.
#[pyfunction(name = "await_job_cancel")]
pub fn await_job_cancel_py<'py>(
    py: Python<'py>,
    job_id: String,
) -> PyResult<Bound<'py, PyAny>> {
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        // Snapshot both tokens once. None means "not registered" —
        // resolve immediately so callers don't hang on stale jobs.
        let Some((cancel, ended)) = cancel_registry::get_state(&job_id) else {
            return Ok(());
        };
        tokio::select! {
            _ = cancel.cancelled() => {},
            _ = ended.cancelled() => {},
        }
        Ok::<(), pyo3::PyErr>(())
    })
}

/// Run an awaitable Python callable inside a fresh
/// [`crate::jobs::run_as_job`] scope so the cancel-registry entry under
/// `job_id` is bound for the duration of the call (so the
/// `POST /jobs/{id}/cancel` HTTP route can fire the in-flight cancel
/// token).
///
/// **Caveat — Rust task-local visibility from Python:** the Rust
/// `tokio::task_local!` bound by `with_job` is only visible to Rust
/// futures polled within the scope; Python coroutines awaited via
/// `pyo3_async_runtimes` run on the asyncio event loop, so a
/// `current_job()` call from inside the awaited Python coroutine returns
/// `None`. The SDK's inbound wrapper compensates by setting the Python
/// `CURRENT_JOB` contextvar in parallel — that one IS visible to user
/// code and to Python-originated outbound calls (which inject job
/// headers via `_mcp_mesh.engine.unified_mcp_proxy`). Rust-originated
/// outbound calls (e.g., LLM provider tool calls) STILL get
/// `X-Mesh-Job-Id` / `X-Mesh-Timeout` injected because the cancel-token
/// dance and any synchronous Rust work below this scope sees the
/// task-local.
///
/// This is the FFI helper the inbound tool wrapper (per-language SDK)
/// uses when an `X-Mesh-Job-Id` arrives on a `tools/call`.
///
/// Arguments:
///   * `job_id` — server-assigned job UUID this call is bound to.
///   * `deadline_secs` — optional per-attempt deadline (relative). `None`
///     means no deadline (unlimited per design-doc default).
///   * `awaitable` — Python coroutine. Awaited inside the
///     `run_as_job` scope; its result (or raised exception) becomes the
///     return value of the returned coroutine.
///
/// Returns a Python coroutine; callers `await` it on asyncio.
#[pyfunction(name = "with_job_async")]
#[pyo3(signature = (job_id, deadline_secs, awaitable, claim_epoch=None))]
pub fn with_job_async_py<'py>(
    py: Python<'py>,
    job_id: String,
    deadline_secs: Option<f64>,
    awaitable: Bound<'py, PyAny>,
    claim_epoch: Option<i64>,
) -> PyResult<Bound<'py, PyAny>> {
    // Build the JobContext on the Rust side (the deadline is set relative
    // to "now" on the Tokio runtime, which matches the semantics of the
    // SDK reading `X-Mesh-Timeout: <secs>` from the inbound request).
    let ctx = match deadline_secs {
        Some(secs) if secs.is_nan() || secs.is_infinite() => {
            return Err(PyValueError::new_err(format!(
                "with_job_async: deadline_secs ({}) must be a finite number or None",
                secs
            )));
        }
        Some(secs) if secs > 0.0 => {
            // Finite-but-huge `secs` (e.g. `sys.float_info.max`) would
            // panic in `Duration::from_secs_f64`. Use the fallible variant
            // and surface a clean `ValueError` instead.
            let dur = Duration::try_from_secs_f64(secs).map_err(|e| {
                PyValueError::new_err(format!(
                    "with_job_async: deadline_secs ({}) out of range for job {} — {}",
                    secs, job_id, e
                ))
            })?;
            JobContext::with_timeout(job_id.clone(), dur)
        }
        _ => JobContext::new(job_id.clone()),
    };
    // Carry the claim generation so `current_job()` can expose it (issue
    // #1252). Additive — `None` leaves the surface unchanged.
    let ctx = ctx.with_claim_epoch(claim_epoch);

    // Race fix: register the cancel token in the process-wide registry
    // BEFORE `into_future` schedules the Python coroutine on asyncio. The
    // Python dispatch wrapper (`_run_and_autocomplete`) starts its
    // `await_job_cancel(job_id)` watcher as soon as the coroutine begins
    // running — and `await_job_cancel` resolves immediately if the
    // registry has no entry for `job_id` (documented "stale job" path in
    // `cancel_registry::get_state`). If we registered inside the spawned
    // future (the way `run_as_job` would), the watcher could poll first,
    // see no entry, resolve, and the dispatch wrapper would interpret
    // that as a real cancel and abort the user task immediately. By
    // registering here — synchronously, before any asyncio scheduling
    // happens — the watcher always observes a live entry.
    let generation = cancel_registry::register_active_job_with_epoch(
        &job_id,
        ctx.cancel_token.clone(),
        ctx.claim_epoch,
    );
    // Panic-safe RAII: cleanup runs whether the body completes normally,
    // returns Err, or panics. Mirrors `CancelRegistryGuard` in
    // `jobs.rs::run_as_job`. Carries the registration generation so only
    // THIS registration is torn down (issue #1166 MED-4).
    struct CleanupGuard {
        job_id: String,
        generation: u64,
    }
    impl Drop for CleanupGuard {
        fn drop(&mut self) {
            cancel_registry::unregister_active_job(&self.job_id, self.generation);
        }
    }
    let guard = CleanupGuard {
        job_id: job_id.clone(),
        generation,
    };

    // Convert the Python awaitable to a Rust future. Per pyo3-async-runtimes
    // v0.27, `into_future` immediately `call_soon_threadsafe`-schedules the
    // Python coroutine onto the asyncio event loop, so the registry entry
    // above MUST already exist at this point.
    let fut = match pyo3_async_runtimes::tokio::into_future(awaitable) {
        Ok(f) => f,
        Err(e) => {
            // Drop the guard explicitly so the registry is cleaned up
            // even on the early-error path.
            drop(guard);
            return Err(e);
        }
    };

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        // Move the guard into the async block so cleanup is tied to the
        // future's lifetime (not this synchronous function's stack frame).
        let _guard = guard;
        // `run_as_job` binds the task-local JobContext for Rust-side
        // futures inside the body. It also registers a SECOND cancel-
        // registry frame for the same job_id (a clone of the same
        // `cancel_token`, so cancels propagate through either frame) and
        // installs its own drop guard. The outer registration above is
        // what closes the race window between this function returning and
        // the body being polled.
        //
        // Duplicate-registration note (issue #1166 MED-4): the registry
        // stacks registrations per job_id — the inner `run_as_job` frame
        // sits on top of the outer one; nothing is displaced and no
        // `ended` token is dropped unfired. Each frame's `ended` fires at
        // its own unregister: the inner frame's when `run_as_job`'s guard
        // drops (body finished), the outer frame's microseconds later
        // when the guard above drops. A Python `await_job_cancel(job_id)`
        // watcher that snapshotted EITHER frame therefore wakes on
        // natural end.
        run_as_job(ctx, async move {
            // Awaiting `fut` yields a `PyResult<Py<PyAny>>` — propagate
            // both the success value and any Python exception verbatim.
            fut.await
        })
        .await
    })
}

/// Snapshot of the active job context on the current Tokio task, or `None`
/// if no job is in scope.
///
/// Returns a dict with the same shape the Python SDK exposes via
/// `_mcp_mesh.engine.job_context.JobContextSnapshot`:
///
/// ```python
/// {"job_id": str, "deadline_secs_remaining": Optional[int],
///  "claim_epoch": Optional[int]}
/// ```
///
/// Source of truth is the Rust [`crate::job_context`] (set via
/// `with_job` / `run_as_job` by the inbound HTTP wrapper or claim worker).
#[pyfunction(name = "current_job")]
pub fn current_job_py(py: Python<'_>) -> PyResult<Option<Py<PyDict>>> {
    match job_context::current() {
        None => Ok(None),
        Some(ctx) => {
            let dict = PyDict::new(py);
            let remaining = ctx.remaining_seconds();
            dict.set_item("job_id", ctx.job_id)?;
            dict.set_item("deadline_secs_remaining", remaining)?;
            dict.set_item("claim_epoch", ctx.claim_epoch)?;
            Ok(Some(dict.unbind()))
        }
    }
}

// NOTE: no `#[cfg(test)] mod tests` here. `parse_timeout_secs`'s error
// path constructs a `PyValueError` which requires a linked Python
// interpreter — `pyo3`'s `extension-module` feature (the default here)
// deliberately omits the interpreter symbols at static-link time so the
// resulting `.so` can be loaded as a Python C extension. The parallel
// overflow test for the panic path lives in `jobs_napi.rs::tests`
// (same helper shape, same `try_from_secs_f64` logic).
