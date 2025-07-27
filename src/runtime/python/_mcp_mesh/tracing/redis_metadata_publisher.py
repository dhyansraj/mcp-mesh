"""
Redis Trace Publisher

Publishes execution trace data to Redis streams for distributed tracing storage and analysis.
Based on the session storage pattern from http_wrapper.py.
"""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None


class RedisTracePublisher:
    """Non-blocking execution trace publisher to Redis."""

    def __init__(self, redis_url: Optional[str] = None):
        # Use existing REDIS_URL pattern from MCP Mesh
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.stream_name = "mesh:trace"
        self._redis_client = None
        self._available = False
        self._tracing_enabled = self._is_tracing_enabled()

        if not REDIS_AVAILABLE:
            logger.warning("redis not available. Execution metadata storage disabled.")
            self._available = False
        else:
            self._init_redis()

    def _is_tracing_enabled(self) -> bool:
        """Check if distributed tracing is enabled via environment variable."""
        return os.getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def _init_redis(self):
        """Initialize Redis connection with graceful fallback (following session storage pattern)."""
        if not self._tracing_enabled:
            self._available = False
            logger.info("Distributed tracing: disabled")
            return

        logger.info("Distributed tracing: enabled")

        if not REDIS_AVAILABLE:
            self._available = False
            return

        try:
            # Use sync Redis client like session storage (no atexit issues)
            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)

            # Test connection
            self._redis_client.ping()
            self._available = True
        except Exception as e:
            # Graceful fallback - metadata storage disabled if Redis unavailable
            self._available = False

    def publish_execution_trace(self, trace_data: dict[str, Any]) -> None:
        """Publish execution trace data to Redis Stream (non-blocking)."""
        if not self._available:
            return  # Silent no-op when Redis unavailable

        try:
            # Add timestamp to trace data if not present
            if "published_at" not in trace_data:
                import time

                trace_data["published_at"] = time.time()

            # Convert complex types to JSON strings for Redis Stream storage
            redis_trace_data = {}
            for key, value in trace_data.items():
                if isinstance(value, (list, dict)):
                    # Convert lists and dicts to JSON strings
                    import json

                    redis_trace_data[key] = json.dumps(value)
                elif value is None:
                    redis_trace_data[key] = "null"
                else:
                    # Keep simple types as-is (str, int, float, bool)
                    redis_trace_data[key] = str(value)

            # Publish to Redis Stream
            if self._redis_client:
                self._redis_client.xadd(self.stream_name, redis_trace_data)

        except Exception as e:
            # Non-blocking - never fail agent operations due to trace publishing
            logger.warning(f"Failed to publish execution trace to Redis: {e}")

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
        stats = {
            "redis_available": self._available,
            "tracing_enabled": self._tracing_enabled,
            "stream_name": self.stream_name,
            "redis_url": (
                self.redis_url.replace("redis:/", "redis://***")
                if self.redis_url
                else None
            ),
        }

        if self._available and self._redis_client:
            try:
                # Get approximate stream length
                stream_info = self._redis_client.xinfo_stream(self.stream_name)
                stats["stream_length"] = stream_info.get("length", 0)
                stats["stream_last_generated_id"] = stream_info.get(
                    "last-generated-id", "N/A"
                )
            except Exception as e:
                stats["stream_error"] = str(e)

        return stats


# Global instance for reuse
_trace_publisher: Optional[RedisTracePublisher] = None


def get_trace_publisher() -> RedisTracePublisher:
    """Get or create global trace publisher instance."""
    global _trace_publisher
    if _trace_publisher is None:
        _trace_publisher = RedisTracePublisher()
    return _trace_publisher


# Legacy alias for backward compatibility
def get_metadata_publisher() -> RedisTracePublisher:
    """Legacy alias for get_trace_publisher - use get_trace_publisher instead."""
    return get_trace_publisher()
