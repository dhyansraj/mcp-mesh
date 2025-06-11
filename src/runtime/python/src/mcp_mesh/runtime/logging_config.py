"""
Centralized logging configuration for MCP Mesh runtime.

This module configures logging based on the MCP_MESH_LOG_LEVEL environment variable.
"""

import logging
import os
import sys


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

    # Configure basic logging
    logging.basicConfig(
        level=log_level,
        format="%(levelname)-8s %(message)s",
        stream=sys.stdout,
    )

    # Set level for all mcp_mesh loggers
    logging.getLogger("mcp_mesh").setLevel(log_level)

    # Return the configured level for reference
    return log_level


# Configure logging on module import
_configured_level = configure_logging()
