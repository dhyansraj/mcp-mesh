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
    Job, JobStatus, RegistryHttpBackend, TaskBackend,
};

// =============================================================================
// Helpers
// =============================================================================

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
        other => PyRuntimeError::new_err(other.to_string()),
    }
}

/// Convert a [`Job`] to a Python `dict`. Mirrors the Go registry's `Job`
/// schema field-for-field so application code can index by the same keys it
/// would see on the wire.
fn job_to_pydict<'py>(py: Python<'py>, job: Job) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", job.id)?;
    dict.set_item("capability", job.capability)?;
    dict.set_item("owner_instance_id", job.owner_instance_id)?;
    dict.set_item("status", job_status_to_str(job.status))?;
    dict.set_item("progress", job.progress)?;
    dict.set_item("progress_message", job.progress_message)?;
    dict.set_item("result", json_value_to_py(py, job.result.unwrap_or(serde_json::Value::Null))?)?;
    dict.set_item("error", job.error)?;
    dict.set_item(
        "submitted_payload",
        json_value_to_py(py, job.submitted_payload)?,
    )?;
    dict.set_item("attempt_count", job.attempt_count)?;
    dict.set_item("max_retries", job.max_retries)?;
    dict.set_item("max_duration", job.max_duration)?;
    dict.set_item("total_deadline", job.total_deadline)?;
    dict.set_item("lease_expires_at", job.lease_expires_at)?;
    dict.set_item("last_heartbeat_at", job.last_heartbeat_at)?;
    dict.set_item("submitted_at", job.submitted_at)?;
    dict.set_item("submitted_by", job.submitted_by)?;
    Ok(dict)
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

/// Convert a `serde_json::Value` to a `Py<PyAny>`. Same shape as
/// `lib.rs::json_value_to_pyobject` — duplicated here to avoid threading the
/// helper across module boundaries.
fn json_value_to_py(py: Python<'_>, val: serde_json::Value) -> PyResult<Py<PyAny>> {
    match val {
        serde_json::Value::Null => Ok(py.None()),
        serde_json::Value::Bool(b) => {
            let obj: Py<PyAny> = b.into_pyobject(py)?.to_owned().into_any().unbind();
            Ok(obj)
        }
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_pyobject(py)?.into_any().unbind())
            } else if let Some(u) = n.as_u64() {
                Ok(u.into_pyobject(py)?.into_any().unbind())
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_pyobject(py)?.into_any().unbind())
            } else {
                Ok(py.None())
            }
        }
        serde_json::Value::String(s) => Ok(s.into_pyobject(py)?.into_any().unbind()),
        serde_json::Value::Array(arr) => {
            let items: Vec<Py<PyAny>> = arr
                .into_iter()
                .map(|v| json_value_to_py(py, v))
                .collect::<PyResult<_>>()?;
            Ok(PyList::new(py, &items)?.into_any().unbind())
        }
        serde_json::Value::Object(map) => {
            let dict = PyDict::new(py);
            for (k, v) in map {
                dict.set_item(k, json_value_to_py(py, v)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
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
    #[pyo3(signature = (job_id, instance_id, registry_url))]
    fn new(job_id: String, instance_id: String, registry_url: &str) -> PyResult<Self> {
        let backend = backend_from_url(registry_url)?;
        let queue = new_coalescing_queue();
        let inner = JobController::new(
            job_id,
            instance_id.clone(),
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
            Python::with_gil(|py| {
                let dict = job_to_pydict(py, job)?;
                Ok(dict.into_any().unbind())
            })
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
        let timeout = timeout_secs.map(Duration::from_secs_f64);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let value = inner.wait(timeout).await.map_err(job_error_to_py)?;
            Python::with_gil(|py| Ok(json_value_to_py(py, value)?))
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
#[pyo3(signature = (job_id, deadline_secs, awaitable))]
pub fn with_job_async_py<'py>(
    py: Python<'py>,
    job_id: String,
    deadline_secs: Option<f64>,
    awaitable: Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    // Convert the Python awaitable to a Rust future BEFORE entering the
    // returned future — `into_future` needs Python and the awaitable in
    // hand right now, not later.
    let fut = pyo3_async_runtimes::tokio::into_future(awaitable)?;

    // Build the JobContext on the Rust side (the deadline is set relative
    // to "now" on the Tokio runtime, which matches the semantics of the
    // SDK reading `X-Mesh-Timeout: <secs>` from the inbound request).
    let ctx = match deadline_secs {
        Some(secs) if secs > 0.0 => {
            JobContext::with_timeout(job_id, Duration::from_secs_f64(secs))
        }
        _ => JobContext::new(job_id),
    };

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        // run_as_job binds both the task-local context AND registers the
        // cancel token in the process-wide registry, with a panic-safe
        // drop guard for cleanup.
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
/// {"job_id": str, "deadline_secs_remaining": Optional[int]}
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
            Ok(Some(dict.unbind()))
        }
    }
}
