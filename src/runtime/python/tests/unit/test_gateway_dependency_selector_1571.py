"""Issue #1571: route and A2A dependency edges must carry the full selector.

The @mesh.tool heartbeat path serializes ``tags``, ``version``, the expected
schema pair, ``match_mode`` and ``required`` onto every ``DependencySpec``.
The @mesh.route and @mesh.a2a paths used to flatten their edges — routes to a
bare capability name with ``tags="[]"``/``version=None``, A2A to
capability+tags+version — so a tag-routed or required gateway edge never
reached the registry.
"""

import json

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.pipeline.a2a_heartbeat import rust_a2a_heartbeat
from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat


@pytest.fixture(autouse=True)
def _clean_registry():
    # ``clear_all()`` does not touch ``_route_wrapper_registry`` (pre-existing
    # gap, unrelated to #1571), so wrappers registered by earlier tests leak
    # into the AgentSpec built here. Clear it explicitly at both ends.
    def _reset():
        DecoratorRegistry.clear_all()
        DecoratorRegistry._route_wrapper_registry.clear()

    _reset()
    yield
    _reset()


def _dep_of(spec):
    """Single dependency of the single tool on an AgentSpec."""
    assert len(spec.tools) == 1, f"expected one tool spec, got {len(spec.tools)}"
    deps = spec.tools[0].dependencies
    assert deps is not None and len(deps) == 1, f"expected one dependency, got {deps}"
    return deps[0]


ROUTE_DEP = {
    "capability": "llm",
    "tags": ["+claude", ["python", "typescript"]],
    "version": ">=2.0.0",
    "required": True,
    "match_mode": "strict",
    "expected_schema_raw": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
    },
}


def test_route_dependency_carries_full_selector():
    def _handler():  # pragma: no cover - never called
        return None

    DecoratorRegistry.register_route_wrapper(
        method="GET",
        path="/api/v1/ask",
        wrapper=_handler,
        dependencies=["llm"],
        dependency_specs=[ROUTE_DEP],
    )

    spec = rust_api_heartbeat._build_api_agent_spec(
        {"agent_config": {"name": "gw"}, "display_config": {}}, service_id="gw-1"
    )
    dep = _dep_of(spec)

    assert dep.capability == "llm"
    assert json.loads(dep.tags) == ["+claude", ["python", "typescript"]]
    assert dep.version == ">=2.0.0"
    assert dep.required is True
    assert dep.match_mode == "strict"
    assert dep.expected_schema_canonical is not None
    assert dep.expected_schema_hash is not None


def test_route_dependency_capability_is_a_string_not_a_dict():
    """Regression guard: ``capability`` must never receive the dep mapping."""

    def _handler():  # pragma: no cover - never called
        return None

    DecoratorRegistry.register_route_wrapper(
        method="GET",
        path="/api/v1/ask",
        wrapper=_handler,
        dependencies=["llm"],
        dependency_specs=[ROUTE_DEP],
    )

    spec = rust_api_heartbeat._build_api_agent_spec(
        {"agent_config": {"name": "gw"}, "display_config": {}}, service_id="gw-1"
    )
    assert isinstance(_dep_of(spec).capability, str)


def test_route_dependency_without_specs_still_registers_capability():
    """Back-compat: a wrapper registered before #1571 has no dependency_specs."""

    def _handler():  # pragma: no cover - never called
        return None

    DecoratorRegistry.register_route_wrapper(
        method="GET", path="/api/v1/ask", wrapper=_handler, dependencies=["llm"]
    )

    spec = rust_api_heartbeat._build_api_agent_spec(
        {"agent_config": {"name": "gw"}, "display_config": {}}, service_id="gw-1"
    )
    dep = _dep_of(spec)
    assert dep.capability == "llm"
    assert json.loads(dep.tags) == []


def test_a2a_dependency_carries_required_and_schema():
    """A2A already carried tags+version; ``required``/schema/match_mode were lost."""

    def _handler():  # pragma: no cover - never called
        return None

    DecoratorRegistry.register_custom_decorator(
        "mesh_a2a",
        _handler,
        {
            "skill_id": "ask",
            "dependencies": [ROUTE_DEP],
        },
    )

    spec = rust_a2a_heartbeat._build_a2a_agent_spec(
        {"agent_config": {"name": "gw"}, "display_config": {}}, service_id="gw-1"
    )
    dep = _dep_of(spec)

    assert json.loads(dep.tags) == ["+claude", ["python", "typescript"]]
    assert dep.version == ">=2.0.0"
    assert dep.required is True
    assert dep.match_mode == "strict"
    assert dep.expected_schema_canonical is not None
    assert dep.expected_schema_hash is not None


def test_route_selector_survives_decorator_to_wire_end_to_end():
    """The real path: @mesh.route -> RouteIntegrationStep -> AgentSpec.

    Asserting on the heartbeat alone would pass even if the integration step
    never handed the selector over, so drive the whole chain.
    """
    from fastapi import FastAPI

    import mesh
    from _mcp_mesh.pipeline.api_startup.route_integration import RouteIntegrationStep
    from _mcp_mesh.shared.server_discovery import ServerDiscoveryUtil

    @mesh.route(
        dependencies=[
            {
                "capability": "llm",
                "tags": ["+claude"],
                "version": ">=2.0.0",
                "required": True,
            }
        ]
    )
    async def ask(llm: mesh.McpMeshTool = None) -> dict:
        return {"ok": llm is not None}

    app = FastAPI()
    app.get("/api/v1/ask")(ask)

    route_info = next(
        r
        for r in ServerDiscoveryUtil._extract_route_info(app)
        if r["endpoint_name"] == "ask"
    )
    route_info["dependencies"] = ask._mesh_route_metadata["dependencies"]

    step = RouteIntegrationStep()
    assert step._integrate_single_route(app, route_info, None)["status"] == "integrated"

    spec = rust_api_heartbeat._build_api_agent_spec(
        {"agent_config": {"name": "gw"}, "display_config": {}}, service_id="gw-1"
    )
    dep = _dep_of(spec)
    assert dep.capability == "llm"
    assert json.loads(dep.tags) == ["+claude"]
    assert dep.version == ">=2.0.0"
    assert dep.required is True


class TestUnifiedSelectorValidation:
    """One ``_validate_dependency_selector`` for all three decorator families.

    The route copy silently dropped ``expected_type``/``match_mode`` and the
    a2a copy dropped ``required`` on top of that, so a selector that validated
    cleanly at decoration time reached the registry with fields missing.
    """

    def _deps(self, decorated):
        return decorated._mesh_route_metadata["dependencies"]

    def test_route_keeps_expected_type_and_match_mode(self):
        import mesh

        @mesh.route(
            dependencies=[
                {
                    "capability": "employee",
                    "expected_type": {"type": "object"},
                    "match_mode": "strict",
                }
            ]
        )
        async def handler(employee: mesh.McpMeshTool = None) -> dict:
            return {}

        dep = self._deps(handler)[0]
        assert dep["expected_schema_raw"] == {"type": "object"}
        assert dep["match_mode"] == "strict"

    def test_route_defaults_match_mode_to_subset(self):
        import mesh

        @mesh.route(
            dependencies=[
                {"capability": "employee", "expected_type": {"type": "object"}}
            ]
        )
        async def handler(employee: mesh.McpMeshTool = None) -> dict:
            return {}

        assert self._deps(handler)[0]["match_mode"] == "subset"

    def test_a2a_keeps_required(self):
        import mesh
        from mesh.decorators import a2a as a2a_decorator

        @a2a_decorator(
            path="/ask", dependencies=[{"capability": "llm", "required": True}]
        )
        async def handler(llm: mesh.McpMeshTool = None) -> dict:
            return {}

        deps = handler._mesh_a2a_metadata["dependencies"]
        assert deps[0]["required"] is True

    def test_a2a_keeps_expected_type_and_match_mode(self):
        import mesh
        from mesh.decorators import a2a as a2a_decorator

        @a2a_decorator(
            path="/ask",
            dependencies=[
                {
                    "capability": "llm",
                    "expected_type": {"type": "object"},
                    "match_mode": "strict",
                }
            ],
        )
        async def handler(llm: mesh.McpMeshTool = None) -> dict:
            return {}

        dep = handler._mesh_a2a_metadata["dependencies"][0]
        assert dep["expected_schema_raw"] == {"type": "object"}
        assert dep["match_mode"] == "strict"

    @pytest.mark.parametrize(
        "bad,message",
        [
            ({"tags": []}, "dependency must have 'capability' field"),
            ({"capability": 1}, "dependency capability must be a string"),
            ({"capability": "c", "tags": "x"}, "dependency tags must be a list"),
            ({"capability": "c", "tags": [1]}, "tags must be strings or arrays"),
            ({"capability": "c", "tags": [[1]]}, "OR alternative tags must be strings"),
            ({"capability": "c", "version": 1}, "dependency version must be a string"),
            (
                {"capability": "c", "required": "yes"},
                "dependency required must be a boolean",
            ),
            (
                {"capability": "c", "match_mode": "loose"},
                "dependency match_mode must be 'subset' or 'strict'",
            ),
            (7, "dependencies must be strings or dictionaries"),
        ],
    )
    def test_all_three_decorators_reject_the_same_shapes(self, bad, message):
        import mesh
        from mesh.decorators import a2a as a2a_decorator

        for make in (
            lambda: mesh.tool(capability="c", dependencies=[bad]),
            lambda: mesh.route(dependencies=[bad]),
            lambda: a2a_decorator(path="/p", dependencies=[bad]),
        ):
            with pytest.raises(ValueError, match=message):

                @make()
                async def handler(**kwargs) -> dict:  # pragma: no cover
                    return {}


class TestDependencyIndexAlignment:
    """Wire specs must be index-aligned with the decorator's dependency list.

    The registry resolves by position (``IndexedResolution.DepIndex``) and the
    injector applies by position in ``metadata["dependencies"]``. Dropping a
    degenerate entry from the wire list would shift every later dependency onto
    the wrong slot — silent cross-wiring, strictly worse than an edge that
    cannot resolve.
    """

    def _specs(self, deps):
        import mcp_mesh_core

        from _mcp_mesh.pipeline.shared.dependency_spec import build_dependency_specs

        return build_dependency_specs(mcp_mesh_core, deps)

    def test_empty_capability_is_published_not_dropped(self):
        specs = self._specs(
            [
                {"capability": "first", "tags": []},
                {"capability": "", "tags": []},
                {"capability": "third", "tags": []},
            ]
        )
        assert [s.capability for s in specs] == ["first", "", "third"], (
            "dropping the empty entry would move 'third' from index 2 to index 1"
        )

    def test_unsupported_entry_type_keeps_its_slot(self):
        specs = self._specs([{"capability": "first", "tags": []}, 7, "third"])
        assert [s.capability for s in specs] == ["first", "", "third"]

    def test_string_and_dict_entries_stay_in_order(self):
        specs = self._specs(["a", {"capability": "b", "tags": ["x"]}, "c"])
        assert [s.capability for s in specs] == ["a", "b", "c"]
        assert json.loads(specs[1].tags) == ["x"]
