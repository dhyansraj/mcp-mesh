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
    """Get or create global trace publisher instance."""
    global _trace_publisher
    if _trace_publisher is None:
        _trace_publisher = RedisTracePublisher()
    return _trace_publisher
