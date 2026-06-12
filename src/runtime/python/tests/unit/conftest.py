"""
Unit-suite settle-window opt-out (issue #1193 fix round).

The settling-window grace makes calls on declared-but-unresolved
dependencies wait up to MCP_MESH_SETTLE_TIMEOUT (default 20s). Dozens of
unit tests in this directory deliberately invoke DI wrappers with
unresolved dependencies to assert the degraded (None-injection) behavior —
without an opt-out each such call would sit out the window (e.g.
``test_wrapper_execution_missing_dependency`` went from milliseconds to
~20s and the whole suite from ~17s to ~59s).

This mirrors the TypeScript treatment in ``route.test.ts``: disable the
grace for the suite via the documented ``MCP_MESH_SETTLE_TIMEOUT=0`` tuning
case and reset the process-wide state so nothing cached survives.

``test_settle_window.py`` is the exception — it tests the grace itself and
manages its own state (per-test env override + state reset via its autouse
``fresh_settle_state`` fixture), so the session-level ``0`` here is simply
its baseline to override.
"""

import os

import pytest

from _mcp_mesh.engine import settle


@pytest.fixture(scope="session", autouse=True)
def _disable_settle_window_for_unit_suite():
    """Disable the settling-window grace for the whole unit session."""
    saved = os.environ.get("MCP_MESH_SETTLE_TIMEOUT")
    os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"
    # Drop any state created during collection-time imports (decoration-time
    # register_declared calls land on the import-time instance) and the
    # cached timeout, so the "0" above is actually read.
    settle._reset_settle_state_for_tests()
    yield
    if saved is None:
        os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
    else:
        os.environ["MCP_MESH_SETTLE_TIMEOUT"] = saved
    settle._reset_settle_state_for_tests()
