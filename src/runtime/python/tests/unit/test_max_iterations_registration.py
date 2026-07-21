"""Issue #1356 regression: a @mesh.llm consumer with max_iterations UNSET must
still register.

The decorator now resolves ``max_iterations`` to ``None`` when nothing
configured it, so "unset" can be told apart from "explicitly 10" for wire
forwarding. The registration spec, however, has always carried a concrete
number — the Rust ``LlmAgentSpec`` types it as a non-optional ``u32``. Passing
``None`` through made every heartbeat raise::

    TypeError: argument 'max_iterations': 'NoneType' object cannot be
               interpreted as an integer

which meant the agent served HTTP but never registered (and never retried).

These tests use the REAL Rust ``LlmAgentSpec`` so the type contract is actually
exercised; only ``AgentSpec`` is stubbed, to capture what got built.
"""

from unittest.mock import patch

import pytest

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.llm_config import DEFAULT_MAX_ITERATIONS


@pytest.fixture(autouse=True)
def _clear_decorator_registry(monkeypatch):
    """Reset shared decorator state and any env-driven cap between tests."""
    monkeypatch.delenv("MESH_LLM_MAX_ITERATIONS", raising=False)
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _build_llm_agent_specs():
    """Run the real registration builder, returning the LlmAgentSpec list.

    Uses the genuine ``core.LlmAgentSpec`` (so a ``None`` cap raises exactly as
    it does in production) and a stub ``AgentSpec`` to capture the result.
    """
    from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

    real_core = rust_heartbeat._get_rust_core()
    captured = {}

    class _FakeAgentSpec:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _HybridCore:
        AgentSpec = _FakeAgentSpec
        LlmAgentSpec = real_core.LlmAgentSpec
        ToolSpec = real_core.ToolSpec
        DependencySpec = getattr(real_core, "DependencySpec", None)

    context = {
        "agent_config": {
            "name": "test-agent",
            "namespace": "default",
            "version": "1.0.0",
            "http_host": "localhost",
            "http_port": 9000,
        },
        "agent_id": "test-agent-deadbeef",
    }

    with patch.object(
        rust_heartbeat, "_get_rust_core", return_value=_HybridCore
    ):
        rust_heartbeat._build_agent_spec(context)

    return captured.get("llm_agents") or []


def test_unset_max_iterations_registers_effective_default():
    """@mesh.llm(provider=...) with no cap must register with 10, not None."""

    @mesh.llm(provider={"capability": "llm", "tags": ["+claude"]})
    def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
        return llm(message)

    # Precondition: the decorator really does leave it unset (tri-state).
    config = next(iter(DecoratorRegistry.get_mesh_llm_agents().values())).config
    assert config["max_iterations"] is None

    llm_agents = _build_llm_agent_specs()
    assert len(llm_agents) == 1
    assert llm_agents[0].max_iterations == DEFAULT_MAX_ITERATIONS == 10


def test_explicit_max_iterations_is_registered_verbatim():
    """An explicitly configured cap must reach the spec unchanged."""

    @mesh.llm(provider={"capability": "llm"}, max_iterations=3)
    def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
        return llm(message)

    llm_agents = _build_llm_agent_specs()
    assert len(llm_agents) == 1
    assert llm_agents[0].max_iterations == 3


def test_env_configured_max_iterations_is_registered(monkeypatch):
    """MESH_LLM_MAX_ITERATIONS on the consumer also reaches the spec."""
    monkeypatch.setenv("MESH_LLM_MAX_ITERATIONS", "7")

    @mesh.llm(provider={"capability": "llm"})
    def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
        return llm(message)

    llm_agents = _build_llm_agent_specs()
    assert len(llm_agents) == 1
    assert llm_agents[0].max_iterations == 7
