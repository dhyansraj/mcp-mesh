"""
Issue #972: @mesh.a2a / @mesh.a2a_consumer detection must flow to AgentSpec
as `a2a_producer` / `a2a_consumer` booleans.

The Python pipeline computes these in `_build_agent_spec`:
- ``a2a_producer = bool(a2a_surfaces)`` — any @mesh.a2a or mount() flips it.
- ``a2a_consumer`` — set when at least one mesh tool carries the
  ``_mesh_a2a_consumer_metadata`` marker stamped by @mesh.a2a_consumer's
  bridge wrapper.

This test covers the wire-up — it doesn't try to assert anything about how
the Rust core forwards the values to the registry (that lives in Rust unit
tests + Go integration tests).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratorRegistry


@pytest.fixture(autouse=True)
def _clear_decorator_registry():
    """Reset shared decorator state between tests."""
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _import_build_agent_spec():
    """Local import so pytest collection doesn't trip on rust_core import side effects."""
    from _mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat import _build_agent_spec

    return _build_agent_spec


def _make_consumer_tool():
    """Return a fake mesh-tool wrapper that mimics @mesh.a2a_consumer's bridge."""
    def _fn():
        return None

    # Marker is the only thing _build_agent_spec checks for.
    _fn._mesh_a2a_consumer_metadata = {
        "capability": "weather",
        "a2a_url": "http://example.com/a2a",
        "a2a_skill_id": "weather",
        "tags": [],
        "auth": None,
        "consumer_name": "downstream",
    }
    return SimpleNamespace(function=_fn, metadata={"capability": "weather"})


def _make_plain_tool():
    """Return a fake mesh-tool wrapper with no consumer marker."""
    def _fn():
        return None

    return SimpleNamespace(function=_fn, metadata={"capability": "noop"})


@pytest.mark.parametrize(
    "has_consumer,has_producer,expected_producer,expected_consumer",
    [
        (False, False, False, False),  # plain MCP agent — neither
        (False, True, True, False),    # producer-only (@mesh.a2a / mount)
        (True, False, False, True),    # consumer-only (@mesh.a2a_consumer)
        (True, True, True, True),      # bridge — both
    ],
)
def test_build_agent_spec_emits_a2a_flags(
    has_consumer, has_producer, expected_producer, expected_consumer
):
    """`_build_agent_spec` must stamp the right pair of flags on the spec.

    Each case independently exercises:
    - producer detection via `_build_a2a_surfaces_for_rust`
    - consumer detection via the `_mesh_a2a_consumer_metadata` marker walk
    """
    _build_agent_spec = _import_build_agent_spec()

    captured = {}

    class _FakeAgentSpec:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _FakeToolSpec:
        def __init__(self, **kwargs):
            pass

    class _FakeCore:
        AgentSpec = _FakeAgentSpec
        ToolSpec = _FakeToolSpec

    fake_tools = {}
    if has_consumer:
        fake_tools["weather_proxy"] = _make_consumer_tool()
    fake_tools["noop"] = _make_plain_tool()

    fake_surfaces = (
        [{"path": "/a2a/x", "skill_id": "x", "description": ""}] if has_producer else []
    )

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

    with (
        patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat._get_rust_core",
            return_value=_FakeCore,
        ),
        patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat._build_a2a_surfaces_for_rust",
            return_value=fake_surfaces,
        ),
        patch.object(
            DecoratorRegistry, "get_mesh_tools", return_value=fake_tools
        ),
        patch.object(
            DecoratorRegistry, "get_mesh_llm_agents", return_value={}
        ),
    ):
        _build_agent_spec(context)

    assert captured.get("a2a_producer") is expected_producer, (
        f"Expected a2a_producer={expected_producer}, got "
        f"{captured.get('a2a_producer')!r}"
    )
    assert captured.get("a2a_consumer") is expected_consumer, (
        f"Expected a2a_consumer={expected_consumer}, got "
        f"{captured.get('a2a_consumer')!r}"
    )
