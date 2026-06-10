//! Distributed tracing publisher for MCP Mesh.
//!
//! Publishes trace spans to Redis streams for distributed tracing.
//! This is the core implementation used by all language SDKs.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use redis::aio::{ConnectionManager, ConnectionManagerConfig};
use redis::AsyncCommands;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

use crate::config::{get_redis_url, is_tracing_enabled};

/// Redis stream name for trace data.
const TRACE_STREAM_NAME: &str = "mesh:trace";

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
    // stall inside init (the previous per-span code failed fast). Two
    // retries with a 500ms per-attempt connect timeout keeps the worst
    // case around ~2s.
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
            match ConnectionManager::new_with_config(client, cm_config).await {
                Ok(mut conn) => {
                    // Ping to verify
                    let result: Result<String, _> = redis::cmd("PING").query_async(&mut conn).await;
                    match result {
                        Ok(_) => {
                            debug!("Redis connection established for tracing");
                            state.conn = Some(conn);
                            state.available = true;
                            true
                        }
                        Err(e) => {
                            warn!("Redis ping failed: {}", e);
                            state.available = false;
                            false
                        }
                    }
                }
                Err(e) => {
                    warn!("Failed to connect to Redis: {}", e);
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
    // Clone the shared connection under a short read lock, then publish
    // without holding the lock. `ConnectionManager` clones share the same
    // underlying multiplexed connection — no per-span TCP dial.
    let mut conn = {
        let publisher = get_publisher();
        let state = publisher.read().await;

        if !state.enabled || !state.available {
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
            // Non-blocking - never fail agent operations. The manager
            // reconnects in the background; subsequent publishes succeed
            // once Redis is reachable again (this span is dropped).
            debug!("Failed to publish trace span: {}", e);
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
}
