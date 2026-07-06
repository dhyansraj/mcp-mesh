"""Unit tests for issue #1293 Python follow-ups.

Item 1 — the untyped single-parameter injection heuristic:
  * 1a: @mesh.service("prefix") producer-sugar methods (single ``args: dict``
    param, MCP input data, NO declared dependencies) must NOT trip the DI
    warning nor force-inject position 0 — there is nothing to inject.
  * 1b: a real consumer tool with an untyped single param still warns, now with
    the v3 DEPRECATION wording, and still injects (returns [0]).

Item 2 — @mesh.selector schema-matching ``expected_type`` defaults to the stub's
  return annotation when ``match_mode`` is set (Java ``schemaMode`` parity).
"""

import logging
import os

import mesh
import pytest
from pydantic import BaseModel

from _mcp_mesh.engine import settle
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.dependency_injector import analyze_injection_strategy
from mesh._service import (
    SERVICE_VIEW_ATTR,
    binding_to_dependency_dict,
)


def _clear():
    DecoratorRegistry.clear_all()
    from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

    clear_debounce_coordinator()


@pytest.fixture(autouse=True)
def _isolate():
    _clear()
    os.environ["MCP_MESH_SETTLE_TIMEOUT"] = "0"
    settle._reset_settle_state_for_tests()
    yield
    os.environ.pop("MCP_MESH_SETTLE_TIMEOUT", None)
    settle._reset_settle_state_for_tests()
    _clear()


# ===========================================================================
# Item 1a — producer sugar does NOT trip the untyped single-param heuristic
# ===========================================================================


class TestProducerSugarNoFalseWarning:
    def test_producer_sugar_single_arg_param_no_warning(self, caplog):
        """A @mesh.service("prefix") producer method with a lone ``args: dict``
        param publishes+serves without emitting the untyped single-parameter
        DI warning (the param is MCP input, not a DI slot)."""
        with caplog.at_level(logging.WARNING):

            @mesh.service("media")
            class MediaProducer:
                async def caption(self, args: dict) -> dict:
                    return {"ok": True}

        assert "Untyped single-parameter injection is DEPRECATED" not in caplog.text
        assert "consider typing as McpMeshTool" not in caplog.text

        # Tool still published + flagged for serving.
        tools = DecoratorRegistry.get_mesh_tools()
        assert "media.caption" in tools
        served = getattr(tools["media.caption"].function, "_mesh_service_served_name", None)
        assert served == "media.caption"

    def test_producer_sugar_analyze_returns_no_injection(self, caplog):
        """Directly assert the analyzer skips (returns []) a marked producer
        wrapper with no dependencies, and emits no warning."""

        async def published(args: dict):
            return args

        published._mesh_service_served_name = "media.caption"

        with caplog.at_level(logging.WARNING):
            result = analyze_injection_strategy(published, [])

        assert result == []
        assert "DEPRECATED" not in caplog.text

    def test_streaming_producer_method_no_warning(self, caplog):
        """A streaming producer method (async-generator) with a lone ``args``
        param is suppressed just like a plain producer method."""
        from mesh.types import Stream

        with caplog.at_level(logging.WARNING):

            @mesh.service("feed")
            class FeedProducer:
                async def tail(self, args: dict) -> Stream[str]:
                    yield "tick"

        assert "Untyped single-parameter injection is DEPRECATED" not in caplog.text
        tools = DecoratorRegistry.get_mesh_tools()
        assert "feed.tail" in tools

    def test_tool_wins_producer_no_deps_suppressed(self, caplog):
        """A tool-wins producer method (own @mesh.tool) with NO dependencies and
        a lone untyped param is still a producer-served wrapper → suppressed."""
        with caplog.at_level(logging.WARNING):

            @mesh.service("shop")
            class ShopProducer:
                @mesh.tool(capability="shop.custom")
                async def custom(self, args: dict) -> dict:
                    return {"ok": True}

        assert "Untyped single-parameter injection is DEPRECATED" not in caplog.text
        tools = DecoratorRegistry.get_mesh_tools()
        assert "shop.custom" in tools

    def test_marked_producer_with_deps_falls_through_and_warns(self, caplog):
        """A producer-served wrapper that DOES carry a dependency is NOT
        suppressed — it falls through to the deprecated inject-and-warn path."""

        async def published(args):
            return args

        published._mesh_service_served_name = "shop.custom"

        with caplog.at_level(logging.WARNING):
            result = analyze_injection_strategy(published, ["dep"])

        assert result == [0]
        assert "Untyped single-parameter injection is DEPRECATED" in caplog.text


# ===========================================================================
# Item 1b — real consumer tool still warns (deprecation wording) + injects
# ===========================================================================


class TestUntypedConsumerDeprecationWarning:
    def test_untyped_single_param_consumer_warns_and_injects(self, caplog):
        def greet(dep):
            return dep

        with caplog.at_level(logging.WARNING):
            result = analyze_injection_strategy(greet, ["some_dep"])

        assert result == [0]  # injection still happens
        assert "Untyped single-parameter injection is DEPRECATED as of v3" in caplog.text
        assert "dep: McpMeshTool = None" in caplog.text

    def test_zero_dependency_single_param_no_warning_still_injects(self, caplog):
        """A plain zero-dependency single-param tool ('def greet(name)') lands
        in the heuristic branch but nothing is injected — no warning (advising
        McpMeshTool would break its schema), and the [0] mechanics are
        unchanged."""

        def greet(name):
            return name

        with caplog.at_level(logging.WARNING):
            result = analyze_injection_strategy(greet, [])

        assert result == [0]  # mechanics unchanged (test_12 relies on this)
        assert "DEPRECATED" not in caplog.text


# ===========================================================================
# Item 2 — selector expected_type derived from stub return annotation
# ===========================================================================


class Employee(BaseModel):
    name: str
    id: int


class Widget(BaseModel):
    sku: str


def _binding(cls, method_name):
    meta = getattr(cls, SERVICE_VIEW_ATTR)
    for b in meta.bindings:
        if b.method_name == method_name:
            return b
    raise AssertionError(f"no binding for {method_name}")


class TestSelectorReturnTypeDerivation:
    def test_match_mode_set_derives_expected_type_from_return(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employee", match_mode="subset")
            async def get(self, args: dict) -> Employee: ...

        b = _binding(View, "get")
        assert b.expected_type is Employee
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" in dep
        assert dep["expected_schema_raw"]["title"] == "Employee"
        assert dep["match_mode"] == "subset"

    def test_explicit_expected_type_overrides_return(self):
        @mesh.service
        class View:
            @mesh.selector(
                "hr.employee", match_mode="subset", expected_type=Widget
            )
            async def get(self, args: dict) -> Employee: ...

        b = _binding(View, "get")
        assert b.expected_type is Widget
        dep = binding_to_dependency_dict(b)
        assert dep["expected_schema_raw"]["title"] == "Widget"

    def test_no_match_mode_no_schema_even_with_return_annotation(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employee")
            async def get(self, args: dict) -> Employee: ...

        b = _binding(View, "get")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep

    def test_match_mode_set_but_return_none_no_schema(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employee", match_mode="subset")
            async def get(self, args: dict) -> None: ...

        b = _binding(View, "get")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep
        assert dep.get("match_mode") == "subset"

    def test_match_mode_set_but_no_return_annotation_no_schema(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employee", match_mode="subset")
            async def get(self, args: dict): ...

        b = _binding(View, "get")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep

    # -- Item 3: only STRUCTURED return types derive a constraining schema ----

    def test_list_of_model_derives_array_schema(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employees", match_mode="subset")
            async def list_all(self, args: dict) -> list[Employee]: ...

        b = _binding(View, "list_all")
        assert b.expected_type == list[Employee]
        dep = binding_to_dependency_dict(b)
        assert dep["expected_schema_raw"]["type"] == "array"
        assert "items" in dep["expected_schema_raw"]

    def test_optional_model_unwraps_and_derives(self):
        from typing import Optional

        @mesh.service
        class View:
            @mesh.selector("hr.employee", match_mode="subset")
            async def maybe(self, args: dict) -> Optional[Employee]: ...

        b = _binding(View, "maybe")
        # Unwrapped to the concrete model, not stored as Optional[...].
        assert b.expected_type is Employee
        dep = binding_to_dependency_dict(b)
        assert dep["expected_schema_raw"]["title"] == "Employee"

    def test_pep604_optional_model_unwraps_and_derives(self):
        @mesh.service
        class View:
            @mesh.selector("hr.employee", match_mode="subset")
            async def maybe(self, args: dict) -> Employee | None: ...

        b = _binding(View, "maybe")
        assert b.expected_type is Employee

    def test_bare_dict_return_derives_no_schema(self):
        @mesh.service
        class View:
            @mesh.selector("hr.raw", match_mode="subset")
            async def raw(self, args: dict) -> dict: ...

        b = _binding(View, "raw")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep

    def test_bare_list_return_derives_no_schema(self):
        @mesh.service
        class View:
            @mesh.selector("hr.raw", match_mode="subset")
            async def raw(self, args: dict) -> list: ...

        b = _binding(View, "raw")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep

    def test_any_return_derives_no_schema(self):
        from typing import Any

        @mesh.service
        class View:
            @mesh.selector("hr.raw", match_mode="subset")
            async def raw(self, args: dict) -> Any: ...

        b = _binding(View, "raw")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep

    def test_future_annotations_stringized_return_derives_no_schema(self):
        """MED-2: under ``from __future__ import annotations`` a
        TYPE_CHECKING-only return type stringizes the annotation and makes
        get_type_hints raise; the signature fallback then yields the raw
        string, which must be rejected (no crash, no schema) rather than
        stored as expected_type and later exploding in schema extraction."""
        import textwrap
        import types as _types

        src = textwrap.dedent(
            """
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:  # only importable at type-check time
                from nonexistent_pkg import Ghost

            import mesh

            @mesh.service
            class GhostView:
                @mesh.selector("hr.ghost", match_mode="subset")
                async def get(self, args: dict) -> Ghost: ...
            """
        )
        mod = _types.ModuleType("test_1293_future_ann_mod")
        exec(compile(src, "test_1293_future_ann_mod", "exec"), mod.__dict__)

        b = _binding(mod.GhostView, "get")
        assert b.expected_type is None
        dep = binding_to_dependency_dict(b)
        assert "expected_schema_raw" not in dep
