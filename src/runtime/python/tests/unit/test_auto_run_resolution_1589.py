"""Issue #1589: one MCP_MESH_AUTO_RUN parser, and honour ``auto_run=False``.

Three call sites parsed the env var three different ways:

* ``_mcp_mesh/__init__.py`` gated ``start_runtime()`` on ``== "true"``
  (and gated it on auto-run at all, which kept a ``false`` agent out of the
  mesh entirely rather than merely declining to start a server)
* ``mesh/decorators.py`` used the truthy rule (``1``/``yes``/``on`` count)
* ``startup_orchestrator`` used a falsy denylist (``false``/``0``/``no``)

so ``MCP_MESH_AUTO_RUN=1`` started the immediate uvicorn and enabled the
blocking-server branch, but never handed the debounce coordinator an
orchestrator — the process served ``/ready`` with "Mesh runtime has not
started yet" forever and never registered. ``off`` diverged the other way.
The orchestrator also never consulted ``@mesh.agent(auto_run=False)``.
"""

from datetime import datetime

import pytest

import _mcp_mesh
from _mcp_mesh.engine.decorator_registry import DecoratedFunction, DecoratorRegistry
from _mcp_mesh.pipeline.mcp_startup.startup_orchestrator import DebounceCoordinator
from _mcp_mesh.shared.config_resolver import resolve_auto_run

TRUTHY = ["true", "TRUE", "True", "1", "yes", "on"]
FALSY = ["false", "FALSE", "0", "no", "off"]


@pytest.fixture(autouse=True)
def _clean_registry():
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _register_agent(auto_run):
    def _agent():  # pragma: no cover - never called
        return None

    DecoratorRegistry._mesh_agents["_agent"] = DecoratedFunction(
        decorator_type="mesh_agent",
        function=_agent,
        metadata={"name": "a", "auto_run": auto_run},
        registered_at=datetime.now(),
    )


def _orchestrator_verdict():
    return DebounceCoordinator(delay_seconds=0.01)._check_auto_run_enabled()


@pytest.mark.parametrize("value", TRUTHY)
def test_all_sites_agree_on_truthy_values(monkeypatch, value):
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
    assert resolve_auto_run() is True
    assert _orchestrator_verdict() is True


@pytest.mark.parametrize("value", FALSY)
def test_all_sites_agree_on_falsy_values(monkeypatch, value):
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
    assert resolve_auto_run() is False
    assert _orchestrator_verdict() is False


def test_unset_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("MCP_MESH_AUTO_RUN", raising=False)
    assert resolve_auto_run() is True
    assert _orchestrator_verdict() is True


def test_unparseable_value_soft_fails_to_the_default(monkeypatch):
    """Garbage falls back to the default rather than half-enabling the agent."""
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", "bogus")
    assert resolve_auto_run() is True
    assert _orchestrator_verdict() is True


@pytest.mark.parametrize("value", FALSY + TRUTHY + ["bogus"])
def test_runtime_bootstrap_never_consults_auto_run(monkeypatch, value):
    """start_runtime() is the prerequisite for REGISTERING, so auto-run — which
    only decides who owns the server — must not gate it. MCP_MESH_ENABLED is
    the switch that turns mesh off."""
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
    # conftest sets MCP_MESH_ENABLED=false to keep the suite inert; drop it so
    # this asserts the gate's dependence on auto-run and nothing else.
    monkeypatch.delenv("MCP_MESH_ENABLED", raising=False)
    assert _mcp_mesh._mesh_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_mesh_enabled_is_the_only_off_switch(monkeypatch, value):
    monkeypatch.setenv("MCP_MESH_ENABLED", value)
    assert _mcp_mesh._mesh_enabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_mesh_enabled_accepts_truthy_variants(monkeypatch, value):
    """MCP_MESH_ENABLED had the identical ``== "true"`` bug on the same line."""
    monkeypatch.setenv("MCP_MESH_ENABLED", value)
    assert _mcp_mesh._mesh_enabled() is True


def test_orchestrator_honours_decorator_auto_run_false(monkeypatch):
    """@mesh.agent(auto_run=False) must not get a blocking uvicorn."""
    monkeypatch.delenv("MCP_MESH_AUTO_RUN", raising=False)
    _register_agent(False)
    assert _orchestrator_verdict() is False


def test_orchestrator_honours_decorator_auto_run_true(monkeypatch):
    monkeypatch.delenv("MCP_MESH_AUTO_RUN", raising=False)
    _register_agent(True)
    assert _orchestrator_verdict() is True


@pytest.mark.parametrize("value", TRUTHY)
def test_env_overrides_decorator_false(monkeypatch, value):
    """Documented hierarchy: ENV > decorator argument > default."""
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
    _register_agent(False)
    assert _orchestrator_verdict() is True


@pytest.mark.parametrize("value", FALSY)
def test_env_overrides_decorator_true(monkeypatch, value):
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
    _register_agent(True)
    assert _orchestrator_verdict() is False


def test_orchestrator_without_mesh_agent_uses_env(monkeypatch):
    """API/A2A processes have no @mesh.agent; they fall through to the env."""
    monkeypatch.setenv("MCP_MESH_AUTO_RUN", "off")
    assert _orchestrator_verdict() is False


def test_check_auto_run_does_not_prime_the_agent_config_cache(monkeypatch):
    """Resolving auto-run must not synthesize (and cache) an agent identity.

    ``get_resolved_agent_config()`` caches a synthetic config with a generated
    agent_id when no @mesh.agent exists. Priming that cache from the auto-run
    check — which runs before the API/A2A pipelines write their own service
    identity — would change the registered service_id.
    """
    monkeypatch.delenv("MCP_MESH_AUTO_RUN", raising=False)
    assert DecoratorRegistry._cached_agent_config is None
    _orchestrator_verdict()
    assert DecoratorRegistry._cached_agent_config is None
