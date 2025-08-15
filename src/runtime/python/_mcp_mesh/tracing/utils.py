"""
Shared tracing utilities for MCP Mesh distributed tracing.

Provides common functions used across multiple tracing modules to reduce code duplication
and maintain consistency.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_tracing_enabled() -> bool:
    """Check if distributed tracing is enabled via environment variable.

    Returns:
        True if tracing is enabled, False otherwise
    """
    return os.getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def generate_span_id() -> str:
    """Generate a unique span ID for tracing.

    Returns:
        UUID string for span identification
    """
    return str(uuid.uuid4())


def generate_trace_id() -> str:
    """Generate a unique trace ID for tracing.

    Returns:
        UUID string for trace identification
    """
    return str(uuid.uuid4())


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

    Args:
        trace_data: Trace metadata to publish
        logger_instance: Logger for debug messages
    """
    try:
        from .redis_metadata_publisher import get_trace_publisher

        publisher = get_trace_publisher()
        if publisher.is_available:
            publisher.publish_execution_trace(trace_data)
            pass
        else:
            pass
    except Exception as e:
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
