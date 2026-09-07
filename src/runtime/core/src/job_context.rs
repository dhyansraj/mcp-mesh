//! Async-local job context primitive (Phase 1 — MeshJob foundation).
//!
//! In-process per-task context for an executing job. Set by the tool wrapper
//! (when `X-Mesh-Job-Id` arrives on an inbound HTTP request) or by the claim
//! worker (when a `POST /jobs/claim` succeeds). Read by the outbound HTTP
//! proxy to inject `X-Mesh-Job-Id` and `X-Mesh-Timeout` on downstream calls.
//!
//! The context follows the executing async task: any `tokio::spawn` that
//! inherits it (via `with_job(...).await`) sees the same `JobContext`. This
//! is the Rust analogue of Python's `contextvars.ContextVar` and JS's
//! `AsyncLocalStorage`.
//!
//! # Sync vs async
//! The primary API is async (`current()`, `with_job(...)` etc.). For sync
//! callers (FFI thunks, blocking shims) `try_current()` returns an owned
//! clone of the context if one is active on the current task, or `None`.
//!
//! # See also
//! - `MESHJOB_DESIGN.org` → "Timeout & Cancellation" → "Async-local primitives"
//! - `crate::jobs` for the producer/consumer controllers that consume this.

use std::future::Future;
use std::time::{Duration, Instant};

use tokio_util::sync::CancellationToken;

/// In-process per-task context for an executing job.
///
/// Cheap to clone — `String` and `CancellationToken` are both `Arc`-like.
#[derive(Debug, Clone)]
pub struct JobContext {
    /// Server-assigned job UUID this task is executing for.
    pub job_id: String,
    /// Absolute monotonic deadline for this attempt. `None` means no deadline
    /// (unlimited — see `MESHJOB_DESIGN.org` "Resolved Decisions" /
    /// `total_deadline` default).
    pub deadline: Option<Instant>,
    /// Cancellation token. Fired by inbound cancel forwarders or by parent
    /// scope; outbound requests within this scope should `select!` on it.
    pub cancel_token: CancellationToken,
    /// Claim generation this attempt executes under (from the registry's
    /// `POST /jobs/claim` response), or `None` for a push-mode inbound job
    /// / an old registry. Additive, read-only surface (issue #1252): handlers
    /// can stamp `claim_epoch` on side effects for downstream dedupe. Never
    /// used for fencing decisions here — that lives on [`crate::jobs::JobController`].
    pub claim_epoch: Option<i64>,
}

impl JobContext {
    /// Construct a new context with no deadline (unlimited).
    pub fn new(job_id: impl Into<String>) -> Self {
        Self {
            job_id: job_id.into(),
            deadline: None,
            cancel_token: CancellationToken::new(),
            claim_epoch: None,
        }
    }

    /// Construct a context with a relative timeout (deadline = now + timeout).
    pub fn with_timeout(job_id: impl Into<String>, timeout: Duration) -> Self {
        Self {
            job_id: job_id.into(),
            deadline: Some(Instant::now() + timeout),
            cancel_token: CancellationToken::new(),
            claim_epoch: None,
        }
    }

    /// Builder: attach the claim generation minted by the registry. Chains
    /// off [`Self::new`] / [`Self::with_timeout`].
    pub fn with_claim_epoch(mut self, claim_epoch: Option<i64>) -> Self {
        self.claim_epoch = claim_epoch;
        self
    }

    /// Seconds remaining until deadline, or `None` if no deadline is set.
    /// Returns `Some(0)` if the deadline has already passed.
    ///
    /// This is the INTROSPECTION shape: `Some(0)` is the meaningful "expired"
    /// answer that `current_job()`-style snapshots expose to SDK callers
    /// (which test it with `<= 0`). Do NOT use it to build the
    /// `X-Mesh-Timeout` header — see [`Self::timeout_header_seconds`].
    pub fn remaining_seconds(&self) -> Option<u64> {
        self.deadline.map(|d| {
            d.checked_duration_since(Instant::now())
                .map(|r| r.as_secs())
                .unwrap_or(0)
        })
    }

    /// The value to advertise in an outbound `X-Mesh-Timeout` header, or
    /// `None` when the header must be OMITTED (issue #1584).
    ///
    /// `None` is returned in two cases, and both mean "do not send the
    /// header":
    ///
    /// * no deadline is set (the design-doc default — unlimited), or
    /// * the deadline has already passed.
    ///
    /// Otherwise the remaining time is rounded UP to whole seconds and
    /// floored at 1.
    ///
    /// # Why not `remaining_seconds()`
    ///
    /// `remaining_seconds()` truncates, so any budget under a second — and
    /// every expired one — renders as `0`. `X-Mesh-Timeout` is `minimum: 1`
    /// in the registry OpenAPI schema (`XMeshTimeoutHeader`), and every
    /// receiver in the mesh treats a `<= 0` value as "unset" and substitutes
    /// its OWN default budget (Python `unified_mcp_proxy`, the registry
    /// proxy, the TS/Java clients). So emitting `0` does not communicate
    /// "almost out of time" — it communicates "no cap at all", which is the
    /// exact opposite of what the parent's deadline means, and it silently
    /// discards the parent-scope cap on every nested call made in the last
    /// second of a job.
    ///
    /// Rounding UP rather than down keeps a sub-second remainder expressible
    /// (`1` — the tightest budget the wire can carry) instead of collapsing
    /// it to the "unset" sentinel. Omitting on expiry matches what the Python
    /// outbound proxy already does today: the parent-scope CANCEL TOKEN, not
    /// a bogus header, is the authoritative signal that the call should not
    /// have been made.
    pub fn timeout_header_seconds(&self) -> Option<u64> {
        let remaining = self.deadline?.checked_duration_since(Instant::now())?;
        if remaining.is_zero() {
            return None;
        }
        // ceil to whole seconds; `remaining > 0` so this is always >= 1.
        let secs = remaining.as_secs() + u64::from(remaining.subsec_nanos() > 0);
        Some(secs.max(1))
    }

    /// Convenience: derive a child context with the same cancel-token but a
    /// tighter deadline. Used by nested-job logic — child cannot outlive
    /// parent (see "Nested jobs: strict deadline cap" in design doc).
    pub fn child(&self, child_job_id: impl Into<String>, child_timeout: Option<Duration>) -> Self {
        let deadline = match (self.deadline, child_timeout) {
            (Some(parent), Some(req)) => Some(parent.min(Instant::now() + req)),
            (Some(parent), None) => Some(parent),
            (None, Some(req)) => Some(Instant::now() + req),
            (None, None) => None,
        };
        Self {
            job_id: child_job_id.into(),
            deadline,
            cancel_token: self.cancel_token.child_token(),
            // A child job is a distinct claim (or none yet) — it does not
            // inherit the parent's claim generation.
            claim_epoch: None,
        }
    }
}

tokio::task_local! {
    /// Tokio task-local storage for the active job context. Use
    /// [`with_job`] to set it and [`current`] / [`try_current`] to read.
    pub static CURRENT_JOB: JobContext;
}

/// Look up the active job context on the current task.
///
/// Returns a cloned `JobContext` if one is active, `None` otherwise. Safe to
/// call from any async context — never panics. Sync callers that have a
/// tokio runtime handle should use this; pure-sync callers see `None`
/// because `task_local!` is task-scoped.
pub fn current() -> Option<JobContext> {
    CURRENT_JOB.try_with(|ctx| ctx.clone()).ok()
}

/// Sync-friendly alias for [`current`]. Documented separately so call sites
/// from FFI / blocking code make their intent clear.
///
/// The restriction is the same: returns `None` outside of any `with_job`
/// scope (i.e., when the current tokio task hasn't been entered through
/// `with_job`).
pub fn try_current() -> Option<JobContext> {
    current()
}

/// Seconds remaining on the active job's deadline, if any. Introspection
/// only — `Some(0)` means "expired". For outbound `X-Mesh-Timeout` header
/// construction use [`timeout_header_seconds`], which never yields the `0`
/// every receiver reads as "unset" (issue #1584).
pub fn remaining_seconds() -> Option<u64> {
    CURRENT_JOB.try_with(|ctx| ctx.remaining_seconds()).ok().flatten()
}

/// The `X-Mesh-Timeout` value for the active job's deadline, or `None` when
/// the header must be omitted (no deadline, no active context, or an expired
/// deadline). See [`JobContext::timeout_header_seconds`].
pub fn timeout_header_seconds() -> Option<u64> {
    CURRENT_JOB
        .try_with(|ctx| ctx.timeout_header_seconds())
        .ok()
        .flatten()
}

/// Run `f` with the given job context bound on the current async task.
///
/// Child tasks spawned via `tokio::spawn` do NOT automatically inherit
/// task-locals — wrap their bodies in `with_job(ctx, ...)` if propagation
/// is desired.
pub async fn with_job<F, R>(ctx: JobContext, f: F) -> R
where
    F: Future<Output = R>,
{
    CURRENT_JOB.scope(ctx, f).await
}

/// Inject job-related headers (`X-Mesh-Job-Id`, `X-Mesh-Timeout`) into a
/// `reqwest::RequestBuilder` if there is an active [`JobContext`] on the
/// current task. No-op otherwise.
///
/// `X-Mesh-Timeout` is only emitted when the active context has a deadline
/// that is set AND has not yet expired (per design doc: deadline is opt-in /
/// unlimited by default). The value is `ceil(remaining)` floored at 1 — never
/// `0`, which every receiver reads as "unset" (issue #1584).
///
/// This is the FFI-friendly hook: language SDKs that build their own
/// outbound HTTP requests through the Rust core (or wrap reqwest
/// directly) should call this at the call site, alongside any existing
/// `X-Trace-Id` propagation.
pub fn inject_job_headers(builder: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    match current() {
        None => builder,
        Some(ctx) => {
            let mut b = builder.header("X-Mesh-Job-Id", &ctx.job_id);
            match ctx.timeout_header_seconds() {
                Some(secs) => b = b.header("X-Mesh-Timeout", secs.to_string()),
                None if ctx.deadline.is_some() => {
                    // Deadline already blown. Omit rather than send "0" —
                    // "0" reads as "unset" downstream and would hand the
                    // child an unbounded budget. The parent-scope cancel
                    // token is the authoritative signal here.
                    tracing::warn!(
                        "outbound call under job={} has an expired deadline; \
                         omitting X-Mesh-Timeout instead of emitting an \
                         invalid '0' value",
                        ctx.job_id
                    );
                }
                None => {}
            }
            b
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap as Map;
    use std::sync::Arc;
    use std::time::Duration;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;
    use tokio::sync::Mutex as AMutex;
    use tokio::time::sleep;

    /// Spin up a one-shot HTTP server that records the request headers.
    /// Returns `(port, captured, join_handle)`.
    async fn spawn_header_capture_server() -> (
        u16,
        Arc<AMutex<Map<String, String>>>,
        tokio::task::JoinHandle<()>,
    ) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let captured: Arc<AMutex<Map<String, String>>> = Arc::new(AMutex::new(Map::new()));
        let captured_clone = captured.clone();
        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.unwrap();
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let mut hdrs = Map::new();
            for line in req.lines().skip(1) {
                if line.is_empty() {
                    break;
                }
                if let Some((k, v)) = line.split_once(':') {
                    hdrs.insert(k.trim().to_lowercase(), v.trim().to_string());
                }
            }
            *captured_clone.lock().await = hdrs;
            let resp = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok";
            sock.write_all(resp).await.unwrap();
        });
        (port, captured, server)
    }

    #[tokio::test]
    async fn current_returns_none_outside_scope() {
        assert!(current().is_none());
        assert!(try_current().is_none());
        assert!(remaining_seconds().is_none());
    }

    #[tokio::test]
    async fn with_job_sets_context_and_inner_sees_it() {
        let ctx = JobContext::new("job-abc");
        with_job(ctx, async {
            let active = current().expect("context should be visible inside with_job");
            assert_eq!(active.job_id, "job-abc");
            assert!(active.deadline.is_none());
        })
        .await;
        // Outside the scope: gone again.
        assert!(current().is_none());
    }

    #[tokio::test]
    async fn remaining_seconds_decreases_over_time() {
        let ctx = JobContext::with_timeout("job-timed", Duration::from_secs(2));
        with_job(ctx, async {
            let r0 = remaining_seconds().unwrap();
            assert!(r0 <= 2, "initial remaining should be <= 2s, got {}", r0);
            sleep(Duration::from_millis(1100)).await;
            let r1 = remaining_seconds().unwrap();
            assert!(r1 < r0, "remaining should decrease (r0={}, r1={})", r0, r1);
        })
        .await;
    }

    /// Issue #1584: the header value never renders as `0` — not for a
    /// sub-second remainder, not for an expired deadline.
    #[tokio::test]
    async fn timeout_header_seconds_never_zero() {
        // Sub-second remaining: truncation would give 0, we must give 1.
        let ctx = JobContext::with_timeout("job-subsec", Duration::from_millis(400));
        assert_eq!(ctx.remaining_seconds(), Some(0), "precondition: truncates to 0");
        assert_eq!(ctx.timeout_header_seconds(), Some(1));

        // Fractional over a second: rounds UP, never down.
        let ctx = JobContext::with_timeout("job-frac", Duration::from_millis(2_400));
        assert_eq!(ctx.remaining_seconds(), Some(2));
        assert_eq!(ctx.timeout_header_seconds(), Some(3));

        // No deadline: omit.
        assert_eq!(JobContext::new("job-none").timeout_header_seconds(), None);
    }

    /// Issue #1584: an expired deadline OMITS the header (returns `None`)
    /// rather than advertising `0`, which every receiver reads as "unset".
    #[tokio::test]
    async fn timeout_header_seconds_none_when_expired() {
        let ctx = JobContext::with_timeout("job-expired", Duration::from_millis(20));
        sleep(Duration::from_millis(80)).await;
        assert_eq!(ctx.remaining_seconds(), Some(0));
        assert_eq!(ctx.timeout_header_seconds(), None);
    }

    #[tokio::test]
    async fn remaining_seconds_zero_after_deadline() {
        let ctx = JobContext::with_timeout("job-expired", Duration::from_millis(50));
        with_job(ctx, async {
            sleep(Duration::from_millis(150)).await;
            assert_eq!(remaining_seconds(), Some(0));
        })
        .await;
    }

    #[tokio::test]
    async fn cancel_token_propagates() {
        let ctx = JobContext::new("job-cancel");
        let token = ctx.cancel_token.clone();

        let task = tokio::spawn(with_job(ctx, async {
            let inner_token = current().unwrap().cancel_token;
            tokio::select! {
                _ = sleep(Duration::from_secs(5)) => "done",
                _ = inner_token.cancelled() => "cancelled",
            }
        }));

        sleep(Duration::from_millis(50)).await;
        token.cancel();
        let outcome = task.await.unwrap();
        assert_eq!(outcome, "cancelled");
    }

    #[tokio::test]
    async fn child_context_caps_deadline_at_parent() {
        let parent = JobContext::with_timeout("parent-job", Duration::from_secs(2));
        let parent_deadline = parent.deadline.unwrap();
        // Request a longer child timeout: should be clamped to parent.
        let child = parent.child("child-job", Some(Duration::from_secs(60)));
        assert!(child.deadline.unwrap() <= parent_deadline);
        assert_eq!(child.job_id, "child-job");
    }

    #[tokio::test]
    async fn child_cancel_token_inherits_from_parent() {
        let parent = JobContext::new("parent-job");
        let child = parent.child("child-job", None);
        // Cancel parent → child cancels too.
        parent.cancel_token.cancel();
        assert!(child.cancel_token.is_cancelled());
    }

    #[tokio::test]
    async fn inject_job_headers_adds_headers_within_scope() {
        // Spin up a tiny mock server that captures incoming headers.
        use std::collections::HashMap as Map;
        use std::sync::Arc;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;
        use tokio::sync::Mutex as AMutex;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let captured: Arc<AMutex<Map<String, String>>> = Arc::new(AMutex::new(Map::new()));
        let captured_clone = captured.clone();

        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.unwrap();
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let mut hdrs = Map::new();
            for line in req.lines().skip(1) {
                if line.is_empty() {
                    break;
                }
                if let Some((k, v)) = line.split_once(':') {
                    hdrs.insert(k.trim().to_lowercase(), v.trim().to_string());
                }
            }
            *captured_clone.lock().await = hdrs;
            let resp = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok";
            sock.write_all(resp).await.unwrap();
        });

        let url = format!("http://127.0.0.1:{}/echo", port);
        let client = reqwest::Client::new();
        let ctx = JobContext::with_timeout("job-xyz", Duration::from_secs(45));
        with_job(ctx, async {
            let req = inject_job_headers(client.get(&url));
            let _ = req.send().await.unwrap();
        })
        .await;

        server.await.unwrap();
        let h = captured.lock().await;
        assert_eq!(h.get("x-mesh-job-id").map(String::as_str), Some("job-xyz"));
        let timeout = h.get("x-mesh-timeout").expect("X-Mesh-Timeout missing");
        let parsed: u64 = timeout.parse().unwrap();
        assert!(parsed <= 45, "remaining should be <= 45, got {}", parsed);
    }

    #[tokio::test]
    async fn inject_job_headers_noop_outside_scope() {
        // Without an active context, the builder should be returned unchanged.
        // Easiest test: build the request, send it (over a mock), and assert
        // the headers are absent.
        use std::collections::HashMap as Map;
        use std::sync::Arc;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;
        use tokio::sync::Mutex as AMutex;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let captured: Arc<AMutex<Map<String, String>>> = Arc::new(AMutex::new(Map::new()));
        let captured_clone = captured.clone();

        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.unwrap();
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let mut hdrs = Map::new();
            for line in req.lines().skip(1) {
                if line.is_empty() {
                    break;
                }
                if let Some((k, v)) = line.split_once(':') {
                    hdrs.insert(k.trim().to_lowercase(), v.trim().to_string());
                }
            }
            *captured_clone.lock().await = hdrs;
            let resp = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok";
            sock.write_all(resp).await.unwrap();
        });

        let url = format!("http://127.0.0.1:{}/echo", port);
        let client = reqwest::Client::new();
        let req = inject_job_headers(client.get(&url));
        let _ = req.send().await.unwrap();
        server.await.unwrap();
        let h = captured.lock().await;
        assert!(h.get("x-mesh-job-id").is_none());
        assert!(h.get("x-mesh-timeout").is_none());
    }

    /// Issue #1584 end-to-end over a real request: a job whose deadline has
    /// blown sends `X-Mesh-Job-Id` and NO `X-Mesh-Timeout`. Before the fix it
    /// sent `X-Mesh-Timeout: 0`, which the receiver treats as "unset" and
    /// replaces with its own (much larger) default budget — silently losing
    /// the parent's deadline cap.
    #[tokio::test]
    async fn inject_job_headers_omits_timeout_when_deadline_expired() {
        let (port, captured, server) = spawn_header_capture_server().await;
        let url = format!("http://127.0.0.1:{}/echo", port);
        let client = reqwest::Client::new();
        let ctx = JobContext::with_timeout("job-blown", Duration::from_millis(20));
        sleep(Duration::from_millis(80)).await;
        with_job(ctx, async {
            let req = inject_job_headers(client.get(&url));
            let _ = req.send().await.unwrap();
        })
        .await;
        server.await.unwrap();
        let h = captured.lock().await;
        assert_eq!(h.get("x-mesh-job-id").map(String::as_str), Some("job-blown"));
        assert!(
            h.get("x-mesh-timeout").is_none(),
            "expired deadline must OMIT X-Mesh-Timeout, got {:?}",
            h.get("x-mesh-timeout")
        );
    }

    /// Issue #1584: a live but sub-second budget is advertised as `1` (the
    /// tightest value the `minimum: 1` wire schema can carry), never `0`.
    #[tokio::test]
    async fn inject_job_headers_floors_sub_second_budget_at_one() {
        let (port, captured, server) = spawn_header_capture_server().await;
        let url = format!("http://127.0.0.1:{}/echo", port);
        let client = reqwest::Client::new();
        let ctx = JobContext::with_timeout("job-tight", Duration::from_millis(700));
        with_job(ctx, async {
            let req = inject_job_headers(client.get(&url));
            let _ = req.send().await.unwrap();
        })
        .await;
        server.await.unwrap();
        let h = captured.lock().await;
        let timeout = h.get("x-mesh-timeout").expect("X-Mesh-Timeout missing");
        assert_eq!(timeout, "1", "sub-second budget must floor at 1, not 0");
    }

    #[tokio::test]
    async fn inject_job_headers_omits_timeout_when_no_deadline() {
        use std::collections::HashMap as Map;
        use std::sync::Arc;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio::net::TcpListener;
        use tokio::sync::Mutex as AMutex;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let captured: Arc<AMutex<Map<String, String>>> = Arc::new(AMutex::new(Map::new()));
        let captured_clone = captured.clone();

        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.unwrap();
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let mut hdrs = Map::new();
            for line in req.lines().skip(1) {
                if line.is_empty() {
                    break;
                }
                if let Some((k, v)) = line.split_once(':') {
                    hdrs.insert(k.trim().to_lowercase(), v.trim().to_string());
                }
            }
            *captured_clone.lock().await = hdrs;
            let resp = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok";
            sock.write_all(resp).await.unwrap();
        });

        let url = format!("http://127.0.0.1:{}/echo", port);
        let client = reqwest::Client::new();
        let ctx = JobContext::new("job-no-deadline");
        with_job(ctx, async {
            let req = inject_job_headers(client.get(&url));
            let _ = req.send().await.unwrap();
        })
        .await;
        server.await.unwrap();
        let h = captured.lock().await;
        assert_eq!(
            h.get("x-mesh-job-id").map(String::as_str),
            Some("job-no-deadline")
        );
        assert!(h.get("x-mesh-timeout").is_none(), "timeout header should be absent");
    }
}
