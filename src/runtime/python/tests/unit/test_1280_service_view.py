"""
Unit tests for RFC #1280 service views — Python runtime.

Python ships the CONSUMER VIEW (tool-parameter form). These tests are the Python
instance of the cross-runtime seam (uc37 is the integration contract; the Java
runtime is the reference). The producer-side ``@mesh.service("prefix")`` sugar
was removed in v3.1.0 (issue #1320) — a fast-fail on the prefix form is asserted
in ``TestProducerSugarRemoved``.

CRITICAL: facade delegation is tested against the EXACT shapes of the real
injected proxies — ``UnifiedMCPProxy.__call__(*args, **kwargs)`` ignores
positionals and sends only kwargs upstream, and ``SelfDependencyProxy`` accepts
kwargs only. A fake that accepts a positional dict would mask the wire bug, so
the fakes below mirror the real signatures deliberately.

Layout contract asserted throughout: explicit deps FIRST, then each view's
method edges appended in parameter order, methods SORTED BY NAME within a view.
"""

import asyncio
import json
import os
import time

import mesh
import pytest
from fastmcp.exceptions import ToolError

from _mcp_mesh.engine import settle
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.signature_analyzer import (
    analyze_service_view_params,
    validate_mesh_dependencies,
)
from mesh import MeshJob, MeshServiceUnavailableError
from mesh.types import McpMeshTool


def _clear():
    DecoratorRegistry.clear_all()
    from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

    clear_debounce_coordinator()


@pytest.fixture(autouse=True)
def _isolate():
    """Fresh registry + settled (no grace) settle state per test."""
    _clear()
    os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"
    settle._reset_settle_state_for_tests()
    yield
    os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
    settle._reset_settle_state_for_tests()
    _clear()


# ---------------------------------------------------------------------------
# Real-shaped proxy fakes — DO NOT accept a positional dict, on purpose.
# ---------------------------------------------------------------------------


class FakeUnifiedProxy:
    """Mirrors ``UnifiedMCPProxy.__call__(*args, **kwargs)``: ignores *args
    entirely (so a positional dict would be silently dropped → empty upstream),
    pops ``headers``, records the kwargs it would send as tool arguments."""

    def __init__(self, name):
        self.name = name
        self.received = None
        self.received_headers = None

    async def __call__(self, *args, **kwargs):
        self.received_headers = kwargs.pop("headers", None)
        self.received = dict(kwargs)
        return {"served": self.name, "args": dict(kwargs)}


class FakeSelfProxy:
    """Mirrors ``SelfDependencyProxy.__call__(**kwargs)``: kwargs only —
    a positional argument raises TypeError."""

    def __init__(self, name):
        self.name = name
        self.received = None

    async def __call__(self, **kwargs):
        self.received = dict(kwargs)
        return {"served": self.name, "args": dict(kwargs)}


# ---------------------------------------------------------------------------
# Module-scope views (consumer views only stamp metadata — no registration).
# ---------------------------------------------------------------------------


@mesh.service
class MediaService:
    @mesh.selector("media.caption", required=True, tags=["+fast"])
    async def caption(self, args: dict) -> dict: ...

    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...


@mesh.service
class OptionalView:
    @mesh.selector("opt.alpha")
    async def alpha(self, args: dict) -> dict: ...

    @mesh.selector("opt.bravo")
    async def bravo(self, args: dict) -> dict: ...


# ===========================================================================
# Detection + expansion order
# ===========================================================================


class TestViewDetectionAndExpansion:
    def test_analyze_detects_view_param(self):
        async def tool(req: dict, media: MediaService = None):
            pass

        views = analyze_service_view_params(tool)
        assert len(views) == 1
        pos, name, meta = views[0]
        assert (pos, name) == (1, "media")
        assert [b.method_name for b in meta.bindings] == ["caption", "thumbnail"]
        assert [b.capability for b in meta.bindings] == [
            "media.caption",
            "media.thumbnail",
        ]

    def test_explicit_deps_first_then_view_methods_name_sorted(self):
        @mesh.tool(capability="process", dependencies=["audit_log"])
        async def process(
            req: dict, audit: McpMeshTool = None, media: MediaService = None
        ):
            return None

        caps = [d["capability"] for d in process._mesh_tool_metadata["dependencies"]]
        assert caps == ["audit_log", "media.caption", "media.thumbnail"]
        req = {
            d["capability"]: d.get("required")
            for d in process._mesh_tool_metadata["dependencies"]
        }
        assert req["media.caption"] is True
        assert req.get("media.thumbnail") in (None, False)
        assert len(process._mesh_injected_deps) == 3

    def test_multi_view_param_order_then_name_sorted_within_each(self):
        @mesh.tool(capability="multi")
        async def multi(
            req: dict, media: MediaService = None, opt: OptionalView = None
        ):
            return None

        caps = [d["capability"] for d in multi._mesh_tool_metadata["dependencies"]]
        assert caps == [
            "media.caption",
            "media.thumbnail",
            "opt.alpha",
            "opt.bravo",
        ]

    def test_explicit_dep_before_two_views(self):
        @mesh.tool(capability="mixed", dependencies=["audit_log"])
        async def mixed(
            audit: McpMeshTool = None,
            media: MediaService = None,
            opt: OptionalView = None,
        ):
            return None

        caps = [d["capability"] for d in mixed._mesh_tool_metadata["dependencies"]]
        assert caps == [
            "audit_log",
            "media.caption",
            "media.thumbnail",
            "opt.alpha",
            "opt.bravo",
        ]

    def test_view_param_hidden_from_fastmcp_signature(self):
        import inspect

        @mesh.tool(capability="hide", dependencies=["audit_log"])
        async def hide(
            req: dict, audit: McpMeshTool = None, media: MediaService = None
        ):
            return None

        params = list(inspect.signature(hide).parameters.keys())
        assert params == ["req"]

    def test_optional_view_annotation_detected(self):
        from typing import Optional

        async def tool(req: dict, media: Optional[MediaService] = None):
            pass

        views = analyze_service_view_params(tool)
        assert len(views) == 1
        assert views[0][1] == "media"

    def test_meshjob_plus_view_layout(self):
        @mesh.tool(capability="combo", dependencies=["the_job"])
        async def combo(user: str, the_job: MeshJob = None, view: OptionalView = None):
            return None

        caps = [d["capability"] for d in combo._mesh_tool_metadata["dependencies"]]
        assert caps == ["the_job", "opt.alpha", "opt.bravo"]
        assert len(combo._mesh_injected_deps) == 3

    def test_hint_failure_view_free_function_no_warning(self, caplog):
        """A view-free function whose get_type_hints fails (unresolvable
        annotation) must NOT emit the @mesh.service view warning."""
        import logging

        async def tool(x: "TotallyMissingType"):  # noqa: F821
            pass

        with caplog.at_level(logging.WARNING, logger="_mcp_mesh.engine.signature_analyzer"):
            views = analyze_service_view_params(tool)
        assert views == []
        assert not any(
            "@mesh.service" in r.message or "view parameter" in r.message
            for r in caplog.records
        )

    def test_hint_failure_recovers_view_and_warns(self, caplog):
        """When get_type_hints fails on a sibling annotation, a resolvable view
        parameter is still recovered per-parameter — and warns (naming it)."""
        import logging

        async def tool(bad: "TotallyMissingType", view: OptionalView = None):  # noqa: F821
            pass

        with caplog.at_level(logging.WARNING, logger="_mcp_mesh.engine.signature_analyzer"):
            views = analyze_service_view_params(tool)
        # View recovered despite the sibling's unresolvable annotation.
        assert [name for _pos, name, _meta in views] == ["view"]
        assert any("view" in r.message and "recovered" in r.message.lower()
                   for r in caplog.records)


# ===========================================================================
# Dependency accounting
# ===========================================================================


class TestDependencyAccounting:
    def test_validate_counts_view_edges(self):
        async def tool(req: dict, media: MediaService = None):
            pass

        ok, msg = validate_mesh_dependencies(
            tool, [{"capability": "media.caption"}, {"capability": "media.thumbnail"}]
        )
        assert ok, msg

    def test_validate_counts_explicit_plus_view(self):
        async def tool(
            req: dict, audit: McpMeshTool = None, media: MediaService = None
        ):
            pass

        deps = [
            {"capability": "audit_log"},
            {"capability": "media.caption"},
            {"capability": "media.thumbnail"},
        ]
        ok, msg = validate_mesh_dependencies(tool, deps)
        assert ok, msg

    def test_validate_mismatch_when_view_edges_missing(self):
        async def tool(req: dict, media: MediaService = None):
            pass

        ok, msg = validate_mesh_dependencies(tool, [{"capability": "media.caption"}])
        assert not ok
        assert "service-view method edge" in msg

    def test_settle_keys_registered_for_view_edges(self):
        @mesh.tool(capability="settle_reg", dependencies=["audit_log"])
        async def settle_reg(
            req: dict, audit: McpMeshTool = None, media: MediaService = None
        ):
            return None

        declared = settle.get_settle_state()._declared
        func_id = (
            f"{settle_reg._mesh_original_func.__module__}."
            f"{settle_reg._mesh_original_func.__qualname__}"
        )
        assert f"{func_id}:dep_0" in declared
        assert f"{func_id}:dep_1" in declared
        assert f"{func_id}:dep_2" in declared

    def test_meshjob_without_matching_dep_raises_clear_error(self):
        with pytest.raises(ValueError) as exc:

            @mesh.tool(capability="bad_combo")  # no dependencies for the_job
            async def bad_combo(
                user: str, the_job: MeshJob = None, view: OptionalView = None
            ):
                return None

        msg = str(exc.value)
        assert "explicit typed slot" in msg
        assert "MeshJob" in msg


# ===========================================================================
# Facade delegation — REAL proxy shapes
# ===========================================================================


class TestFacadeDelegation:
    def test_delegates_named_params_through_unified_proxy_shape(self):
        """Owner-idiom positional dict must be SPREAD into kwargs — a proxy
        that ignores *args (like UnifiedMCPProxy) must still receive the args."""

        @mesh.tool(capability="deleg_unified")
        async def deleg(media: OptionalView = None):
            return {
                "a": await media.alpha({"x": 1, "y": 2}),
                "b": await media.bravo({"z": 3}),
            }

        alpha_proxy = FakeUnifiedProxy("alpha")
        bravo_proxy = FakeUnifiedProxy("bravo")
        deleg._mesh_update_dependency(0, alpha_proxy)  # opt.alpha
        deleg._mesh_update_dependency(1, bravo_proxy)  # opt.bravo

        out = asyncio.run(deleg())
        assert alpha_proxy.received == {"x": 1, "y": 2}
        assert bravo_proxy.received == {"z": 3}
        assert out["a"]["served"] == "alpha"
        assert out["b"]["served"] == "bravo"

    def test_delegates_through_self_dependency_proxy_shape(self):
        @mesh.tool(capability="deleg_self")
        async def deleg(media: OptionalView = None):
            return await media.alpha({"k": "v"})

        proxy = FakeSelfProxy("self_alpha")
        deleg._mesh_update_dependency(0, proxy)
        deleg._mesh_update_dependency(1, FakeSelfProxy("b"))

        out = asyncio.run(deleg())
        assert proxy.received == {"k": "v"}
        assert out["served"] == "self_alpha"

    def test_no_arg_method_call(self):
        @mesh.service
        class NoArgView:
            @mesh.selector("na.ping")
            async def ping(self) -> dict: ...

        @mesh.tool(capability="noarg")
        async def noarg(view: NoArgView = None):
            return await view.ping()

        proxy = FakeUnifiedProxy("ping")
        noarg._mesh_update_dependency(0, proxy)
        out = asyncio.run(noarg())
        assert proxy.received == {}
        assert out["served"] == "ping"

    def test_headers_thread_through_kwargs(self):
        @mesh.tool(capability="hdr")
        async def hdr(media: OptionalView = None):
            return await media.alpha({"x": 1}, headers={"x-audit-id": "abc"})

        proxy = FakeUnifiedProxy("alpha")
        hdr._mesh_update_dependency(0, proxy)
        hdr._mesh_update_dependency(1, FakeUnifiedProxy("b"))
        asyncio.run(hdr())
        assert proxy.received == {"x": 1}
        assert proxy.received_headers == {"x-audit-id": "abc"}

    def test_offset_delegation_with_explicit_dep(self):
        @mesh.tool(capability="offset", dependencies=["audit_log"])
        async def offset(audit: McpMeshTool = None, media: OptionalView = None):
            return {
                "audit": audit is not None,
                "a": await media.alpha({"n": 1}),
            }

        offset._mesh_update_dependency(0, FakeUnifiedProxy("audit"))  # audit_log
        alpha_proxy = FakeUnifiedProxy("alpha")
        offset._mesh_update_dependency(1, alpha_proxy)  # opt.alpha
        offset._mesh_update_dependency(2, FakeUnifiedProxy("bravo"))  # opt.bravo

        out = asyncio.run(offset())
        assert out["audit"] is True
        assert alpha_proxy.received == {"n": 1}
        assert out["a"]["served"] == "alpha"

    def test_rebinding_picked_up_at_call_time(self):
        @mesh.tool(capability="rebind")
        async def rebind(media: OptionalView = None):
            return await media.alpha({"n": 1})

        rebind._mesh_update_dependency(0, FakeUnifiedProxy("first"))
        rebind._mesh_update_dependency(1, FakeUnifiedProxy("b"))
        assert asyncio.run(rebind())["served"] == "first"

        rebind._mesh_update_dependency(0, FakeUnifiedProxy("second"))
        assert asyncio.run(rebind())["served"] == "second"

    def test_unresolved_optional_method_raises_naming_capability(self):
        @mesh.tool(capability="opt_unresolved")
        async def opt_unresolved(media: OptionalView = None):
            return await media.bravo({"z": 1})

        opt_unresolved._mesh_update_dependency(0, FakeUnifiedProxy("alpha"))
        with pytest.raises(ToolError) as exc:
            asyncio.run(opt_unresolved())
        assert json.loads(str(exc.value)) == {
            "error": "dependency_unavailable",
            "capability": "opt.bravo",
        }

    def test_unknown_method_raises_attribute_error(self):
        @mesh.tool(capability="unknown_method")
        async def unknown_method(media: OptionalView = None):
            return await media.nonexistent({})

        unknown_method._mesh_update_dependency(0, FakeUnifiedProxy("a"))
        unknown_method._mesh_update_dependency(1, FakeUnifiedProxy("b"))
        with pytest.raises(AttributeError):
            asyncio.run(unknown_method())

    def test_non_dict_positional_raises_typeerror(self):
        @mesh.tool(capability="baddict")
        async def baddict(media: OptionalView = None):
            return await media.alpha("not-a-dict")

        baddict._mesh_update_dependency(0, FakeUnifiedProxy("a"))
        baddict._mesh_update_dependency(1, FakeUnifiedProxy("b"))
        with pytest.raises(TypeError):
            asyncio.run(baddict())


# ===========================================================================
# Required view edge → pre-invoke refusal + mock contract
# ===========================================================================


class TestRequiredViewEdgeRefusal:
    def test_required_view_method_unresolved_refuses_before_handler(self):
        called = []

        @mesh.tool(capability="req_view")
        async def req_view(media: MediaService = None):
            called.append(True)
            return await media.caption({"t": "x"})

        with pytest.raises(ToolError) as exc:
            asyncio.run(req_view())
        assert json.loads(str(exc.value)) == {
            "error": "dependency_unavailable",
            "capability": "media.caption",
        }
        assert called == []

    def test_required_view_method_available_runs_handler(self):
        called = []

        @mesh.tool(capability="req_view_ok")
        async def req_view_ok(media: MediaService = None):
            called.append(True)
            return await media.caption({"t": "y"})

        proxy = FakeUnifiedProxy("caption")
        req_view_ok._mesh_update_dependency(0, proxy)  # media.caption (required)
        out = asyncio.run(req_view_ok())
        assert called == [True]
        assert proxy.received == {"t": "y"}

    def test_mock_contract_supplied_facade_skips_refusal(self):
        """A caller that supplies a fake facade for the view param skips the
        required-edge pre-invoke refusal for ALL that view's edges."""
        called = []

        class FakeFacade:
            async def caption(self, args=None, **kw):
                return {"mocked": True}

        @mesh.tool(capability="mock_view")
        async def mock_view(media: MediaService = None):
            called.append(True)
            return await media.caption({"t": "z"})

        out = asyncio.run(mock_view(media=FakeFacade()))
        assert called == [True]
        assert out == {"mocked": True}


# ===========================================================================
# min_available floor
# ===========================================================================


@mesh.service(min_available=2)
class FlooredView:
    @mesh.selector("floor.alpha")
    async def alpha(self, args: dict) -> dict: ...

    @mesh.selector("floor.bravo")
    async def bravo(self, args: dict) -> dict: ...


class TestMinAvailableFloor:
    def test_below_floor_raises_service_unavailable_with_counts(self):
        @mesh.tool(capability="floored")
        async def floored(view: FlooredView = None):
            return await view.alpha({})

        floored._mesh_update_dependency(0, FakeUnifiedProxy("a"))  # only 1 of 2
        with pytest.raises(MeshServiceUnavailableError) as exc:
            asyncio.run(floored())
        err = exc.value
        assert err.service == "FlooredView"
        assert err.methods_available == 1
        assert err.methods_total == 2
        assert err.min_available == 2

    def test_floor_satisfied_delegates(self):
        @mesh.tool(capability="floor_ok")
        async def floor_ok(view: FlooredView = None):
            return await view.alpha({"q": 1})

        alpha_p = FakeUnifiedProxy("alpha")
        floor_ok._mesh_update_dependency(0, alpha_p)
        floor_ok._mesh_update_dependency(1, FakeUnifiedProxy("bravo"))
        out = asyncio.run(floor_ok())
        assert out["served"] == "alpha"
        assert alpha_p.received == {"q": 1}

    def test_floor_already_satisfied_no_wait(self, monkeypatch):
        """_enforce_floor counts FIRST: floor=1 with one resolved + one
        unresolvable must not park on the unresolvable edge. Tested against the
        facade directly to isolate it from the wrapper-level settle grace."""
        from _mcp_mesh.engine.service_view import MeshServiceFacade

        monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", "5")
        settle._reset_settle_state_for_tests()
        state = settle.get_settle_state()
        state.register_declared("t.OneFloor:dep_0")
        state.register_declared("t.OneFloor:dep_1")  # never resolves

        injected = [FakeUnifiedProxy("alpha"), None]
        facade = MeshServiceFacade(
            view_name="OneFloor",
            min_available=1,
            methods=[
                {"method_name": "alpha", "capability": "of.alpha", "dep_index": 0},
                {"method_name": "bravo", "capability": "of.bravo", "dep_index": 1},
            ],
            func_id="t.OneFloor",
            injected_deps_array=injected,
            get_dependency_fn=lambda k: None,
        )

        start = time.monotonic()
        asyncio.run(facade._enforce_floor())  # already satisfied → returns fast
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        settle._reset_settle_state_for_tests()

    def test_floor_cross_edge_wake(self, monkeypatch):
        """Below floor while settling → wake on ANY edge resolving (race, not
        serial), recount, proceed early. Tested against the facade directly."""
        from _mcp_mesh.engine.service_view import MeshServiceFacade

        monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", "5")
        settle._reset_settle_state_for_tests()
        state = settle.get_settle_state()
        state.register_declared("t.Wake:dep_0")
        state.register_declared("t.Wake:dep_1")

        injected = [None, None]
        facade = MeshServiceFacade(
            view_name="Wake",
            min_available=1,
            methods=[
                {"method_name": "alpha", "capability": "wf.alpha", "dep_index": 0},
                {"method_name": "bravo", "capability": "wf.bravo", "dep_index": 1},
            ],
            func_id="t.Wake",
            injected_deps_array=injected,
            get_dependency_fn=lambda k: None,
        )

        async def scenario():
            async def resolve_soon():
                await asyncio.sleep(0.1)
                injected[0] = FakeUnifiedProxy("alpha")  # only ONE resolves
                settle.get_settle_state().mark_resolved("t.Wake:dep_0")

            task = asyncio.create_task(resolve_soon())
            start = time.monotonic()
            await facade._enforce_floor()  # below floor → races, wakes on alpha
            elapsed = time.monotonic() - start
            await task
            return elapsed

        elapsed = asyncio.run(scenario())
        assert elapsed < 2.0  # woke early on the alpha resolution, not full 5s
        settle._reset_settle_state_for_tests()


# ===========================================================================
# Producer sugar removed (issue #1320) — fast-fail on the prefix form
# ===========================================================================


class TestProducerSugarRemoved:
    def test_prefixed_service_raises_removed_error(self):
        with pytest.raises(ValueError) as exc:

            @mesh.service("media")
            class MediaTools:
                async def caption(self, args: dict) -> dict:
                    return {"cap": "caption"}

        msg = str(exc.value)
        assert "removed in v3.1.0" in msg
        assert "@mesh.tool" in msg
        # The prefix is echoed into the actionable capability hint.
        assert 'capability="media.' in msg


# ===========================================================================
# Validation boot-fails (item 7)
# ===========================================================================


class TestValidationBootFails:
    def test_view_public_method_without_selector_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.service
            class BadView:
                @mesh.selector("x.y")
                async def good(self, args: dict) -> dict: ...

                async def missing(self, args: dict) -> dict: ...

        assert "selector" in str(exc.value).lower()

    def test_sync_selector_stub_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.service
            class SyncStub:
                @mesh.selector("x.y")
                def sync_method(self, args: dict) -> dict: ...

        assert "async" in str(exc.value).lower()

    def test_sync_tool_consuming_view_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.tool(capability="sync_consumer")
            def sync_consumer(media: MediaService = None):
                return None

        assert "async" in str(exc.value).lower()

    def test_blank_capability_in_selector_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.service
            class BlankCap:
                @mesh.selector("")
                async def m(self, args: dict) -> dict: ...

        assert "blank" in str(exc.value).lower() or "capability" in str(exc.value).lower()

    def test_min_available_exceeds_method_count_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.service(min_available=3)
            class TooHigh:
                @mesh.selector("a.b")
                async def a(self, args: dict) -> dict: ...

                @mesh.selector("c.d")
                async def b(self, args: dict) -> dict: ...

        assert "min_available" in str(exc.value)

    def test_negative_min_available_raises(self):
        with pytest.raises(ValueError):

            @mesh.service(min_available=-1)
            class Neg:
                @mesh.selector("a.b")
                async def a(self, args: dict) -> dict: ...


# ===========================================================================
# View inheritance (item 5)
# ===========================================================================


class TestViewInheritance:
    def test_decorated_subclass_is_own_view(self):
        @mesh.service
        class Base:
            @mesh.selector("base.a")
            async def a(self, args: dict) -> dict: ...

        @mesh.service
        class Child(Base):
            @mesh.selector("child.b")
            async def b(self, args: dict) -> dict: ...

        async def tool(view: Child = None):
            pass

        views = analyze_service_view_params(tool)
        assert len(views) == 1
        meta = views[0][2]
        assert meta.name == "Child"
        assert sorted(bnd.capability for bnd in meta.bindings) == [
            "base.a",
            "child.b",
        ]

    def test_undecorated_subclass_is_not_a_view(self):
        @mesh.service
        class Parent:
            @mesh.selector("p.a")
            async def a(self, args: dict) -> dict: ...

        class PlainChild(Parent):  # NOT decorated
            pass

        async def tool(view: PlainChild = None):
            pass

        assert analyze_service_view_params(tool) == []

        @mesh.tool(capability="undecorated_child")
        async def undecorated_child(view: PlainChild = None):
            return None

        assert undecorated_child._mesh_tool_metadata["dependencies"] == []


# ===========================================================================
# Stream tool + view (item 10)
# ===========================================================================


class TestStreamToolView:
    def test_stream_tool_with_view_injects_facade(self):
        @mesh.tool(capability="stream_view")
        async def stream_view(view: OptionalView = None) -> mesh.Stream[str]:
            res = await view.alpha({"x": 1})
            yield res["served"]

        proxy = FakeUnifiedProxy("alpha")
        stream_view._mesh_update_dependency(0, proxy)
        stream_view._mesh_update_dependency(1, FakeUnifiedProxy("b"))

        result = asyncio.run(stream_view())
        assert result == "alpha"
        assert proxy.received == {"x": 1}


# ===========================================================================
# @mesh.route views out of scope
# ===========================================================================


class TestRouteViewBootFail:
    def test_view_param_in_route_raises(self):
        with pytest.raises(ValueError) as exc:

            @mesh.route(dependencies=["audit_log"])
            async def handler(audit: McpMeshTool = None, media: MediaService = None):
                return {}

        assert "view" in str(exc.value).lower()


# ===========================================================================
# Public API surface
# ===========================================================================


class TestPublicSurface:
    def test_service_selector_importable(self):
        assert callable(mesh.service)
        assert callable(mesh.selector)

    def test_exception_importable_and_shaped(self):
        err = MeshServiceUnavailableError("V", 1, 3, 2)
        assert err.service == "V"
        assert err.methods_available == 1
        assert err.methods_total == 3
        assert err.min_available == 2

    def test_view_class_has_pydantic_schema_marker(self):
        assert hasattr(MediaService, "__get_pydantic_core_schema__")
