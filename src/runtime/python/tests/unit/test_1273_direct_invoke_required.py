"""
Unit tests for issue #1273: direct ``tools/call`` dispatch must refuse when a
``required=True`` dependency slot is unresolved at invocation time.

The claim path (#1268) and the @mesh.route perimeter (#1249, 503) already
refuse before a handler can observe a null required dependency; this closes the
same DOWN→UP flap window on the plain tool-dispatch path. A required slot that
is unresolved at call time raises a ``dependency_unavailable`` tool error (an
``isError`` result whose text carries ``{"error":"dependency_unavailable",
"capability":"<cap>"}`` — the SAME semantic class as the route perimeter's 503)
rather than invoking the handler with a null required proxy. Optional deps keep
their documented None-passthrough.

Mirrors the route-perimeter tests in ``test_1249_required_dependency.py`` but
drives ``tool_required_caps`` (the @mesh.tool analogue of ``route_required_caps``)
and asserts the raised ``ToolError`` rather than a 503 ``JSONResponse``.
"""

import asyncio
import json
import os
from unittest.mock import patch

import mesh
import pytest
from _mcp_mesh.engine import settle
from _mcp_mesh.engine.dependency_injector import DependencyInjector
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from fastmcp.exceptions import ToolError


def _clear():
    DecoratorRegistry.clear_all()
    from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

    clear_debounce_coordinator()


def _make_tool_wrapper(func, deps, required_caps):
    injector = DependencyInjector()
    with patch(
        "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
        return_value=[0],
    ):
        return injector.create_injection_wrapper(
            func, deps, tool_required_caps=required_caps
        )


class TestToolDirectInvokeRefusal:
    def setup_method(self):
        _clear()
        # Force a SETTLED state (no grace window) so the unavailable-cases refuse
        # immediately regardless of env / prior-test order — the guard is
        # evaluated after settle, so a leftover armed window would otherwise make
        # these block instead of refuse (mirrors TestToolGuardVsSettle).
        os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"
        settle._reset_settle_state_for_tests()

    def teardown_method(self):
        os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
        settle._reset_settle_state_for_tests()

    def test_required_unavailable_raises_refusal_handler_not_invoked(self):
        called = []

        async def tool(lookup=None):
            called.append(True)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        # Proxy unavailable (never resolved) — default injected_deps is [None].
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(wrapper())

        body = json.loads(str(excinfo.value))
        assert body == {
            "error": "dependency_unavailable",
            "capability": "lookup",
        }
        assert called == []  # handler must NOT run

    def test_required_available_runs_handler(self):
        called = []

        async def tool(lookup=None):
            called.append(lookup)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        proxy = object()
        wrapper._mesh_update_dependency(0, proxy)

        result = asyncio.run(wrapper())
        assert result == {"ok": True}
        assert called == [proxy]  # handler ran with the live proxy

    def test_optional_unavailable_runs_handler_with_none(self):
        called = []

        async def tool(lookup=None):
            called.append(lookup)
            return {"ok": True}

        # No required caps → soft-fail preserved (None passthrough).
        wrapper = _make_tool_wrapper(tool, ["lookup"], None)

        result = asyncio.run(wrapper())
        assert result == {"ok": True}
        assert called == [None]  # ran with None injected, no refusal

    def test_sync_tool_required_unavailable_raises_refusal(self):
        called = []

        def tool(lookup=None):
            called.append(True)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        with pytest.raises(ToolError) as excinfo:
            wrapper()

        assert json.loads(str(excinfo.value))["capability"] == "lookup"
        assert called == []

    def test_sync_tool_required_available_runs_handler(self):
        called = []

        def tool(lookup=None):
            called.append(lookup)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        proxy = object()
        wrapper._mesh_update_dependency(0, proxy)

        result = wrapper()
        assert result == {"ok": True}
        assert called == [proxy]

    def test_caller_supplied_mock_satisfies_required_dep(self):
        """Mock contract: an explicit fake for a required dep runs the handler.

        Mirrors the route-perimeter mock skip — passing the parameter directly
        must NOT trip the refusal even while the mesh proxy is unresolved.
        """
        called = []

        async def tool(lookup=None):
            called.append(lookup)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        fake = object()
        result = asyncio.run(wrapper(lookup=fake))
        assert result == {"ok": True}
        assert called == [fake]


class TestToolRequiredCapsWiring:
    """The @mesh.tool decorator threads ``tool_required_caps`` into the
    injector (index-aligned capability-or-None), so the guard is armed for
    required tool deps and a no-op otherwise."""

    def setup_method(self):
        _clear()

    def test_decorator_passes_tool_required_caps(self):
        seen = {}

        real = DependencyInjector.create_injection_wrapper

        def spy(self, func, dependencies, route_required_caps=None, tool_required_caps=None):
            seen["tool_required_caps"] = tool_required_caps
            return real(
                self,
                func,
                dependencies,
                route_required_caps=route_required_caps,
                tool_required_caps=tool_required_caps,
            )

        with patch.object(DependencyInjector, "create_injection_wrapper", spy):

            @mesh.tool(
                capability="enrich",
                dependencies=[
                    {"capability": "lookup", "required": True},
                    "audit",
                ],
            )
            def enrich(lookup: mesh.McpMeshTool = None, audit: mesh.McpMeshTool = None):
                return "ok"

        assert seen["tool_required_caps"] == ["lookup", None]

    def test_decorator_omits_caps_when_no_required(self):
        seen = {}

        real = DependencyInjector.create_injection_wrapper

        def spy(self, func, dependencies, route_required_caps=None, tool_required_caps=None):
            seen["tool_required_caps"] = tool_required_caps
            return real(
                self,
                func,
                dependencies,
                route_required_caps=route_required_caps,
                tool_required_caps=tool_required_caps,
            )

        with patch.object(DependencyInjector, "create_injection_wrapper", spy):

            @mesh.tool(capability="enrich", dependencies=["lookup"])
            def enrich(lookup: mesh.McpMeshTool = None):
                return "ok"

        # No required slot → None (guard stays a no-op).
        assert seen["tool_required_caps"] is None


class TestToolGuardVsSettle:
    """Issue #1273 review: the refusal is evaluated AFTER the settle wait, so a
    required dep that lands within the settle window runs the handler (a fresh
    restart must block-then-succeed, not burst-refuse); only a dep still down
    once settled is refused."""

    def setup_method(self):
        _clear()
        os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
        settle._reset_settle_state_for_tests()

    def teardown_method(self):
        os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
        settle._reset_settle_state_for_tests()

    def test_required_dep_lands_mid_settle_invokes_no_refusal(self):
        os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "10"
        settle._reset_settle_state_for_tests()

        called = []

        async def tool(lookup=None):
            called.append(lookup)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        proxy = object()

        async def run():
            async def resolve_later():
                await asyncio.sleep(0.2)
                wrapper._mesh_update_dependency(0, proxy)

            resolver = asyncio.create_task(resolve_later())
            result = await wrapper()
            await resolver
            return result

        result = asyncio.run(run())
        assert result == {"ok": True}
        assert called == [proxy]  # waited out settle, ran with the proxy

    def test_required_dep_down_after_settle_refuses(self):
        os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"  # disabled → settled
        settle._reset_settle_state_for_tests()

        called = []

        async def tool(lookup=None):
            called.append(True)
            return {"ok": True}

        wrapper = _make_tool_wrapper(tool, ["lookup"], ["lookup"])
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(wrapper())

        assert json.loads(str(excinfo.value))["capability"] == "lookup"
        assert called == []


class TestToolMinimalPathRequiredWarns:
    """Issue #1273: a required dep declared on a tool with NO injectable
    McpMeshTool slot takes the minimal path — the refusal has no slot to
    evaluate (the handler can never observe the dep), so enforcement stays OFF
    and a one-line INACTIVE warning is emitted (mirrors the route perimeter's
    INACTIVE handling at #1249). The handler still runs."""

    def setup_method(self):
        _clear()
        os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"
        settle._reset_settle_state_for_tests()

    def teardown_method(self):
        os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
        settle._reset_settle_state_for_tests()

    def test_required_dep_no_slot_warns_and_runs(self, caplog):
        called = []

        async def tool():  # zero injectable params → minimal path
            called.append(True)
            return {"ok": True}

        injector = DependencyInjector()
        with caplog.at_level("WARNING"):
            # Real analyze_injection_strategy → mesh_positions == [] for a
            # zero-param function → minimal wrapper.
            wrapper = injector.create_injection_wrapper(
                tool, ["lookup"], tool_required_caps=["lookup"]
            )

        assert any(
            "required-dependency guard" in rec.message and "INACTIVE" in rec.message
            for rec in caplog.records
        ), "a slotless required dep must emit the INACTIVE guard warning"

        # Enforcement is OFF (no slot to evaluate) — the handler still runs.
        result = asyncio.run(wrapper())
        assert result == {"ok": True}
        assert called == [True]
