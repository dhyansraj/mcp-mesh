"""
Centralized logging configuration for MCP Mesh runtime.

This module configures logging based on the MCP_MESH_LOG_LEVEL environment variable.
"""

import logging
import os
import sys


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
    """Configure logging based on MCP_MESH_LOG_LEVEL environment variable."""
    # Get log level from environment, default to INFO
    log_level_str = os.environ.get("MCP_MESH_LOG_LEVEL", "INFO").upper()

    # Map string to logging level
    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,  # Alias
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    log_level = log_levels.get(log_level_str, logging.INFO)

    # Check if debug mode is enabled
    debug_mode = os.environ.get("MCP_MESH_DEBUG_MODE", "").lower() in (
        "true",
        "1",
        "yes",
    )
    if debug_mode:
        log_level = logging.DEBUG

    # Clear any existing handlers to avoid conflicts
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure with safe stream handler for background threads
    handler = SafeStreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))

    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Set level for all mcp_mesh loggers
    logging.getLogger("mcp_mesh").setLevel(log_level)

    # Return the configured level for reference
    return log_level


# Configure logging on module import
_configured_level = configure_logging()
