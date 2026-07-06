//! Generic claim loop. The Rust core owns the loop, the per-language SDK
//! provides the [`ClaimDispatcher`] impl that knows how to look up the
//! tool handler and invoke it for the claimed job.
//!
//! Wakeup model: the loop sleeps on a `watch::Receiver<Option<u32>>`
//! published by [`crate::runtime::AgentRuntime`] from each fast
//! heartbeat. When the receiver yields `Some(n>0)`, the loop drains by
//! calling [`crate::task_backend::TaskBackend::claim_next`] until either
//! (a) the backend reports no more work or (b) the in-flight cap is
//! reached. Then it parks again.
//!
//! See `MESHJOB_DESIGN.org` → "Wire Protocol / HEAD heartbeat extension"
//! and "Architecture / Producer-side flow / Resched".
//!
//! # SDK boundary
//! The dispatcher is responsible for:
//! 1. Resolving the per-capability tool handler (language registry lookup).
//! 2. Constructing the [`crate::jobs::JobController`] (or its language
//!    analogue) and binding it to the user function via DDDI.
//! 3. Calling [`crate::jobs::run_as_job`] internally so [`crate::JobContext`]
//!    is bound for the body.
//! 4. Invoking the user function and translating completion → terminal
//!    `complete` / `fail` calls on the controller.
//!
//! The core does NOT touch any of those concerns — it just hands the
//! claimed payload + a fresh controller to the dispatcher.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tokio::sync::{watch, Mutex, Semaphore};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, trace, warn};

use crate::jobs::{CoalescingQueue, JobController};
use crate::task_backend::{ClaimedJob, TaskBackend};

// =============================================================================
// Public types
// =============================================================================

/// Outcome reported by the [`ClaimDispatcher`] for an individual job.
///
/// The dispatcher is expected to have already invoked the appropriate
/// terminal call on the [`JobController`] (`complete` / `fail`) before
/// returning. The variants are advisory — they let the worker emit
/// useful diagnostics without re-issuing terminal calls itself.
#[derive(Debug, Clone)]
pub enum DispatchOutcome {
    /// Dispatcher already called `controller.complete(...)`.
    Completed,
    /// Dispatcher already called `controller.fail(...)`.
    Failed,
    /// Unexpected: the dispatcher returned without calling a terminal.
    /// String carries a human-readable reason for diagnostics. The core
    /// may emit a sentinel `fail` itself in a future revision; for Phase 1
    /// this just logs.
    Errored(String),
}

/// Trait the SDK implements so the core's claim worker can dispatch to a
/// language-specific handler. Required `async fn` flavor (`async_trait`)
/// because tokio task spawn requires `'static + Send` futures.
#[async_trait]
pub trait ClaimDispatcher: Send + Sync {
    /// Run the user's tool function for the claimed job. The dispatcher
    /// receives a fresh [`JobController`] already bound to the claimed
    /// job's id (and the worker's `instance_id`).
    ///
    /// Implementations MUST call [`crate::jobs::run_as_job`] internally
    /// so the [`crate::JobContext`] is bound while the user function
    /// executes. Otherwise, outbound HTTP calls won't get the
    /// `X-Mesh-Job-Id` / `X-Mesh-Timeout` headers injected.
    async fn dispatch(
        &self,
        claimed: ClaimedJob,
        controller: JobController,
    ) -> DispatchOutcome;
}

/// Configuration knobs for [`spawn_claim_worker`].
#[derive(Debug, Clone)]
pub struct ClaimWorkerConfig {
    /// Capability the worker is claiming for. Passed verbatim to
    /// `TaskBackend::claim_next`.
    pub capability: String,
    /// Owner instance ID written to claimed rows. Same value the
    /// `JobController` uses when flushing batches.
    pub instance_id: String,
    /// Maximum jobs in flight at once (semaphore cap). Default 4.
    pub max_concurrent: usize,
    /// Backoff floor when the backend reports "no work" or errors.
    pub backoff_min: Duration,
    /// Backoff ceiling. Doubles up from `backoff_min` on consecutive
    /// empty / errored claim cycles, capped at this value.
    pub backoff_max: Duration,
    /// Whether reclaimed jobs resume from their persisted per-filter
    /// `recv_cursor` (issue #1277) instead of replaying the event log from
    /// seq 0. Default `false` ⇒ replay-from-0 (byte-identical to prior
    /// behavior). This is the Rust-native gate; the per-language SDKs gate
    /// resume in their own dispatchers via the binding constructors.
    pub resume_cursor: bool,
}

impl ClaimWorkerConfig {
    /// Construct a config with default tuning (4 concurrent, 200ms ceiling
    /// climbing to 5s).
    pub fn new(capability: impl Into<String>, instance_id: impl Into<String>) -> Self {
        Self {
            capability: capability.into(),
            instance_id: instance_id.into(),
            max_concurrent: 4,
            backoff_min: Duration::from_millis(200),
            backoff_max: Duration::from_secs(5),
            resume_cursor: false,
        }
    }
}

// =============================================================================
// Worker handle
// =============================================================================

/// Handle returned by [`spawn_claim_worker`]. Drop = stop signaled.
pub struct ClaimWorkerHandle {
    cancel: CancellationToken,
    join: Option<JoinHandle<()>>,
}

impl ClaimWorkerHandle {
    /// Signal the loop to stop and await its join.
    pub async fn shutdown(mut self) {
        self.cancel.cancel();
        if let Some(j) = self.join.take() {
            let _ = j.await;
        }
    }
}

impl Drop for ClaimWorkerHandle {
    fn drop(&mut self) {
        self.cancel.cancel();
    }
}

// =============================================================================
// spawn_claim_worker
// =============================================================================

/// Spawn the claim worker loop. Returns a handle whose `shutdown()`
/// cleanly stops the loop.
///
/// The loop:
/// 1. Waits for the `pending_signal` to indicate `Some(n>0)`.
/// 2. While pending and under the in-flight cap: calls
///    `backend.claim_next(...)`, spawns a task per claim that calls
///    `dispatcher.dispatch(...)` (with a fresh `JobController`).
/// 3. On `None` from the backend (no work) — sleeps `backoff_min` and
///    waits for the next pending signal change.
/// 4. On backend error — logs, applies exponential backoff, retries.
pub fn spawn_claim_worker(
    backend: Arc<dyn TaskBackend>,
    dispatcher: Arc<dyn ClaimDispatcher>,
    pending_signal: watch::Receiver<Option<u32>>,
    queue: Arc<Mutex<CoalescingQueue>>,
    cfg: ClaimWorkerConfig,
) -> ClaimWorkerHandle {
    let cancel = CancellationToken::new();
    let cancel_clone = cancel.clone();
    let join = tokio::spawn(run_loop(
        backend,
        dispatcher,
        pending_signal,
        queue,
        cfg,
        cancel_clone,
    ));
    ClaimWorkerHandle {
        cancel,
        join: Some(join),
    }
}

async fn run_loop(
    backend: Arc<dyn TaskBackend>,
    dispatcher: Arc<dyn ClaimDispatcher>,
    mut pending_signal: watch::Receiver<Option<u32>>,
    queue: Arc<Mutex<CoalescingQueue>>,
    cfg: ClaimWorkerConfig,
    cancel: CancellationToken,
) {
    info!(
        "Claim worker starting (capability={}, instance={}, max_concurrent={})",
        cfg.capability, cfg.instance_id, cfg.max_concurrent
    );

    let semaphore = Arc::new(Semaphore::new(cfg.max_concurrent));
    let mut backoff = cfg.backoff_min;

    loop {
        // Wait for either a pending-signal change or shutdown.
        if !pending_has_work(&pending_signal) {
            tokio::select! {
                _ = cancel.cancelled() => break,
                changed = pending_signal.changed() => {
                    if changed.is_err() {
                        // Sender dropped — runtime shutting down; exit cleanly.
                        debug!("Claim worker: pending_signal sender dropped, exiting");
                        break;
                    }
                }
            }
            // Re-check after wakeup; signal may have already gone back to None.
            if !pending_has_work(&pending_signal) {
                continue;
            }
        }

        // Drain inner loop: keep claiming while signal says >0 AND we still
        // have capacity. Break out on empty or error to backoff + recheck.
        loop {
            if cancel.is_cancelled() {
                break;
            }

            // Acquire a permit before claiming so we never claim a job we
            // can't immediately dispatch. `acquire_owned` so we can move
            // it into the spawned task and release on completion.
            //
            // Wrap the await in a tokio::select so a worker that's
            // blocked at the semaphore (all permits held by long-running
            // dispatches) can still observe a `cancel.cancelled()`
            // signal and exit cleanly during agent shutdown — without
            // this, the runtime hangs on Drop until every in-flight
            // handler returns.
            let permit = tokio::select! {
                p = Arc::clone(&semaphore).acquire_owned() => match p {
                    Ok(p) => p,
                    Err(_) => {
                        // Semaphore closed — should never happen since we hold
                        // the only reference besides the spawned tasks.
                        warn!("Claim worker semaphore closed unexpectedly");
                        break;
                    }
                },
                _ = cancel.cancelled() => break,
            };

            match backend
                .claim_next(&cfg.capability, &cfg.instance_id)
                .await
            {
                Ok(Some(claimed)) => {
                    trace!(
                        "Claim worker: dispatching job {} (attempt={})",
                        claimed.id, claimed.attempt_count
                    );
                    // Carry the claim generation the registry minted for this
                    // claim so the controller fences its deltas + executor
                    // reads (issue #1252). `None` (old registry) degrades to
                    // legacy owner-only behavior.
                    //
                    // Resume gating (issue #1277): seed the controller from the
                    // persisted per-filter `recv_cursor` ONLY when this worker
                    // opted into resume (`cfg.resume_cursor`). Default `false`
                    // ⇒ `None` ⇒ replay-from-0, byte-identical to prior
                    // behavior.
                    let initial_cursors = if cfg.resume_cursor {
                        claimed.recv_cursor.clone()
                    } else {
                        None
                    };
                    let controller = JobController::new_with_epoch(
                        claimed.id.clone(),
                        cfg.instance_id.clone(),
                        claimed.claim_epoch,
                        backend.clone(),
                        queue.clone(),
                        initial_cursors,
                    );
                    let dispatcher_clone = dispatcher.clone();
                    let job_id_for_log = claimed.id.clone();
                    tokio::spawn(async move {
                        let outcome = dispatcher_clone.dispatch(claimed, controller).await;
                        match outcome {
                            DispatchOutcome::Completed => {
                                debug!("Claim dispatcher reported completed: {}", job_id_for_log);
                            }
                            DispatchOutcome::Failed => {
                                debug!("Claim dispatcher reported failed: {}", job_id_for_log);
                            }
                            DispatchOutcome::Errored(reason) => {
                                warn!(
                                    "Claim dispatcher errored without terminal call ({}): {}",
                                    job_id_for_log, reason
                                );
                            }
                        }
                        // Permit released on drop.
                        drop(permit);
                    });
                    // Reset backoff on a successful claim.
                    backoff = cfg.backoff_min;

                    // If the signal already says zero pending, there's no
                    // point in another claim immediately — break out and
                    // wait for the next signal.
                    if !pending_has_work(&pending_signal) {
                        break;
                    }
                }
                Ok(None) => {
                    trace!(
                        "Claim worker: no work available for {}; backing off {:?}",
                        cfg.capability, backoff
                    );
                    drop(permit);
                    break;
                }
                Err(e) => {
                    warn!(
                        "Claim worker: claim_next failed ({}): {}; backing off {:?}",
                        cfg.capability, e, backoff
                    );
                    drop(permit);
                    break;
                }
            }
        }

        // Backoff between drain attempts. Cancellable so shutdown is snappy.
        tokio::select! {
            _ = cancel.cancelled() => break,
            _ = tokio::time::sleep(backoff) => {}
        }
        backoff = (backoff * 2).min(cfg.backoff_max);
    }

    info!(
        "Claim worker stopped (capability={}, instance={})",
        cfg.capability, cfg.instance_id
    );
}

/// Cheap check on the watch channel's current value.
fn pending_has_work(rx: &watch::Receiver<Option<u32>>) -> bool {
    matches!(*rx.borrow(), Some(n) if n > 0)
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex as StdMutex;
    use tokio::sync::Notify;
    use tokio::time::sleep;

    use crate::jobs::new_coalescing_queue;
    use crate::task_backend::{
        BackendError, CancelJobResponse, CreateJobRequest, CreateJobResponse, Job,
        JobBatchResponse, JobDelta, JobStatus, ReleaseJobResponse,
    };

    // ---- mock backend (claim-focused) ---------------------------------------

    struct MockClaimBackend {
        /// Queue of claimed jobs to hand out. `claim_next` pops the front.
        claims: StdMutex<Vec<ClaimedJob>>,
        /// Claim counter for diagnostics.
        claim_calls: AtomicUsize,
    }

    impl MockClaimBackend {
        fn new(claims: Vec<ClaimedJob>) -> Arc<Self> {
            Arc::new(Self {
                claims: StdMutex::new(claims),
                claim_calls: AtomicUsize::new(0),
            })
        }
    }

    fn fake_claim(i: usize) -> ClaimedJob {
        ClaimedJob {
            id: format!("job-{}", i),
            submitted_payload: serde_json::json!({"i": i}),
            attempt_count: 1,
            claim_epoch: Some(1),
            lease_expires_at: None,
            max_duration: None,
            recv_cursor: None,
        }
    }

    #[async_trait]
    impl TaskBackend for MockClaimBackend {
        async fn create_job(
            &self,
            _req: CreateJobRequest,
        ) -> Result<CreateJobResponse, BackendError> {
            unimplemented!()
        }
        async fn submit_batch(
            &self,
            _instance_id: &str,
            _deltas: Vec<JobDelta>,
        ) -> Result<JobBatchResponse, BackendError> {
            // Tests don't care about terminal-flush traffic.
            Ok(JobBatchResponse { accepted: 0, rejected: vec![] })
        }
        async fn claim_next(
            &self,
            _capability: &str,
            _instance_id: &str,
        ) -> Result<Option<ClaimedJob>, BackendError> {
            self.claim_calls.fetch_add(1, Ordering::SeqCst);
            Ok(self.claims.lock().unwrap().pop())
        }
        async fn get_job(&self, _job_id: &str) -> Result<Job, BackendError> {
            unimplemented!()
        }
        async fn cancel_job(
            &self,
            _job_id: &str,
            _reason: Option<String>,
        ) -> Result<CancelJobResponse, BackendError> {
            Ok(CancelJobResponse {
                status: JobStatus::Cancelled,
                forwarded_to_instance_id: None,
            })
        }
        async fn release_lease(
            &self,
            _job_id: &str,
            _instance_id: &str,
            _reason: Option<String>,
        ) -> Result<ReleaseJobResponse, BackendError> {
            Ok(ReleaseJobResponse {
                status: JobStatus::Working,
                attempt_count: 1,
            })
        }
        async fn list_job_events(
            &self,
            _job_id: &str,
            _after: i64,
            _types: Option<&[String]>,
            _wait: Duration,
            _limit: usize,
            _identity: Option<(&str, i64)>,
        ) -> Result<crate::task_backend::JobEventListResponse, BackendError> {
            // Claim-worker tests don't exercise the event channel.
            Ok(crate::task_backend::JobEventListResponse {
                events: vec![],
                next_after: 0,
            })
        }
        async fn post_job_event(
            &self,
            _job_id: &str,
            _event_type: &str,
            _payload: Option<serde_json::Value>,
            _trace_context: Option<serde_json::Value>,
        ) -> Result<crate::task_backend::JobEventReceipt, BackendError> {
            // Claim-worker tests don't exercise the event-injection
            // surface; return a clean error rather than panicking so a
            // future test that accidentally calls this fails with a
            // readable message instead of unwinding.
            Err(BackendError::Other(
                "post_job_event not used in claim-worker tests".into(),
            ))
        }
    }

    // ---- mock dispatchers ---------------------------------------------------

    struct CountingDispatcher {
        seen: AtomicUsize,
        ids: StdMutex<Vec<String>>,
        notify: Arc<Notify>,
        target: usize,
    }

    impl CountingDispatcher {
        fn new(target: usize) -> Arc<Self> {
            Arc::new(Self {
                seen: AtomicUsize::new(0),
                ids: StdMutex::new(Vec::new()),
                notify: Arc::new(Notify::new()),
                target,
            })
        }
    }

    #[async_trait]
    impl ClaimDispatcher for CountingDispatcher {
        async fn dispatch(
            &self,
            claimed: ClaimedJob,
            _controller: JobController,
        ) -> DispatchOutcome {
            self.ids.lock().unwrap().push(claimed.id.clone());
            let n = self.seen.fetch_add(1, Ordering::SeqCst) + 1;
            if n >= self.target {
                self.notify.notify_waiters();
            }
            DispatchOutcome::Completed
        }
    }

    struct ConcurrencyTrackingDispatcher {
        in_flight: AtomicUsize,
        peak: AtomicUsize,
        seen: AtomicUsize,
        notify: Arc<Notify>,
        target: usize,
        hold: Duration,
    }

    impl ConcurrencyTrackingDispatcher {
        fn new(target: usize, hold: Duration) -> Arc<Self> {
            Arc::new(Self {
                in_flight: AtomicUsize::new(0),
                peak: AtomicUsize::new(0),
                seen: AtomicUsize::new(0),
                notify: Arc::new(Notify::new()),
                target,
                hold,
            })
        }
    }

    #[async_trait]
    impl ClaimDispatcher for ConcurrencyTrackingDispatcher {
        async fn dispatch(
            &self,
            _claimed: ClaimedJob,
            _controller: JobController,
        ) -> DispatchOutcome {
            let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            // Track running peak.
            let mut peak = self.peak.load(Ordering::SeqCst);
            while now > peak {
                match self.peak.compare_exchange(
                    peak, now, Ordering::SeqCst, Ordering::SeqCst,
                ) {
                    Ok(_) => break,
                    Err(actual) => peak = actual,
                }
            }
            sleep(self.hold).await;
            self.in_flight.fetch_sub(1, Ordering::SeqCst);
            let n = self.seen.fetch_add(1, Ordering::SeqCst) + 1;
            if n >= self.target {
                self.notify.notify_waiters();
            }
            DispatchOutcome::Completed
        }
    }

    // ---- tests --------------------------------------------------------------

    #[tokio::test]
    async fn dispatches_when_pending_signal_goes_nonzero() {
        let backend = MockClaimBackend::new(vec![
            fake_claim(0),
            fake_claim(1),
            fake_claim(2),
        ]);
        let dispatcher = CountingDispatcher::new(3);
        let queue = new_coalescing_queue();
        let (tx, rx) = watch::channel::<Option<u32>>(None);
        let cfg = ClaimWorkerConfig::new("plan_trip", "inst-1");

        let handle = spawn_claim_worker(
            backend.clone() as Arc<dyn TaskBackend>,
            dispatcher.clone(),
            rx,
            queue,
            cfg,
        );

        // Wakeup: signal 3 pending.
        tx.send_replace(Some(3));

        // Wait until the dispatcher has seen all 3 (or timeout).
        let notify = dispatcher.notify.clone();
        tokio::time::timeout(Duration::from_secs(2), notify.notified())
            .await
            .expect("dispatcher never received expected count");

        assert_eq!(dispatcher.seen.load(Ordering::SeqCst), 3);
        let ids = dispatcher.ids.lock().unwrap().clone();
        let mut sorted = ids.clone();
        sorted.sort();
        assert_eq!(sorted, vec!["job-0", "job-1", "job-2"]);

        handle.shutdown().await;
    }

    #[tokio::test]
    async fn respects_max_concurrent_cap() {
        // Queue 10 jobs. With max_concurrent=2 and a 100ms hold per job,
        // peak in-flight should never exceed 2.
        let claims: Vec<ClaimedJob> = (0..10).map(fake_claim).collect();
        let backend = MockClaimBackend::new(claims);
        let dispatcher = ConcurrencyTrackingDispatcher::new(10, Duration::from_millis(100));
        let queue = new_coalescing_queue();
        let (tx, rx) = watch::channel::<Option<u32>>(None);

        let mut cfg = ClaimWorkerConfig::new("cap", "inst-1");
        cfg.max_concurrent = 2;
        cfg.backoff_min = Duration::from_millis(20);
        cfg.backoff_max = Duration::from_millis(40);

        let handle = spawn_claim_worker(
            backend.clone() as Arc<dyn TaskBackend>,
            dispatcher.clone(),
            rx,
            queue,
            cfg,
        );

        tx.send_replace(Some(10));

        let notify = dispatcher.notify.clone();
        tokio::time::timeout(Duration::from_secs(5), notify.notified())
            .await
            .expect("did not finish 10 jobs in time");

        assert_eq!(dispatcher.seen.load(Ordering::SeqCst), 10);
        let peak = dispatcher.peak.load(Ordering::SeqCst);
        assert!(peak <= 2, "peak in-flight exceeded cap: {}", peak);

        handle.shutdown().await;
    }

    #[tokio::test]
    async fn no_work_response_backs_off() {
        // Empty backend. The worker should call claim_next a bounded number
        // of times and then park (waiting for the next signal change).
        let backend = MockClaimBackend::new(vec![]);
        let dispatcher = CountingDispatcher::new(usize::MAX);
        let queue = new_coalescing_queue();
        let (tx, rx) = watch::channel::<Option<u32>>(None);

        let mut cfg = ClaimWorkerConfig::new("cap", "inst-1");
        cfg.backoff_min = Duration::from_millis(50);
        cfg.backoff_max = Duration::from_millis(50);

        let handle = spawn_claim_worker(
            backend.clone() as Arc<dyn TaskBackend>,
            dispatcher,
            rx,
            queue,
            cfg,
        );

        // Wake the worker. Empty backend → it returns None on first call →
        // backs off → signal still says >0 so it re-tries → none again. After
        // ~200ms we'd expect a small bounded number of calls, not a tight
        // spin (which would be hundreds).
        tx.send_replace(Some(5));
        sleep(Duration::from_millis(220)).await;

        let calls = backend.claim_calls.load(Ordering::SeqCst);
        assert!(
            calls > 0 && calls < 20,
            "expected bounded claim_calls (got {})",
            calls
        );

        handle.shutdown().await;
    }

    #[tokio::test]
    async fn shutdown_stops_loop_cleanly() {
        let backend = MockClaimBackend::new(vec![]);
        let dispatcher = CountingDispatcher::new(usize::MAX);
        let queue = new_coalescing_queue();
        let (_tx, rx) = watch::channel::<Option<u32>>(None);

        let cfg = ClaimWorkerConfig::new("cap", "inst-1");

        let handle = spawn_claim_worker(
            backend as Arc<dyn TaskBackend>,
            dispatcher,
            rx,
            queue,
            cfg,
        );

        // Worker should be parked (signal is None). Shutdown should return
        // promptly.
        tokio::time::timeout(Duration::from_secs(1), handle.shutdown())
            .await
            .expect("shutdown did not return promptly");
    }

    /// Sanity: `pending_has_work` agrees with the documented contract.
    #[test]
    fn pending_has_work_correct() {
        let (_tx, rx) = watch::channel::<Option<u32>>(None);
        assert!(!pending_has_work(&rx));
        let (_tx, rx) = watch::channel::<Option<u32>>(Some(0));
        assert!(!pending_has_work(&rx));
        let (_tx, rx) = watch::channel::<Option<u32>>(Some(7));
        assert!(pending_has_work(&rx));
    }
}
