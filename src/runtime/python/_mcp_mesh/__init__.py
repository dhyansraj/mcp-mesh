"""
MCP Mesh - Internal implementation for Model Context Protocol service mesh.

⚠️  INTERNAL PACKAGE - DO NOT IMPORT DIRECTLY
This package contains internal implementation details and is not part of the public API.
Use the 'mesh' package instead for all user-facing functionality.

The underscore prefix (_mcp_mesh) indicates this is a private package following
Python naming conventions. Direct imports from this package are not supported
and may break in future versions.

Public API: import mesh
"""

import sys

# Type alias for mesh agent proxy injections - use Any for Pydantic compatibility
from typing import Any

# Old mesh_agent decorator has been replaced by mesh.tool and mesh.agent
# Import mesh.tool and mesh.agent instead
from mesh.types import McpMeshAgent

# Import all the existing exports
from .engine.decorator_registry import (
    DecoratedFunction,
    DecoratorRegistry,
    clear_decorator_registry,
    get_all_mesh_agents,
    get_decorator_stats,
)

__version__ = "3.7.1"

# Store reference to runtime processor if initialized
_runtime_processor = None


# Values that mean "on" for MCP_MESH_ENABLED. Deliberately NOT resolved through
# ``get_config_value``: that helper soft-fails an unparseable value back to its
# default, so a typo — or ``MCP_MESH_ENABLED=""``, a routine empty-Helm-value
# outcome — would ENABLE the one flag whose entire job is to turn mesh off.
# Every other truthy knob can afford to fail open; the master off switch cannot.
# Widening the accepted spellings beyond the old ``== "true"`` is the fix here;
# making a typo mean "on" is not.
_ENABLED_TRUTHY = frozenset({"true", "1", "yes", "on"})


def _mesh_enabled() -> bool:
    """Resolve MCP_MESH_ENABLED. Unset means on; anything unrecognized means off.

    Accepts the same truthy spellings as the rest of the mesh (``true``, ``1``,
    ``yes``, ``on``, case-insensitive) but fails CLOSED: an unset variable
    enables mesh, and any other value — ``false``, ``0``, ``off``, ``""`` or a
    typo — disables it. Disabling is the safe direction: a mesh that did not
    start is obvious and local, whereas one that started against the wrong
    ``MCP_MESH_REGISTRY_URL`` registers into someone else's topology.
    """
    import os

    raw = os.environ.get("MCP_MESH_ENABLED")
    if raw is None:
        return True
    value = raw.strip().lower()
    if value in _ENABLED_TRUTHY:
        return True
    if value not in {"false", "0", "no", "off", ""}:
        sys.stderr.write(
            f"MCP_MESH_ENABLED={raw!r} is not a recognized boolean; "
            f"treating it as disabled. Use one of "
            f"{sorted(_ENABLED_TRUTHY)} to enable MCP Mesh.\n"
        )
    return False


def initialize_runtime():
    """Initialize the MCP Mesh runtime processor."""
    global _runtime_processor

    if _runtime_processor is not None:
        return  # Already initialized

    try:
        # Legacy processor system has been replaced by pipeline architecture

        # Use pipeline-based runtime
        from .pipeline.mcp_startup import start_runtime

        start_runtime()

        sys.stderr.write("MCP Mesh runtime initialized\n")
    except Exception as e:
        # Log but don't fail - allows graceful degradation
        sys.stderr.write(f"MCP Mesh runtime initialization failed: {e}\n")


# Auto-initialize runtime if mesh is enabled.
#
# Issue #1589: this gate used to also require MCP_MESH_AUTO_RUN, string-compared
# against "true", and that was wrong twice over.
#
# The comparison disagreed with the decorator and the orchestrator, which both
# accepted the wider truthy set: "1"/"yes"/"on" started the immediate uvicorn but
# skipped start_runtime(), so the debounce coordinator never got an orchestrator
# and the process served /ready with "Mesh runtime has not started yet" forever,
# never registering.
#
# Consulting auto-run here at all was the deeper error. start_runtime() only
# wires the debounce coordinator to the orchestrator — it starts no server and
# blocks nothing — but it is the prerequisite for the pipeline that REGISTERS the
# agent. Gating it on auto-run meant MCP_MESH_AUTO_RUN=false silently kept the
# agent out of the mesh entirely, rather than merely declining to start a server.
# Auto-run is decided once, later, in DebounceCoordinator._check_auto_run_enabled,
# where it gates the server and the keep-alive and nothing else.
#
# MCP_MESH_ENABLED remains the switch that turns mesh off completely.
if _mesh_enabled():
    # Use debounced initialization instead of immediate MCP startup
    # This allows the system to determine MCP vs API pipeline based on decorators
    try:
        from .pipeline.mcp_startup import start_runtime

        # Start the debounced runtime (sets up coordinator, no immediate pipeline execution)
        start_runtime()

        sys.stderr.write("MCP Mesh debounced runtime initialized\n")
    except Exception as e:
        # Log but don't fail - allows graceful degradation
        sys.stderr.write(f"MCP Mesh runtime initialization failed: {e}\n")


__all__ = [
    # mesh_agent has been removed - use mesh.tool and mesh.agent instead
    "McpMeshAgent",
    "initialize_runtime",
    "DecoratedFunction",
    "DecoratorRegistry",
    "clear_decorator_registry",
    "get_all_mesh_agents",
    "get_decorator_stats",
]
