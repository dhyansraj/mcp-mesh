"""
Centralized logging configuration for MCP Mesh runtime.

This module configures logging based on the MCP_MESH_LOG_LEVEL environment variable.

Log Levels:
    CRITICAL (50) - Fatal errors
    ERROR    (40) - Errors
    WARNING  (30) - Warnings
    INFO     (20) - Normal operation (heartbeat counts, connections)
    DEBUG    (10) - Debugging info (tool calls, actual issues)
    TRACE    (5)  - Verbose internals (heartbeat steps, SSE parsing)
"""

import logging
import os
import sys

# Define TRACE level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self, message, *args, **kwargs):
    """Log a message with TRACE level."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


# Add trace method to Logger class
logging.Logger.trace = _trace


class SafeStreamHandler(logging.StreamHandler):
    """A stream handler that gracefully handles closed streams."""

    def emit(self, record):
        try:
            # Check if stream is usable first
            if hasattr(self.stream, "closed") and self.stream.closed:
                return

            # Try to emit the record
            super().emit(record)

        except (ValueError, OSError, AttributeError, BrokenPipeError):
            # Stream is closed or unusable, silently ignore
            # This handles "I/O operation on closed file" and similar errors
            pass
        except Exception:
            # Catch any other unexpected errors to prevent crashes
            pass


def configure_logging():
    """Configure logging based on MCP_MESH_LOG_LEVEL environment variable.

    Uses allowlist approach: root logger stays at INFO to keep third-party libs quiet,
    only mcp-mesh loggers are elevated to DEBUG when debug mode is enabled.
    """
    # Get log level from environment, default to INFO
    log_level_str = os.environ.get("MCP_MESH_LOG_LEVEL", "INFO").upper()

    # Map string to logging level
    log_levels = {
        "TRACE": TRACE,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,  # Alias
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    log_level = log_levels.get(log_level_str, logging.INFO)

    # Check if debug mode is enabled (sets DEBUG level)
    debug_mode = os.environ.get("MCP_MESH_DEBUG_MODE", "").lower() in (
        "true",
        "1",
        "yes",
    )

    # Check if trace mode is enabled via log level
    trace_mode = log_level_str == "TRACE"

    # Clear any existing handlers to avoid conflicts
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure with safe stream handler for background threads
    handler = SafeStreamHandler(sys.stdout)
    handler.setLevel(TRACE)  # Handler allows all levels including TRACE
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger.addHandler(handler)

    # Root logger always INFO - all third-party libs stay quiet
    # This is the allowlist approach: instead of blocklisting noisy loggers one by one,
    # we keep root at INFO and only elevate mcp-mesh loggers
    root_logger.setLevel(logging.INFO)

    # Suppress noisy third-party loggers (FastMCP/MCP library logs)
    # These produce verbose INFO logs like "Terminating session: None" and
    # "Processing request of type CallToolRequest" that clutter debug output
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server").setLevel(logging.WARNING)
    logging.getLogger("mcp.client").setLevel(logging.WARNING)
    logging.getLogger("fastmcp").setLevel(logging.WARNING)

    # Set MCP Mesh logger levels based on configuration
    if trace_mode:
        # TRACE mode: show everything including verbose heartbeat internals
        logging.getLogger("mesh").setLevel(TRACE)
        logging.getLogger("mcp_mesh").setLevel(TRACE)
        logging.getLogger("_mcp_mesh").setLevel(TRACE)
    elif debug_mode:
        # DEBUG mode: show debug info but not verbose trace logs
        logging.getLogger("mesh").setLevel(logging.DEBUG)
        logging.getLogger("mcp_mesh").setLevel(logging.DEBUG)
        logging.getLogger("_mcp_mesh").setLevel(logging.DEBUG)
    else:
        # Use the configured log level for mcp-mesh loggers
        logging.getLogger("mesh").setLevel(log_level)
        logging.getLogger("mcp_mesh").setLevel(log_level)
        logging.getLogger("_mcp_mesh").setLevel(log_level)

    # Return the configured level for reference
    if trace_mode:
        return TRACE
    elif debug_mode:
        return logging.DEBUG
    else:
        return log_level


# Configure logging on module import
_configured_level = configure_logging()


# ============================================================================
# Log Value Formatting Helpers
# ============================================================================


def get_trace_prefix() -> str:
    """Get trace ID prefix for log lines if tracing is active.

    Returns:
        String like "[trace=abc12345] " if trace context exists, empty string otherwise.
    """
    try:
        from ..tracing.context import TraceContext

        trace_info = TraceContext.get_current()
        if trace_info and trace_info.trace_id:
            # Use first 8 chars for readability
            short_id = trace_info.trace_id[:8]
            return f"[{short_id}] "
    except Exception:
        # Tracing not available or not configured
        pass
    return ""


def format_log_value(value, max_len: int = 0) -> str:
    """Format a value for logging.

    Provides a readable representation of values with size info.
    By default, no truncation is applied (max_len=0) to enable full
    request/response logging at DEBUG/TRACE levels.

    Args:
        value: Any value to format
        max_len: Maximum length before truncation (0 = no truncation)

    Returns:
        Formatted string representation
    """
    if value is None:
        return "None"

    type_name = type(value).__name__

    try:
        if isinstance(value, dict):
            content = str(value)
            if max_len > 0 and len(content) > max_len:
                return f"{type_name}({len(value)} keys): {content[:max_len]}..."
            return content

        elif isinstance(value, (list, tuple)):
            content = str(value)
            if max_len > 0 and len(content) > max_len:
                return f"{type_name}({len(value)} items): {content[:max_len]}..."
            return content

        elif isinstance(value, str):
            if max_len > 0 and len(value) > max_len:
                return f'"{value[:max_len]}..." ({len(value)} chars)'
            return f'"{value}"'

        elif isinstance(value, bytes):
            return f"bytes({len(value)} bytes)"

        elif hasattr(value, "__dict__"):
            # Object with attributes - show class name and key attributes
            content = str(value)
            if max_len > 0 and len(content) > max_len:
                return f"{type_name}: {content[:max_len]}..."
            return f"{type_name}: {content}"

        else:
            content = str(value)
            if max_len > 0 and len(content) > max_len:
                return f"{type_name}: {content[:max_len]}..."
            return content

    except Exception as e:
        return f"{type_name}: <error formatting: {e}>"


def format_args_summary(args: tuple, kwargs: dict) -> str:
    """Format function arguments as a summary (keys only).

    Suitable for concise DEBUG logging showing what was passed.

    Args:
        args: Positional arguments tuple
        kwargs: Keyword arguments dict

    Returns:
        Summary string like "args=(2), kwargs=['name', 'value']"
    """
    parts = []

    if args:
        parts.append(f"args=({len(args)})")

    if kwargs:
        keys = list(kwargs.keys())
        parts.append(f"kwargs={keys}")

    return ", ".join(parts) if parts else "no args"


def format_result_summary(result) -> str:
    """Format a result value as a summary (type and size).

    Suitable for concise DEBUG logging showing what was returned.

    Args:
        result: The return value

    Returns:
        Summary string like "dict(3 keys)" or "str(150 chars)"
    """
    if result is None:
        return "None"

    type_name = type(result).__name__

    try:
        if isinstance(result, dict):
            return f"dict({len(result)} keys)"
        elif isinstance(result, (list, tuple)):
            return f"{type_name}({len(result)} items)"
        elif isinstance(result, str):
            return f"str({len(result)} chars)"
        elif isinstance(result, bytes):
            return f"bytes({len(result)} bytes)"
        elif isinstance(result, (int, float, bool)):
            return str(result)
        else:
            return type_name
    except Exception:
        return type_name
