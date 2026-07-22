//! Distributed tracing publisher for MCP Mesh.
//!
//! Publishes trace spans to Redis streams for distributed tracing.
//! This is the core implementation used by all language SDKs.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use redis::aio::{ConnectionManager, ConnectionManagerConfig};
use redis::AsyncCommands;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

use crate::config::{get_redis_url, is_tracing_enabled};

/// Redis stream name for trace data.
const TRACE_STREAM_NAME: &str = "mesh:trace";

/// Cooldown between re-probes once Redis has been marked unavailable.
///
/// Issue #1363 RC2: on a publish failure `available` is flipped to false so
/// subsequent spans short-circuit instantly instead of each paying the full
/// Redis timeout (connect 500ms + response 2s × retries) for the whole
/// outage. Redis can recover though, so one span per cooldown is let through
/// to re-test the connection and flip `available` back on when it succeeds.
const REPROBE_COOLDOWN: Duration = Duration::from_secs(5);

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
    /// Whether Redis is available.
    available: bool,
    /// When Redis publishing was last marked unavailable / last re-probed
    /// (issue #1363 RC2). Gates the lazy re-probe: while unavailable, only one
    /// span per `REPROBE_COOLDOWN` is let through to re-test the connection so
    /// a sustained outage never makes every span pay the full Redis timeout.
    last_failure: Option<Instant>,
    /// Redis URL.
    redis_url: String,
}

impl Default for TracePublisherState {
    fn default() -> Self {
        Self {
            conn: None,
            enabled: false,
            available: false,
            last_failure: None,
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

/// Initialize the trace publisher.
///
/// Must be called before publishing spans. Checks if tracing is enabled
/// and initializes Redis connection.
///
/// # Returns
/// true if tracing is enabled and Redis is available, false otherwise.
pub async fn init_trace_publisher() -> bool {
    let publisher = get_publisher();
    let mut state = publisher.write().await;

    // Check if tracing is enabled
    state.enabled = is_tracing_enabled();
    if !state.enabled {
        debug!("Distributed tracing: disabled");
        return false;
    }

    info!("Distributed tracing: enabled");

    // Get Redis URL
    state.redis_url = get_redis_url();

    // Initialize the reconnecting connection once; publishes clone it.
    //
    // Bound the initial connect: ConnectionManager's DEFAULTS retry the
    // first connection 6 times with exponential backoff and no connect
    // timeout, which turns a down Redis into a multi-second agent-startup
    // stall inside init (the previous per-span code failed fast). The bounded
    // config below (2 retries × 500ms per-attempt connect timeout, hard-wrapped
    // by the 3s `tokio::time::timeout` further down) keeps a down or
    // blackholed Redis from stalling startup.
    //
    // The response timeout bounds every subsequent command too (the XADD
    // on the drain task): without it, a black-holed Redis (accepts
    // connections, never replies) would stall publishes forever — the
    // manager only triggers a reconnect when a command actually errors.
    match redis::Client::open(state.redis_url.as_str()) {
        Ok(client) => {
            let cm_config = ConnectionManagerConfig::new()
                .set_number_of_retries(2)
                .set_connection_timeout(Duration::from_millis(500))
                .set_response_timeout(Duration::from_secs(2));

            // Hard outer bound on the whole connect + PING (issue #1363).
            // `set_connection_timeout` above does NOT reliably bound the very
            // first `new_with_config` dial for every failure mode: a
            // black-holed Redis (a host that silently drops the SYN) was
            // observed stalling this init ~118s — the OS TCP connect timeout —
            // despite the 500ms per-attempt setting, because that per-attempt
            // timeout isn't applied to the initial connection in the redis
            // crate version in use. This `tokio::time::timeout` guarantees init
            // can never stall startup (or any caller) past the budget; on
            // timeout we soft-fail (available=false, log a warn) and continue
            // with tracing effectively no-op'd until the lazy re-probe.
            const INIT_CONNECT_BUDGET: Duration = Duration::from_secs(3);
            let connect = async {
                let mut conn = ConnectionManager::new_with_config(client, cm_config).await?;
                // Ping to verify
                let _: String = redis::cmd("PING").query_async(&mut conn).await?;
                Ok::<ConnectionManager, redis::RedisError>(conn)
            };
            match tokio::time::timeout(INIT_CONNECT_BUDGET, connect).await {
                Ok(Ok(conn)) => {
                    debug!("Redis connection established for tracing");
                    state.conn = Some(conn);
                    state.available = true;
                    true
                }
                Ok(Err(e)) => {
                    warn!("Failed to connect to Redis for tracing: {}", e);
                    state.available = false;
                    false
                }
                Err(_) => {
                    warn!(
                        "Redis connect for tracing exceeded {}s budget; tracing paused (will re-probe)",
                        INIT_CONNECT_BUDGET.as_secs()
                    );
                    state.available = false;
                    false
                }
            }
        }
        Err(e) => {
            warn!("Failed to create Redis client: {}", e);
            state.available = false;
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

    // Clone the shared connection under a short lock, then publish without
    // holding the lock. `ConnectionManager` clones share the same underlying
    // multiplexed connection — no per-span TCP dial.
    //
    // Fast-paths (issue #1363 RC2):
    //   * tracing disabled or no connection → drop silently.
    //   * Redis previously marked unavailable → short-circuit instantly (no
    //     per-span Redis timeout) until the re-probe cooldown elapses, then
    //     let exactly ONE span through to re-test the connection.
    // `was_available` records which path we took so the healthy path never
    // pays a write lock: the flag is only toggled on a state *transition*.
    let (mut conn, was_available) = {
        let state = publisher.read().await;
        if !state.enabled {
            return false;
        }
        if state.available {
            match &state.conn {
                Some(c) => (c.clone(), true),
                None => return false,
            }
        } else {
            // Unavailable: gate a single re-probe per cooldown under the write
            // lock so concurrent spans don't all pay the timeout together.
            drop(state);
            let mut state = publisher.write().await;
            if !state.enabled {
                return false;
            }
            // Another span may have re-probed successfully while we waited.
            if state.available {
                match &state.conn {
                    Some(c) => (c.clone(), true),
                    None => return false,
                }
            } else {
                let due = state
                    .last_failure
                    .map(|t| t.elapsed() >= REPROBE_COOLDOWN)
                    .unwrap_or(true);
                if !due {
                    return false;
                }
                // Reserve this cooldown window for our probe; other spans that
                // race in now see the fresh timestamp and short-circuit.
                state.last_failure = Some(Instant::now());
                match &state.conn {
                    Some(c) => (c.clone(), false),
                    None => return false,
                }
            }
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
            if was_available {
                debug!("Published trace span to Redis stream");
            } else {
                // Re-probe succeeded: Redis is back. Flip `available` on so
                // the fast healthy path resumes for subsequent spans.
                let mut state = publisher.write().await;
                state.available = true;
                state.last_failure = None;
                debug!("Redis reachable again; trace publishing resumed");
            }
            true
        }
        Err(e) => {
            // Non-blocking - never fail agent operations (issue #1363 RC2):
            // flip `available` off so subsequent spans short-circuit instantly
            // instead of each paying the full Redis timeout for the whole
            // outage. The manager reconnects in the background; the lazy
            // re-probe (one span per cooldown) flips it back on once Redis is
            // reachable again (this span is dropped).
            //
            // NB: this recovery only covers a MID-LIFE outage — Redis was
            // reachable at init (so `conn` is `Some`) and later dropped; the
            // re-probe clones that live `ConnectionManager`, which reconnects.
            // A STARTUP outage (Redis never reachable at init → `conn` is
            // `None`) does NOT recover: the re-probe branch hits `None` and
            // returns without ever re-establishing a connection. Tracked in
            // issue #1364.
            let mut state = publisher.write().await;
            state.available = false;
            state.last_failure = Some(Instant::now());
            debug!("Failed to publish trace span: {} (tracing paused; will re-probe)", e);
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
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

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
}
