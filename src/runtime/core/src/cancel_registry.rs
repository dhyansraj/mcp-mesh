//! Process-wide registry of active job cancel tokens.
//!
//! SDK-owned HTTP routes (`POST /jobs/{id}/cancel`) call
//! [`cancel_active_job`] to fire the in-flight job's cancel token. The
//! `job_context` module handles the actual abort propagation through
//! outbound HTTP cancel-token select wrapping; this module is just the
//! lookup table that maps job IDs to their tokens.
//!
//! Two callers register entries here:
//! 1. The inbound HTTP tool-wrapper (per-language SDK) when it receives a
//!    request bearing `X-Mesh-Job-Id`.
//! 2. The core's [`crate::claim_worker`] when it claims a job for execution.
//!
//! Both paths converge on [`crate::jobs::run_as_job`], which performs the
//! register/run/unregister dance in a panic-safe manner.
//!
//! # Concurrency model
//! Backed by a `std::sync::Mutex<HashMap<String, JobCancelState>>` held
//! behind a `OnceLock` (matches `tracing_publish.rs`, `tls.rs`, etc.).
//! Critical sections are short — clone-and-drop — so contention is not a
//! concern at the scale of in-flight jobs per process.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use tokio_util::sync::CancellationToken;

/// Per-job state held by the cancel registry. The two tokens are
/// distinct: `cancel` is fired by user-initiated cancel (the existing
/// behaviour); `ended` is fired by the registry itself when
/// `unregister_active_job` runs, so awaiters that need to clean up
/// when the job finishes naturally (without cancel) can do so.
pub struct JobCancelState {
    pub cancel: CancellationToken,
    pub ended: CancellationToken,
}

/// Process-wide map of active job ID → per-job cancel state.
static REGISTRY: OnceLock<Mutex<HashMap<String, JobCancelState>>> = OnceLock::new();

fn registry() -> &'static Mutex<HashMap<String, JobCancelState>> {
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Insert (or replace) the cancel token for the given job ID.
///
/// If a prior entry exists (e.g. previous attempt was never unregistered),
/// it is silently overwritten — the latest registration wins. The old
/// token is dropped, which does NOT fire it (cancellation requires an
/// explicit `.cancel()` call). The companion `ended` token is freshly
/// constructed inside the registry for each registration; it fires only
/// on `unregister_active_job` so awaiters can wake up when a job ends
/// naturally (without explicit cancel).
pub fn register_active_job(job_id: &str, token: CancellationToken) {
    let state = JobCancelState {
        cancel: token,
        ended: CancellationToken::new(),
    };
    let mut map = registry().lock().expect("cancel_registry mutex poisoned");
    map.insert(job_id.to_string(), state);
}

/// Fire the cancel token for the given job ID, if one is registered.
///
/// Returns `true` if a token was found and fired, `false` if the job is
/// not currently active in this process. Idempotent — repeated calls on
/// an already-cancelled token are no-ops on the token side, but only the
/// first call returns `true` (subsequent calls still return `true` while
/// the entry exists; once unregistered, returns `false`).
///
/// This does NOT fire the `ended` token — `ended` is reserved for
/// natural lifecycle teardown via [`unregister_active_job`].
pub fn cancel_active_job(job_id: &str) -> bool {
    let token = {
        let map = registry().lock().expect("cancel_registry mutex poisoned");
        map.get(job_id).map(|s| s.cancel.clone())
    };
    match token {
        Some(t) => {
            t.cancel();
            true
        }
        None => false,
    }
}

/// Remove the registry entry for the given job ID. Safe to call even if
/// no entry exists. The associated `cancel` token is NOT cancelled by
/// this call — callers that want both behaviors should call
/// [`cancel_active_job`] first. The `ended` token IS fired before the
/// entry is removed, so awaiters tracking natural job termination wake
/// up promptly (used by the napi `await_job_cancel` path so per-call
/// listeners don't leak when a job finishes without explicit cancel).
pub fn unregister_active_job(job_id: &str) {
    let ended = {
        let mut map = registry().lock().expect("cancel_registry mutex poisoned");
        let ended = map.get(job_id).map(|s| s.ended.clone());
        map.remove(job_id);
        ended
    };
    if let Some(t) = ended {
        t.cancel();
    }
}

/// Number of active job entries currently registered. For diagnostics
/// (tests, /health endpoints, dashboards). Cheap snapshot — does not
/// hold the lock across other work.
pub fn active_job_count() -> usize {
    registry().lock().expect("cancel_registry mutex poisoned").len()
}

/// Snapshot both per-job tokens (cancel, ended) without firing either.
/// Used by the napi `await_job_cancel` accessor so callers in non-Rust
/// runtimes can race their outbound work against EITHER the in-flight
/// job's cancel signal OR its natural-termination signal — without this,
/// an `awaitJobCancel(...)` future on a job that finishes normally would
/// hang forever (its sole resolve path would be explicit cancel) and
/// leak one Rust task + one JS Promise per outbound call. Returns `None`
/// if the job is not currently registered (already terminal / never
/// claimed) — callers should treat `None` as "no cancellation possible
/// from here" and resolve immediately.
pub fn get_state(job_id: &str) -> Option<(CancellationToken, CancellationToken)> {
    let map = registry().lock().expect("cancel_registry mutex poisoned");
    map.get(job_id).map(|s| (s.cancel.clone(), s.ended.clone()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use tokio::sync::Barrier;

    /// Generate a unique job ID prefix per test so tests can run in
    /// parallel without colliding on the global map.
    fn unique_id(suffix: &str) -> String {
        format!(
            "job-{}-{}",
            uuid::Uuid::new_v4().simple(),
            suffix
        )
    }

    #[test]
    fn register_then_cancel_fires_token() {
        let id = unique_id("a");
        let token = CancellationToken::new();
        register_active_job(&id, token.clone());

        assert!(!token.is_cancelled());
        let fired = cancel_active_job(&id);
        assert!(fired, "should report a token was found");
        assert!(token.is_cancelled(), "token should be fired");

        // Cleanup so this test doesn't leak entries.
        unregister_active_job(&id);
    }

    #[test]
    fn cancel_unknown_returns_false() {
        let id = unique_id("missing");
        // Never registered.
        assert!(!cancel_active_job(&id));
    }

    #[test]
    fn unregister_then_cancel_returns_false() {
        let id = unique_id("ephemeral");
        let token = CancellationToken::new();
        register_active_job(&id, token.clone());
        unregister_active_job(&id);
        assert!(!cancel_active_job(&id));
        assert!(!token.is_cancelled(), "token should remain un-fired");
    }

    #[test]
    fn re_registration_overwrites_prior_token() {
        let id = unique_id("overwrite");
        let first = CancellationToken::new();
        let second = CancellationToken::new();
        register_active_job(&id, first.clone());
        register_active_job(&id, second.clone());

        let fired = cancel_active_job(&id);
        assert!(fired);
        assert!(second.is_cancelled());
        assert!(!first.is_cancelled(), "first token should NOT be fired");

        unregister_active_job(&id);
    }

    #[test]
    fn get_state_returns_clones_for_registered_job() {
        let id = unique_id("get-state");
        let token = CancellationToken::new();
        register_active_job(&id, token.clone());

        let (cancel, ended) = get_state(&id).expect("state should be present");
        // Cancel snapshot is a clone of the token the caller registered —
        // firing it fires the original (and vice versa) since
        // `CancellationToken::clone` shares the same underlying state.
        assert!(!cancel.is_cancelled());
        assert!(!ended.is_cancelled());
        cancel.cancel();
        assert!(token.is_cancelled(), "original token should also fire");
        assert!(!ended.is_cancelled(), "ended must remain un-fired");

        unregister_active_job(&id);
    }

    #[test]
    fn get_state_returns_none_for_unregistered_job() {
        let id = unique_id("get-state-missing");
        assert!(get_state(&id).is_none());
    }

    #[test]
    fn get_state_after_unregister_returns_none() {
        let id = unique_id("get-state-ephemeral");
        register_active_job(&id, CancellationToken::new());
        assert!(get_state(&id).is_some());
        unregister_active_job(&id);
        assert!(get_state(&id).is_none());
    }

    #[test]
    fn get_ended_token_fires_on_unregister() {
        let id = unique_id("ended-on-unregister");
        register_active_job(&id, CancellationToken::new());
        let (_cancel, ended) = get_state(&id).expect("state should be present");
        assert!(!ended.is_cancelled());
        unregister_active_job(&id);
        assert!(
            ended.is_cancelled(),
            "ended token must fire when job is unregistered (natural end)"
        );
    }

    #[test]
    fn get_cancel_token_isolated_from_ended() {
        let id = unique_id("cancel-isolated-from-ended");
        register_active_job(&id, CancellationToken::new());
        let (cancel, ended) = get_state(&id).expect("state should be present");

        // Firing cancel must NOT fire ended — they are distinct tokens.
        cancel.cancel();
        assert!(cancel.is_cancelled());
        assert!(
            !ended.is_cancelled(),
            "ended must remain un-fired when only cancel is fired"
        );

        unregister_active_job(&id);
    }

    #[test]
    fn active_job_count_reflects_registrations() {
        // Don't make absolute assertions about the count (other tests run
        // in parallel) — just check delta within this test's lifetime.
        let baseline = active_job_count();
        let id1 = unique_id("count-1");
        let id2 = unique_id("count-2");

        register_active_job(&id1, CancellationToken::new());
        register_active_job(&id2, CancellationToken::new());
        assert!(active_job_count() >= baseline + 2);

        unregister_active_job(&id1);
        unregister_active_job(&id2);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_register_and_cancel_does_not_deadlock() {
        // Spawn N tasks that each do register → spawn cancel → unregister.
        // Verifies the mutex strategy holds up under concurrent multi-task
        // access on a multi-thread runtime.
        const N: usize = 64;
        let barrier = Arc::new(Barrier::new(N));
        let mut handles = Vec::with_capacity(N);

        for i in 0..N {
            let b = barrier.clone();
            handles.push(tokio::spawn(async move {
                let id = format!(
                    "job-conc-{}-{}",
                    uuid::Uuid::new_v4().simple(),
                    i
                );
                let token = CancellationToken::new();
                register_active_job(&id, token.clone());

                // Wait for everyone to register before any of us cancels.
                b.wait().await;

                let fired = cancel_active_job(&id);
                assert!(fired, "task {} expected its token to be present", i);
                assert!(token.is_cancelled());
                unregister_active_job(&id);
                assert!(!cancel_active_job(&id));
            }));
        }

        for h in handles {
            h.await.expect("task panicked");
        }
    }
}
