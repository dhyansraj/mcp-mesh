"""
API heartbeat pipeline for FastAPI integration.

Provides periodic service registration and health monitoring
for FastAPI applications using @mesh.route decorators.

Uses Rust core for registry communication, dependency resolution,
and deregistration.
"""

from .api_lifespan_integration import (api_heartbeat_lifespan_task,
                                       create_api_lifespan_handler,
                                       integrate_api_heartbeat_with_fastapi)
from .rust_api_heartbeat import rust_api_heartbeat_task

__all__ = [
    "api_heartbeat_lifespan_task",
    "create_api_lifespan_handler",
    "integrate_api_heartbeat_with_fastapi",
    "rust_api_heartbeat_task",
]
