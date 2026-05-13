"""
Issue #969: @mesh.agent(description=...) must reach the Rust AgentSpec.

The Python pipeline pulls the description out of the resolved agent_config
dict and forwards it to ``core.AgentSpec(description=...)``. This test
covers that wire-up — it doesn't try to assert anything about how the Rust
core then forwards it to the registry (that's covered in Rust unit tests).
"""

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


@pytest.mark.parametrize(
    "configured_description,expected",
    [
        ("Hello from the mesh", "Hello from the mesh"),
        ("", ""),
        (None, ""),
    ],
)
def test_build_agent_spec_forwards_description(configured_description, expected):
    """`description` from agent_config must reach the AgentSpec verbatim.

    The Rust core (`core.AgentSpec`) normalises empty strings to None on the
    wire; the Python side is just responsible for passing the value through.
    None is treated the same as empty by the production code (`or ""`).
    """
    _build_agent_spec = _import_build_agent_spec()

    captured = {}

    class _FakeAgentSpec:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _FakeCore:
        AgentSpec = _FakeAgentSpec

    context = {
        "agent_config": {
            "name": "test-agent",
            "description": configured_description,
            "namespace": "default",
            "version": "1.0.0",
            "http_host": "localhost",
            "http_port": 9000,
        },
        "agent_id": "test-agent-deadbeef",
    }

    # Stub the rust core loader so we don't need the compiled extension here.
    with patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat._get_rust_core",
        return_value=_FakeCore,
    ):
        _build_agent_spec(context)

    assert captured.get("description") == expected, (
        f"Expected description={expected!r} on the AgentSpec, "
        f"got {captured.get('description')!r}"
    )
