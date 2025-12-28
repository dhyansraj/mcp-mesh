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
    handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))

    root_logger.addHandler(handler)

    # Root logger always INFO - all third-party libs stay quiet
    # This is the allowlist approach: instead of blocklisting noisy loggers one by one,
    # we keep root at INFO and only elevate mcp-mesh loggers
    root_logger.setLevel(logging.INFO)

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
