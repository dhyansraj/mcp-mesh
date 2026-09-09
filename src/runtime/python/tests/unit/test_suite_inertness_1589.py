"""The test suite must not arm a real pipeline or heartbeat (issue #1589).

Before the auto-run semantics changed, ``MCP_MESH_AUTO_RUN=false`` in
``conftest.py`` kept the suite inert as a side effect: it stopped
``_mcp_mesh/__init__.py`` from calling ``start_runtime()``, so the debounce
coordinator never got an orchestrator and ``_execute_processing`` bailed out.

That side effect is gone by design — ``auto_run=False`` now registers. The
inert switch is ``MCP_MESH_ENABLED``. These tests assert inertness POSITIVELY,
because a green suite proves nothing here: the pipeline runs on a
``threading.Timer``, so a contaminated run raises into ``threading.excepthook``
and pytest never sees it.
"""

import os
import threading

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.mcp_startup import get_debounce_coordinator


def test_conftest_sets_the_inert_switch():
    assert os.environ.get("MCP_MESH_ENABLED") == "false", (
        "conftest must disable mesh outright; MCP_MESH_AUTO_RUN=false no longer "
        "keeps the runtime from starting (that is the whole point of #1589)"
    )


def test_conftest_still_suppresses_the_immediate_uvicorn():
    """The @mesh.agent immediate uvicorn is gated on auto_run alone."""
    assert os.environ.get("MCP_MESH_AUTO_RUN") == "false"


def test_no_orchestrator_is_wired_in_the_test_process():
    """``start_runtime()`` is what sets this; if it ran, the suite registers."""
    assert get_debounce_coordinator()._orchestrator is None, (
        "an orchestrator is wired — the suite will run real pipelines and "
        "heartbeat to MCP_MESH_REGISTRY_URL"
    )


def test_no_heartbeat_thread_is_running():
    running = [t.name for t in threading.enumerate() if "run_heartbeat" in t.name]
    assert not running, f"live heartbeat thread(s) in the test process: {running}"


def test_decorating_an_agent_does_not_arm_a_pipeline():
    """Decorators must still register metadata — just not execute anything."""
    try:

        @mesh.tool(capability="inertness_probe")
        def _probe() -> str:  # pragma: no cover - never called
            return "ok"

        @mesh.agent(name="inertness-probe-agent")
        class _A:  # pragma: no cover - never instantiated
            pass

        # Metadata registration still works (the suite depends on it)...
        assert "inertness_probe" in {
            (d.metadata or {}).get("capability")
            for d in DecoratorRegistry.get_mesh_tools().values()
        }
        # ...but nothing was armed.
        assert get_debounce_coordinator()._orchestrator is None
        assert not [t.name for t in threading.enumerate() if "run_heartbeat" in t.name]
    finally:
        DecoratorRegistry.clear_all()
