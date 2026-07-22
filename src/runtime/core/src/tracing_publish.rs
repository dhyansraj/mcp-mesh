//! Distributed tracing publisher for MCP Mesh.
//!
//! Publishes trace spans to Redis streams for distributed tracing.
//! This is the core implementation used by all language SDKs.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use redis::aio::{ConnectionManager, ConnectionManagerConfig};
use redis::AsyncCommands;
use tokio::sync::RwLock;
use tracing::{debug, info, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

use crate::config::{get_redis_url, is_tracing_enabled};

/// Redis stream name for trace data.
const TRACE_STREAM_NAME: &str = "mesh:trace";

/// Cooldown between re-probe attempts once Redis has been marked unavailable
/// (issue #1364). Stored as an atomic so tests can shrink it for a
/// deterministic recovery assertion; production always uses the 5s default.
static REPROBE_COOLDOWN_MS: AtomicU64 = AtomicU64::new(5_000);

/// Current re-probe cooldown as a `Duration`.
fn reprobe_cooldown() -> Duration {
    Duration::from_millis(REPROBE_COOLDOWN_MS.load(Ordering::Relaxed))
}

/// Hard outer bound on a single connect + PING (issue #1363/#1364). Shared by
/// the startup connect and every background re-probe so the two never diverge.
///
/// `set_connection_timeout` on `ConnectionManagerConfig` does NOT reliably
/// bound the very first dial for every failure mode: a black-holed Redis (a
/// host that silently drops the SYN) was observed stalling ~118s — the OS TCP
/// connect timeout — despite the 500ms per-attempt setting, because that
/// per-attempt timeout isn't applied to the initial connection in the redis
/// crate version in use. This `tokio::time::timeout` guarantees the connect can
/// never stall a caller past the budget.
const INIT_CONNECT_BUDGET: Duration = Duration::from_secs(3);

/// Single-flight guard for the background re-prober (issue #1364): at most one
/// prober task exists at a time. Set via CAS before spawning and cleared by a
/// RAII [`ReproberGuard`] when the prober task ends for ANY reason — normal
/// return, panic, or cancellation at runtime shutdown — so it can never wedge
/// `true` and silently kill recovery (issue #1364 W1). As a second safety net,
/// `publish_span`'s unavailable short-circuit re-spawns the prober (idempotent
/// via the CAS), so even a prober that somehow died self-heals on the next
/// suppressed span.
static REPROBE_RUNNING: AtomicBool = AtomicBool::new(false);

/// Global trace publisher state.
struct TracePublisherState {
    /// Reconnecting multiplexed connection, created once at init and
    /// cheaply cloned per publish (issue #1166 MED-3 — previously every
    /// span paid a fresh TCP dial + handshake via
    /// `get_multiplexed_async_connection`). `ConnectionManager` is the
    /// redis crate's reconnect convention: when a command fails because
    /// the underlying connection died, the manager triggers a background
    /// reconnect and subsequent commands succeed once Redis is back — so
    /// a transient outage drops spans (acceptable for tracing) without
    /// failing forever.
    conn: Option<ConnectionManager>,
    /// Whether tracing is enabled.
    enabled: bool,
    /// Whether Redis is available. When false the publish path short-circuits
    /// instantly (read-lock only) and a single-flight background re-prober
    /// (issue #1364) is responsible for flipping it back on — no request ever
    /// pays a Redis reconnect.
    available: bool,
    /// Redis URL.
    redis_url: String,
}

impl Default for TracePublisherState {
    fn default() -> Self {
        Self {
            conn: None,
            enabled: false,
            available: false,
            redis_url: String::new(),
        }
    }
}

/// Global trace publisher singleton.
static PUBLISHER: std::sync::OnceLock<Arc<RwLock<TracePublisherState>>> = std::sync::OnceLock::new();

fn get_publisher() -> Arc<RwLock<TracePublisherState>> {
    PUBLISHER
        .get_or_init(|| Arc::new(RwLock::new(TracePublisherState::default())))
        .clone()
}

/// Build a fresh bounded `ConnectionManager` and verify it with a PING, all
/// under the hard [`INIT_CONNECT_BUDGET`] timeout.
///
/// Shared by [`init_trace_publisher`] and the background re-prober (issue
/// #1364) so the connect configuration and hard bound can never diverge.
/// Because it always constructs a brand-new manager it handles BOTH the cold
/// start (`conn == None`) and the rebuild-after-death (`conn == Some`) cases —
/// we never rely on a dead `ConnectionManager`'s own internal reconnect.
///
/// Takes no lock and performs no shared-state mutation; callers store the
/// result. Returns `None` (already logged) on any client-open, connect, PING,
/// or timeout failure.
async fn connect_and_verify(redis_url: &str) -> Option<ConnectionManager> {
    let client = match redis::Client::open(redis_url) {
        Ok(client) => client,
        Err(e) => {
            warn!("Failed to create Redis client for tracing: {}", e);
            return None;
        }
    };

    // Bounded config: ConnectionManager's DEFAULTS retry the first connection 6
    // times with exponential backoff and no connect timeout, which turns a down
    // Redis into a multi-second stall. 2 retries × 500ms per-attempt connect
    // timeout (hard-wrapped by INIT_CONNECT_BUDGET below) keeps a down or
    // black-holed Redis from stalling. The response timeout bounds every
    // subsequent command (the XADD): without it a black-holed Redis (accepts
    // connections, never replies) would stall publishes forever.
    let cm_config = ConnectionManagerConfig::new()
        .set_number_of_retries(2)
        .set_connection_timeout(Duration::from_millis(500))
        .set_response_timeout(Duration::from_secs(2));

    let connect = async {
        let mut conn = ConnectionManager::new_with_config(client, cm_config).await?;
        // Ping to verify the connection is actually usable.
        let _: String = redis::cmd("PING").query_async(&mut conn).await?;
        Ok::<ConnectionManager, redis::RedisError>(conn)
    };

    match tokio::time::timeout(INIT_CONNECT_BUDGET, connect).await {
        Ok(Ok(conn)) => {
            debug!("Redis connection established for tracing");
            Some(conn)
        }
        Ok(Err(e)) => {
            warn!("Failed to connect to Redis for tracing: {}", e);
            None
        }
        Err(_) => {
            warn!(
                "Redis connect for tracing exceeded {}s budget; tracing paused (will re-probe)",
                INIT_CONNECT_BUDGET.as_secs()
            );
            None
        }
    }
}

/// RAII reset for the single-flight guard (issue #1364 W1).
///
/// Dropping this clears [`REPROBE_RUNNING`] unconditionally. It is constructed
/// inside the spawned prober task right after the CAS wins, so it is dropped —
/// and the guard reset to `false` — on EVERY way the task can end: a normal
/// `return`, a panic while dialing Redis or taking a lock (the runtime catches
/// task panics and drops the future), or cancellation when the tokio runtime is
/// torn down. That guarantees the guard can never wedge `true` and permanently
/// kill recovery.
struct ReproberGuard;

impl Drop for ReproberGuard {
    fn drop(&mut self) {
        REPROBE_RUNNING.store(false, Ordering::SeqCst);
    }
}

/// Spawn the single-flight background re-prober (issue #1364).
///
/// This is the ONLY place that dials Redis on the unhealthy path — no request
/// ever pays a reconnect. Guarded by [`REPROBE_RUNNING`] via CAS so at most one
/// prober runs at a time. The prober loops `sleep(reprobe_cooldown())` → one
/// bounded [`connect_and_verify`] → on success stores the fresh connection and
/// flips `available` back on, then exits (the [`ReproberGuard`] clears the
/// single-flight guard on the way out); on failure it loops again — immortal
/// until it reconnects. `available == false` suppresses publishes, so the loop
/// must never give up on its own; single-flight keeps it to one task, the tokio
/// runtime cancels it at process shutdown, and `publish_span`'s unavailable
/// branch re-kicks it (idempotent CAS) should a prober ever die.
///
/// Spawned on the current tokio runtime handle. Every caller (the pyo3
/// `get_runtime().block_on`, the napi runtime, and the ffi `block_on`) reaches
/// this from inside an async context, so a current handle is always available;
/// if somehow it is not, we clear the guard and bail rather than panic.
///
/// Cheap and idempotent on the request path: when called from a suppressed
/// span the whole cost is `Handle::try_current` + a failed CAS (no lock, no
/// dial) if a prober is already running.
fn spawn_reprober(publisher: Arc<RwLock<TracePublisherState>>) {
    // Single-flight: only spawn if no prober is already running.
    if REPROBE_RUNNING
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return;
    }

    let handle = match tokio::runtime::Handle::try_current() {
        Ok(handle) => handle,
        Err(_) => {
            // No runtime to spawn on (should never happen — every call site is
            // inside an async context). No task was spawned, so no
            // ReproberGuard exists yet; release the guard directly so a later
            // failure can try again.
            REPROBE_RUNNING.store(false, Ordering::Release);
            warn!("trace re-prober not spawned: no current tokio runtime");
            return;
        }
    };

    handle.spawn(async move {
        // RAII reset: clears REPROBE_RUNNING on EVERY exit of this task —
        // normal return, panic, or cancellation (issue #1364 W1). Held for the
        // whole task body and dropped LAST, after the write lock below is
        // released, so a racing publish-failure that observes the cleared guard
        // has already seen `available == true` and won't spawn a redundant
        // prober (no lost-recovery window).
        let _guard = ReproberGuard;

        loop {
            tokio::time::sleep(reprobe_cooldown()).await;

            // Read the URL / enabled flag under a short read lock; never hold a
            // lock across the network dial below.
            let (enabled, url) = {
                let state = publisher.read().await;
                (state.enabled, state.redis_url.clone())
            };
            if !enabled {
                return;
            }

            // ONE bounded reconnect, off any lock.
            if let Some(conn) = connect_and_verify(&url).await {
                // Flip state ON under the write lock, then return. The write
                // guard drops at the end of this block (releasing the lock);
                // `_guard` drops afterwards, clearing REPROBE_RUNNING only once
                // `available == true` is already visible — so a racing publish-
                // failure that sees the cleared guard also sees availability
                // recovered (no spawn needed) or, if it flipped `available` off
                // again, re-spawns a fresh prober.
                let mut state = publisher.write().await;
                state.conn = Some(conn);
                state.available = true;
                info!("Redis reachable again; trace publishing resumed");
                return;
            }
        }
    });
}

/// Initialize the trace publisher.
///
/// Must be called before publishing spans. Checks if tracing is enabled
/// and initializes Redis connection.
///
/// # Returns
/// true if tracing is enabled and Redis is available, false otherwise.
pub async fn init_trace_publisher() -> bool {
    let publisher = get_publisher();

    let enabled = is_tracing_enabled();
    let redis_url = get_redis_url();

    {
        let mut state = publisher.write().await;
        state.enabled = enabled;
        state.redis_url = redis_url.clone();
        if !enabled {
            debug!("Distributed tracing: disabled");
            return false;
        }
    }

    info!("Distributed tracing: enabled");

    // Connect off the lock so the healthy read path is never blocked behind a
    // startup dial, and store the result under a brief write lock.
    match connect_and_verify(&redis_url).await {
        Some(conn) => {
            let mut state = publisher.write().await;
            state.conn = Some(conn);
            state.available = true;
            true
        }
        None => {
            {
                let mut state = publisher.write().await;
                state.available = false;
            }
            // Redis was down/unreachable at startup (`conn` stays None). Kick
            // the background re-prober so a Redis-down-at-startup agent recovers
            // when Redis later comes up (issue #1364 facet 2) — connect_and_verify
            // constructs a brand-new manager, no existing connection required.
            spawn_reprober(publisher.clone());
            false
        }
    }
}

/// Publish a trace span to Redis.
///
/// Publishes span data to the `mesh:trace` Redis stream.
/// Non-blocking - silently handles failures to never break agent operations.
///
/// # Arguments
/// * `span_data` - Map of span data (all values must be strings)
///
/// # Returns
/// true if published successfully, false otherwise.
pub async fn publish_span(span_data: HashMap<String, String>) -> bool {
    let publisher = get_publisher();

    // Request path — never pays a Redis reconnect (issue #1364).
    //
    // Clone the shared connection under a READ lock only, then publish without
    // holding the lock. `ConnectionManager` clones share the same underlying
    // multiplexed connection — no per-span TCP dial.
    //
    // Fast-paths:
    //   * tracing disabled or no connection → drop silently.
    //   * Redis marked unavailable → short-circuit INSTANTLY (read-lock only).
    //     The background re-prober is the only thing that dials Redis while
    //     unavailable, so no request ever stalls on a reconnect.
    let mut conn = {
        let state = publisher.read().await;
        if !state.enabled {
            return false;
        }
        if !state.available {
            // Short-circuit INSTANTLY (read-lock only) — never dial Redis on the
            // request path. Self-heal (issue #1364 W1): re-kick the single-flight
            // re-prober in case a prior one died (panic/cancellation). This is
            // idempotent — a no-op failed CAS while a prober is already running —
            // so the per-span cost here is just `Handle::try_current` + one
            // atomic CAS; spawn_reprober itself takes no lock and does no I/O.
            drop(state);
            spawn_reprober(publisher.clone());
            return false;
        }
        match &state.conn {
            Some(c) => c.clone(),
            None => return false,
        }
    };

    // Add timestamp if missing
    let mut data = span_data;
    if !data.contains_key("published_at") {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        data.insert("published_at".to_string(), timestamp.to_string());
    }

    // Convert to Redis field-value pairs
    let items: Vec<(&str, &str)> = data
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();

    // Publish to stream
    let result: Result<String, redis::RedisError> = conn
        .xadd(TRACE_STREAM_NAME, "*", &items)
        .await;
    match result {
        Ok(_msg_id) => {
            debug!("Published trace span to Redis stream");
            true
        }
        Err(e) => {
            // Non-blocking - never fail agent operations (issue #1364):
            // flip `available` off so subsequent spans short-circuit instantly
            // instead of each paying the full Redis timeout for the whole
            // outage, then KICK the single-flight background re-prober which is
            // the ONLY thing that dials Redis on the unhealthy path. The
            // reconnect rebuilds a fresh `ConnectionManager`, so this recovers
            // regardless of whether the socket died mid-life or was never up.
            {
                let mut state = publisher.write().await;
                state.available = false;
            }
            spawn_reprober(publisher.clone());
            debug!("Failed to publish trace span: {} (tracing paused; re-prober kicked)", e);
            false
        }
    }
}

/// Check if trace publishing is available.
pub async fn is_trace_publisher_available() -> bool {
    let publisher = get_publisher();
    let state = publisher.read().await;
    state.enabled && state.available
}

// =============================================================================
// Python bindings
// =============================================================================

// NB on shape: these detach from the Python interpreter around the
// ENTIRE block_on. The previous `block_on(py.allow_threads(|| async ...))`
// only released the GIL while *constructing* the future — block_on then
// ran the Redis I/O with the GIL held, stalling every Python thread for
// the duration of the network call.

#[cfg(feature = "python")]
#[pyfunction]
pub fn init_trace_publisher_py(py: Python<'_>) -> PyResult<bool> {
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime()
            .block_on(async { Ok(init_trace_publisher().await) })
    })
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn publish_span_py(py: Python<'_>, span_data: HashMap<String, String>) -> PyResult<bool> {
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime()
            .block_on(async { Ok(publish_span(span_data).await) })
    })
}

/// Async variant of [`publish_span_py`] (issue #1363 RC1).
///
/// Returns an awaitable that drives the Redis publish on the tokio runtime
/// and yields the asyncio loop while the network I/O is in flight, instead of
/// `block_on`-ing the calling OS thread. Callers running ON the event loop
/// (the async-tool wrapper and the `@mesh.route` middleware) must `await` this
/// so a stalled/unreachable Redis never freezes concurrent request coroutines.
/// The sync `publish_span_py` stays for the sync-tool path, which already runs
/// on an anyio worker thread where blocking is harmless.
#[cfg(feature = "python")]
#[pyfunction]
pub fn publish_span_async_py(
    py: Python<'_>,
    span_data: HashMap<String, String>,
) -> PyResult<Bound<'_, PyAny>> {
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        Ok(publish_span(span_data).await)
    })
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn is_trace_publisher_available_py(py: Python<'_>) -> PyResult<bool> {
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime()
            .block_on(async { Ok(is_trace_publisher_available().await) })
    })
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::Instant;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    /// Reset the process-global re-probe state so prober-sensitive tests are
    /// order-independent (issue #1364 W3). Each `#[tokio::test]` gets its own
    /// runtime, so a leaked immortal prober from a prior test is cancelled when
    /// that runtime drops (and the RAII [`ReproberGuard`] clears the guard on
    /// the way out) — but we reset the static atomics explicitly here so tests
    /// never depend on that drop timing. Call at the START of any test that
    /// asserts on `REPROBE_RUNNING`, connection counts, or recovery.
    fn reset_reprober_state() {
        REPROBE_RUNNING.store(false, Ordering::SeqCst);
        REPROBE_COOLDOWN_MS.store(5_000, Ordering::SeqCst);
    }

    #[test]
    fn test_trace_stream_name() {
        assert_eq!(TRACE_STREAM_NAME, "mesh:trace");
    }

    /// Issue #1166 MED-3: the publisher must establish ONE connection at
    /// init and reuse it across publishes — not dial Redis per span.
    /// Uses a minimal fake RESP server that counts accepted TCP
    /// connections and answers PING/XADD.
    ///
    /// NB: mutates process env (REDIS_URL, tracing flag) and the global
    /// publisher singleton; the test suite runs with --test-threads=1 in
    /// CI, matching the other env-mutating tests in this crate.
    #[tokio::test]
    async fn publisher_reuses_connection_across_publishes() {
        // Order-independence (issue #1364 W3): clear any leaked re-probe guard
        // so this test's connection-count assertion isn't perturbed by a prober
        // spawned in a prior test.
        reset_reprober_state();

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind fake redis");
        let addr = listener.local_addr().unwrap();
        let conn_count = Arc::new(AtomicUsize::new(0));
        let conn_count_srv = conn_count.clone();

        tokio::spawn(async move {
            loop {
                let Ok((mut sock, _)) = listener.accept().await else {
                    break;
                };
                conn_count_srv.fetch_add(1, Ordering::SeqCst);
                tokio::spawn(async move {
                    let mut buf = [0u8; 8192];
                    loop {
                        match sock.read(&mut buf).await {
                            Ok(0) | Err(_) => break,
                            Ok(n) => {
                                let req = String::from_utf8_lossy(&buf[..n]);
                                // RESP requests are arrays — one line
                                // starting with '*' per command. The
                                // client pipelines connection-setup
                                // commands (CLIENT SETINFO x2) in a
                                // single chunk, so reply once PER
                                // command or the connect handshake
                                // hangs waiting for missing replies.
                                // "+PONG" parses fine as the reply to
                                // every command this test triggers
                                // (PING, CLIENT SETINFO, XADD-as-String).
                                let ncmds = req
                                    .split("\r\n")
                                    .filter(|line| line.starts_with('*'))
                                    .count()
                                    .max(1);
                                let resp = "+PONG\r\n".repeat(ncmds);
                                if sock.write_all(resp.as_bytes()).await.is_err() {
                                    break;
                                }
                            }
                        }
                    }
                });
            }
        });

        std::env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        std::env::set_var("REDIS_URL", format!("redis://{}", addr));

        // Bound every await so a handshake regression fails the test
        // instead of hanging the (single-threaded) suite.
        let budget = std::time::Duration::from_secs(10);
        let inited = tokio::time::timeout(budget, init_trace_publisher())
            .await
            .expect("init timed out against the fake server");
        assert!(inited, "init must succeed against the fake server");
        assert!(is_trace_publisher_available().await);

        for i in 0..3 {
            let span: HashMap<String, String> =
                HashMap::from([("span".to_string(), format!("s{}", i))]);
            let published = tokio::time::timeout(budget, publish_span(span))
                .await
                .unwrap_or_else(|_| panic!("publish {} timed out", i));
            assert!(published, "publish {} must succeed", i);
        }

        assert_eq!(
            conn_count.load(Ordering::SeqCst),
            1,
            "all publishes must reuse the single init-time connection"
        );

        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        std::env::remove_var("REDIS_URL");
    }

    /// Issue #1363: a black-holed / non-accepting Redis must not stall init
    /// past the hard connect budget. Uses TEST-NET-1 (192.0.2.1, RFC 5737),
    /// guaranteed unroutable, so the SYN is silently dropped — the exact
    /// failure mode observed hanging ~118s before the outer `tokio::time::
    /// timeout` was added. init must soft-fail (return false) well within a
    /// few seconds instead of waiting out the OS TCP connect timeout.
    ///
    /// NB: mutates process env + the global publisher singleton; the suite
    /// runs --test-threads=1 in CI, matching the other env-mutating tests.
    #[tokio::test]
    async fn init_bounds_blackholed_redis_connect() {
        // Order-independence (issue #1364 W3): this test's failed init spawns an
        // immortal prober toward the black-holed host that leaks
        // REPROBE_RUNNING=true until the runtime drops; reset up front so a
        // leaked guard from a prior test can't suppress this init's own prober.
        reset_reprober_state();

        std::env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        std::env::set_var("REDIS_URL", "redis://192.0.2.1:6379");

        let start = Instant::now();
        // Generous outer assertion budget: the internal hard bound is 3s, so
        // this must resolve well under 8s even with scheduler jitter. Without
        // the fix this would sit for the full OS connect timeout (~118s).
        let inited = tokio::time::timeout(Duration::from_secs(8), init_trace_publisher())
            .await
            .expect("init must not hang past the hard connect budget");
        let elapsed = start.elapsed();

        assert!(!inited, "init against a black-holed Redis must return false");
        assert!(
            !is_trace_publisher_available().await,
            "publisher must be unavailable after a failed init"
        );
        assert!(
            elapsed < Duration::from_secs(6),
            "init must soft-fail within the hard budget, took {:?}",
            elapsed
        );

        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        std::env::remove_var("REDIS_URL");
    }

    /// Issue #1364: after a Redis-down-at-startup init fails, the single-flight
    /// background re-prober must construct a fresh connection when Redis comes
    /// up and flip `available` back on — WITHOUT any request paying the
    /// reconnect. Fake RESP server that rejects (closes immediately) the first
    /// two TCP connections, then serves PONG: init's connect is rejected
    /// (available=false, prober spawned), the prober's first attempt is
    /// rejected, and its second attempt succeeds — proving recovery from a cold
    /// start (`conn == None` at init) within a bounded number of cooldowns.
    ///
    /// NB: mutates process env + the global publisher singleton + the shared
    /// re-probe cooldown/guard; the suite runs --test-threads=1 in CI.
    #[tokio::test]
    async fn reprober_recovers_from_cold_start() {
        use std::sync::atomic::AtomicUsize;

        // Order-independence (issue #1364 W3): a prior test may have left the
        // single-flight guard set when its runtime was torn down mid-probe;
        // clear it (and restore the default cooldown) so this test's init can
        // spawn a prober. Then shrink the cooldown for a fast, deterministic
        // recovery assertion.
        reset_reprober_state();
        REPROBE_COOLDOWN_MS.store(50, Ordering::SeqCst);

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind fake redis");
        let addr = listener.local_addr().unwrap();
        let accepted = Arc::new(AtomicUsize::new(0));
        let accepted_srv = accepted.clone();

        // Reject the first N connections (close immediately → fast connect
        // failure), then serve PONG so the prober's later attempt succeeds.
        //
        // W2: init's connect_and_verify uses set_number_of_retries(2), so a
        // rejecting server can see up to 1 initial + 2 retries = 3 connection
        // attempts from init alone. REJECT_FIRST must STRICTLY exceed that so
        // init can never stumble onto a served socket and succeed (which would
        // break `assert!(!inited)` and the whole cold-start premise). 4 > 3
        // guarantees every one of init's attempts is rejected regardless of how
        // many it actually makes; the prober's attempt #5 is the first served.
        const REJECT_FIRST: usize = 4;
        tokio::spawn(async move {
            loop {
                let Ok((mut sock, _)) = listener.accept().await else {
                    break;
                };
                let n = accepted_srv.fetch_add(1, Ordering::SeqCst) + 1;
                if n <= REJECT_FIRST {
                    // Drop the socket to force a fast connect/handshake failure.
                    drop(sock);
                    continue;
                }
                tokio::spawn(async move {
                    let mut buf = [0u8; 8192];
                    loop {
                        match sock.read(&mut buf).await {
                            Ok(0) | Err(_) => break,
                            Ok(rn) => {
                                let req = String::from_utf8_lossy(&buf[..rn]);
                                let ncmds = req
                                    .split("\r\n")
                                    .filter(|line| line.starts_with('*'))
                                    .count()
                                    .max(1);
                                let resp = "+PONG\r\n".repeat(ncmds);
                                if sock.write_all(resp.as_bytes()).await.is_err() {
                                    break;
                                }
                            }
                        }
                    }
                });
            }
        });

        std::env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        std::env::set_var("REDIS_URL", format!("redis://{}", addr));

        // Init's connect is rejected → soft-fail, prober spawned.
        let inited = tokio::time::timeout(Duration::from_secs(8), init_trace_publisher())
            .await
            .expect("init must not hang");
        assert!(!inited, "init must fail while the fake server rejects connects");
        assert!(
            !is_trace_publisher_available().await,
            "publisher must be unavailable right after the rejected init"
        );
        assert!(
            REPROBE_RUNNING.load(Ordering::SeqCst),
            "a background re-prober must be running after a failed init"
        );

        // W2: assert on the OBSERVED attempt count rather than assuming init
        // makes exactly one. Read before the prober's first ~50ms cooldown
        // elapses, so this reflects init's attempts alone: at least one dial,
        // and all of them within the rejected window (init never reached a
        // served socket — it soft-failed, exactly as the cold-start test needs).
        let init_attempts = accepted.load(Ordering::SeqCst);
        assert!(
            init_attempts >= 1,
            "init must have made at least one connection attempt, saw {init_attempts}"
        );
        assert!(
            init_attempts <= REJECT_FIRST,
            "init must not have reached a served socket, saw {init_attempts} (> {REJECT_FIRST})"
        );

        // The prober rebuilds a fresh ConnectionManager each attempt; once the
        // server starts serving it must flip `available` back on within a
        // bounded number of ~50ms cooldowns.
        let deadline = Instant::now() + Duration::from_secs(5);
        let mut recovered = false;
        while Instant::now() < deadline {
            if is_trace_publisher_available().await {
                recovered = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        assert!(
            recovered,
            "re-prober must reconnect (cold start) and flip available=true"
        );
        assert!(
            !REPROBE_RUNNING.load(Ordering::SeqCst),
            "the re-prober must clear its single-flight guard on success"
        );
        assert!(
            accepted.load(Ordering::SeqCst) > REJECT_FIRST,
            "recovery must have required more than the rejected connects"
        );

        // A publish now succeeds against the recovered connection.
        let span: HashMap<String, String> =
            HashMap::from([("span".to_string(), "recovered".to_string())]);
        let published = tokio::time::timeout(Duration::from_secs(5), publish_span(span))
            .await
            .expect("publish must not hang");
        assert!(published, "publish must succeed after recovery");

        // Restore shared state for other tests.
        REPROBE_COOLDOWN_MS.store(5_000, Ordering::SeqCst);
        std::env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
        std::env::remove_var("REDIS_URL");
    }
}
