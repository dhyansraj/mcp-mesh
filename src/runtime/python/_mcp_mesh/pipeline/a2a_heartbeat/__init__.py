"""
A2A heartbeat pipeline for FastAPI integration (issue #903 Phase 1B).

Sibling pipeline to ``api_heartbeat`` (handles ``@mesh.route`` services)
and ``mcp_heartbeat`` (handles ``@mesh.agent`` agents).

Provides periodic service registration and health monitoring for
FastAPI applications hosting ``@mesh.a2a`` / ``mesh.a2a.mount``
surfaces. Emits ``agent_type="a2a"`` + the ``surfaces`` JSON array on
each heartbeat round-trip so the registry stamps FQDNs and surfaces
the agent on ``GET /a2a/agents``.

Uses Rust core for registry communication, dependency resolution, and
deregistration — same pattern as ``api_heartbeat``.
"""

from .a2a_lifespan_integration import (a2a_heartbeat_lifespan_task,
                                        create_a2a_lifespan_handler,
                                        integrate_a2a_heartbeat_with_fastapi)
from .rust_a2a_heartbeat import rust_a2a_heartbeat_task

__all__ = [
    "a2a_heartbeat_lifespan_task",
    "create_a2a_lifespan_handler",
    "integrate_a2a_heartbeat_with_fastapi",
    "rust_a2a_heartbeat_task",
]
