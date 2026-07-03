"""
Unit tests for issue #1249: opt-in ``required`` dependency edges.

Covers the Python SDK half of the converged design:

* Declaration — ``dependencies=[{"capability": "x", "required": True}]`` parses
  on both @mesh.tool and @mesh.route; string-form deps default ``required=False``;
  the flag is validated as a bool.
* Serialization — the built registration payload
  (``HeartbeatPreparationStep._process_dependencies``) carries ``required``.
* Route perimeter 503 — a @mesh.route whose required dep's proxy is unavailable
  at call time returns HTTP 503 (naming the capability) BEFORE user code runs;
  an available dep runs the handler; an OPTIONAL unavailable dep still runs the
  handler (None injected, soft-fail preserved); a streaming route is unaffected.
* Count-mismatch validation ride-along — the pre-existing positional-contract
  count warning still fires.
"""

import asyncio
import json
from unittest.mock import patch

import mesh
import pytest
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.dependency_injector import (
    DependencyInjector,
    analyze_injection_strategy,
)
from _mcp_mesh.pipeline.mcp_startup.heartbeat_preparation import (
    HeartbeatPreparationStep,
)


def _clear():
    DecoratorRegistry.clear_all()
    from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

    clear_debounce_coordinator()


# --------------------------------------------------------------------------- #
# Declaration
# --------------------------------------------------------------------------- #
class TestRequiredDeclaration:
    def setup_method(self):
        _clear()

    def test_tool_dict_with_required_true_parses(self):
        @mesh.tool(
            capability="analyst",
            dependencies=[{"capability": "weather-api", "required": True}],
        )
        def analyst(weather: mesh.McpMeshTool = None):
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["analyst"].metadata
        (dep,) = meta["dependencies"]
        assert dep["capability"] == "weather-api"
        assert dep["required"] is True

    def test_tool_string_form_defaults_false(self):
        @mesh.tool(capability="analyst", dependencies=["weather-api"])
        def analyst(weather: mesh.McpMeshTool = None):
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["analyst"].metadata
        (dep,) = meta["dependencies"]
        # Absent → false (optional-field style: key omitted).
        assert dep.get("required", False) is False

    def test_tool_dict_required_false_omitted(self):
        @mesh.tool(
            capability="analyst",
            dependencies=[{"capability": "weather-api", "required": False}],
        )
        def analyst(weather: mesh.McpMeshTool = None):
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["analyst"].metadata
        (dep,) = meta["dependencies"]
        assert dep.get("required", False) is False

    def test_tool_required_non_bool_rejected(self):
        with pytest.raises(ValueError, match="required must be a boolean"):

            @mesh.tool(
                capability="analyst",
                dependencies=[{"capability": "weather-api", "required": "yes"}],
            )
            def analyst(weather: mesh.McpMeshTool = None):
                return "ok"

    def test_route_dict_with_required_true_parses(self):
        @mesh.route(dependencies=[{"capability": "weather-api", "required": True}])
        async def handler(weather: mesh.McpMeshTool = None):
            return "ok"

        (dep,) = handler._mesh_route_metadata["dependencies"]
        assert dep["capability"] == "weather-api"
        assert dep["required"] is True

    def test_route_string_form_defaults_false(self):
        @mesh.route(dependencies=["weather-api"])
        async def handler(weather: mesh.McpMeshTool = None):
            return "ok"

        (dep,) = handler._mesh_route_metadata["dependencies"]
        assert dep.get("required", False) is False

    def test_route_required_non_bool_rejected(self):
        with pytest.raises(ValueError, match="required must be a boolean"):

            @mesh.route(
                dependencies=[{"capability": "weather-api", "required": 1}]
            )
            async def handler(weather: mesh.McpMeshTool = None):
                return "ok"


# --------------------------------------------------------------------------- #
# Serialization into the built registration payload
# --------------------------------------------------------------------------- #
class TestRequiredSerialization:
    def test_required_true_serialized(self):
        step = HeartbeatPreparationStep()
        out = step._process_dependencies(
            [{"capability": "weather-api", "required": True}]
        )
        assert out == [
            {
                "capability": "weather-api",
                "tags": [],
                "version": "",
                "namespace": "default",
                "required": True,
            }
        ]

    def test_dict_without_required_serialized_false(self):
        step = HeartbeatPreparationStep()
        out = step._process_dependencies([{"capability": "weather-api"}])
        assert out[0]["required"] is False

    def test_string_form_serialized_false(self):
        step = HeartbeatPreparationStep()
        out = step._process_dependencies(["weather-api"])
        assert out[0]["capability"] == "weather-api"
        assert out[0]["required"] is False


# --------------------------------------------------------------------------- #
# Wire serialization through the Rust core (primary heartbeat path)
# --------------------------------------------------------------------------- #
class TestCoreDependencySpecRequired:
    """The core.DependencySpec (built by rust_heartbeat.py) carries required.

    Serde wire-shape ("required": true present, omitted when false, round-trip)
    is proven by the Rust unit test ``test_dependency_required_serialization``;
    here we assert the Python→core boundary transmits the flag the same way
    rust_heartbeat.py constructs the spec.
    """

    def _core(self):
        core = pytest.importorskip("mcp_mesh_core")
        if "required" not in dir(core.DependencySpec):
            pytest.skip("core.DependencySpec predates issue #1249 (rebuild core)")
        return core

    def _build_like_heartbeat(self, core, dep_info):
        # Mirror the exact kwargs rust_heartbeat.py passes.
        import json

        return core.DependencySpec(
            capability=dep_info.get("capability", ""),
            tags=json.dumps(dep_info.get("tags", [])),
            version=dep_info.get("version"),
            expected_schema_canonical=None,
            expected_schema_hash=None,
            match_mode=dep_info.get("match_mode"),
            required=bool(dep_info.get("required", False)),
        )

    def test_required_true_reaches_core(self):
        core = self._core()
        spec = self._build_like_heartbeat(
            core, {"capability": "weather-api", "required": True}
        )
        assert spec.required is True

    def test_required_absent_defaults_false(self):
        core = self._core()
        spec = self._build_like_heartbeat(core, {"capability": "weather-api"})
        assert spec.required is False


# --------------------------------------------------------------------------- #
# Route perimeter 503
# --------------------------------------------------------------------------- #
class TestRoutePerimeter503:
    def _make_route_wrapper(self, func, deps, required_caps):
        injector = DependencyInjector()
        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            return injector.create_injection_wrapper(
                func, deps, route_required_caps=required_caps
            )

    def test_required_unavailable_returns_503_handler_not_invoked(self):
        called = []

        async def handler(weather=None):
            called.append(True)
            return {"ok": True}

        wrapper = self._make_route_wrapper(
            handler, ["weather-api"], ["weather-api"]
        )
        # Proxy unavailable (never resolved) — default injected_deps is [None].
        result = asyncio.run(wrapper())

        assert result.status_code == 503
        body = json.loads(result.body)
        assert body == {
            "error": "dependency_unavailable",
            "capability": "weather-api",
        }
        assert called == []  # handler must NOT run

    def test_required_available_runs_handler(self):
        called = []

        async def handler(weather=None):
            called.append(weather)
            return {"ok": True}

        wrapper = self._make_route_wrapper(
            handler, ["weather-api"], ["weather-api"]
        )
        proxy = object()
        wrapper._mesh_update_dependency(0, proxy)

        result = asyncio.run(wrapper())
        assert result == {"ok": True}
        assert called == [proxy]  # handler ran with the live proxy

    def test_optional_unavailable_runs_handler_with_none(self):
        called = []

        async def handler(weather=None):
            called.append(weather)
            return {"ok": True}

        # No required caps (all None) → soft-fail preserved.
        wrapper = self._make_route_wrapper(handler, ["weather-api"], [None])

        result = asyncio.run(wrapper())
        assert result == {"ok": True}
        assert called == [None]  # ran with None injected, no 503

    def test_sync_route_required_unavailable_returns_503(self):
        called = []

        def handler(weather=None):
            called.append(True)
            return {"ok": True}

        wrapper = self._make_route_wrapper(
            handler, ["weather-api"], ["weather-api"]
        )
        result = wrapper()

        assert result.status_code == 503
        assert json.loads(result.body)["capability"] == "weather-api"
        assert called == []

    def test_caller_supplied_mock_satisfies_required_dep(self):
        """Mock contract: an explicit fake for a required dep runs the handler.

        Even with the mesh proxy unresolved, passing the parameter directly
        (test/mock contract, mirrors _prepare_injection_kwargs' caller skip)
        must NOT trip the 503 — the handler runs with the caller's value.
        """
        called = []

        async def handler(weather=None):
            called.append(weather)
            return {"ok": True}

        wrapper = self._make_route_wrapper(
            handler, ["weather-api"], ["weather-api"]
        )
        # Proxy deliberately unresolved (_mesh_injected_deps == [None]); caller
        # supplies a fake for the 'weather' parameter.
        fake = object()
        result = asyncio.run(wrapper(weather=fake))

        assert result == {"ok": True}
        assert called == [fake]  # ran with the caller's mock, no 503

    def test_required_perimeter_inactive_warns_when_no_injectable_slot(self, caplog):
        """A required route with no injectable slot warns loudly (perimeter off)."""

        async def handler():  # no McpMeshTool param to receive the proxy
            return {"ok": True}

        injector = DependencyInjector()
        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[],
        ):
            with caplog.at_level("WARNING"):
                injector.create_injection_wrapper(
                    handler,
                    ["weather-api"],
                    route_required_caps=["weather-api"],
                )

        assert "required perimeter INACTIVE" in caplog.text
        assert "weather-api" in caplog.text

    def _make_stream_wrapper(self, stream_handler, caplog=None):
        injector = DependencyInjector()
        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            return injector.create_injection_wrapper(
                stream_handler,
                ["weather-api"],
                route_required_caps=["weather-api"],
            )

    def test_streaming_required_route_warns_perimeter_not_enforced(self, caplog):
        """A streaming route with required deps warns that 503 is not enforced."""

        async def stream_handler(weather=None):
            yield "chunk-a"

        with caplog.at_level("WARNING"):
            self._make_stream_wrapper(stream_handler)

        assert "required perimeter NOT enforced" in caplog.text
        assert "streaming" in caplog.text
        assert "weather-api" in caplog.text

    def test_streaming_route_satisfied_dep_streams(self):
        """Streaming route with the required dep AVAILABLE streams normally."""

        async def stream_handler(weather=None):
            yield "chunk-a"
            yield "chunk-b"

        wrapper = self._make_stream_wrapper(stream_handler)
        wrapper._mesh_update_dependency(0, object())  # dep satisfied
        result = asyncio.run(wrapper())
        assert result == "chunk-achunk-b"

    def test_streaming_route_unavailable_dep_still_streams(self):
        """The perimeter is bypassed BY DESIGN on the stream path.

        With the required dep UNAVAILABLE (never resolved), the stream path
        keeps its soft-fail behaviour and still streams (injecting None) rather
        than returning a 503 — proving the perimeter check is transparent to
        streaming.
        """

        async def stream_handler(weather=None):
            yield "chunk-a"
            yield "chunk-b"

        wrapper = self._make_stream_wrapper(stream_handler)
        # Dep deliberately left unresolved (_mesh_injected_deps == [None]).
        result = asyncio.run(wrapper())
        assert result == "chunk-achunk-b"  # streamed, no 503


# --------------------------------------------------------------------------- #
# Count-mismatch validation ride-along (pre-existing warning still fires)
# --------------------------------------------------------------------------- #
class TestCountMismatchWarning:
    def test_excess_dependencies_warns(self, caplog):
        """More declared deps than injectable slots → loud warning.

        This is the pre-existing positional-contract count check in
        ``analyze_injection_strategy``; #1249 relies on it rather than
        introducing a parallel one (position remains the contract).
        """

        def handler(a, b):
            return (a, b)

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[0],
        ):
            with caplog.at_level("WARNING"):
                analyze_injection_strategy(handler, ["x", "y", "z"])

        assert "will not be injected" in caplog.text
        assert "['y', 'z']" in caplog.text
