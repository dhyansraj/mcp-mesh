"""
Redis Trace Publisher

Publishes execution trace data to Redis streams for distributed tracing storage and analysis.
Uses Rust core for Redis publishing to share implementation across all language SDKs.
"""

import logging
from typing import Any, Optional

import mcp_mesh_core

logger = logging.getLogger(__name__)


class RedisTracePublisher:
    """Non-blocking execution trace publisher to Redis via Rust core."""

    def __init__(self):
        self.stream_name = "mesh:trace"
        self._available = False
        self._tracing_enabled = mcp_mesh_core.is_tracing_enabled_py()

        if self._tracing_enabled:
            logger.info("Distributed tracing: enabled")
            # Initialize Rust core trace publisher (handles Redis connection)
            self._available = mcp_mesh_core.init_trace_publisher_py()
            if not self._available:
                logger.warning("Rust core trace publisher initialization failed")
        else:
            logger.debug("Distributed tracing: disabled")

    def publish_execution_trace(self, trace_data: dict[str, Any]) -> None:
        """Publish execution trace data to Redis Stream via Rust core (non-blocking)."""
        if not self._available:
            return  # Silent no-op when Redis unavailable

        try:
            # Convert trace data to strings for Redis storage
            from .utils import add_timestamp_if_missing, convert_for_redis_storage

            add_timestamp_if_missing(trace_data)
            redis_trace_data = convert_for_redis_storage(trace_data)

            # Publish via Rust core
            mcp_mesh_core.publish_span_py(redis_trace_data)
            logger.debug(
                f"Published trace for '{trace_data.get('function_name', 'unknown')}' via Rust core"
            )

        except Exception as e:
            # Non-blocking - never fail agent operations due to trace publishing
            logger.debug(f"Failed to publish trace: {e}")

    async def publish_execution_trace_async(self, trace_data: dict[str, Any]) -> None:
        """Publish execution trace via Rust core, awaiting the async binding.

        Issue #1363 RC1: callers running ON the asyncio event loop (the
        async-tool wrapper and @mesh.route middleware) must use this instead of
        the sync ``publish_execution_trace`` so a stalled/unreachable telemetry
        Redis yields the loop rather than blocking every concurrent request.
        """
        if not self._available:
            return  # Silent no-op when Redis unavailable

        try:
            from .utils import add_timestamp_if_missing, convert_for_redis_storage

            add_timestamp_if_missing(trace_data)
            redis_trace_data = convert_for_redis_storage(trace_data)

            # Await the async Rust binding so the network I/O never blocks the
            # event-loop thread. Falls back to the sync binding on a worker
            # thread if an older core lacks the async export (version skew).
            publish_async = getattr(mcp_mesh_core, "publish_span_async_py", None)
            if publish_async is not None:
                await publish_async(redis_trace_data)
            else:
                import asyncio

                await asyncio.to_thread(
                    mcp_mesh_core.publish_span_py, redis_trace_data
                )
            logger.debug(
                f"Published trace for '{trace_data.get('function_name', 'unknown')}' via Rust core (async)"
            )

        except Exception as e:
            # Non-blocking - never fail agent operations due to trace publishing
            logger.debug(f"Failed to publish trace (async): {e}")

    @property
    def is_available(self) -> bool:
        """Check if Redis trace storage is available."""
        return self._available

    @property
    def is_enabled(self) -> bool:
        """Check if tracing is enabled via environment variable."""
        return self._tracing_enabled

    def get_stats(self) -> dict[str, Any]:
        """Get Redis trace publisher statistics."""
        return {
            "redis_available": self._available,
            "tracing_enabled": self._tracing_enabled,
            "stream_name": self.stream_name,
            "backend": "rust_core",
        }


# Global instance for reuse
_trace_publisher: Optional[RedisTracePublisher] = None


def get_trace_publisher() -> RedisTracePublisher:
    """Get or create global trace publisher instance.

    Constructing the publisher runs a SYNC ``block_on`` Redis connect in the
    Rust core (``RedisTracePublisher.__init__``). Do NOT call this on the
    request event loop — use :func:`init_trace_publisher_at_startup` at agent
    startup and :func:`get_initialized_trace_publisher` on the request path
    (issue #1363).
    """
    global _trace_publisher
    if _trace_publisher is None:
        _trace_publisher = RedisTracePublisher()
    return _trace_publisher


def get_initialized_trace_publisher() -> Optional[RedisTracePublisher]:
    """Return the publisher singleton IF already built, else None.

    Request-path callers running ON the asyncio event loop use this instead of
    :func:`get_trace_publisher` so a missing/late startup init can never trigger
    the sync ``block_on`` Redis connect on the serving loop (issue #1363). When
    the singleton hasn't been constructed yet the span is simply dropped.
    """
    return _trace_publisher


def init_trace_publisher_at_startup() -> None:
    """Construct the trace-publisher singleton once, at agent startup.

    Issue #1363: the publisher was previously built lazily on the FIRST traced
    span, and its ``__init__`` runs a SYNC ``block_on`` Redis connect. On the
    request event loop that froze every concurrent coroutine for the connect
    duration (empirically ~118s against a black-holed telemetry Redis before the
    Rust-side hard bound). Building it here — off the request path, once —
    performs that (now hard-bounded) connect at startup so the request-path
    lookup is a pure cached read.

    No-op when tracing is disabled (no publisher, no connection). Never raises:
    a telemetry Redis outage must never fail agent startup.
    """
    try:
        if not mcp_mesh_core.is_tracing_enabled_py():
            logger.debug("Distributed tracing disabled; skipping publisher init")
            return
        get_trace_publisher()
    except Exception as e:
        # Telemetry Redis must never fail agent startup — log and continue.
        logger.warning(
            "Trace publisher startup init failed (continuing without tracing): %s",
            e,
        )
