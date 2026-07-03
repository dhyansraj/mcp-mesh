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
//! # Registration model (issue #1166 MED-4)
//!
//! Multiple registrations for the same `job_id` can legitimately overlap:
//!
//! * **Same logical scope, registered twice** — `with_job_async_py`
//!   registers synchronously (to close the asyncio-scheduling race), then
//!   `run_as_job` registers again when the future is first polled.
//! * **Two live scopes** — a claimed job whose handler loops back into
//!   the same process with `X-Mesh-Job-Id` (nested inbound dispatch), or
//!   a re-claim of a job whose previous overlong attempt is still
//!   unwinding after lease expiry.
//!
//! A naive insert/remove-by-id map loses tokens in both cases: an
//! overwrite drops the displaced entry's `ended` token unfired (waiters
//! that snapshotted it never wake on natural end), and remove-by-id lets
//! the first scope to exit delete the second's registration (its `ended`
//! fires while the job still runs, and a later cancel finds nothing —
//! the cancel is silently lost).
//!
//! Instead, each `job_id` maps to a **stack of registration frames**, each
//! carrying a unique generation:
//!
//! * [`register_active_job`] pushes a frame and returns its generation.
//!   Nothing is displaced and nothing fires — an outer scope's `ended`
//!   stays armed while an inner scope is live.
//! * [`unregister_active_job`] removes ONLY the caller's own frame (by
//!   generation) and fires that frame's `ended`, regardless of stack
//!   position. If an inner frame exits first the outer frame becomes the
//!   active one again; if the outer exits first (zombie attempt after a
//!   re-claim) the inner frame is untouched.
//! * [`cancel_active_job`] / [`get_state`] operate on the TOP frame —
//!   the most recent registration is the live attempt the registry would
//!   forward a cancel to.
//!
//! # Concurrency model
//! Backed by a `std::sync::Mutex<HashMap<String, Vec<Frame>>>` held
//! behind a `OnceLock` (matches `tracing_publish.rs`, `tls.rs`, etc.).
//! Critical sections are short — clone-and-drop — so contention is not a
//! concern at the scale of in-flight jobs per process.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

use tokio_util::sync::CancellationToken;

/// Per-registration state held by the cancel registry. The two tokens
/// are distinct: `cancel` is fired by user-initiated cancel (the
/// existing behaviour); `ended` is fired by the registry itself when the
/// owning scope's [`unregister_active_job`] runs, so awaiters that need
/// to clean up when the job finishes naturally (without cancel) can do
/// so.
struct Frame {
    /// Unique registration identity. [`unregister_active_job`] removes
    /// only the frame whose generation matches — a different scope that
    /// registered later under the same `job_id` is never disturbed.
    generation: u64,
    /// Claim generation (epoch) this execution attempt runs under, or
    /// `None` for a push-mode inbound job / legacy path. Used by
    /// [`cancel_superseded`] / [`get_state_for_epoch`] to target the
    /// EXACT superseded frame — never the top-of-stack. Critical for the
    /// same-instance re-claim shape: the zombie H1 (epoch 1) and the fresh
    /// healthy H2 (epoch 2) both live under one `job_id`; a stale-epoch
    /// supersession must fire ONLY H1's token, leaving H2 running (issue
    /// #1252 review).
    claim_epoch: Option<i64>,
    cancel: CancellationToken,
    ended: CancellationToken,
}

/// Process-wide map of active job ID → stack of registration frames
/// (last element = most recent registration = the live attempt).
static REGISTRY: OnceLock<Mutex<HashMap<String, Vec<Frame>>>> = OnceLock::new();

/// Monotonic generation source for registration identities.
static NEXT_GENERATION: AtomicU64 = AtomicU64::new(1);

fn registry() -> &'static Mutex<HashMap<String, Vec<Frame>>> {
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Register the cancel token for the given job ID and return the
/// registration's generation. The caller MUST pass the returned
/// generation back to [`unregister_active_job`] when its scope ends —
/// that is what scopes the teardown to this registration only.
///
/// If a prior registration exists for the same `job_id` (same-scope
/// double registration via `with_job_async_py` + `run_as_job`, a nested
/// inbound dispatch carrying the same `X-Mesh-Job-Id`, or a re-claim
/// racing a zombie attempt), it is kept underneath the new frame: its
/// `ended` token stays armed (it fires when ITS scope unregisters), and
/// [`cancel_active_job`] / [`get_state`] switch to the new top frame.
///
/// The companion `ended` token is freshly constructed inside the
/// registry for each registration; it fires only when this
/// registration's [`unregister_active_job`] runs.
pub fn register_active_job(job_id: &str, token: CancellationToken) -> u64 {
    register_active_job_with_epoch(job_id, token, None)
}

/// Like [`register_active_job`] but records the execution's `claim_epoch`
/// (issue #1252) so [`cancel_superseded`] / [`get_state_for_epoch`] can
/// target this exact frame rather than the top-of-stack. Pass `None` for a
/// push-mode inbound job / legacy path (identical to `register_active_job`).
pub fn register_active_job_with_epoch(
    job_id: &str,
    token: CancellationToken,
    claim_epoch: Option<i64>,
) -> u64 {
    let generation = NEXT_GENERATION.fetch_add(1, Ordering::Relaxed);
    let frame = Frame {
        generation,
        claim_epoch,
        cancel: token,
        ended: CancellationToken::new(),
    };
    let mut map = registry().lock().expect("cancel_registry mutex poisoned");
    map.entry(job_id.to_string()).or_default().push(frame);
    generation
}

/// Fire the cancel token of the most recent registration for the given
/// job ID, if any.
///
/// Returns `true` if a token was found and fired, `false` if the job is
/// not currently active in this process. Idempotent — repeated calls on
/// an already-cancelled token are no-ops on the token side, but only the
/// first call returns `true` (subsequent calls still return `true` while
/// the entry exists; once unregistered, returns `false`).
///
/// This does NOT fire any `ended` token — `ended` is reserved for
/// natural lifecycle teardown via [`unregister_active_job`].
pub fn cancel_active_job(job_id: &str) -> bool {
    let token = {
        let map = registry().lock().expect("cancel_registry mutex poisoned");
        map.get(job_id)
            .and_then(|stack| stack.last())
            .map(|f| f.cancel.clone())
    };
    match token {
        Some(t) => {
            t.cancel();
            true
        }
        None => false,
    }
}

/// Fire the cancel token of the frame(s) registered for `job_id` whose
/// `claim_epoch` matches `epoch` — the SUPERSEDED execution, targeted by
/// epoch rather than stack position (issue #1252 review).
///
/// Unlike [`cancel_active_job`] (which fires the top-of-stack = the current
/// LIVE attempt, the right target for a user-initiated cancel), this fires
/// exactly the fenced frame. In the same-instance re-claim shape the zombie
/// H1 (epoch 1) sits UNDERNEATH the fresh healthy H2 (epoch 2); a
/// `claim_superseded` from H1's stale delta / read must abort H1 only —
/// firing H2 (top) would kill the healthy attempt while the zombie keeps
/// running. Epochs are strictly monotonic per job, so `epoch` identifies a
/// unique attempt (its double-registered frames share one token — firing
/// both is idempotent).
///
/// Returns `true` if at least one matching frame was found and fired.
/// Frames with `claim_epoch == None` (legacy) never match a real epoch, so
/// they are never collaterally cancelled here.
pub fn cancel_superseded(job_id: &str, epoch: i64) -> bool {
    let tokens: Vec<CancellationToken> = {
        let map = registry().lock().expect("cancel_registry mutex poisoned");
        map.get(job_id)
            .map(|stack| {
                stack
                    .iter()
                    .filter(|f| f.claim_epoch == Some(epoch))
                    .map(|f| f.cancel.clone())
                    .collect()
            })
            .unwrap_or_default()
    };
    let mut fired = false;
    for t in tokens {
        t.cancel();
        fired = true;
    }
    fired
}

/// Snapshot `(cancel, ended)` of the topmost frame for `job_id` whose
/// `claim_epoch` matches `epoch`, without firing either. Lets an executor
/// (a [`crate::jobs::JobController`] carrying `epoch`) watch ITS OWN frame's
/// cancel token — not the top-of-stack, which after a re-claim is a
/// different attempt (issue #1252 review). Returns `None` when no frame with
/// that epoch is registered.
pub fn get_state_for_epoch(
    job_id: &str,
    epoch: i64,
) -> Option<(CancellationToken, CancellationToken)> {
    let map = registry().lock().expect("cancel_registry mutex poisoned");
    map.get(job_id).and_then(|stack| {
        stack
            .iter()
            .rev()
            .find(|f| f.claim_epoch == Some(epoch))
            .map(|f| (f.cancel.clone(), f.ended.clone()))
    })
}

/// Remove the registration identified by (`job_id`, `generation`). Safe
/// to call even if the registration no longer exists. The associated
/// `cancel` token is NOT cancelled by this call — callers that want both
/// behaviors should call [`cancel_active_job`] first. The registration's
/// `ended` token IS fired after removal, so awaiters tracking natural
/// job termination wake up promptly (used by the `await_job_cancel`
/// paths in all three bindings so per-call listeners don't leak when a
/// job finishes without explicit cancel).
///
/// Only the caller's own frame is removed: a different registration for
/// the same `job_id` (nested scope, re-claimed attempt) keeps its tokens
/// — this is what prevents the "first scope to exit deletes the second's
/// registration" cancel loss (issue #1166 MED-4).
pub fn unregister_active_job(job_id: &str, generation: u64) {
    let ended = {
        let mut map = registry().lock().expect("cancel_registry mutex poisoned");
        let mut ended = None;
        if let Some(stack) = map.get_mut(job_id) {
            if let Some(pos) = stack.iter().position(|f| f.generation == generation) {
                ended = Some(stack.remove(pos).ended);
            }
            if stack.is_empty() {
                map.remove(job_id);
            }
        }
        ended
    };
    if let Some(t) = ended {
        t.cancel();
    }
}

/// Number of job IDs with at least one active registration. For
/// diagnostics (tests, /health endpoints, dashboards). Cheap snapshot —
/// does not hold the lock across other work.
pub fn active_job_count() -> usize {
    registry()
        .lock()
        .expect("cancel_registry mutex poisoned")
        .len()
}

/// Snapshot both tokens (cancel, ended) of the most recent registration
/// for `job_id`, without firing either. Used by the `await_job_cancel`
/// accessors so callers in non-Rust runtimes can race their outbound
/// work against EITHER the in-flight job's cancel signal OR its
/// natural-termination signal — without this, an `awaitJobCancel(...)`
/// future on a job that finishes normally would hang forever (its sole
/// resolve path would be explicit cancel) and leak one Rust task + one
/// JS Promise per outbound call. Returns `None` if the job is not
/// currently registered (already terminal / never claimed) — callers
/// should treat `None` as "no cancellation possible from here" and
/// resolve immediately.
pub fn get_state(job_id: &str) -> Option<(CancellationToken, CancellationToken)> {
    let map = registry().lock().expect("cancel_registry mutex poisoned");
    map.get(job_id)
        .and_then(|stack| stack.last())
        .map(|f| (f.cancel.clone(), f.ended.clone()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::time::Duration;
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
        let generation = register_active_job(&id, token.clone());

        assert!(!token.is_cancelled());
        let fired = cancel_active_job(&id);
        assert!(fired, "should report a token was found");
        assert!(token.is_cancelled(), "token should be fired");

        // Cleanup so this test doesn't leak entries.
        unregister_active_job(&id, generation);
        assert!(get_state(&id).is_none());
    }

    #[test]
    fn cancel_unknown_returns_false() {
        let id = unique_id("missing");
        // Never registered.
        assert!(!cancel_active_job(&id));
    }

    /// Issue #1252 review, item 1: the same-instance re-claim shape. Two live
    /// frames under one job_id — zombie H1 (epoch 1) UNDER healthy H2 (epoch
    /// 2, top). A stale-epoch supersession must fire ONLY the matching frame
    /// (H1), never the top-of-stack (H2).
    #[test]
    fn cancel_superseded_fires_only_matching_epoch_frame() {
        let id = unique_id("reclaim-epoch");
        let h1 = CancellationToken::new();
        let h2 = CancellationToken::new();
        let g1 = register_active_job_with_epoch(&id, h1.clone(), Some(1));
        let g2 = register_active_job_with_epoch(&id, h2.clone(), Some(2));

        assert!(cancel_superseded(&id, 1), "should fire the epoch-1 frame");
        assert!(h1.is_cancelled(), "superseded zombie H1 must be cancelled");
        assert!(
            !h2.is_cancelled(),
            "healthy re-claim H2 (top-of-stack) must be untouched"
        );

        unregister_active_job(&id, g1);
        unregister_active_job(&id, g2);
    }

    #[test]
    fn cancel_superseded_no_match_returns_false_and_spares_legacy_frames() {
        // No frame with the requested epoch → nothing fired.
        let id = unique_id("epoch-nomatch");
        let tok = CancellationToken::new();
        let g = register_active_job_with_epoch(&id, tok.clone(), Some(5));
        assert!(!cancel_superseded(&id, 99));
        assert!(!tok.is_cancelled());
        unregister_active_job(&id, g);

        // Legacy (None) frames never match a real epoch — never collaterally
        // cancelled by a supersession.
        let id2 = unique_id("legacy-frame");
        let tok2 = CancellationToken::new();
        let g2 = register_active_job(&id2, tok2.clone());
        assert!(!cancel_superseded(&id2, 1));
        assert!(!tok2.is_cancelled());
        unregister_active_job(&id2, g2);
    }

    #[test]
    fn get_state_for_epoch_targets_matching_frame_only() {
        let id = unique_id("get-epoch");
        let t1 = CancellationToken::new();
        let t2 = CancellationToken::new();
        let g1 = register_active_job_with_epoch(&id, t1.clone(), Some(1));
        let g2 = register_active_job_with_epoch(&id, t2.clone(), Some(2));

        let (c1, _e1) = get_state_for_epoch(&id, 1).expect("epoch-1 frame visible");
        c1.cancel();
        assert!(t1.is_cancelled());
        assert!(!t2.is_cancelled(), "epoch-2 frame must be unaffected");
        assert!(get_state_for_epoch(&id, 99).is_none(), "no epoch-99 frame");

        unregister_active_job(&id, g1);
        unregister_active_job(&id, g2);
    }

    #[test]
    fn unregister_then_cancel_returns_false() {
        let id = unique_id("ephemeral");
        let token = CancellationToken::new();
        let generation = register_active_job(&id, token.clone());
        unregister_active_job(&id, generation);
        assert!(!cancel_active_job(&id));
        assert!(!token.is_cancelled(), "token should remain un-fired");
    }

    #[test]
    fn unregister_with_stale_generation_is_noop() {
        let id = unique_id("stale-gen");
        let token = CancellationToken::new();
        let generation = register_active_job(&id, token.clone());
        // A generation that never belonged to this job must not disturb it.
        unregister_active_job(&id, generation + 1_000_000);
        assert!(get_state(&id).is_some(), "live registration must survive");
        assert!(cancel_active_job(&id));
        unregister_active_job(&id, generation);
    }

    /// MED-4 (b): with two live registrations for one job_id (nested
    /// inbound dispatch / zombie attempt + re-claim), the first scope to
    /// exit must remove ONLY its own frame — the second registration
    /// stays live and a subsequent cancel reaches it.
    #[test]
    fn unregister_by_generation_does_not_remove_successor() {
        let id = unique_id("two-scopes");
        let first = CancellationToken::new();
        let second = CancellationToken::new();
        let gen1 = register_active_job(&id, first.clone());
        let gen2 = register_active_job(&id, second.clone());

        // First (outer) scope exits first.
        unregister_active_job(&id, gen1);

        // The second registration is still live — cancel reaches it.
        assert!(
            cancel_active_job(&id),
            "cancel after the outer scope exited must reach the live scope"
        );
        assert!(second.is_cancelled());
        assert!(!first.is_cancelled());

        unregister_active_job(&id, gen2);
        assert!(!cancel_active_job(&id));
    }

    /// Re-registration stacks: cancel targets the most recent (top)
    /// registration; the older one is preserved underneath and becomes
    /// active again when the newer scope unregisters.
    #[test]
    fn re_registration_stacks_and_cancel_targets_top() {
        let id = unique_id("overwrite");
        let first = CancellationToken::new();
        let second = CancellationToken::new();
        let gen1 = register_active_job(&id, first.clone());
        let gen2 = register_active_job(&id, second.clone());

        let fired = cancel_active_job(&id);
        assert!(fired);
        assert!(second.is_cancelled(), "cancel must hit the top frame");
        assert!(!first.is_cancelled(), "first token should NOT be fired");

        // Inner scope exits: the first registration is active again.
        unregister_active_job(&id, gen2);
        assert!(cancel_active_job(&id));
        assert!(first.is_cancelled(), "restored frame must receive cancel");

        unregister_active_job(&id, gen1);
        assert!(get_state(&id).is_none());
    }

    /// MED-4 (a): every registration's `ended` token fires when ITS
    /// scope unregisters — a waiter that snapshotted the older frame
    /// before a re-registration still wakes on natural end (previously
    /// the overwrite dropped that token unfired and the waiter hung
    /// forever).
    #[test]
    fn each_frame_ended_fires_at_its_own_unregister() {
        let id = unique_id("ended-per-frame");
        let gen1 = register_active_job(&id, CancellationToken::new());
        let (_c1, ended1) = get_state(&id).expect("first frame visible");

        let gen2 = register_active_job(&id, CancellationToken::new());
        let (_c2, ended2) = get_state(&id).expect("second frame visible");

        // Registering a second scope must NOT wake the first scope's
        // waiters — that scope is still live (nested dispatch case).
        assert!(!ended1.is_cancelled());
        assert!(!ended2.is_cancelled());

        unregister_active_job(&id, gen2);
        assert!(ended2.is_cancelled(), "inner ended fires at inner exit");
        assert!(!ended1.is_cancelled(), "outer scope is still live");

        unregister_active_job(&id, gen1);
        assert!(ended1.is_cancelled(), "outer ended fires at outer exit");
    }

    /// The `with_job_async_py` double-register window (Rust-level
    /// equivalent): the same cancel token is registered twice for the
    /// same logical scope (outer synchronous registration + inner
    /// `run_as_job` registration). A watcher that snapshots state at any
    /// point must (1) see a live entry, (2) be cancellable through the
    /// shared token, and (3) wake on natural end when the scopes tear
    /// down (LIFO).
    #[tokio::test]
    async fn same_scope_double_register_keeps_waiters_wakeable() {
        let id = unique_id("same-scope");
        let token = CancellationToken::new();

        // Outer registration (with_job_async_py, synchronous).
        let outer = register_active_job(&id, token.clone());
        let (cancel_snap_outer, ended_snap_outer) =
            get_state(&id).expect("entry visible after outer register");

        // Inner registration when run_as_job's future is polled — a
        // clone of the SAME token.
        let inner = register_active_job(&id, token.clone());
        let (cancel_snap_inner, ended_snap_inner) =
            get_state(&id).expect("entry visible after inner register");

        // A watcher racing cancel-vs-ended on either snapshot.
        let watcher = |cancel: CancellationToken, ended: CancellationToken| async move {
            tokio::select! {
                _ = cancel.cancelled() => "cancel",
                _ = ended.cancelled() => "ended",
            }
        };
        let w_outer = tokio::spawn(watcher(cancel_snap_outer.clone(), ended_snap_outer));
        let w_inner = tokio::spawn(watcher(cancel_snap_inner.clone(), ended_snap_inner));

        // Cancel through the registry reaches the shared token, so both
        // snapshots observe it.
        assert!(!cancel_snap_outer.is_cancelled());
        assert!(!cancel_snap_inner.is_cancelled());

        // Natural end: scopes unwind LIFO (run_as_job guard, then the
        // outer guard). Both watchers must wake.
        unregister_active_job(&id, inner);
        unregister_active_job(&id, outer);

        let outcome_inner = tokio::time::timeout(Duration::from_secs(2), w_inner)
            .await
            .expect("inner watcher must wake on natural end")
            .unwrap();
        let outcome_outer = tokio::time::timeout(Duration::from_secs(2), w_outer)
            .await
            .expect("outer watcher must wake on natural end")
            .unwrap();
        assert_eq!(outcome_inner, "ended");
        assert_eq!(outcome_outer, "ended");

        assert!(get_state(&id).is_none(), "registry must be clean");
    }

    /// Cancel after a re-claim reaches the live (new) scope, never the
    /// finished one — and `mesh_job_cancel_fired` semantics survive:
    /// after natural end + re-claim, the fresh frame's token is un-fired.
    #[test]
    fn cancel_after_reclaim_reaches_live_scope() {
        let id = unique_id("reclaim");
        let first_attempt = CancellationToken::new();
        let gen1 = register_active_job(&id, first_attempt.clone());
        // First attempt ends naturally.
        unregister_active_job(&id, gen1);

        // Re-claimed in the same process under the same job_id.
        let second_attempt = CancellationToken::new();
        let gen2 = register_active_job(&id, second_attempt.clone());

        // The fresh registration must not look cancelled.
        let (cancel, _ended) = get_state(&id).expect("re-claimed entry visible");
        assert!(!cancel.is_cancelled());

        assert!(cancel_active_job(&id));
        assert!(second_attempt.is_cancelled());
        assert!(!first_attempt.is_cancelled());

        unregister_active_job(&id, gen2);
    }

    #[test]
    fn get_state_returns_clones_for_registered_job() {
        let id = unique_id("get-state");
        let token = CancellationToken::new();
        let generation = register_active_job(&id, token.clone());

        let (cancel, ended) = get_state(&id).expect("state should be present");
        // Cancel snapshot is a clone of the token the caller registered —
        // firing it fires the original (and vice versa) since
        // `CancellationToken::clone` shares the same underlying state.
        assert!(!cancel.is_cancelled());
        assert!(!ended.is_cancelled());
        cancel.cancel();
        assert!(token.is_cancelled(), "original token should also fire");
        assert!(!ended.is_cancelled(), "ended must remain un-fired");

        unregister_active_job(&id, generation);
    }

    #[test]
    fn get_state_returns_none_for_unregistered_job() {
        let id = unique_id("get-state-missing");
        assert!(get_state(&id).is_none());
    }

    #[test]
    fn get_state_after_unregister_returns_none() {
        let id = unique_id("get-state-ephemeral");
        let generation = register_active_job(&id, CancellationToken::new());
        assert!(get_state(&id).is_some());
        unregister_active_job(&id, generation);
        assert!(get_state(&id).is_none());
    }

    #[test]
    fn get_ended_token_fires_on_unregister() {
        let id = unique_id("ended-on-unregister");
        let generation = register_active_job(&id, CancellationToken::new());
        let (_cancel, ended) = get_state(&id).expect("state should be present");
        assert!(!ended.is_cancelled());
        unregister_active_job(&id, generation);
        assert!(
            ended.is_cancelled(),
            "ended token must fire when job is unregistered (natural end)"
        );
    }

    #[test]
    fn get_cancel_token_isolated_from_ended() {
        let id = unique_id("cancel-isolated-from-ended");
        let generation = register_active_job(&id, CancellationToken::new());
        let (cancel, ended) = get_state(&id).expect("state should be present");

        // Firing cancel must NOT fire ended — they are distinct tokens.
        cancel.cancel();
        assert!(cancel.is_cancelled());
        assert!(
            !ended.is_cancelled(),
            "ended must remain un-fired when only cancel is fired"
        );

        unregister_active_job(&id, generation);
    }

    #[test]
    fn active_job_count_reflects_registrations() {
        // The registry is process-global and other tests register/
        // unregister concurrently, so NO baseline comparison is safe: a
        // `count >= baseline + 2` snapshot races concurrent unregisters
        // (the baseline may include jobs that vanish before our assert).
        // The only race-free assertion is the lower bound guaranteed by
        // our own live registrations.
        let id1 = unique_id("count-1");
        let id2 = unique_id("count-2");

        let gen1 = register_active_job(&id1, CancellationToken::new());
        let gen2 = register_active_job(&id2, CancellationToken::new());
        // Our two jobs are registered right now, so the global map holds
        // at least 2 entries regardless of what parallel tests do.
        assert!(active_job_count() >= 2);

        unregister_active_job(&id1, gen1);
        unregister_active_job(&id2, gen2);
        assert!(get_state(&id1).is_none(), "id1 must be gone after unregister");
        assert!(get_state(&id2).is_none(), "id2 must be gone after unregister");
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
                let generation = register_active_job(&id, token.clone());

                // Wait for everyone to register before any of us cancels.
                b.wait().await;

                let fired = cancel_active_job(&id);
                assert!(fired, "task {} expected its token to be present", i);
                assert!(token.is_cancelled());
                unregister_active_job(&id, generation);
                assert!(!cancel_active_job(&id));
            }));
        }

        for h in handles {
            h.await.expect("task panicked");
        }
    }
}
