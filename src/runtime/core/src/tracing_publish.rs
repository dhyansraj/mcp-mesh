//! Distributed tracing publisher for MCP Mesh.
//!
//! Publishes trace spans to Redis streams for distributed tracing.
//! This is the core implementation used by all language SDKs.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

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
    /// Redis client (lazily initialized).
    client: Option<redis::Client>,
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
            client: None,
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

    // Initialize Redis client
    match redis::Client::open(state.redis_url.as_str()) {
        Ok(client) => {
            // Test connection
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    // Ping to verify
                    let result: Result<String, _> = redis::cmd("PING").query_async(&mut conn).await;
                    match result {
                        Ok(_) => {
                            debug!("Redis connection established for tracing");
                            state.client = Some(client);
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
    let publisher = get_publisher();
    let state = publisher.read().await;

    if !state.enabled || !state.available {
        return false;
    }

    let client = match &state.client {
        Some(c) => c,
        None => return false,
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
    match client.get_multiplexed_async_connection().await {
        Ok(mut conn) => {
            let result: Result<String, redis::RedisError> = conn
                .xadd(TRACE_STREAM_NAME, "*", &items)
                .await;
            match result {
                Ok(_msg_id) => {
                    debug!("Published trace span to Redis stream");
                    true
                }
                Err(e) => {
                    // Non-blocking - never fail agent operations
                    debug!("Failed to publish trace span: {}", e);
                    false
                }
            }
        }
        Err(e) => {
            debug!("Failed to get Redis connection: {}", e);
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

#[cfg(feature = "python")]
#[pyfunction]
pub fn init_trace_publisher_py(py: Python<'_>) -> PyResult<bool> {
    // Run async function in tokio runtime
    pyo3_async_runtimes::tokio::get_runtime().block_on(py.allow_threads(|| async {
        Ok(init_trace_publisher().await)
    }))
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn publish_span_py(py: Python<'_>, span_data: HashMap<String, String>) -> PyResult<bool> {
    // Run async function in tokio runtime
    pyo3_async_runtimes::tokio::get_runtime().block_on(py.allow_threads(|| async {
        Ok(publish_span(span_data).await)
    }))
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn is_trace_publisher_available_py(py: Python<'_>) -> PyResult<bool> {
    pyo3_async_runtimes::tokio::get_runtime().block_on(py.allow_threads(|| async {
        Ok(is_trace_publisher_available().await)
    }))
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_trace_stream_name() {
        assert_eq!(TRACE_STREAM_NAME, "mesh:trace");
    }
}
