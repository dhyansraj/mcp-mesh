"""
Shared tracing utilities for MCP Mesh distributed tracing.

Provides common functions used across multiple tracing modules to reduce code duplication
and maintain consistency.
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Try to import the Rust core module for tracing
# Falls back gracefully if not available
try:
    import mcp_mesh_core

    _RUST_CORE_AVAILABLE = True
except ImportError:
    mcp_mesh_core = None  # type: ignore[assignment]
    _RUST_CORE_AVAILABLE = False
    logger.warning(
        "mcp_mesh_core not available - tracing features will be disabled. "
        "Build/install mcp-mesh-core for full functionality."
    )


def is_tracing_enabled() -> bool:
    """Check if distributed tracing is enabled via Rust core config resolution.

    Delegates to mcp_mesh_core.is_tracing_enabled_py() for consistent behavior
    across all language SDKs. Priority: ENV > param > default (false)

    Returns:
        True if tracing is enabled, False otherwise
    """
    if not _RUST_CORE_AVAILABLE or mcp_mesh_core is None:
        return False

    return mcp_mesh_core.is_tracing_enabled_py()


def generate_span_id() -> str:
    """Generate a unique span ID for tracing (OpenTelemetry compliant).

    Returns:
        16-character hex string (64-bit span ID per OTel spec)
    """
    if _RUST_CORE_AVAILABLE:
        return mcp_mesh_core.generate_span_id_py()
    # Fallback when Rust core unavailable
    import uuid

    return uuid.uuid4().hex[:16]


def generate_trace_id() -> str:
    """Generate a unique trace ID for tracing (OpenTelemetry compliant).

    Returns:
        32-character hex string (128-bit trace ID per OTel spec)
    """
    if _RUST_CORE_AVAILABLE:
        return mcp_mesh_core.generate_trace_id_py()
    # Fallback when Rust core unavailable
    import uuid

    return uuid.uuid4().hex


def get_agent_metadata_with_fallback(logger_instance: logging.Logger) -> dict[str, Any]:
    """Get agent context metadata with graceful fallback.

    Attempts to retrieve agent metadata from the context helper, falling back
    to minimal defaults if unavailable. Never fails execution.

    Args:
        logger_instance: Logger for debug messages

    Returns:
        Dictionary containing agent metadata
    """
    try:
        from .agent_context_helper import get_trace_metadata

        return get_trace_metadata()
    except Exception as e:
        # Never fail execution due to agent metadata collection
        logger_instance.debug(f"Failed to get agent metadata: {e}")
        # Return minimal fallback metadata
        return {
            "agent_id": "unknown",
            "agent_name": "unknown",
            "agent_hostname": "unknown",
            "agent_ip": "unknown",
        }


def publish_trace_with_fallback(
    trace_data: dict[str, Any], logger_instance: logging.Logger
) -> None:
    """Publish trace data to Redis with graceful fallback.

    Attempts to publish trace data to Redis, silently handling failures
    to ensure trace publishing never breaks application execution.

    Issue #1364: does NOT gate on the cached ``publisher.is_available`` flag
    (latched at construction). Always delegate to the Rust sync binding
    (``publish_span_py``), which is the single source of truth — it short-
    circuits internally in microseconds while Redis is unavailable and resumes
    automatically once the Rust background re-prober reconnects, so a stale
    Python latch must never keep skipping a recovered connection. This is the
    SYNC path: it runs on an anyio worker thread (off the event loop), so the
    binding's block_on is harmless here. ``get_trace_publisher()`` is used
    (constructing) on purpose — off-loop construction is fine; the request event
    loop uses the non-constructing ``get_initialized_trace_publisher`` instead.

    Args:
        trace_data: Trace metadata to publish
        logger_instance: Logger for debug messages
    """
    try:
        from .redis_metadata_publisher import get_trace_publisher

        publisher = get_trace_publisher()
        publisher.publish_execution_trace(trace_data)
    except Exception:
        # Never fail agent operations due to trace publishing
        pass


async def publish_trace_with_fallback_async(
    trace_data: dict[str, Any], logger_instance: logging.Logger
) -> None:
    """Publish trace data to Redis on the event loop without blocking it.

    Async counterpart of ``publish_trace_with_fallback`` (issue #1363 RC1).
    Callers running ON the asyncio event loop (the async-tool wrapper and
    @mesh.route middleware) must ``await`` this so the Redis publish yields the
    loop instead of freezing concurrent request coroutines when the telemetry
    Redis is unreachable. Failures stay silent, matching the sync variant.

    Args:
        trace_data: Trace metadata to publish
        logger_instance: Logger for debug messages
    """
    try:
        from .redis_metadata_publisher import get_initialized_trace_publisher

        # Pure cached lookup — never construct the publisher here (issue #1363).
        # Its __init__ runs a sync block_on Redis connect; on this event loop
        # that would freeze concurrent request coroutines. The singleton is
        # built off the request path at agent startup
        # (init_trace_publisher_at_startup); if it isn't set yet, drop the span.
        # Issue #1364: do NOT gate on the cached ``publisher.is_available`` flag
        # (latched at construction). Always delegate to the Rust async binding,
        # which short-circuits internally in microseconds while Redis is
        # unavailable and resumes automatically once the Rust background
        # re-prober reconnects — a stale Python latch must never keep skipping a
        # recovered connection. Still uses the NON-constructing
        # get_initialized_trace_publisher() so no sync block_on init ever runs on
        # the event loop (RC4 preserved); if the singleton isn't built yet the
        # span is simply dropped.
        publisher = get_initialized_trace_publisher()
        if publisher is not None:
            await publisher.publish_execution_trace_async(trace_data)
    except Exception:
        # Never fail agent operations due to trace publishing
        pass


def add_timestamp_if_missing(trace_data: dict[str, Any]) -> None:
    """Add published_at timestamp to trace data if not present.

    Args:
        trace_data: Trace data dictionary to modify in-place
    """
    if "published_at" not in trace_data:
        trace_data["published_at"] = time.time()


def convert_for_redis_storage(trace_data: dict[str, Any]) -> dict[str, str]:
    """Convert trace data for Redis Stream storage.

    Converts complex types (lists, dicts) to JSON strings and handles None values
    for proper Redis Stream storage.

    Args:
        trace_data: Original trace data with mixed types

    Returns:
        Dictionary with all values converted to strings suitable for Redis
    """
    redis_trace_data = {}
    for key, value in trace_data.items():
        if isinstance(value, (list, dict)):
            # Convert lists and dicts to JSON strings
            redis_trace_data[key] = json.dumps(value)
        elif value is None:
            redis_trace_data[key] = "null"
        else:
            # Keep simple types as-is (str, int, float, bool)
            redis_trace_data[key] = str(value)

    return redis_trace_data
