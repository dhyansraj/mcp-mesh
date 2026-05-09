"""Shared collector for ``@mesh.a2a`` surface metadata (issue #903 Phase 1B refactor).

The same registry-bound surfaces shape is consumed by THREE heartbeat paths:

  * ``mcp_startup/heartbeat_preparation.py`` — legacy Python heartbeat
    payload builder (sends dict directly).
  * ``mcp_heartbeat/rust_heartbeat.py`` — Rust-backed heartbeat (sends
    JSON string via ``AgentSpec.surfaces``).
  * ``api_heartbeat/rust_api_heartbeat.py`` — Rust-backed heartbeat for
    pure ``@mesh.route`` / ``mesh.a2a.mount`` (no ``@mesh.agent``) FastAPI
    apps. Same JSON shape as the mcp_heartbeat path.

The shape MUST stay in sync across all three or the registry's
``MeshAgentRegistration.surfaces`` JSONB column will land mixed shapes
across agent types — making the GET ``/a2a/agents`` listing fragile.
Centralizing the construction here makes any future field additions a
single-point edit.

The output is the shape persisted on the registry's ``a2a_surfaces`` JSON
field (see Go ``MeshAgentRegistration.surfaces`` and the OpenAPI
``A2ASurface`` schema).
"""

from __future__ import annotations

from typing import Any

# Module-level import (rather than late) so unit tests can patch
# ``_mcp_mesh.engine.a2a_surfaces.DecoratorRegistry`` directly. The
# circular-import worry doesn't apply here in practice — by the time
# any heartbeat path imports this module, ``decorator_registry`` is
# fully initialised (see test sweep on the fix #5 commit).
from .decorator_registry import DecoratorRegistry


def collect_a2a_surfaces() -> list[dict[str, Any]]:
    """Return the registry-bound surfaces array for all ``@mesh.a2a`` decorators.

    Reads ``DecoratorRegistry.get_all_by_type("mesh_a2a")`` and projects each
    entry to the registry shape. Returns ``[]`` when no surfaces are
    declared — callers decide whether to omit the field on the wire.

    Optional fields (``name``, ``description``, ``input_modes``,
    ``output_modes``, ``tags``) are only populated when set on the decorator
    so the registry's OpenAPI defaults aren't overridden with empty values.
    """
    a2a_funcs = DecoratorRegistry.get_all_by_type("mesh_a2a")
    if not a2a_funcs:
        return []

    surfaces: list[dict[str, Any]] = []
    for _, decorated in a2a_funcs.items():
        md = decorated.metadata or {}
        entry: dict[str, Any] = {
            "path": md["path"],
            "skill_id": md["skill_id"],
        }
        if md.get("skill_name"):
            entry["name"] = md["skill_name"]
        if md.get("description"):
            entry["description"] = md["description"]
        if md.get("input_modes"):
            entry["input_modes"] = list(md["input_modes"])
        if md.get("output_modes"):
            entry["output_modes"] = list(md["output_modes"])
        if md.get("tags"):
            entry["tags"] = list(md["tags"])
        surfaces.append(entry)
    return surfaces
