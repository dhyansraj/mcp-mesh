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
    pub fn remaining_seconds(&self) -> Option<u64> {
        self.deadline.map(|d| {
            d.checked_duration_since(Instant::now())
                .map(|r| r.as_secs())
                .unwrap_or(0)
        })
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

/// Seconds remaining on the active job's deadline, if any. Convenience for
/// outbound header injection: `X-Mesh-Timeout: <remaining>`.
pub fn remaining_seconds() -> Option<u64> {
    CURRENT_JOB.try_with(|ctx| ctx.remaining_seconds()).ok().flatten()
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
/// set (per design doc: deadline is opt-in / unlimited by default).
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
            if let Some(remaining) = ctx.remaining_seconds() {
                b = b.header("X-Mesh-Timeout", remaining.to_string());
            }
            b
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tokio::time::sleep;

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
