"""
Heartbeat pipeline infrastructure for MCP Mesh processing.

This module contains the Rust-backed heartbeat implementation for registry
communication and dependency resolution. The Rust core handles all registry
communication including heartbeats, dependency resolution, and deregistration.
"""

from .rust_heartbeat import rust_heartbeat_task

__all__ = [
    "rust_heartbeat_task",
]
