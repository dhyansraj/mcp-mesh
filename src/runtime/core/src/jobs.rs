//! Producer-side `JobController` and consumer-side `JobProxy`, plus the
//! batching tick that flushes coalesced deltas to the registry.
//!
//! Phase 1 — see `MESHJOB_DESIGN.org` → "Architecture / Producer-side flow"
//! and "Consumer-side flow". Persistence is in-memory only (the
//! coalescing queue lives in process); no per-agent SQLite cache yet
//! (per design doc note: "per-agent in-process SQLite is premature for
//! v1"). TODO(phase 2/3): SQLite backing for crash-survival across replica
//! restarts.

use std::collections::HashMap;
use std::future::Future;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use thiserror::Error;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio::time::{sleep, Instant};
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use crate::cancel_registry;
use crate::job_context::{self, JobContext};
use crate::task_backend::{
    BackendError, CreateJobRequest, CreateJobResponse, Job, JobDelta, JobEvent,
    JobEventReceipt, JobStatus, ReleaseJobResponse, TaskBackend,
};

// =============================================================================
// Errors
// =============================================================================

/// Errors surfaced by `JobController` / `JobProxy` to application code.
#[derive(Debug, Error)]
pub enum JobError {
    #[error("backend error: {0}")]
    Backend(#[from] BackendError),

    #[error("wait timed out after {0:?}")]
    Timeout(Duration),

    #[error("job cancelled by enclosing context")]
    Cancelled,

    #[error("job ended in non-success terminal state: {status:?} ({error:?})")]
    NonSuccessTerminal {
        status: JobStatus,
        error: Option<String>,
    },

    /// Registry has been unreachable (continuous transient errors) for
    /// longer than `registry_unreachable_max`. The wait loop gives up so
    /// the caller can surface a clean error rather than blocking forever.
    #[error("registry unreachable for {duration:?}")]
    RegistryUnreachable { duration: Duration },

    /// `send_event` was called against a job that has already reached a
    /// terminal state — the registry rejects the post with 409. Distinct
    /// from `Backend(Conflict(_))` so callers can `match` cleanly.
    #[error("cannot post event: job is in a terminal state ({0})")]
    JobTerminal(String),
}

/// Marker error used by [`run_cancellable`].
#[derive(Debug, Error)]
#[error("cancelled")]
pub struct JobCancelled;

// =============================================================================
// CoalescingQueue
// =============================================================================

/// In-memory coalescing queue: progress-only deltas with the same `job_id`
/// collapse to the latest; terminal deltas are kept as-is and replace any
/// pending progress for that job.
///
/// The "no progress after terminal" sentinel does NOT live here: it is a
/// per-[`JobController`] flag (`JobController::terminal`) checked under
/// this queue's mutex. Keeping it per-controller (instead of a
/// process-lived `HashSet<String>` inside the queue) matters on the
/// claim-worker path, where ONE queue is shared across every
/// `JobController` the worker constructs — a queue-resident set would
/// retain one string per completed job for the life of the process
/// (issue #1166 LOW), and would also wrongly block progress from a NEW
/// controller that re-claims a previously completed `job_id`.
///
/// Public so the FFI layer (and language SDKs that wrap the producer-side
/// pipeline directly) can construct one. Fields are private so callers can't
/// poke at internal state; use `enqueue` / `drain` through a `JobController`
/// or the batching tick.
#[derive(Default)]
pub struct CoalescingQueue {
    pending: HashMap<String, JobDelta>,
}

impl CoalescingQueue {
    fn enqueue(&mut self, delta: JobDelta) {
        // Terminal deltas always replace anything pending for that id;
        // progress-only deltas also replace prior pending progress for the
        // same id (coalesce). Same insert behavior either way. The
        // post-terminal drop guard lives in `JobController::update_progress`
        // (checked under this queue's lock).
        self.pending.insert(delta.id.clone(), delta);
    }

    fn drain(&mut self) -> Vec<JobDelta> {
        std::mem::take(&mut self.pending).into_values().collect()
    }

    fn len(&self) -> usize {
        self.pending.len()
    }
}

// =============================================================================
// BatchingTick
// =============================================================================

/// Configuration for the background batching task.
#[derive(Debug, Clone)]
pub struct BatchingConfig {
    /// How often to flush the coalescing queue.
    pub interval: Duration,
}

impl Default for BatchingConfig {
    fn default() -> Self {
        Self {
            interval: Duration::from_secs(2),
        }
    }
}

/// Handle to a running batching task. Drop = stop signaled (graceful).
pub struct BatchingHandle {
    cancel: CancellationToken,
    join: Option<JoinHandle<()>>,
}

impl BatchingHandle {
    /// Signal the batching task to stop; await the join handle.
    pub async fn shutdown(mut self) {
        self.cancel.cancel();
        if let Some(j) = self.join.take() {
            let _ = j.await;
        }
    }
}

impl Drop for BatchingHandle {
    fn drop(&mut self) {
        self.cancel.cancel();
    }
}

/// Spawn the background flush loop. Caller retains the `BatchingHandle` to
/// shut it down on agent stop.
pub fn spawn_batching_tick(
    queue: Arc<Mutex<CoalescingQueue>>,
    backend: Arc<dyn TaskBackend>,
    instance_id: String,
    config: BatchingConfig,
) -> BatchingHandle {
    let cancel = CancellationToken::new();
    let cancel_clone = cancel.clone();
    let join = tokio::spawn(async move {
        info!(
            "Job batching tick started (instance={}, interval={:?})",
            instance_id, config.interval
        );
        loop {
            tokio::select! {
                _ = cancel_clone.cancelled() => {
                    debug!("Job batching tick stopping (cancelled)");
                    // Final flush before shutdown so terminal/progress
                    // deltas don't get dropped on the floor.
                    flush_once(&queue, backend.as_ref(), &instance_id).await;
                    break;
                }
                _ = sleep(config.interval) => {
                    flush_once(&queue, backend.as_ref(), &instance_id).await;
                }
            }
        }
        info!("Job batching tick stopped (instance={})", instance_id);
    });
    BatchingHandle {
        cancel,
        join: Some(join),
    }
}

/// Translate `claim_superseded` batch rejections into a cancel of the
/// EXACT superseded execution's frame — keyed by the epoch the rejected
/// delta was sent under, never the top-of-stack.
///
/// A newer claim (a reclaim + fresh claim, possibly by this same instance)
/// fenced the owner that produced these deltas. `epoch_by_id` maps each
/// sent delta's `job_id` to the `claim_epoch` it carried; the rejected
/// frame is the one registered under that epoch. Firing the top-of-stack
/// instead would abort a healthy same-instance re-claim (H2) while the
/// zombie (H1) kept running (issue #1252 review). A no-op when the job
/// isn't registered under that epoch (already terminal / never wrapped in
/// `run_as_job`). Surfaces to the handler through the SAME cancel path as an
/// explicit user cancel.
fn fire_superseded_cancels(
    rejected: &[crate::task_backend::RejectedDelta],
    epoch_by_id: &HashMap<String, Option<i64>>,
) {
    for r in rejected {
        if r.reason != crate::task_backend::CLAIM_SUPERSEDED_REASON {
            continue;
        }
        match epoch_by_id.get(&r.id).copied().flatten() {
            Some(epoch) => {
                warn!(
                    "Job {} superseded by a newer claim (delta rejected \
                     claim_superseded, epoch={}); firing this execution's \
                     cancel token to abort it",
                    r.id, epoch
                );
                cancel_registry::cancel_superseded(&r.id, epoch);
            }
            None => {
                // A superseded rejection with no epoch on the sent delta
                // should not happen (the registry only supersedes epoch-
                // bearing deltas), but if it does we deliberately do NOT
                // fall back to a top-of-stack cancel — that could kill a
                // healthy re-claim. Log and leave the frame alone.
                warn!(
                    "Job {} rejected claim_superseded but the sent delta \
                     carried no epoch; not firing a cancel (avoids killing a \
                     healthy re-claim)",
                    r.id
                );
            }
        }
    }
}

async fn flush_once(
    queue: &Arc<Mutex<CoalescingQueue>>,
    backend: &dyn TaskBackend,
    instance_id: &str,
) {
    let drained = {
        let mut q = queue.lock().await;
        if q.len() == 0 {
            return;
        }
        q.drain()
    };
    if drained.is_empty() {
        return;
    }
    let count = drained.len();
    // Capture each delta's job_id → claim_epoch BEFORE the deltas move into
    // submit_batch, so a claim_superseded rejection fires the exact frame
    // that produced the delta (by epoch), never the top-of-stack.
    let epoch_by_id: HashMap<String, Option<i64>> = drained
        .iter()
        .map(|d| (d.id.clone(), d.claim_epoch))
        .collect();
    match backend.submit_batch(instance_id, drained).await {
        Ok(resp) => {
            debug!(
                "Flushed batch (sent={}, accepted={}, rejected={})",
                count,
                resp.accepted,
                resp.rejected.len()
            );
            // A superseded owner's progress deltas are rejected here —
            // translate to a cancel so the zombie execution stops.
            fire_superseded_cancels(&resp.rejected, &epoch_by_id);
        }
        Err(e) => {
            warn!("Failed to flush job batch ({}): {}", count, e);
            // Phase 1: dropped deltas on transport failure. Phase 2 will
            // re-enqueue (with bounded retry) once we have idempotency
            // keys to dedupe. Note in design doc: "Phase 1 retry restarts
            // from scratch" — this matches that model.
        }
    }
}

// =============================================================================
// JobController (producer-side)
// =============================================================================

/// Producer-side handle bound to a single job row. Application code calls
/// `update_progress`/`complete`/`fail`. Updates are coalesced and flushed
/// by the background batching tick (or immediately for terminal calls).
///
/// Also exposes [`Self::recv_event`] for handlers running inside a
/// `task=True` job to drain events posted via [`JobProxy::send_event`].
/// The per-controller `last_seen_seq` cursor is shared across `Clone`s of
/// the same instance (via `Arc<AtomicI64>`), so passing the controller
/// into helper tasks doesn't reset the cursor. A NEW controller created
/// for the same `job_id` starts from seq=0 — replay is per-instance.
#[derive(Clone)]
pub struct JobController {
    job_id: String,
    instance_id: String,
    /// Claim generation this controller executes under, as minted by the
    /// registry on the `POST /jobs/claim` that handed this replica the job
    /// (see [`crate::task_backend::ClaimedJob::claim_epoch`]). `None` for a
    /// push-mode inbound job (never claimed) or an old registry that predates
    /// epochs — in that case the controller sends NO identity on reads and
    /// NO epoch on deltas, i.e. byte-identical legacy owner-only behavior.
    /// `Some(e)` fences this execution: deltas carry `e`, executor reads
    /// carry `(instance_id, e)`, and a `claim_superseded` from either fires
    /// the job's cancel token so the superseded handler aborts.
    claim_epoch: Option<i64>,
    backend: Arc<dyn TaskBackend>,
    queue: Arc<Mutex<CoalescingQueue>>,
    /// Set once `complete` / `fail` / `release_lease` has dispatched a
    /// terminal for this controller's job. Shared across `Clone`s of the
    /// same instance. Checked (under the queue mutex) by
    /// `update_progress` so a racing late progress delta can't land in
    /// the queue after the terminal left it — per-controller rather than
    /// queue-resident so the shared claim-worker queue doesn't accumulate
    /// one entry per completed job forever (issue #1166 LOW).
    terminal: Arc<std::sync::atomic::AtomicBool>,
    /// Last event seq returned by `recv_event` on this controller (or any
    /// of its `Clone`s). `0` means no events consumed yet — the next
    /// `recv_event` will return the first event in the job's event log.
    last_seen_seq: Arc<AtomicI64>,
    /// Serialises the entire `recv_event` load→list→store window across
    /// `Clone`s of this controller. Without this, two concurrent callers
    /// on clones can both load the same `last_seen_seq`, both call
    /// `list_job_events`, and both return the SAME head event — the
    /// AtomicI64 prevents memory tearing but not the read-fetch-write
    /// race across the `.await`. The `Arc` keeps clones cheap while
    /// pinning every clone to the same lock instance; lock contention
    /// is naturally bounded to the small number of helper tasks a
    /// single handler typically spawns.
    recv_event_lock: Arc<Mutex<()>>,
}

impl JobController {
    /// Construct a new controller with NO claim epoch (push-mode inbound
    /// job, or version-skew against an old registry). Deltas carry no epoch
    /// and reads are anonymous — legacy owner-only behavior. Normally
    /// created by the tool wrapper; agent code receives one via DDDI
    /// injection. Use [`Self::new_with_epoch`] on the claim path.
    pub fn new(
        job_id: impl Into<String>,
        instance_id: impl Into<String>,
        backend: Arc<dyn TaskBackend>,
        queue: Arc<Mutex<CoalescingQueue>>,
    ) -> Self {
        Self::new_with_epoch(job_id, instance_id, None, backend, queue)
    }

    /// Construct a controller carrying the claim generation minted by the
    /// registry on `POST /jobs/claim`. Pass `Some(epoch)` from
    /// [`crate::task_backend::ClaimedJob::claim_epoch`] on the claim-worker
    /// path so this execution is fenced; `None` degrades to legacy
    /// owner-only behavior (never fabricate `0`).
    pub fn new_with_epoch(
        job_id: impl Into<String>,
        instance_id: impl Into<String>,
        claim_epoch: Option<i64>,
        backend: Arc<dyn TaskBackend>,
        queue: Arc<Mutex<CoalescingQueue>>,
    ) -> Self {
        Self {
            job_id: job_id.into(),
            instance_id: instance_id.into(),
            claim_epoch,
            backend,
            queue,
            terminal: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            last_seen_seq: Arc::new(AtomicI64::new(0)),
            recv_event_lock: Arc::new(Mutex::new(())),
        }
    }

    /// The job ID this controller is bound to.
    pub fn job_id(&self) -> &str {
        &self.job_id
    }

    /// The claim generation this controller executes under, if any. `None`
    /// for a push-mode inbound job or version-skew against an old registry.
    pub fn claim_epoch(&self) -> Option<i64> {
        self.claim_epoch
    }

    /// Enqueue a progress update. Coalesces with any prior pending
    /// progress for this job — only the latest survives the next flush.
    pub async fn update_progress(&self, progress: f32, message: Option<String>) {
        let mut delta = JobDelta::progress(self.job_id.clone(), progress, message);
        // Stamp the claim epoch so the registry can fence a superseded owner
        // (no-op when `None` — the field is omitted from the wire).
        delta.claim_epoch = self.claim_epoch;
        let mut q = self.queue.lock().await;
        // Check the terminal sentinel UNDER the queue lock: flush_terminal
        // sets it (and evicts pending) while holding the same lock, so a
        // racing late progress delta can never land in the queue after the
        // terminal left it (would push stale progress to the registry on
        // the next batching tick — silently overwriting the terminal status
        // or getting rejected as not_owner / illegal-transition).
        if self.terminal.load(Ordering::SeqCst) {
            // Late progress after a terminal flush — drop it. Logged at
            // debug because this is the *expected* path when an
            // application thread fires one last update_progress while
            // the controller is already shutting down; only operators
            // tracing missing progress events care.
            debug!(
                "JobController: dropping post-terminal progress delta for job {}",
                self.job_id
            );
            return;
        }
        q.enqueue(delta);
    }

    /// Transition the job to `input_required`, signalling the consumer that
    /// the handler is blocked awaiting an external answer. STATUS-ONLY
    /// primitive: it posts the `input_required` delta (with `prompt` carried
    /// on the existing `progress_message` field) and returns once posted — it
    /// does NOT await the answer. The canonical flow composes this with the
    /// existing event primitives: the handler calls `request_input(prompt)`,
    /// then parks on `recv_event(types=[...])`; an external party answers via
    /// `JobProxy::send_event`; the handler resumes and `complete()`s (or
    /// `fail()`s).
    ///
    /// Flushes IMMEDIATELY via the same `submit_batch` path `flush_terminal`
    /// uses — NOT the coalescing batch tick — because this is a control-plane
    /// transition the consumer is blocked on; it must not wait up to a tick
    /// interval. Unlike `flush_terminal`, it does NOT set the terminal
    /// sentinel: `input_required` is non-terminal, the handler keeps running,
    /// and a subsequent `update_progress`/`complete`/`fail` is still valid.
    /// The registry lease-extends on this delta (`ApplyJobDeltas`).
    ///
    /// Exit: `complete()` / `fail()` already transition out of
    /// `input_required` (the registry confirms). There is no mid-flight
    /// resume-to-`working` primitive in v1 — a `resume_working()` is a future
    /// follow-up.
    pub async fn request_input(&self, prompt: Option<String>) -> Result<(), JobError> {
        let mut delta = JobDelta::input_required(self.job_id.clone(), prompt);
        delta.claim_epoch = self.claim_epoch;
        // Evict any pending coalesced progress delta for this job UNDER the
        // queue lock before the immediate flush — same fence `flush_terminal`
        // uses — so a stale progress delta queued just before this call can't
        // land at the registry AFTER the input_required transition on the next
        // batching tick. We do NOT set the terminal sentinel: the job stays
        // live and later progress/terminal deltas are still valid.
        //
        // Guard on the terminal sentinel UNDER the same lock first, mirroring
        // `update_progress` / `flush_terminal` / `release_lease`: a helper task
        // that calls `request_input` AFTER the controller went terminal
        // (`complete` / `fail` / `release_lease`) must NOT submit a late
        // `input_required` delta — the job is already done, and the registry
        // would reject it (or it would stomp the terminal status). Unlike
        // `update_progress` (which returns `()` and can only drop silently),
        // this method returns a `Result`, so we surface `JobTerminal` — the
        // same variant `send_event` raises for the identical "acted on an
        // already-terminal job" condition, with SDK re-classification already
        // wired across Python / TS / Java / FFI.
        {
            let mut q = self.queue.lock().await;
            if self.terminal.load(Ordering::SeqCst) {
                return Err(JobError::JobTerminal(format!(
                    "request_input on terminal job {}",
                    self.job_id
                )));
            }
            q.pending.remove(&self.job_id);
        }
        let resp = self
            .backend
            .submit_batch(&self.instance_id, vec![delta])
            .await?;
        // Single delta carrying this controller's epoch — fire only this
        // execution's frame on a superseded rejection.
        let epoch_by_id =
            HashMap::from([(self.job_id.clone(), self.claim_epoch)]);
        fire_superseded_cancels(&resp.rejected, &epoch_by_id);
        Ok(())
    }

    /// Mark the job complete with the given result. Flushes immediately
    /// (terminal status — application is done).
    pub async fn complete(&self, result: serde_json::Value) -> Result<(), JobError> {
        let delta = JobDelta::completed(self.job_id.clone(), result);
        self.flush_terminal(delta).await
    }

    /// Mark the job failed with the given error. Flushes immediately.
    /// Retry semantics (or lack thereof) are decided by the registry based
    /// on the job's `max_retries` — see design doc "Failure & Retry".
    pub async fn fail(&self, error: impl Into<String>) -> Result<(), JobError> {
        let delta = JobDelta::failed(self.job_id.clone(), error);
        self.flush_terminal(delta).await
    }

    async fn flush_terminal(&self, mut delta: JobDelta) -> Result<(), JobError> {
        // Stamp the claim epoch onto the terminal delta too (no-op when
        // `None`). A terminal write from a superseded owner is rejected
        // claim_superseded rather than stomping the new owner's row.
        delta.claim_epoch = self.claim_epoch;
        // Set the per-controller terminal sentinel and evict the pending
        // entry BEFORE dropping the lock — this slams the door on any
        // racing `update_progress` that lands while the backend submit is
        // in flight. Without the sentinel, a concurrent progress update
        // after we'd released the lock would land in the queue and the
        // next batching-tick flush would push stale progress AFTER a
        // terminal status was already on the wire. (`update_progress`
        // checks the sentinel under this same lock.)
        //
        // BEFORE we drop the pending entry, harvest its `progress_message`
        // and `progress` (if any) and fold them into the terminal delta —
        // `complete`/`fail` don't take a message arg, and `fail()` leaves
        // `progress=None`, so without this the registry's `progress_message`
        // and `progress` columns would still reflect whatever the last
        // batching-tick flush wrote (e.g. "section 6/7" / 0.5 when the
        // user's last update_progress was "section 7/7" / 0.99 immediately
        // before fail()). See issue #880.
        {
            let mut q = self.queue.lock().await;
            if let Some(pending) = q.pending.get(&self.job_id) {
                if delta.progress_message.is_none() {
                    delta.progress_message = pending.progress_message.clone();
                }
                if delta.progress.is_none() {
                    delta.progress = pending.progress;
                }
            }
            self.terminal.store(true, Ordering::SeqCst);
            q.pending.remove(&self.job_id);
        }
        let resp = self
            .backend
            .submit_batch(&self.instance_id, vec![delta])
            .await?;
        // Contract (issue #1252 review, item 3): when the terminal delta is
        // rejected `claim_superseded` this returns `Ok(())` and the discarded
        // terminal is intentional. The registry row is owned by the newer
        // claim (H2); THIS (superseded) execution must NOT re-assert a
        // terminal — the registry already rejected it and, crucially,
        // `fire_superseded_cancels` fires THIS execution's own frame (by
        // epoch, never top-of-stack), so cancellation — not the return value
        // — is the surfacing mechanism. Swallowing the rejection here is safe
        // precisely because the cancel targets the right frame.
        let epoch_by_id =
            HashMap::from([(self.job_id.clone(), self.claim_epoch)]);
        fire_superseded_cancels(&resp.rejected, &epoch_by_id);
        Ok(())
    }

    /// Whether `complete` / `fail` has already been called on this
    /// controller. Exposed so per-language SDKs can tell whether a
    /// returning user function still needs an auto-`complete` (the
    /// "if the user forgot, finish the job for them" path).
    ///
    /// Per-controller (shared across `Clone`s) — a NEW controller for the
    /// same `job_id` (e.g. a re-claim) starts non-terminal. Kept `async`
    /// for binding-surface stability even though the read is lock-free.
    pub async fn is_terminal(&self) -> bool {
        self.terminal.load(Ordering::SeqCst)
    }

    /// Whether the cancel token bound to this controller's job in the
    /// process-wide [`cancel_registry`] has been fired. Returns `false`
    /// if the controller's job is not currently registered (not yet
    /// wrapped in [`run_as_job`], or already unregistered).
    ///
    /// Distinct from [`is_terminal`] — `is_terminal` is set by the
    /// controller's own `complete`/`fail`/`release_lease` calls and
    /// reflects local intent, whereas `is_cancelled` reflects an
    /// external cancel signal (e.g. `POST /jobs/{id}/cancel` on the
    /// SDK-owned HTTP route, the Rust task-deadline tripping, etc.).
    /// Per-language SDKs (notably the Java fixture's `runs_overlong`
    /// loop) poll this between blocking sleep intervals so a mid-flight
    /// cancel can break out instead of running to natural completion —
    /// languages whose blocking primitives can't be interrupted by a
    /// Tokio token firing have no other observation point. On the Java
    /// path this is the ONLY supersession-observation surface, so it MUST
    /// read this execution's OWN frame.
    ///
    /// Frame targeting (issue #1252 review): when this controller carries a
    /// claim epoch it observes ITS OWN frame (keyed by epoch), NOT the
    /// top-of-stack. After a same-instance re-claim the top frame is the
    /// fresh healthy attempt H2 (token un-fired); a superseded zombie H1
    /// polling `is_cancelled()` against the top would forever read `false`
    /// and keep running non-idempotent work. Reading H1's own epoch frame
    /// makes a `cancel_superseded(job_id, H1_epoch)` visible to H1 and
    /// invisible to H2. A legacy no-epoch controller has no dedicated frame,
    /// so it reads the top-of-stack as before (single-attempt semantics).
    pub async fn is_cancelled(&self) -> bool {
        let state = match self.claim_epoch {
            Some(epoch) => cancel_registry::get_state_for_epoch(&self.job_id, epoch),
            None => cancel_registry::get_state(&self.job_id),
        };
        match state {
            Some((cancel, _ended)) => cancel.is_cancelled(),
            None => false,
        }
    }

    /// Voluntarily release the lease for retry. Used when the user
    /// handler raised an exception matched by the tool's `retry_on`
    /// whitelist (#879) — instead of marking the job `failed` (which
    /// terminates it), we drop the lease so a peer replica can re-claim
    /// within ~5s via the HEAD-heartbeat path.
    ///
    /// Locally we mark the queue terminal BEFORE the backend call, same
    /// as `flush_terminal`: this slams the door on any racing
    /// `update_progress` so a late progress delta can't arrive at the
    /// registry AFTER we've voluntarily released ownership (where it
    /// would be rejected as `not_owner` at best, or stomp on a peer's
    /// in-flight retry attempt at worst).
    ///
    /// The registry's response carries the post-update status. Status
    /// stays `working` when there's retry budget left (claim already
    /// incremented `attempt_count` when picking the row up; release does
    /// NOT increment). Transitions to `failed` (terminal, with
    /// `error="exhausted (release): <reason>"`) when the row's existing
    /// `attempt_count` is already past `max_retries` — i.e. the handler
    /// raised on the row's final allowed attempt. Either way, this
    /// controller is single-use after release — the queue is locked
    /// terminal so subsequent `update_progress` / `complete` / `fail`
    /// calls become no-ops.
    pub async fn release_lease(
        &self,
        reason: Option<String>,
    ) -> Result<ReleaseJobResponse, JobError> {
        // Mark terminal locally first to mirror the flush_terminal pattern
        // (#880): prevents any racing update_progress from re-enqueuing a
        // delta that would land at the registry after we've released
        // ownership. Sentinel set + pending eviction under the queue lock,
        // same as flush_terminal.
        {
            let mut q = self.queue.lock().await;
            self.terminal.store(true, Ordering::SeqCst);
            q.pending.remove(&self.job_id);
        }
        let resp = self
            .backend
            .release_lease(&self.job_id, &self.instance_id, reason)
            .await?;
        Ok(resp)
    }

    /// Wait for the next event posted to this job's event log.
    ///
    /// On first call (or for a freshly-constructed controller) starts from
    /// `seq=0` and returns the first matching event in the log. Subsequent
    /// calls return events strictly newer than the last consumed — the
    /// internal cursor is incremented on every successful return. The
    /// cursor is per-`JobController`-instance (shared across `Clone`s of
    /// the same instance via `Arc<AtomicI64>`); a NEW controller for the
    /// same `job_id` starts replay from `seq=0`.
    ///
    /// `types`: if `Some`, only events whose `event_type` matches one of
    /// the provided strings are returned. If `None`, all event types match.
    ///
    /// `timeout` bounds the long-poll. `None` waits indefinitely (loops
    /// the registry's 60s cap until an event arrives). `Some(d)` returns
    /// `Ok(None)` once roughly `d` has elapsed without a matching event.
    ///
    /// Trace context: when an event with `trace_context` is returned, the
    /// field is passed through verbatim on [`JobEvent::trace_context`].
    /// TODO: wire OpenTelemetry child-span creation when the core crate
    /// adopts the `opentelemetry` crate (today this crate uses only the
    /// `tracing` facade with no OTel surface).
    ///
    /// Returns:
    /// - `Ok(Some(event))` on event arrival
    /// - `Ok(None)` on timeout
    /// - `Err(Backend(NotFound(_)))` if the registry reports the job
    ///   no longer exists
    /// - `Err(Backend(...))` for other transport-layer failures (with
    ///   the same transient-error backoff pattern as `JobProxy::wait`)
    pub async fn recv_event(
        &self,
        types: Option<Vec<String>>,
        timeout: Option<Duration>,
    ) -> Result<Option<JobEvent>, JobError> {
        // Per-round long-poll cap. Matches the registry's server-side
        // ceiling (`wait` query param ≤ 60s); requesting longer is
        // silently truncated, so we loop client-side instead.
        const REGISTRY_LONG_POLL_CAP: Duration = Duration::from_secs(60);
        // Server-side limit (matches OpenAPI `limit` maximum).
        const FETCH_LIMIT: usize = 100;

        // Serialise the load→list→store window across `Clone`s of this
        // controller. Without this, two concurrent callers can both load
        // the same `last_seen_seq` cursor, both issue `list_job_events`
        // with the same `after`, and both return the SAME head event.
        // The AtomicI64 prevents tearing but not the read-fetch-write
        // race across the `.await`. Acquire BEFORE the deadline check
        // so a fast clone-vs-clone race ordering is deterministic.
        let _guard = self.recv_event_lock.lock().await;

        let deadline = timeout.map(|t| Instant::now() + t);
        // Tracks the start of the current contiguous transient-failure
        // window for the same recovery semantics as `JobProxy::wait`.
        let mut transient_failure_started: Option<Instant> = None;
        let registry_unreachable_max = DEFAULT_REGISTRY_UNREACHABLE_MAX;
        // Exponential backoff for transient registry errors. Reset to
        // `POLL_INITIAL_MS` on every successful list, capped at
        // `POLL_MAX_MS` — same shape as `JobProxy::wait_with_config`.
        let mut backoff_ms = POLL_INITIAL_MS;

        loop {
            // Honour the caller's overall timeout BEFORE issuing the next
            // long-poll round-trip so a tight `timeout` doesn't get one
            // 60s-cap round-trip past its budget.
            let remaining = match deadline {
                Some(d) => {
                    let now = Instant::now();
                    if now >= d {
                        return Ok(None);
                    }
                    Some(d - now)
                }
                None => None,
            };

            // Cap the long-poll at min(remaining, REGISTRY_LONG_POLL_CAP).
            let wait = match remaining {
                Some(r) => r.min(REGISTRY_LONG_POLL_CAP),
                None => REGISTRY_LONG_POLL_CAP,
            };

            // Cancellation check each iteration (issue #1252 / #882): a user
            // cancel (`POST /jobs/{id}/cancel`) OR a supersession fires this
            // job's token in the cancel registry. A handler parked in a
            // blocking `recv_event` gate must break out promptly — the loop
            // otherwise round-trips a fresh 60s long-poll oblivious to the
            // cancel. Snapshot the token so we can BOTH short-circuit an
            // already-fired cancel here AND race it against the long-poll
            // below (so a mid-poll cancel returns without waiting out the
            // registry's 60s window). Surfaces as `JobError::Cancelled` —
            // the same shape an explicit user cancel takes.
            //
            // Watch THIS execution's OWN frame, keyed by claim epoch — NOT
            // the top-of-stack. After a same-instance re-claim the top frame
            // is the fresh healthy attempt H2; the superseded H1 (this one)
            // must observe its own token so a batch-path supersession firing
            // H1's frame wakes H1's parked poll without depending on H2
            // (issue #1252 review). A legacy controller (no epoch) has no
            // dedicated frame, so it watches the top-of-stack as before.
            let cancel_token = match self.claim_epoch {
                Some(epoch) => cancel_registry::get_state_for_epoch(&self.job_id, epoch),
                None => cancel_registry::get_state(&self.job_id),
            }
            .map(|(cancel, _ended)| cancel);
            if let Some(tok) = &cancel_token {
                if tok.is_cancelled() {
                    return Err(JobError::Cancelled);
                }
            }

            let after = self.last_seen_seq.load(Ordering::SeqCst);
            let types_ref = types.as_deref();
            // Executor identity: the OWNER's controller supplies
            // `(instance_id, claim_epoch)` so the registry fences this read
            // and extends the lease (poll-liveness). Only sent when this
            // controller carries a real epoch — a push-mode / legacy
            // controller reads anonymously (`None`), byte-identical to today.
            let identity = self
                .claim_epoch
                .map(|epoch| (self.instance_id.as_str(), epoch));
            let list_fut =
                self.backend
                    .list_job_events(&self.job_id, after, types_ref, wait, FETCH_LIMIT, identity);
            // Race the long-poll against the cancel token so a cancel fired
            // mid-poll returns immediately instead of after the registry's
            // 60s cap. Poll cadence / backoff are otherwise unchanged.
            let list_result = match &cancel_token {
                Some(tok) => {
                    tokio::select! {
                        biased;
                        _ = tok.cancelled() => return Err(JobError::Cancelled),
                        r = list_fut => r,
                    }
                }
                None => list_fut.await,
            };
            match list_result {
                Ok(resp) => {
                    transient_failure_started = None;
                    // Reset exponential backoff on every successful list,
                    // mirroring `JobProxy::wait_with_config`'s reset on
                    // any successful poll.
                    backoff_ms = POLL_INITIAL_MS;
                    // First matching event wins. The registry already
                    // filters by `types` and orders ascending; we return
                    // the head and advance the cursor to its seq so the
                    // next call picks up strictly after it.
                    if let Some(ev) = resp.events.into_iter().next() {
                        self.last_seen_seq.store(ev.seq, Ordering::SeqCst);
                        return Ok(Some(ev));
                    }
                    // Empty page: keep next_after as the cursor (matches
                    // the registry's contract — the watermark may have
                    // advanced even though no matching event arrived).
                    // We only ever advance, never retreat.
                    let cur = self.last_seen_seq.load(Ordering::SeqCst);
                    if resp.next_after > cur {
                        self.last_seen_seq.store(resp.next_after, Ordering::SeqCst);
                    }
                    // No event yet — loop. The deadline check at the top
                    // of the next iteration returns Ok(None) if expired.
                }
                Err(BackendError::ClaimSuperseded(_)) => {
                    // The registry fenced this executor read: a newer claim
                    // (a reclaim + fresh claim, possibly by this same
                    // instance) superseded this execution. Fire THIS
                    // execution's own frame — keyed by our claim epoch, never
                    // the top-of-stack — so a healthy re-claim (H2) is not
                    // collaterally cancelled (issue #1252 review). Then
                    // surface `Cancelled` — indistinguishable from a user
                    // cancel at the handler surface (no reason field).
                    warn!(
                        "JobController::recv_event superseded by a newer claim \
                         (job_id={}, epoch={:?}); firing this execution's cancel \
                         token and aborting",
                        self.job_id, self.claim_epoch
                    );
                    if let Some(epoch) = self.claim_epoch {
                        cancel_registry::cancel_superseded(&self.job_id, epoch);
                    }
                    return Err(JobError::Cancelled);
                }
                Err(e) if e.is_transient() => {
                    let started = *transient_failure_started.get_or_insert_with(Instant::now);
                    let elapsed = started.elapsed();
                    if elapsed > registry_unreachable_max {
                        warn!(
                            "JobController::recv_event giving up after {:?} of \
                             transient registry errors (job_id={}, last_err={})",
                            elapsed, self.job_id, e
                        );
                        return Err(JobError::RegistryUnreachable { duration: elapsed });
                    }
                    debug!(
                        "JobController::recv_event absorbing transient registry \
                         error (job_id={}, elapsed={:?}, err={}, backoff_ms={})",
                        self.job_id, elapsed, e, backoff_ms
                    );
                    // Exponential backoff so we don't hot-loop while the
                    // registry is restarting. Bound the sleep by the
                    // caller's remaining `timeout` budget — without this
                    // a long backoff could blow past the deadline.
                    let mut sleep_ms = backoff_ms;
                    if let Some(r) = remaining {
                        let r_ms = r.as_millis() as u64;
                        if r_ms < sleep_ms {
                            sleep_ms = r_ms;
                        }
                    }
                    sleep(Duration::from_millis(sleep_ms)).await;
                    backoff_ms = (backoff_ms * 2).min(POLL_MAX_MS);
                }
                Err(e) => return Err(e.into()),
            }
        }
    }
}

// =============================================================================
// JobProxy (consumer-side)
// =============================================================================

/// Polling cadence: start at 200ms, exponential backoff to 5s max.
const POLL_INITIAL_MS: u64 = 200;
const POLL_MAX_MS: u64 = 5_000;

/// Default ceiling on continuous transient registry-error windows during
/// [`JobProxy::wait`]. 60s comfortably covers a typical k8s rolling
/// restart of the registry deployment; beyond that we surface
/// [`JobError::RegistryUnreachable`] so the caller can fail loudly.
const DEFAULT_REGISTRY_UNREACHABLE_MAX: Duration = Duration::from_secs(60);

/// Configuration knobs for [`JobProxy::wait_with_config`]. Use
/// [`WaitConfig::default`] for the documented defaults; override
/// `registry_unreachable_max` to widen / narrow the resilience window
/// (tests use a few hundred ms; production code typically leaves it at
/// the 60s default).
#[derive(Debug, Clone)]
pub struct WaitConfig {
    /// Caller-supplied wall-clock timeout (returns [`JobError::Timeout`]).
    /// `None` ≡ no timeout (wait until terminal or parent deadline fires).
    pub timeout: Option<Duration>,

    /// Maximum continuous duration the registry can be returning transient
    /// errors before the wait gives up with [`JobError::RegistryUnreachable`].
    /// Reset to zero on every successful poll.
    pub registry_unreachable_max: Duration,
}

impl Default for WaitConfig {
    fn default() -> Self {
        Self {
            timeout: None,
            registry_unreachable_max: DEFAULT_REGISTRY_UNREACHABLE_MAX,
        }
    }
}

/// Consumer-side handle: returned by [`submit_job`] and exposes
/// `wait`/`status`/`cancel` for code that wants to await a remote job.
#[derive(Clone)]
pub struct JobProxy {
    job_id: String,
    backend: Arc<dyn TaskBackend>,
}

impl JobProxy {
    /// Construct directly from a known job id. Normally callers obtain a
    /// `JobProxy` via [`submit_job`].
    pub fn new(job_id: impl Into<String>, backend: Arc<dyn TaskBackend>) -> Self {
        Self {
            job_id: job_id.into(),
            backend,
        }
    }

    /// The job id this proxy is bound to.
    pub fn job_id(&self) -> &str {
        &self.job_id
    }

    /// Read the latest status without blocking (single registry call).
    pub async fn status(&self) -> Result<Job, JobError> {
        Ok(self.backend.get_job(&self.job_id).await?)
    }

    /// Request cancellation. Registry forwards the signal to the owner
    /// replica when alive.
    pub async fn cancel(&self, reason: Option<String>) -> Result<(), JobError> {
        self.backend.cancel_job(&self.job_id, reason).await?;
        Ok(())
    }

    /// Post an event into this job's event log. The executing handler
    /// (inside the running `task=True` job) will see it on its next
    /// `recv_event` call — or wake immediately if it's currently long-polling.
    ///
    /// Trace context propagation: when the core crate adopts the
    /// `opentelemetry` crate, the current span's W3C trace context will
    /// be captured and forwarded automatically via `trace_context` so the
    /// receiver's `recv_event` can link a child span. Today this crate
    /// uses only the `tracing` facade with no OTel surface — language
    /// SDKs (Python, TS, Java) capture trace context on their side and
    /// can pass it as part of `payload` if needed. The wire field is
    /// reserved on `JobEventPostRequest` for the eventual wire-through.
    /// TODO: capture OTel current span context here.
    ///
    /// Returns:
    /// - `Ok(receipt)` on success
    /// - `Err(Backend(NotFound(_)))` if the job doesn't exist
    /// - `Err(JobTerminal(_))` if the job is already terminal
    ///   (`completed` / `failed` / `cancelled`) — the registry rejects
    ///   the post with 409 Conflict and the SDK surfaces it as a
    ///   dedicated variant for clean `match`-ing
    /// - `Err(Backend(...))` for transport failures
    pub async fn send_event(
        &self,
        event_type: String,
        payload: serde_json::Value,
    ) -> Result<JobEventReceipt, JobError> {
        // TODO: capture OpenTelemetry current span context once the core
        // crate adopts the `opentelemetry` crate and wire it as
        // `trace_context`. For now: pass-through None — language SDKs
        // can populate trace_context themselves via a future overload
        // (or by carrying it inside `payload`).
        let trace_context: Option<serde_json::Value> = None;
        let payload_opt = if payload.is_null() { None } else { Some(payload) };
        match self
            .backend
            .post_job_event(&self.job_id, &event_type, payload_opt, trace_context)
            .await
        {
            Ok(receipt) => Ok(receipt),
            Err(BackendError::Conflict(msg)) => Err(JobError::JobTerminal(msg)),
            Err(e) => Err(e.into()),
        }
    }

    /// Fetch a batch of events with `seq > after`, optionally filtered by
    /// `types`.
    ///
    /// This is the low-level building block for the language SDKs'
    /// ``subscribe_events`` async-iterator semantics — callers manage
    /// their own cursor across calls. See [`JobController::recv_event`]
    /// for the alternative single-event-with-internal-cursor shape used
    /// inside running ``task=True`` jobs.
    ///
    /// `wait`: long-poll budget (`None` = single immediate read; `Some(d)`
    /// = long-poll up to `d`, capped at 60s by the registry). An empty
    /// result means "no events arrived within the wait window" — the
    /// caller continues with the same cursor.
    ///
    /// Unlike [`JobController::recv_event`] this method:
    ///
    /// * Does NOT advance any internal cursor — `after` is supplied by
    ///   the caller and the returned events leave it to the caller to
    ///   track the next watermark.
    /// * Is NOT serialised under a mutex — multiple subscribers against
    ///   the same proxy run independently, observing the same events.
    /// * Returns ALL matching events from the single registry round
    ///   trip (up to 100), not just the head — this is a batch primitive,
    ///   not a single-event primitive.
    /// * Returns the registry-supplied `next_after` watermark alongside
    ///   the events — callers should feed it back as `after` on the next
    ///   call so empty pages caused by server-side filters still advance
    ///   the cursor.
    pub async fn list_events(
        &self,
        after: i64,
        types: Option<Vec<String>>,
        wait: Option<Duration>,
    ) -> Result<(Vec<JobEvent>, i64), JobError> {
        // Server-side limit (matches OpenAPI `limit` maximum).
        const FETCH_LIMIT: usize = 100;
        let resp = self
            .backend
            .list_job_events(
                &self.job_id,
                after,
                types.as_deref(),
                wait.unwrap_or_default(),
                FETCH_LIMIT,
                // Observer read: JobProxy never claims — no executor identity,
                // no lease side-effects (A2A / UI / meshctl all rely on this).
                None,
            )
            .await?;
        Ok((resp.events, resp.next_after))
    }

    /// Poll until the job reaches a terminal state, returns its `result`
    /// payload, or surfaces an error. Convenience wrapper around
    /// [`Self::wait_with_config`] that uses [`WaitConfig::default`] for
    /// the resilience window (60s).
    ///
    /// Honours:
    /// 1. Caller-supplied `timeout` (returns `JobError::Timeout`).
    /// 2. Active `JobContext` deadline (parent-scope deadline cap).
    /// 3. Active `JobContext` cancel token (parent cancellation).
    /// 4. Transient registry errors are absorbed for up to
    ///    [`DEFAULT_REGISTRY_UNREACHABLE_MAX`] before bubbling up as
    ///    [`JobError::RegistryUnreachable`].
    pub async fn wait(&self, timeout: Option<Duration>) -> Result<serde_json::Value, JobError> {
        self.wait_with_config(WaitConfig {
            timeout,
            ..WaitConfig::default()
        })
        .await
    }

    /// Like [`Self::wait`] but with explicit configuration. Lets tests
    /// (and advanced callers) tune `registry_unreachable_max`.
    ///
    /// Resilience semantics: a contiguous window of transient
    /// [`BackendError`]s (network drops, 503, other 5xx) is treated as a
    /// no-op poll — the wait keeps backing off, just as if the job were
    /// still running. The window starts on the first transient failure
    /// and resets on any successful poll; if it ever exceeds
    /// `registry_unreachable_max`, the wait gives up with
    /// [`JobError::RegistryUnreachable`]. Non-transient errors (404,
    /// 409, serialisation, generic 4xx) propagate immediately.
    pub async fn wait_with_config(
        &self,
        config: WaitConfig,
    ) -> Result<serde_json::Value, JobError> {
        let parent_ctx = job_context::current();
        let parent_cancel = parent_ctx.as_ref().map(|c| c.cancel_token.clone());
        let parent_deadline = parent_ctx.as_ref().and_then(|c| c.deadline);

        let user_deadline = config.timeout.map(|t| Instant::now() + t);
        // Effective deadline = min(user, parent) — whichever fires first.
        let effective_deadline = match (user_deadline, parent_deadline.map(to_tokio_instant)) {
            (Some(u), Some(p)) => Some(u.min(p)),
            (Some(u), None) => Some(u),
            (None, Some(p)) => Some(p),
            (None, None) => None,
        };

        let mut backoff_ms = POLL_INITIAL_MS;
        // Tracks the start of the current contiguous transient-failure
        // window. `None` after every successful poll.
        let mut transient_failure_started: Option<Instant> = None;

        loop {
            // Check absolute deadline first (cheap).
            if let Some(d) = effective_deadline {
                if Instant::now() >= d {
                    return Err(JobError::Timeout(config.timeout.unwrap_or_default()));
                }
            }

            // Check cancel.
            if let Some(c) = parent_cancel.as_ref() {
                if c.is_cancelled() {
                    return Err(JobError::Cancelled);
                }
            }

            // Poll the registry.
            match self.backend.get_job(&self.job_id).await {
                Ok(job) => {
                    // Recovered: drop any in-flight transient window.
                    transient_failure_started = None;
                    if job.status.is_terminal() {
                        return match job.status {
                            JobStatus::Completed => {
                                Ok(job.result.unwrap_or(serde_json::Value::Null))
                            }
                            other => Err(JobError::NonSuccessTerminal {
                                status: other,
                                error: job.error,
                            }),
                        };
                    }
                }
                Err(e) if e.is_transient() => {
                    // Open or extend the transient window. If we've been
                    // failing too long, give up cleanly; otherwise treat
                    // this poll as if we'd seen a non-terminal status —
                    // back off and try again. Log at warn so operators
                    // see the registry blip in the agent log.
                    let started = *transient_failure_started.get_or_insert_with(Instant::now);
                    let elapsed = started.elapsed();
                    if elapsed > config.registry_unreachable_max {
                        warn!(
                            "JobProxy::wait giving up after {:?} of transient \
                             registry errors (job_id={}, last_err={})",
                            elapsed, self.job_id, e
                        );
                        return Err(JobError::RegistryUnreachable { duration: elapsed });
                    }
                    debug!(
                        "JobProxy::wait absorbing transient registry error \
                         (job_id={}, elapsed={:?}, err={})",
                        self.job_id, elapsed, e
                    );
                }
                Err(e) => return Err(e.into()),
            }

            // Sleep with deadline / cancel honored.
            let sleep_dur = Duration::from_millis(backoff_ms);
            let sleep_until = match effective_deadline {
                Some(d) => d.min(Instant::now() + sleep_dur),
                None => Instant::now() + sleep_dur,
            };

            tokio::select! {
                _ = tokio::time::sleep_until(sleep_until) => {}
                _ = wait_on_optional_cancel(&parent_cancel) => {
                    return Err(JobError::Cancelled);
                }
            }

            // Exponential backoff (capped).
            backoff_ms = (backoff_ms * 2).min(POLL_MAX_MS);
        }
    }
}

/// Convert std `Instant` to tokio `Instant` (they share a clock).
fn to_tokio_instant(std: std::time::Instant) -> Instant {
    Instant::from_std(std)
}

/// Future that completes only if the passed-in cancel token (if any) is
/// cancelled. If `None`, never completes — `select!` will pick the other
/// branch.
async fn wait_on_optional_cancel(token: &Option<CancellationToken>) {
    match token {
        Some(t) => t.cancelled().await,
        None => std::future::pending::<()>().await,
    }
}

// =============================================================================
// run_cancellable helper
// =============================================================================

/// Wrap an arbitrary future so that it aborts if the active job context's
/// cancel token fires. If no job context is active, the future runs to
/// completion as normal.
pub async fn run_cancellable<F, T>(future: F) -> Result<T, JobCancelled>
where
    F: Future<Output = T>,
{
    let token = job_context::current().map(|c| c.cancel_token);
    match token {
        Some(t) => {
            tokio::select! {
                v = future => Ok(v),
                _ = t.cancelled() => Err(JobCancelled),
            }
        }
        None => Ok(future.await),
    }
}

// =============================================================================
// run_as_job — unified context-setup primitive
// =============================================================================

/// Drop guard that unregisters the job from [`crate::cancel_registry`]
/// when scope exits — including the panic-unwind path. Pairs with the
/// `register_active_job` call at the top of [`run_as_job`]. Carries the
/// registration generation so only THIS scope's registration is torn
/// down — a different registration for the same `job_id` (nested
/// dispatch, re-claimed attempt) is never disturbed (issue #1166 MED-4).
struct CancelRegistryGuard {
    job_id: String,
    generation: u64,
}

impl Drop for CancelRegistryGuard {
    fn drop(&mut self) {
        cancel_registry::unregister_active_job(&self.job_id, self.generation);
    }
}

/// Run `body` with `ctx` as the active [`JobContext`] AND the context's
/// cancel token registered in [`crate::cancel_registry`] under
/// `ctx.job_id` for the duration of the body.
///
/// This is the ONE primitive that BOTH the inbound HTTP tool-wrapper path
/// (per-language SDK reads `X-Mesh-Job-Id` from headers, builds the
/// context, calls `run_as_job`) AND the core's [`crate::claim_worker`]
/// path (claim succeeds, builds the context, calls `run_as_job`)
/// converge on. Documents the design's "two callers, one context-setup
/// primitive" invariant.
///
/// Cleanup of the cancel-registry entry is panic-safe via a drop guard:
/// even if `body` panics, the entry is removed during unwind.
pub async fn run_as_job<F, T>(ctx: JobContext, body: F) -> T
where
    F: Future<Output = T>,
{
    // Record the claim epoch on the frame so a supersession fires THIS
    // execution's token by epoch, never the top-of-stack (issue #1252).
    let generation = cancel_registry::register_active_job_with_epoch(
        &ctx.job_id,
        ctx.cancel_token.clone(),
        ctx.claim_epoch,
    );
    let _guard = CancelRegistryGuard {
        job_id: ctx.job_id.clone(),
        generation,
    };
    job_context::with_job(ctx, body).await
}

// =============================================================================
// submit_job entry point
// =============================================================================

/// Arguments for [`submit_job`]. Constructed builder-style by callers; this
/// struct keeps the function signature manageable.
#[derive(Debug, Clone, Serialize)]
pub struct SubmitJobArgs {
    pub capability: String,
    pub payload: serde_json::Value,
    pub submitted_by: String,
    pub owner_instance_id: Option<String>,
    pub max_duration: Option<u32>,
    pub max_retries: Option<u32>,
    /// Optional absolute Unix-epoch deadline across all retries. `None`
    /// means unlimited (per "Resolved Decisions" in design doc).
    pub total_deadline: Option<i64>,
}

/// Producer-side helper: register a new job with the backend, return a
/// [`JobProxy`] for the consumer to await.
///
/// Push mode: pass `owner_instance_id=Some(...)` to pin the job to a
/// specific replica.  Pull mode: pass `owner_instance_id=None` and the job
/// starts unclaimed (a replica will claim it via `POST /jobs/claim`).
pub async fn submit_job(
    backend: Arc<dyn TaskBackend>,
    args: SubmitJobArgs,
) -> Result<(JobProxy, CreateJobResponse), JobError> {
    let req = CreateJobRequest {
        capability: args.capability,
        submitted_payload: args.payload,
        submitted_by: args.submitted_by,
        max_retries: args.max_retries,
        max_duration: args.max_duration,
        total_deadline: args.total_deadline,
        owner_instance_id: args.owner_instance_id,
    };
    let resp = backend.create_job(req).await?;
    let proxy = JobProxy::new(resp.id.clone(), backend);
    Ok((proxy, resp))
}

// =============================================================================
// Public re-exports for queue construction (used by agent runtime wiring)
// =============================================================================

/// Construct a fresh empty coalescing queue. Callers should wrap in
/// `Arc<Mutex<...>>` and share between [`JobController`] instances and the
/// batching tick.
pub fn new_coalescing_queue() -> Arc<Mutex<CoalescingQueue>> {
    Arc::new(Mutex::new(CoalescingQueue::default()))
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex as StdMutex;

    use crate::task_backend::{
        CancelJobResponse, ClaimedJob, JobBatchResponse, JobEventListResponse,
    };

    // ---- mock backend -------------------------------------------------------

    /// What `get_job` should return for the next call.
    enum GetJobInjection {
        /// Return the in-memory job state normally.
        Ok,
        /// Return a transient error (used by the resilience tests).
        TransientUnavailable,
        /// Return NotFound (non-transient — propagated immediately).
        NotFound,
    }

    /// Stateful mock backend used by the rest of the test suite.
    struct MockBackend {
        jobs: StdMutex<HashMap<String, Job>>,
        batches: StdMutex<Vec<(String, Vec<JobDelta>)>>,
        cancels: StdMutex<Vec<(String, Option<String>)>>,
        /// Voluntary release calls: (job_id, instance_id, reason)
        releases: StdMutex<Vec<(String, String, Option<String>)>>,
        /// All persisted events keyed by job_id. Seq is 1-based per job.
        events: StdMutex<HashMap<String, Vec<JobEvent>>>,
        /// Record of post_job_event calls: (job_id, event_type, payload, trace_context)
        event_posts: StdMutex<
            Vec<(
                String,
                String,
                Option<serde_json::Value>,
                Option<serde_json::Value>,
            )>,
        >,
        /// If set, every post_job_event returns Conflict (terminal job).
        events_post_returns_conflict: AtomicUsize,
        /// If set, every list_job_events returns NotFound.
        events_list_returns_not_found: AtomicUsize,
        /// Current claim generation per job_id, as the registry would hold
        /// it. Absent ⇒ treated as epoch 0. An executor read / delta whose
        /// epoch mismatches this (owner check aside) is `claim_superseded`.
        epochs: StdMutex<HashMap<String, i64>>,
        /// Every `identity` arg seen by `list_job_events`, in call order —
        /// lets tests assert executor (Some) vs observer (None) reads.
        list_identities: StdMutex<Vec<Option<(String, i64)>>>,
        next_id: AtomicUsize,
        /// Auto-progress to terminal on the Nth `get_job` call. 0 = never.
        terminal_after: AtomicUsize,
        get_calls: AtomicUsize,
        /// Number of leading `get_job` calls that should return a
        /// transient error before normal handling resumes. Decremented on
        /// each call until zero.
        transient_remaining: AtomicUsize,
        /// If set, EVERY `get_job` returns a transient error (until the
        /// test toggles it back off). Used to simulate "registry never
        /// recovers" for the timeout test.
        always_transient: AtomicUsize, // 0 = false, 1 = true
        /// If set, every `get_job` returns NotFound (non-transient).
        always_not_found: AtomicUsize,
    }

    impl MockBackend {
        fn new() -> Arc<Self> {
            Arc::new(Self {
                jobs: StdMutex::new(HashMap::new()),
                batches: StdMutex::new(Vec::new()),
                cancels: StdMutex::new(Vec::new()),
                releases: StdMutex::new(Vec::new()),
                events: StdMutex::new(HashMap::new()),
                event_posts: StdMutex::new(Vec::new()),
                events_post_returns_conflict: AtomicUsize::new(0),
                events_list_returns_not_found: AtomicUsize::new(0),
                epochs: StdMutex::new(HashMap::new()),
                list_identities: StdMutex::new(Vec::new()),
                next_id: AtomicUsize::new(0),
                terminal_after: AtomicUsize::new(0),
                get_calls: AtomicUsize::new(0),
                transient_remaining: AtomicUsize::new(0),
                always_transient: AtomicUsize::new(0),
                always_not_found: AtomicUsize::new(0),
            })
        }
        fn push_event(&self, job_id: &str, event_type: &str, payload: serde_json::Value) {
            let mut all = self.events.lock().unwrap();
            let list = all.entry(job_id.to_string()).or_default();
            let seq = (list.len() as i64) + 1;
            list.push(JobEvent {
                job_id: job_id.to_string(),
                seq,
                event_type: event_type.to_string(),
                payload: Some(payload),
                trace_context: None,
                posted_by: None,
                created_at: 1700000000 + seq,
            });
        }
        /// Set the registry-side current claim generation for a job so
        /// tests can simulate a reclaim + fresh claim bumping the epoch out
        /// from under a superseded owner.
        fn set_current_epoch(&self, job_id: &str, epoch: i64) {
            self.epochs
                .lock()
                .unwrap()
                .insert(job_id.to_string(), epoch);
        }
        /// Current claim generation the registry holds for `job_id` (0 when
        /// never set).
        fn current_epoch(&self, job_id: &str) -> i64 {
            self.epochs
                .lock()
                .unwrap()
                .get(job_id)
                .copied()
                .unwrap_or(0)
        }
        /// Snapshot of every `identity` arg `list_job_events` has seen.
        fn list_identities(&self) -> Vec<Option<(String, i64)>> {
            self.list_identities.lock().unwrap().clone()
        }
        fn set_events_post_conflict(&self, on: bool) {
            self.events_post_returns_conflict
                .store(usize::from(on), Ordering::SeqCst);
        }
        fn set_events_list_not_found(&self, on: bool) {
            self.events_list_returns_not_found
                .store(usize::from(on), Ordering::SeqCst);
        }
        fn set_terminal_after(&self, n: usize) {
            self.terminal_after.store(n, Ordering::SeqCst);
        }
        fn set_transient_for_n_calls(&self, n: usize) {
            self.transient_remaining.store(n, Ordering::SeqCst);
        }
        fn set_always_transient(&self, on: bool) {
            self.always_transient.store(usize::from(on), Ordering::SeqCst);
        }
        fn set_always_not_found(&self, on: bool) {
            self.always_not_found.store(usize::from(on), Ordering::SeqCst);
        }
        fn next_get_injection(&self) -> GetJobInjection {
            if self.always_not_found.load(Ordering::SeqCst) == 1 {
                return GetJobInjection::NotFound;
            }
            if self.always_transient.load(Ordering::SeqCst) == 1 {
                return GetJobInjection::TransientUnavailable;
            }
            // Burn one off the remaining transient budget atomically.
            let mut cur = self.transient_remaining.load(Ordering::SeqCst);
            while cur > 0 {
                match self.transient_remaining.compare_exchange(
                    cur,
                    cur - 1,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                ) {
                    Ok(_) => return GetJobInjection::TransientUnavailable,
                    Err(actual) => cur = actual,
                }
            }
            GetJobInjection::Ok
        }
        fn batch_count(&self) -> usize {
            self.batches.lock().unwrap().len()
        }
        fn cancel_count(&self) -> usize {
            self.cancels.lock().unwrap().len()
        }
        fn last_batch(&self) -> Option<(String, Vec<JobDelta>)> {
            self.batches.lock().unwrap().last().cloned()
        }
    }

    #[async_trait::async_trait]
    impl TaskBackend for MockBackend {
        async fn create_job(
            &self,
            req: CreateJobRequest,
        ) -> Result<CreateJobResponse, BackendError> {
            let n = self.next_id.fetch_add(1, Ordering::SeqCst);
            let id = format!("job-{}", n);
            let job = Job {
                id: id.clone(),
                capability: req.capability,
                owner_instance_id: req.owner_instance_id.clone(),
                status: JobStatus::Working,
                progress: None,
                progress_message: None,
                result: None,
                error: None,
                submitted_payload: req.submitted_payload,
                attempt_count: 0,
                max_retries: req.max_retries.unwrap_or(1),
                max_duration: req.max_duration,
                total_deadline: req.total_deadline,
                lease_expires_at: None,
                last_heartbeat_at: None,
                submitted_at: 0,
                submitted_by: req.submitted_by,
            };
            self.jobs.lock().unwrap().insert(id.clone(), job);
            Ok(CreateJobResponse {
                id,
                status: JobStatus::Working,
                owner_instance_id: req.owner_instance_id,
            })
        }

        async fn submit_batch(
            &self,
            instance_id: &str,
            deltas: Vec<JobDelta>,
        ) -> Result<JobBatchResponse, BackendError> {
            // Epoch fencing (mirrors the registry's ApplyJobDeltas): a delta
            // carrying a claim_epoch that mismatches the job's current
            // generation (and the job is non-terminal) is rejected
            // claim_superseded rather than applied. Deltas without an epoch
            // fall back to owner-only validation (always accepted here).
            let mut rejected: Vec<crate::task_backend::RejectedDelta> = Vec::new();
            {
                let mut jobs = self.jobs.lock().unwrap();
                for d in &deltas {
                    if let Some(j) = jobs.get_mut(&d.id) {
                        if let Some(epoch) = d.claim_epoch {
                            let cur = self
                                .epochs
                                .lock()
                                .unwrap()
                                .get(&d.id)
                                .copied()
                                .unwrap_or(0);
                            if epoch != cur && !j.status.is_terminal() {
                                rejected.push(crate::task_backend::RejectedDelta {
                                    id: d.id.clone(),
                                    reason:
                                        crate::task_backend::CLAIM_SUPERSEDED_REASON
                                            .to_string(),
                                });
                                continue;
                            }
                        }
                        if let Some(s) = d.status {
                            j.status = s;
                        }
                        if let Some(p) = d.progress {
                            j.progress = Some(p);
                        }
                        if let Some(m) = &d.progress_message {
                            j.progress_message = Some(m.clone());
                        }
                        if let Some(r) = &d.result {
                            j.result = Some(r.clone());
                        }
                        if let Some(e) = &d.error {
                            j.error = Some(e.clone());
                        }
                    }
                }
            }
            let accepted = (deltas.len() - rejected.len()) as u32;
            self.batches
                .lock()
                .unwrap()
                .push((instance_id.to_string(), deltas));
            Ok(JobBatchResponse { accepted, rejected })
        }

        async fn claim_next(
            &self,
            _capability: &str,
            _instance_id: &str,
        ) -> Result<Option<ClaimedJob>, BackendError> {
            Ok(None)
        }

        async fn get_job(&self, job_id: &str) -> Result<Job, BackendError> {
            let n = self.get_calls.fetch_add(1, Ordering::SeqCst) + 1;
            // Honour error injection FIRST so the resilience tests can
            // simulate registry blips independently of the auto-terminal
            // counter.
            match self.next_get_injection() {
                GetJobInjection::Ok => {}
                GetJobInjection::TransientUnavailable => {
                    return Err(BackendError::BackendUnavailable(
                        "registry rolling restart (mock)".into(),
                    ));
                }
                GetJobInjection::NotFound => {
                    return Err(BackendError::NotFound(job_id.to_string()));
                }
            }
            let trip = self.terminal_after.load(Ordering::SeqCst);
            if trip > 0 && n >= trip {
                if let Some(j) = self.jobs.lock().unwrap().get_mut(job_id) {
                    j.status = JobStatus::Completed;
                    j.result = Some(serde_json::json!({"ok": true, "n": n}));
                }
            }
            self.jobs
                .lock()
                .unwrap()
                .get(job_id)
                .cloned()
                .ok_or_else(|| BackendError::NotFound(job_id.to_string()))
        }

        async fn cancel_job(
            &self,
            job_id: &str,
            reason: Option<String>,
        ) -> Result<CancelJobResponse, BackendError> {
            self.cancels
                .lock()
                .unwrap()
                .push((job_id.to_string(), reason));
            if let Some(j) = self.jobs.lock().unwrap().get_mut(job_id) {
                j.status = JobStatus::Cancelled;
            }
            Ok(CancelJobResponse {
                status: JobStatus::Cancelled,
                forwarded_to_instance_id: None,
            })
        }

        async fn release_lease(
            &self,
            job_id: &str,
            instance_id: &str,
            reason: Option<String>,
        ) -> Result<ReleaseJobResponse, BackendError> {
            self.releases.lock().unwrap().push((
                job_id.to_string(),
                instance_id.to_string(),
                reason,
            ));
            // Simulate the registry's atomic update: clear owner and
            // recompute status against the EXISTING attempt_count. Release
            // does NOT increment — the claim that picked the row up already
            // counted this attempt (mirrors Go's EntService.ReleaseJob).
            // Tests can pre-seed `attempt_count` to drive the exhausted
            // branch.
            let mut jobs = self.jobs.lock().unwrap();
            let (status, attempt_count) = if let Some(j) = jobs.get_mut(job_id) {
                j.owner_instance_id = None;
                if j.attempt_count > j.max_retries {
                    j.status = JobStatus::Failed;
                }
                (j.status, j.attempt_count)
            } else {
                (JobStatus::Working, 0)
            };
            Ok(ReleaseJobResponse {
                status,
                attempt_count,
            })
        }

        async fn list_job_events(
            &self,
            job_id: &str,
            after: i64,
            types: Option<&[String]>,
            _wait: Duration,
            limit: usize,
            identity: Option<(&str, i64)>,
        ) -> Result<JobEventListResponse, BackendError> {
            // Record the identity so tests can assert executor-vs-observer.
            self.list_identities.lock().unwrap().push(
                identity.map(|(inst, epoch)| (inst.to_string(), epoch)),
            );
            if self.events_list_returns_not_found.load(Ordering::SeqCst) == 1 {
                return Err(BackendError::NotFound(job_id.to_string()));
            }
            // Executor read: fence against the job's current owner + epoch,
            // mirroring the registry's AuthorizeExecutorRead. Terminal jobs
            // never fence (safe post-completion polling); a live job whose
            // (owner, epoch) no longer matches → 409 claim_superseded.
            if let Some((inst, epoch)) = identity {
                if let Some(j) = self.jobs.lock().unwrap().get(job_id) {
                    if !j.status.is_terminal() {
                        let owner_ok =
                            j.owner_instance_id.as_deref() == Some(inst);
                        let epoch_ok = self.current_epoch(job_id) == epoch;
                        if !owner_ok || !epoch_ok {
                            return Err(BackendError::ClaimSuperseded(
                                crate::task_backend::CLAIM_SUPERSEDED_REASON
                                    .to_string(),
                            ));
                        }
                    }
                }
            }
            let all = self.events.lock().unwrap();
            let list = match all.get(job_id) {
                Some(l) => l,
                None => {
                    // No events yet for this job — registry returns empty
                    // (NOT NotFound — `not found` is the job-row state).
                    return Ok(JobEventListResponse {
                        events: vec![],
                        next_after: after,
                    });
                }
            };
            let mut out: Vec<JobEvent> = list
                .iter()
                .filter(|e| e.seq > after)
                .filter(|e| match types {
                    Some(ts) if !ts.is_empty() => ts.iter().any(|t| t == &e.event_type),
                    _ => true,
                })
                .take(limit)
                .cloned()
                .collect();
            // Default `next_after` to the caller's watermark when nothing
            // matched; otherwise advance to the last returned seq.
            let next_after = out.last().map(|e| e.seq).unwrap_or(after);
            // Mock semantics: no actual long-poll. Tests that need wait
            // behaviour drive the clock manually.
            // (We don't drain — list_job_events is read-only.)
            out.shrink_to_fit();
            Ok(JobEventListResponse {
                events: out,
                next_after,
            })
        }

        async fn post_job_event(
            &self,
            job_id: &str,
            event_type: &str,
            payload: Option<serde_json::Value>,
            trace_context: Option<serde_json::Value>,
        ) -> Result<crate::task_backend::JobEventReceipt, BackendError> {
            if self.events_post_returns_conflict.load(Ordering::SeqCst) == 1 {
                return Err(BackendError::Conflict(
                    "job is in a terminal state (mock)".into(),
                ));
            }
            self.event_posts.lock().unwrap().push((
                job_id.to_string(),
                event_type.to_string(),
                payload.clone(),
                trace_context.clone(),
            ));
            let mut all = self.events.lock().unwrap();
            let list = all.entry(job_id.to_string()).or_default();
            let seq = (list.len() as i64) + 1;
            let created_at = 1700000000 + seq;
            list.push(JobEvent {
                job_id: job_id.to_string(),
                seq,
                event_type: event_type.to_string(),
                payload,
                trace_context,
                posted_by: None,
                created_at,
            });
            Ok(crate::task_backend::JobEventReceipt {
                job_id: job_id.to_string(),
                seq,
                created_at,
            })
        }
    }

    // ---- tests --------------------------------------------------------------

    #[tokio::test]
    async fn update_progress_coalesces_same_job_id() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let ctrl = JobController::new(
            "j1".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        ctrl.update_progress(0.1, Some("a".into())).await;
        ctrl.update_progress(0.5, Some("b".into())).await;
        ctrl.update_progress(0.9, Some("c".into())).await;
        let q = queue.lock().await;
        assert_eq!(q.len(), 1);
        let pending = q.pending.get("j1").unwrap();
        assert_eq!(pending.progress, Some(0.9));
        assert_eq!(pending.progress_message.as_deref(), Some("c"));
    }

    #[tokio::test]
    async fn batching_tick_drains_and_calls_backend() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let ctrl = JobController::new(
            "j-tick".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        ctrl.update_progress(0.25, None).await;

        let handle = spawn_batching_tick(
            queue.clone(),
            backend.clone() as Arc<dyn TaskBackend>,
            "inst-1".to_string(),
            BatchingConfig {
                interval: Duration::from_millis(80),
            },
        );

        // Wait for at least one flush.
        sleep(Duration::from_millis(250)).await;
        handle.shutdown().await;

        assert!(
            backend.batch_count() >= 1,
            "expected >= 1 batch, got {}",
            backend.batch_count()
        );
        let q = queue.lock().await;
        assert_eq!(q.len(), 0, "queue should be drained");
    }

    #[tokio::test]
    async fn complete_flushes_immediately_and_writes_terminal() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        // Pre-create the job so the mock has somewhere to apply the delta.
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        ctrl.update_progress(0.4, None).await;
        ctrl.complete(serde_json::json!({"ans": 42})).await.unwrap();

        // Pending progress should have been discarded by the terminal.
        let q = queue.lock().await;
        assert_eq!(q.len(), 0);
        drop(q);

        // Backend should have seen exactly one batch (the terminal one).
        assert_eq!(backend.batch_count(), 1);
        let (instance, deltas) = backend.last_batch().unwrap();
        assert_eq!(instance, "inst-1");
        assert_eq!(deltas.len(), 1);
        assert!(deltas[0].is_terminal());
        assert_eq!(deltas[0].status, Some(JobStatus::Completed));

        // get_job should reflect the terminal state.
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.status, JobStatus::Completed);
        assert_eq!(job.result, Some(serde_json::json!({"ans": 42})));
    }

    #[tokio::test]
    async fn request_input_flushes_immediately_non_terminal() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        // A pending progress delta should be evicted by request_input so it
        // can't land after the input_required transition.
        ctrl.update_progress(0.4, Some("pre".into())).await;
        ctrl.request_input(Some("need approval".into()))
            .await
            .unwrap();

        // Queue drained (pending progress evicted under the lock).
        {
            let q = queue.lock().await;
            assert_eq!(q.len(), 0);
        }

        // Exactly one batch flushed immediately — the input_required delta.
        assert_eq!(backend.batch_count(), 1);
        let (instance, deltas) = backend.last_batch().unwrap();
        assert_eq!(instance, "inst-1");
        assert_eq!(deltas.len(), 1);
        assert_eq!(deltas[0].status, Some(JobStatus::InputRequired));
        assert_eq!(deltas[0].progress_message.as_deref(), Some("need approval"));
        // NON-terminal: the controller stays live.
        assert!(!deltas[0].is_terminal());
        assert!(!ctrl.is_terminal().await);

        // Registry reflects input_required + the prompt on progress_message.
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.status, JobStatus::InputRequired);
        assert_eq!(job.progress_message.as_deref(), Some("need approval"));

        // The controller is still usable: complete() works from
        // input_required (mirrors the registry's accepted transition).
        ctrl.complete(serde_json::json!({"ok": true})).await.unwrap();
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.status, JobStatus::Completed);
    }

    #[tokio::test]
    async fn request_input_after_terminal_is_guarded() {
        // A helper task calling request_input AFTER the controller went
        // terminal (complete/fail) must NOT submit a late input_required
        // delta — mirrors the update_progress/release_lease terminal guard.
        // request_input returns a Result, so the guard surfaces JobTerminal
        // (same variant send_event raises) rather than dropping silently.
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );

        ctrl.complete(serde_json::json!({"done": true})).await.unwrap();
        assert!(ctrl.is_terminal().await);
        // Exactly one batch so far — the terminal one.
        assert_eq!(backend.batch_count(), 1);

        // Late request_input: must be rejected with JobTerminal and must
        // NOT submit another batch.
        let err = ctrl
            .request_input(Some("too late".into()))
            .await
            .unwrap_err();
        assert!(
            matches!(err, JobError::JobTerminal(_)),
            "expected JobTerminal, got {:?}",
            err
        );

        // No additional batch flushed — the registry never saw a
        // post-terminal input_required delta.
        assert_eq!(backend.batch_count(), 1);
        let (_, deltas) = backend.last_batch().unwrap();
        assert!(deltas[0].is_terminal());

        // Job status unchanged — still Completed, not InputRequired.
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.status, JobStatus::Completed);
    }

    #[tokio::test]
    async fn complete_preserves_last_progress_message_from_pending() {
        // Issue #880: complete() must fold the pending progress_message
        // into the terminal delta so the registry's progress_message
        // column reflects the LAST update_progress call, not the one
        // that happened to flush via the batching tick most recently.
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );

        // Two progress updates, the second is the "last word".
        ctrl.update_progress(0.5, Some("section 6/7".into())).await;
        ctrl.update_progress(1.0, Some("section 7/7".into())).await;
        // No batching tick runs in this test — pending still has 7/7.
        ctrl.complete(serde_json::json!({"ans": 42})).await.unwrap();

        // Backend received exactly one batch (the terminal one), and
        // the terminal delta carries progress_message="section 7/7".
        assert_eq!(backend.batch_count(), 1);
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas.len(), 1);
        assert!(deltas[0].is_terminal());
        assert_eq!(deltas[0].status, Some(JobStatus::Completed));
        assert_eq!(
            deltas[0].progress_message.as_deref(),
            Some("section 7/7"),
            "terminal delta must carry the last update_progress message",
        );

        // And the mock-applied state reflects it (registry would too).
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.progress_message.as_deref(), Some("section 7/7"));
    }

    #[tokio::test]
    async fn fail_preserves_last_progress_from_pending() {
        // Issue #880 (follow-up): fail() builds a terminal delta with
        // `progress: None`, so without harvesting the pending progress
        // value we'd lose the last numeric progress (e.g. 0.99) along
        // with the message when the batching tick hadn't fired yet.
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );

        // Last update_progress before fail is the "last word".
        ctrl.update_progress(0.5, Some("section 6/7".into())).await;
        ctrl.update_progress(0.99, Some("section 7/7".into())).await;
        // No batching tick runs in this test — pending still has 7/7 / 0.99.
        ctrl.fail("backend exploded").await.unwrap();

        // Backend received exactly one batch (the terminal one), and the
        // terminal delta carries BOTH the last progress_message and the
        // last numeric progress.
        assert_eq!(backend.batch_count(), 1);
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas.len(), 1);
        assert!(deltas[0].is_terminal());
        assert_eq!(deltas[0].status, Some(JobStatus::Failed));
        assert_eq!(
            deltas[0].progress_message.as_deref(),
            Some("section 7/7"),
            "terminal fail() delta must carry the last update_progress message",
        );
        assert_eq!(
            deltas[0].progress,
            Some(0.99),
            "terminal fail() delta must carry the last update_progress numeric value",
        );

        // Mock-applied state reflects it (registry would too).
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.progress_message.as_deref(), Some("section 7/7"));
        assert_eq!(job.progress, Some(0.99));
    }

    #[tokio::test]
    async fn post_terminal_progress_is_dropped() {
        // After flush_terminal marks a job, any racing update_progress
        // must NOT land in the queue (would push stale progress to the
        // registry on the next batching tick — see CoalescingQueue
        // docs for the invariant).
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );

        ctrl.complete(serde_json::json!({"done": true})).await.unwrap();
        // is_terminal() reflects the post-flush state.
        assert!(ctrl.is_terminal().await);

        // Late progress: must be silently dropped.
        ctrl.update_progress(0.99, Some("late".into())).await;

        let q = queue.lock().await;
        assert_eq!(q.len(), 0, "queue must stay empty after terminal");
        drop(q);

        // Backend saw only the terminal batch — no stale progress.
        assert_eq!(backend.batch_count(), 1);
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas.len(), 1);
        assert!(deltas[0].is_terminal());
    }

    /// Issue #1166 LOW: the terminal sentinel is per-controller, not
    /// queue-resident. On the claim-worker path one queue is shared
    /// across all controllers — a queue-lived `HashSet<job_id>` would
    /// (a) retain one string per completed job forever and (b) wrongly
    /// block progress from a NEW controller that re-claims a previously
    /// completed job_id. A fresh controller for the same job_id on the
    /// same shared queue must be able to enqueue progress.
    #[tokio::test]
    async fn terminal_guard_is_per_controller_not_shared_queue() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();

        let first_attempt = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        first_attempt
            .complete(serde_json::json!({"done": true}))
            .await
            .unwrap();
        assert!(first_attempt.is_terminal().await);

        // Same job_id re-claimed: a NEW controller on the SAME queue.
        let second_attempt = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );
        assert!(
            !second_attempt.is_terminal().await,
            "fresh controller must start non-terminal"
        );
        second_attempt.update_progress(0.5, Some("retry".into())).await;
        {
            let q = queue.lock().await;
            assert_eq!(
                q.len(),
                1,
                "fresh controller's progress must reach the shared queue"
            );
        }

        // The first controller's clone still drops late progress.
        let clone_of_first = first_attempt.clone();
        assert!(clone_of_first.is_terminal().await);
    }

    #[tokio::test]
    async fn release_lease_marks_terminal_locally_so_no_post_release_progress() {
        // After release_lease(), any racing update_progress must be
        // dropped — we've voluntarily handed ownership back, and a stale
        // progress delta arriving at the registry after a peer replica
        // claims the row would either be rejected as `not_owner` or, in
        // a concurrency window, stomp on the peer's in-flight attempt.
        // Mirrors the flush_terminal pattern from #880.
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: Some(3),
                max_duration: None,
                total_deadline: None,
                owner_instance_id: Some("inst-1".into()),
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue.clone(),
        );

        let release_resp = ctrl
            .release_lease(Some("OSError: connection refused".into()))
            .await
            .unwrap();
        // Within budget → status stays working. attempt_count UNCHANGED —
        // claim already counted this attempt; release does NOT increment.
        assert_eq!(release_resp.status, JobStatus::Working);
        assert_eq!(release_resp.attempt_count, 0);

        // Local terminal sentinel set so post-release update_progress is dropped.
        assert!(ctrl.is_terminal().await);

        // A racing update_progress lands AFTER release: queue must remain empty.
        ctrl.update_progress(0.99, Some("ghost".into())).await;
        let q = queue.lock().await;
        assert_eq!(q.len(), 0, "post-release progress delta must be dropped");
    }

    #[tokio::test]
    async fn release_lease_calls_backend_with_correct_reason() {
        // The reason argument must reach the backend verbatim — the
        // registry uses it to build the exhausted-error message when
        // the row's existing attempt_count is already past max_retries
        // (release does NOT increment; claim already counted the attempt).
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: Some(2),
                max_duration: None,
                total_deadline: None,
                owner_instance_id: Some("inst-7".into()),
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-7".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue,
        );
        ctrl.release_lease(Some("ConnectionError: refused".into()))
            .await
            .unwrap();

        let releases = backend.releases.lock().unwrap();
        assert_eq!(releases.len(), 1);
        let (job_id, instance_id, reason) = &releases[0];
        assert_eq!(job_id, &resp.id);
        assert_eq!(instance_id, "inst-7");
        assert_eq!(reason.as_deref(), Some("ConnectionError: refused"));
    }

    #[tokio::test]
    async fn fail_writes_terminal_failed() {
        let backend = MockBackend::new();
        let queue = new_coalescing_queue();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "inst-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let ctrl = JobController::new(
            resp.id.clone(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue,
        );
        ctrl.fail("upstream_unavailable").await.unwrap();
        let job = backend.get_job(&resp.id).await.unwrap();
        assert_eq!(job.status, JobStatus::Failed);
        assert_eq!(job.error.as_deref(), Some("upstream_unavailable"));
    }

    #[tokio::test]
    async fn submit_job_returns_proxy() {
        let backend = MockBackend::new() as Arc<dyn TaskBackend>;
        let (proxy, resp) = submit_job(
            backend.clone(),
            SubmitJobArgs {
                capability: "plan_trip".into(),
                payload: serde_json::json!({"user": "x"}),
                submitted_by: "client-1".into(),
                owner_instance_id: Some("replica-2".into()),
                max_duration: Some(120),
                max_retries: Some(1),
                total_deadline: None,
            },
        )
        .await
        .unwrap();
        assert_eq!(proxy.job_id(), resp.id);
        assert_eq!(resp.status, JobStatus::Working);
        assert_eq!(resp.owner_instance_id.as_deref(), Some("replica-2"));
    }

    #[tokio::test]
    async fn proxy_wait_polls_until_terminal() {
        let backend = MockBackend::new();
        // Create a job, then auto-complete it on the 3rd get_job.
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        backend.set_terminal_after(3);
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let result = proxy.wait(Some(Duration::from_secs(5))).await.unwrap();
        assert!(result.get("ok").is_some());
    }

    #[tokio::test]
    async fn proxy_wait_honors_timeout() {
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        // Never auto-completes. Short timeout should fire.
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let err = proxy
            .wait(Some(Duration::from_millis(300)))
            .await
            .unwrap_err();
        assert!(matches!(err, JobError::Timeout(_)));
    }

    #[tokio::test]
    async fn proxy_wait_rides_through_transient_errors_then_succeeds() {
        // Simulates a brief registry blip mid-poll: first 3 get_job calls
        // return BackendUnavailable, then normal handling resumes and
        // the job auto-completes on call 5.
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        backend.set_transient_for_n_calls(3);
        backend.set_terminal_after(5);
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        // Generous timeout: backoff is 200/400/800/1600/3200ms = ~6.2s worst case.
        let result = proxy.wait(Some(Duration::from_secs(15))).await.unwrap();
        assert!(result.get("ok").is_some());
    }

    #[tokio::test]
    async fn proxy_wait_returns_registry_unreachable_after_window() {
        // Registry never recovers — wait should give up with
        // RegistryUnreachable after the configured window (not Timeout).
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        backend.set_always_transient(true);
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let cfg = WaitConfig {
            timeout: Some(Duration::from_secs(30)), // wider than the unreachable window
            registry_unreachable_max: Duration::from_millis(300),
        };
        let err = proxy.wait_with_config(cfg).await.unwrap_err();
        match err {
            JobError::RegistryUnreachable { duration } => {
                assert!(
                    duration >= Duration::from_millis(300),
                    "expected duration >= 300ms, got {:?}",
                    duration
                );
            }
            other => panic!("expected RegistryUnreachable, got {:?}", other),
        }
    }

    #[tokio::test]
    async fn proxy_wait_propagates_non_transient_errors_immediately() {
        // 404 NotFound is non-transient — must surface on the first
        // failed poll without waiting out any window.
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        backend.set_always_not_found(true);
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let started = std::time::Instant::now();
        let err = proxy
            .wait_with_config(WaitConfig {
                timeout: Some(Duration::from_secs(30)),
                registry_unreachable_max: Duration::from_secs(60),
            })
            .await
            .unwrap_err();
        assert!(
            matches!(err, JobError::Backend(BackendError::NotFound(_))),
            "expected immediate NotFound propagation, got {:?}",
            err
        );
        // Should fail on the very first poll — well under any backoff window.
        assert!(
            started.elapsed() < Duration::from_secs(1),
            "non-transient errors must propagate immediately, took {:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn proxy_wait_window_resets_on_successful_poll() {
        // Two transient blips separated by a successful poll — the second
        // blip should NOT see the timer carried over from the first.
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        // Sequence: blip, blip, ok, blip, ok, then auto-terminal.
        backend.set_transient_for_n_calls(2);
        // After two blips comes ok. To insert another blip after that we'd
        // need a more elaborate harness — instead just verify two blips +
        // recovery succeeds with a tight window that wouldn't cover both
        // blips end-to-end if the timer didn't reset.
        backend.set_terminal_after(4); // call 4 trips terminal
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let cfg = WaitConfig {
            timeout: Some(Duration::from_secs(15)),
            registry_unreachable_max: Duration::from_millis(800),
        };
        // Backoff after blips: 200, 400 = 600ms — fits inside 800ms window.
        // If we never reset on success, accumulated transient time stays
        // > 0 for the rest of the wait, but no further blips happen so
        // this still passes. The real "reset" guarantee is exercised by
        // the assertion that we DON'T return RegistryUnreachable here.
        let result = proxy.wait_with_config(cfg).await.unwrap();
        assert!(result.get("ok").is_some());
    }

    #[tokio::test]
    async fn proxy_cancel_calls_backend() {
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let proxy = JobProxy::new(resp.id.clone(), backend.clone() as Arc<dyn TaskBackend>);
        proxy.cancel(Some("user_requested".into())).await.unwrap();
        assert_eq!(backend.cancel_count(), 1);
        let cancels = backend.cancels.lock().unwrap();
        assert_eq!(cancels[0].0, resp.id);
        assert_eq!(cancels[0].1.as_deref(), Some("user_requested"));
    }

    #[tokio::test]
    async fn run_cancellable_returns_value_when_no_context() {
        let r = run_cancellable(async { 42 }).await;
        assert!(matches!(r, Ok(42)));
    }

    #[tokio::test]
    async fn run_cancellable_aborts_on_token_fire() {
        let ctx = crate::job_context::JobContext::new("j1");
        let token = ctx.cancel_token.clone();
        let r = job_context::with_job(ctx, async {
            tokio::spawn(async move {
                sleep(Duration::from_millis(50)).await;
                token.cancel();
            });
            run_cancellable(async {
                sleep(Duration::from_secs(5)).await;
                "completed"
            })
            .await
        })
        .await;
        assert!(r.is_err(), "expected cancellation, got {:?}", r);
    }

    // ---- run_as_job tests ---------------------------------------------------

    fn unique_job_id(suffix: &str) -> String {
        format!("job-raj-{}-{}", uuid::Uuid::new_v4().simple(), suffix)
    }

    #[tokio::test]
    async fn run_as_job_binds_context_and_cleans_up() {
        let id = unique_job_id("bind");
        let ctx = JobContext::new(id.clone());
        let observed_id = run_as_job(ctx, async {
            // Inside the scope: context is active.
            let cur = job_context::current().expect("context should be active");
            // And the cancel-registry entry should exist (calling
            // cancel_active_job here returns true because we found it; we
            // only verify presence, not whether the token was already
            // cancelled — token cancellation is a separate concern from
            // registration).
            assert!(
                crate::cancel_registry::cancel_active_job(&cur.job_id),
                "registry entry should be present inside run_as_job scope"
            );
            cur.job_id
        })
        .await;
        assert_eq!(observed_id, id);

        // Outside the scope: context is gone AND registry entry is gone.
        assert!(job_context::current().is_none());
        assert!(
            !crate::cancel_registry::cancel_active_job(&id),
            "registry entry should have been cleaned up"
        );
    }

    #[tokio::test]
    async fn run_as_job_mid_flight_cancel_propagates() {
        let id = unique_job_id("midflight");
        let ctx = JobContext::new(id.clone());
        let id_for_canceller = id.clone();

        // Spawn an external canceller that fires after a brief delay.
        tokio::spawn(async move {
            sleep(Duration::from_millis(50)).await;
            let fired = crate::cancel_registry::cancel_active_job(&id_for_canceller);
            assert!(fired, "canceller should find the active job");
        });

        let outcome = run_as_job(ctx, async {
            let token = job_context::current().unwrap().cancel_token;
            tokio::select! {
                _ = sleep(Duration::from_secs(5)) => "completed",
                _ = token.cancelled() => "cancelled",
            }
        })
        .await;
        assert_eq!(outcome, "cancelled");

        // Registry should be clean.
        assert!(!crate::cancel_registry::cancel_active_job(&id));
    }

    #[tokio::test]
    async fn run_as_job_cleans_up_on_panic() {
        let id = unique_job_id("panic");
        let ctx = JobContext::new(id.clone());

        // Use catch_unwind via spawn so the panic doesn't tear down the test
        // task itself.
        let id_clone = id.clone();
        let join = tokio::spawn(async move {
            run_as_job(ctx, async {
                panic!("intentional panic for guard test");
            })
            .await
        });
        let result = join.await;
        assert!(result.is_err(), "spawned task should panic");

        // Even though body panicked, the guard should have removed the entry.
        assert!(
            !crate::cancel_registry::cancel_active_job(&id_clone),
            "registry entry must be removed even on panic"
        );
    }

    #[tokio::test]
    async fn proxy_wait_honors_parent_cancel() {
        let backend = MockBackend::new();
        let resp = backend
            .create_job(CreateJobRequest {
                capability: "cap".into(),
                submitted_payload: serde_json::json!({}),
                submitted_by: "client-1".into(),
                max_retries: None,
                max_duration: None,
                total_deadline: None,
                owner_instance_id: None,
            })
            .await
            .unwrap();
        let proxy = JobProxy::new(resp.id, backend.clone() as Arc<dyn TaskBackend>);
        let ctx = crate::job_context::JobContext::new("parent");
        let token = ctx.cancel_token.clone();
        let result = job_context::with_job(ctx, async {
            tokio::spawn(async move {
                sleep(Duration::from_millis(100)).await;
                token.cancel();
            });
            proxy.wait(None).await
        })
        .await;
        assert!(matches!(result, Err(JobError::Cancelled)));
    }

    // ---- recv_event / send_event tests --------------------------------------

    /// Build a working JobController against a fresh MockBackend with the
    /// given job_id pre-created in the backend's job map.
    async fn make_controller(job_id: &str) -> (Arc<MockBackend>, JobController) {
        let backend = MockBackend::new();
        backend.jobs.lock().unwrap().insert(
            job_id.to_string(),
            Job {
                id: job_id.to_string(),
                capability: "cap".into(),
                owner_instance_id: Some("inst-1".into()),
                status: JobStatus::Working,
                progress: None,
                progress_message: None,
                result: None,
                error: None,
                submitted_payload: serde_json::json!({}),
                attempt_count: 0,
                max_retries: 1,
                max_duration: None,
                total_deadline: None,
                lease_expires_at: None,
                last_heartbeat_at: None,
                submitted_at: 0,
                submitted_by: "client-1".into(),
            },
        );
        let queue = new_coalescing_queue();
        let ctrl = JobController::new(
            job_id.to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue,
        );
        (backend, ctrl)
    }

    /// Like [`make_controller`] but the controller carries `claim_epoch`
    /// and the mock's registry-side current epoch is seeded to `cur_epoch`
    /// so tests can drive the match / supersede branches.
    async fn make_controller_with_epoch(
        job_id: &str,
        claim_epoch: Option<i64>,
        cur_epoch: i64,
    ) -> (Arc<MockBackend>, JobController) {
        let (backend, _legacy) = make_controller(job_id).await;
        backend.set_current_epoch(job_id, cur_epoch);
        let ctrl = JobController::new_with_epoch(
            job_id.to_string(),
            "inst-1".to_string(),
            claim_epoch,
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        (backend, ctrl)
    }

    // ---- claim-epoch / supersession tests -----------------------------------

    #[test]
    fn claim_epoch_accessor_reflects_construction() {
        let backend = MockBackend::new();
        let with_epoch = JobController::new_with_epoch(
            "j-e",
            "inst-1",
            Some(7),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        assert_eq!(with_epoch.claim_epoch(), Some(7));
        let legacy = JobController::new(
            "j-e2",
            "inst-1",
            backend as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        assert_eq!(legacy.claim_epoch(), None);
    }

    #[tokio::test]
    async fn deltas_carry_claim_epoch_when_present() {
        // A controller carrying an epoch stamps it onto the deltas it
        // flushes so the registry can fence a superseded owner. The terminal
        // delta (flushed immediately by complete) is the deterministic probe;
        // progress deltas go through the same stamping in update_progress.
        let (backend, ctrl) = make_controller_with_epoch("j-delta-epoch", Some(3), 3).await;
        ctrl.complete(serde_json::json!({"ok": true})).await.unwrap();
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas.len(), 1);
        assert_eq!(
            deltas[0].claim_epoch,
            Some(3),
            "terminal delta must carry the controller's claim epoch"
        );
    }

    #[tokio::test]
    async fn legacy_controller_omits_epoch_on_deltas() {
        // A controller with no epoch (push-mode / old registry) sends
        // deltas with claim_epoch=None — byte-identical legacy behavior.
        let (backend, ctrl) = make_controller("j-delta-legacy").await;
        ctrl.complete(serde_json::json!({"ok": true})).await.unwrap();
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas[0].claim_epoch, None);
    }

    #[tokio::test]
    async fn recv_event_sends_executor_identity_when_epoch_present() {
        // The owner's controller supplies (instance_id, claim_epoch) on the
        // event read so the registry fences + lease-extends.
        let (backend, ctrl) = make_controller_with_epoch("j-recv-exec", Some(4), 4).await;
        backend.push_event("j-recv-exec", "tick", serde_json::json!({}));
        let ev = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .expect("event");
        assert_eq!(ev.seq, 1);
        let ids = backend.list_identities();
        assert!(
            ids.iter().all(|i| *i == Some(("inst-1".to_string(), 4))),
            "executor reads must carry (inst-1, 4); got {:?}",
            ids
        );
    }

    #[tokio::test]
    async fn recv_event_legacy_controller_reads_anonymously() {
        // No epoch → anonymous observer read (no identity params).
        let (backend, ctrl) = make_controller("j-recv-anon").await;
        backend.push_event("j-recv-anon", "tick", serde_json::json!({}));
        ctrl.recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .expect("event");
        let ids = backend.list_identities();
        assert!(
            ids.iter().all(|i| i.is_none()),
            "legacy controller must read anonymously; got {:?}",
            ids
        );
    }

    #[tokio::test]
    async fn proxy_list_events_is_anonymous_observer() {
        // JobProxy is the observer path — never sends executor identity.
        let backend = MockBackend::new();
        backend.push_event("j-proxy-anon", "tick", serde_json::json!({}));
        let proxy = JobProxy::new("j-proxy-anon", backend.clone() as Arc<dyn TaskBackend>);
        proxy.list_events(0, None, None).await.unwrap();
        let ids = backend.list_identities();
        assert_eq!(ids, vec![None]);
    }

    #[tokio::test]
    async fn supersession_fires_only_superseded_frame_not_healthy_reclaim() {
        // Issue #1252 review, item 1 — the critical same-instance re-claim
        // shape (every single-replica deployment). Two live frames under one
        // job_id: the zombie H1 (epoch 1) UNDER the fresh healthy H2 (epoch
        // 2, top-of-stack). H1's stale terminal delta is rejected
        // claim_superseded; the cancel MUST fire ONLY H1's frame (by epoch),
        // never the top-of-stack — else H2 dies spuriously while the zombie
        // keeps running.
        let (_backend, h1_ctrl) =
            make_controller_with_epoch("j-reclaim", Some(1), 2).await;
        let h1_token = CancellationToken::new();
        let h2_token = CancellationToken::new();
        let g1 = cancel_registry::register_active_job_with_epoch(
            "j-reclaim",
            h1_token.clone(),
            Some(1),
        );
        let g2 = cancel_registry::register_active_job_with_epoch(
            "j-reclaim",
            h2_token.clone(),
            Some(2),
        );

        // H1 (epoch 1) posts its terminal delta → mock's current epoch is 2
        // → rejected claim_superseded → fire H1's frame only.
        h1_ctrl
            .complete(serde_json::json!({"ok": true}))
            .await
            .unwrap();

        assert!(
            h1_token.is_cancelled(),
            "the superseded zombie H1 (epoch 1) must be cancelled"
        );
        assert!(
            !h2_token.is_cancelled(),
            "the healthy re-claim H2 (epoch 2, top-of-stack) must be UNTOUCHED"
        );

        cancel_registry::unregister_active_job("j-reclaim", g1);
        cancel_registry::unregister_active_job("j-reclaim", g2);
    }

    #[tokio::test]
    async fn is_cancelled_reads_own_epoch_frame_not_top_of_stack() {
        // Issue #1252 review (Java path): `controller.is_cancelled()` is the
        // ONLY supersession-observation surface for a CPU-bound handler that
        // can't be interrupted by a Tokio token. It MUST read this
        // execution's OWN frame. Same-instance re-claim: H1 (epoch 1) UNDER
        // H2 (epoch 2, top). When H1's frame is fired, H1's controller must
        // see is_cancelled()==true while H2's controller stays false.
        let backend = MockBackend::new();
        backend.jobs.lock().unwrap().insert(
            "j-iscancel".to_string(),
            Job {
                id: "j-iscancel".to_string(),
                capability: "cap".into(),
                owner_instance_id: Some("inst-1".into()),
                status: JobStatus::Working,
                progress: None,
                progress_message: None,
                result: None,
                error: None,
                submitted_payload: serde_json::json!({}),
                attempt_count: 0,
                max_retries: 1,
                max_duration: None,
                total_deadline: None,
                lease_expires_at: None,
                last_heartbeat_at: None,
                submitted_at: 0,
                submitted_by: "client-1".into(),
            },
        );
        let h1_ctrl = JobController::new_with_epoch(
            "j-iscancel",
            "inst-1",
            Some(1),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        let h2_ctrl = JobController::new_with_epoch(
            "j-iscancel",
            "inst-1",
            Some(2),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );

        // Register both execution frames (H1 under H2). The frame tokens are
        // what is_cancelled() observes.
        let h1_token = CancellationToken::new();
        let h2_token = CancellationToken::new();
        let g1 = cancel_registry::register_active_job_with_epoch(
            "j-iscancel",
            h1_token.clone(),
            Some(1),
        );
        let g2 = cancel_registry::register_active_job_with_epoch(
            "j-iscancel",
            h2_token.clone(),
            Some(2),
        );

        // Nothing fired yet.
        assert!(!h1_ctrl.is_cancelled().await);
        assert!(!h2_ctrl.is_cancelled().await);

        // Supersede H1 (epoch 1) — fires only H1's frame.
        assert!(cancel_registry::cancel_superseded("j-iscancel", 1));

        assert!(
            h1_ctrl.is_cancelled().await,
            "superseded H1 must observe its own frame fired"
        );
        assert!(
            !h2_ctrl.is_cancelled().await,
            "healthy H2 (top-of-stack) must NOT read cancelled"
        );

        cancel_registry::unregister_active_job("j-iscancel", g1);
        cancel_registry::unregister_active_job("j-iscancel", g2);
    }

    #[tokio::test]
    async fn recv_event_supersession_fires_cancel_and_returns_cancelled() {
        // Controller carries epoch 1 but the registry bumped the current
        // generation to 2 (a reclaim + fresh claim). The executor read is
        // fenced → 409 claim_superseded → recv_event fires the job's cancel
        // token and returns Cancelled (indistinguishable from user cancel).
        let (backend, ctrl) = make_controller_with_epoch("j-super", Some(1), 2).await;
        backend.push_event("j-super", "tick", serde_json::json!({}));
        // Register the job so the fired cancel is observable (as run_as_job
        // would in production). Frame carries this execution's epoch (1) so
        // the epoch-keyed supersession fires it.
        let token = CancellationToken::new();
        let generation =
            cancel_registry::register_active_job_with_epoch("j-super", token.clone(), Some(1));

        let started = Instant::now();
        let err = ctrl
            .recv_event(None, Some(Duration::from_secs(5)))
            .await
            .unwrap_err();
        assert!(
            matches!(err, JobError::Cancelled),
            "supersession must surface as Cancelled, got {:?}",
            err
        );
        assert!(token.is_cancelled(), "supersession must fire the cancel token");
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "must return promptly, took {:?}",
            started.elapsed()
        );
        cancel_registry::unregister_active_job("j-super", generation);
    }

    #[tokio::test]
    async fn batch_superseded_rejection_fires_cancel() {
        // A terminal (or progress) delta rejected claim_superseded on
        // /jobs/batch drives the SAME cancel path as an executor-read 409.
        let (backend, ctrl) = make_controller_with_epoch("j-batch-super", Some(1), 2).await;
        let token = CancellationToken::new();
        let generation = cancel_registry::register_active_job_with_epoch(
            "j-batch-super",
            token.clone(),
            Some(1),
        );

        // complete() flushes a terminal delta immediately; the mock rejects
        // it (epoch 1 != current 2, job still non-terminal) as
        // claim_superseded. flush_terminal still returns Ok — the cancel is
        // the surfacing mechanism.
        ctrl.complete(serde_json::json!({"ok": true})).await.unwrap();
        assert!(
            token.is_cancelled(),
            "a claim_superseded batch rejection must fire the cancel token"
        );
        // The delta was rejected, not applied.
        let (_, deltas) = backend.last_batch().unwrap();
        assert_eq!(deltas[0].claim_epoch, Some(1));
        cancel_registry::unregister_active_job("j-batch-super", generation);
    }

    // Multi-thread flavor: the mock's `list_job_events` returns instantly,
    // so `recv_event` becomes a CPU hot-loop (a real registry long-poll is a
    // pending future). On a single-threaded runtime that starves the timer
    // driver and the canceller task never fires. A real deployment never hot-
    // loops; the multi-thread runtime lets the concurrent canceller run so
    // this exercises the per-iteration cancel check + prompt return.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn recv_event_long_poll_interrupts_on_user_cancel() {
        // Regression for the blocked-gate case: a handler parked in
        // recv_event with no events must break out promptly when the job's
        // cancel token fires (user cancel), returning Cancelled rather than
        // running to the full timeout. Uses a legacy (no-epoch) controller
        // so this is pure user-cancel, no supersession.
        let (_backend, ctrl) = make_controller("j-longpoll-cancel").await;
        let token = CancellationToken::new();
        let generation =
            cancel_registry::register_active_job("j-longpoll-cancel", token.clone());

        let ctrl_clone = ctrl.clone();
        let recv = tokio::spawn(async move {
            ctrl_clone
                .recv_event(None, Some(Duration::from_secs(10)))
                .await
        });
        // Fire the cancel shortly after the recv parks.
        sleep(Duration::from_millis(80)).await;
        assert!(cancel_registry::cancel_active_job("j-longpoll-cancel"));

        let started = Instant::now();
        let result = tokio::time::timeout(Duration::from_secs(3), recv)
            .await
            .expect("recv_event must return after cancel")
            .unwrap();
        assert!(
            matches!(result, Err(JobError::Cancelled)),
            "user cancel must surface as Cancelled, got {:?}",
            result
        );
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "cancel must interrupt the poll promptly, took {:?}",
            started.elapsed()
        );
        cancel_registry::unregister_active_job("j-longpoll-cancel", generation);
    }

    #[tokio::test]
    async fn recv_event_returns_event_after_post() {
        // Pre-post an event then call recv_event — should see it on the
        // first poll without waiting out the timeout.
        let (backend, ctrl) = make_controller("j-recv-1").await;
        backend.push_event("j-recv-1", "extend_deadline", serde_json::json!({"secs": 30}));

        let ev = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .expect("expected an event");
        assert_eq!(ev.seq, 1);
        assert_eq!(ev.event_type, "extend_deadline");
        assert_eq!(ev.payload, Some(serde_json::json!({"secs": 30})));
    }

    #[tokio::test]
    async fn recv_event_returns_none_on_timeout() {
        // No events posted — recv_event with a tight timeout returns
        // Ok(None). The mock's list_job_events doesn't actually long-poll
        // (returns immediately), so the recv loop spins through the
        // deadline within the requested budget.
        let (_backend, ctrl) = make_controller("j-recv-timeout").await;

        let result = ctrl
            .recv_event(None, Some(Duration::from_millis(150)))
            .await
            .unwrap();
        assert!(result.is_none(), "expected timeout (None), got {:?}", result);
    }

    #[tokio::test]
    async fn recv_event_filter_by_types() {
        // Three events with different types; recv_event(types=["B"])
        // should skip past A and return B (then on a follow-up, skip C).
        let (backend, ctrl) = make_controller("j-recv-filter").await;
        backend.push_event("j-recv-filter", "A", serde_json::json!({"n": 1}));
        backend.push_event("j-recv-filter", "B", serde_json::json!({"n": 2}));
        backend.push_event("j-recv-filter", "C", serde_json::json!({"n": 3}));

        let ev = ctrl
            .recv_event(Some(vec!["B".into()]), Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .expect("expected event of type B");
        assert_eq!(ev.event_type, "B");
        assert_eq!(ev.seq, 2);
    }

    #[tokio::test]
    async fn recv_event_increments_cursor_between_calls() {
        // Two successive calls return seq=1 then seq=2 — the cursor must
        // advance between calls so we don't replay the first event.
        let (backend, ctrl) = make_controller("j-recv-cursor").await;
        backend.push_event("j-recv-cursor", "tick", serde_json::json!({"n": 1}));
        backend.push_event("j-recv-cursor", "tick", serde_json::json!({"n": 2}));

        let first = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(first.seq, 1);

        let second = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.seq, 2);
    }

    #[tokio::test]
    async fn recv_event_new_controller_starts_from_zero() {
        // Cursor is per-instance: a freshly-constructed controller for the
        // same job_id replays from seq=0.
        let (backend, ctrl) = make_controller("j-recv-replay").await;
        backend.push_event("j-recv-replay", "tick", serde_json::json!({}));

        // First controller consumes the event.
        let first = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(first.seq, 1);

        // Second controller pointing at the same job + backend replays.
        let queue2 = new_coalescing_queue();
        let ctrl2 = JobController::new(
            "j-recv-replay".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            queue2,
        );
        let replayed = ctrl2
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(replayed.seq, 1);
    }

    #[tokio::test]
    async fn recv_event_clone_shares_cursor() {
        // Cloning the controller (e.g. into a helper task) must share the
        // cursor — otherwise the cloned handle would replay events the
        // original already consumed.
        let (backend, ctrl) = make_controller("j-recv-clone").await;
        backend.push_event("j-recv-clone", "tick", serde_json::json!({"n": 1}));
        backend.push_event("j-recv-clone", "tick", serde_json::json!({"n": 2}));

        let cloned = ctrl.clone();
        let first = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(first.seq, 1);

        // Clone picks up where the original left off.
        let second = cloned
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.seq, 2);
    }

    #[tokio::test]
    async fn recv_event_returns_error_on_job_not_found() {
        // Registry NotFound surfaces as JobError::Backend(NotFound(_)).
        let (backend, ctrl) = make_controller("j-recv-404").await;
        backend.set_events_list_not_found(true);

        let err = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap_err();
        assert!(
            matches!(err, JobError::Backend(BackendError::NotFound(_))),
            "expected Backend(NotFound), got {:?}",
            err
        );
    }

    #[tokio::test]
    async fn send_event_calls_backend_with_expected_args() {
        // send_event hits post_job_event verbatim — args reach the backend
        // unmodified and the receipt is propagated back.
        let backend = MockBackend::new();
        backend.jobs.lock().unwrap().insert(
            "j-send-1".to_string(),
            Job {
                id: "j-send-1".to_string(),
                capability: "cap".into(),
                owner_instance_id: None,
                status: JobStatus::Working,
                progress: None,
                progress_message: None,
                result: None,
                error: None,
                submitted_payload: serde_json::json!({}),
                attempt_count: 0,
                max_retries: 1,
                max_duration: None,
                total_deadline: None,
                lease_expires_at: None,
                last_heartbeat_at: None,
                submitted_at: 0,
                submitted_by: "client-1".into(),
            },
        );
        let proxy = JobProxy::new("j-send-1", backend.clone() as Arc<dyn TaskBackend>);
        let receipt = proxy
            .send_event(
                "extend_deadline".into(),
                serde_json::json!({"secs": 60}),
            )
            .await
            .unwrap();
        assert_eq!(receipt.job_id, "j-send-1");
        assert_eq!(receipt.seq, 1);

        let posts = backend.event_posts.lock().unwrap();
        assert_eq!(posts.len(), 1);
        assert_eq!(posts[0].0, "j-send-1");
        assert_eq!(posts[0].1, "extend_deadline");
        assert_eq!(posts[0].2, Some(serde_json::json!({"secs": 60})));
        // Trace context: not wired yet (TODO comment in send_event).
        // Pass-through-only — the wire field defaults to None.
        assert!(posts[0].3.is_none());
    }

    #[tokio::test]
    async fn send_event_returns_job_terminal_on_409() {
        // Registry returns 409 Conflict for events posted to terminal
        // jobs — send_event surfaces JobError::JobTerminal so callers can
        // match cleanly without inspecting strings.
        let backend = MockBackend::new();
        backend.set_events_post_conflict(true);
        let proxy = JobProxy::new("j-send-term", backend.clone() as Arc<dyn TaskBackend>);
        let err = proxy
            .send_event("anything".into(), serde_json::json!({}))
            .await
            .unwrap_err();
        assert!(
            matches!(err, JobError::JobTerminal(_)),
            "expected JobTerminal, got {:?}",
            err
        );
    }

    #[tokio::test]
    async fn send_event_then_recv_event_roundtrip() {
        // End-to-end: a proxy sends, a controller for the same job receives.
        // Validates the SDK's primary use case — out-of-band signalling
        // between an external sender and the in-flight handler.
        let (backend, ctrl) = make_controller("j-roundtrip").await;
        let proxy = JobProxy::new("j-roundtrip", backend.clone() as Arc<dyn TaskBackend>);

        // Post from the "outside" (proxy).
        let receipt = proxy
            .send_event("user_input".into(), serde_json::json!({"answer": "yes"}))
            .await
            .unwrap();
        assert_eq!(receipt.seq, 1);

        // The handler drains it from the "inside" (controller).
        let ev = ctrl
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(ev.event_type, "user_input");
        assert_eq!(ev.payload, Some(serde_json::json!({"answer": "yes"})));
        assert_eq!(ev.seq, 1);
    }

    #[tokio::test]
    async fn recv_event_concurrent_callers_get_distinct_events() {
        // Two concurrent `recv_event` calls on CLONES of the same controller
        // must NOT both return the same event. Without the
        // `recv_event_lock`, the AtomicI64 cursor prevents memory tearing
        // but NOT the read-fetch-write race across `.await`: caller A
        // loads after=0, issues list, gets seq=1; caller B loads after=0
        // (A hasn't stored yet), issues list, ALSO gets seq=1.
        //
        // With the per-controller `recv_event_lock`, callers serialise on
        // the load→list→store window so the second caller observes the
        // cursor A has advanced and picks up seq=2.
        let (backend, ctrl) = make_controller("j-recv-concurrent").await;
        backend.push_event("j-recv-concurrent", "tick", serde_json::json!({"n": 1}));
        backend.push_event("j-recv-concurrent", "tick", serde_json::json!({"n": 2}));

        let ctrl_a = ctrl.clone();
        let ctrl_b = ctrl.clone();
        let a = tokio::spawn(async move {
            ctrl_a
                .recv_event(None, Some(Duration::from_secs(2)))
                .await
                .unwrap()
                .unwrap()
        });
        let b = tokio::spawn(async move {
            ctrl_b
                .recv_event(None, Some(Duration::from_secs(2)))
                .await
                .unwrap()
                .unwrap()
        });
        let ev_a = a.await.unwrap();
        let ev_b = b.await.unwrap();

        // The two callers must observe DIFFERENT seqs — one gets 1, the
        // other gets 2. Order between them is not deterministic.
        assert_ne!(
            ev_a.seq, ev_b.seq,
            "concurrent callers must not return the same event seq",
        );
        let seen: std::collections::HashSet<i64> = [ev_a.seq, ev_b.seq].into_iter().collect();
        let want: std::collections::HashSet<i64> = [1, 2].into_iter().collect();
        assert_eq!(
            seen, want,
            "concurrent callers must collectively observe seqs {{1,2}}, got {:?}",
            seen
        );
    }

    #[tokio::test]
    async fn recv_event_lock_is_per_controller() {
        // Two SEPARATE JobController instances must NOT serialise against
        // each other — the lock is per-controller (matches the cursor
        // scope), so an A long-poll must never block B's progress.
        let backend = MockBackend::new();
        for jid in ["j-lock-a", "j-lock-b"] {
            backend.jobs.lock().unwrap().insert(
                jid.to_string(),
                Job {
                    id: jid.to_string(),
                    capability: "cap".into(),
                    owner_instance_id: Some("inst-1".into()),
                    status: JobStatus::Working,
                    progress: None,
                    progress_message: None,
                    result: None,
                    error: None,
                    submitted_payload: serde_json::json!({}),
                    attempt_count: 0,
                    max_retries: 1,
                    max_duration: None,
                    total_deadline: None,
                    lease_expires_at: None,
                    last_heartbeat_at: None,
                    submitted_at: 0,
                    submitted_by: "client-1".into(),
                },
            );
        }
        backend.push_event("j-lock-b", "tick", serde_json::json!({}));

        let ctrl_a = JobController::new(
            "j-lock-a".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        let ctrl_b = JobController::new(
            "j-lock-b".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );

        // Launch a long recv on A — no events, will time out.
        let a_handle = tokio::spawn(async move {
            ctrl_a
                .recv_event(None, Some(Duration::from_millis(500)))
                .await
        });
        // B should NOT be blocked; it has its own lock and an event ready.
        let start = std::time::Instant::now();
        let ev_b = ctrl_b
            .recv_event(None, Some(Duration::from_secs(2)))
            .await
            .unwrap()
            .expect("B should observe its event");
        let elapsed = start.elapsed();
        assert_eq!(ev_b.seq, 1);
        assert!(
            elapsed < Duration::from_millis(400),
            "controller B must not have serialised against A's long-poll \
             (elapsed={:?})",
            elapsed,
        );

        // Drain A.
        let _ = a_handle.await.unwrap();
    }

    // ---- JobProxy::list_events ---------------------------------------------
    //
    // `list_events` is the low-level batch primitive that the language
    // SDKs build their `subscribe_events` async-iterator semantics on top
    // of. Unlike `JobController::recv_event` it has NO per-call mutex (no
    // shared cursor), advances NO internal state, and returns the full
    // batch up to limit. Tests below pin those three differences.

    #[tokio::test]
    async fn list_events_returns_all_matching_events_in_one_call() {
        // Three events on the job; `list_events(after=0)` returns all three
        // in ascending-seq order (the batch shape `subscribe_events` relies on).
        let backend = MockBackend::new();
        backend.push_event("j-list-1", "tick", serde_json::json!({"n": 1}));
        backend.push_event("j-list-1", "tick", serde_json::json!({"n": 2}));
        backend.push_event("j-list-1", "tick", serde_json::json!({"n": 3}));

        let proxy = JobProxy::new("j-list-1", backend.clone() as Arc<dyn TaskBackend>);
        let (events, next_after) = proxy.list_events(0, None, None).await.unwrap();
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].seq, 1);
        assert_eq!(events[1].seq, 2);
        assert_eq!(events[2].seq, 3);
        assert_eq!(next_after, 3);
    }

    #[tokio::test]
    async fn list_events_honors_after_cursor() {
        // `after=1` skips seq=1; the caller-managed cursor pattern that
        // `subscribe_events` uses to avoid re-yielding observed events.
        let backend = MockBackend::new();
        backend.push_event("j-list-2", "tick", serde_json::json!({"n": 1}));
        backend.push_event("j-list-2", "tick", serde_json::json!({"n": 2}));
        backend.push_event("j-list-2", "tick", serde_json::json!({"n": 3}));

        let proxy = JobProxy::new("j-list-2", backend.clone() as Arc<dyn TaskBackend>);
        let (events, next_after) = proxy.list_events(1, None, None).await.unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].seq, 2);
        assert_eq!(events[1].seq, 3);
        assert_eq!(next_after, 3);
    }

    #[tokio::test]
    async fn list_events_filters_by_types() {
        // `types=["target"]` filters out unrelated event types — same
        // filter contract the registry's `types=` query param honours.
        let backend = MockBackend::new();
        backend.push_event("j-list-3", "ignore", serde_json::json!({"n": 1}));
        backend.push_event("j-list-3", "target", serde_json::json!({"n": 2}));
        backend.push_event("j-list-3", "ignore", serde_json::json!({"n": 3}));
        backend.push_event("j-list-3", "target", serde_json::json!({"n": 4}));

        let proxy = JobProxy::new("j-list-3", backend.clone() as Arc<dyn TaskBackend>);
        let (events, _next_after) = proxy
            .list_events(0, Some(vec!["target".into()]), None)
            .await
            .unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].seq, 2);
        assert_eq!(events[1].seq, 4);
    }

    #[tokio::test]
    async fn list_events_returns_empty_when_no_events() {
        // No events on the job → empty batch (NOT NotFound). The caller's
        // `subscribe_events` loop interprets this as "no events arrived
        // within the wait window".
        let backend = MockBackend::new();
        let proxy = JobProxy::new("j-list-empty", backend.clone() as Arc<dyn TaskBackend>);
        let (events, _next_after) = proxy.list_events(0, None, None).await.unwrap();
        assert!(events.is_empty());
    }

    #[tokio::test]
    async fn list_events_propagates_not_found_error() {
        // Registry-side NotFound (job reaped from registry) surfaces as
        // `JobError::Backend(NotFound(_))` — the SDK translates it to a
        // typed `JobNotFoundError` so `subscribe_events` callers can
        // terminate cleanly when the job is gone.
        let backend = MockBackend::new();
        backend.set_events_list_not_found(true);
        let proxy = JobProxy::new("j-list-404", backend.clone() as Arc<dyn TaskBackend>);
        let err = proxy.list_events(0, None, None).await.unwrap_err();
        assert!(
            matches!(err, JobError::Backend(BackendError::NotFound(_))),
            "expected Backend(NotFound), got {:?}",
            err
        );
    }

    #[tokio::test]
    async fn list_events_does_not_share_cursor_with_recv_event() {
        // Two independent observer cursors per proxy call: a `JobController`
        // recv_event consumes seq=1; a parallel `list_events(after=0)` MUST
        // still see seq=1 (subscribe_events observes events without
        // affecting the producer's recv_event cursor).
        let backend = MockBackend::new();
        backend.jobs.lock().unwrap().insert(
            "j-mixed".to_string(),
            Job {
                id: "j-mixed".to_string(),
                capability: "cap".into(),
                owner_instance_id: Some("inst-1".into()),
                status: JobStatus::Working,
                progress: None,
                progress_message: None,
                result: None,
                error: None,
                submitted_payload: serde_json::json!({}),
                attempt_count: 0,
                max_retries: 1,
                max_duration: None,
                total_deadline: None,
                lease_expires_at: None,
                last_heartbeat_at: None,
                submitted_at: 0,
                submitted_by: "client-1".into(),
            },
        );
        backend.push_event("j-mixed", "tick", serde_json::json!({"n": 1}));

        let ctrl = JobController::new(
            "j-mixed".to_string(),
            "inst-1".to_string(),
            backend.clone() as Arc<dyn TaskBackend>,
            new_coalescing_queue(),
        );
        let observed_by_recv = ctrl
            .recv_event(None, Some(Duration::from_secs(1)))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(observed_by_recv.seq, 1);

        // Observer-side: still sees seq=1 because `list_events` is
        // stateless wrt the producer's recv_event cursor.
        let proxy = JobProxy::new("j-mixed", backend.clone() as Arc<dyn TaskBackend>);
        let (observer_batch, _next_after) =
            proxy.list_events(0, None, None).await.unwrap();
        assert_eq!(observer_batch.len(), 1);
        assert_eq!(observer_batch[0].seq, 1);
    }
}
