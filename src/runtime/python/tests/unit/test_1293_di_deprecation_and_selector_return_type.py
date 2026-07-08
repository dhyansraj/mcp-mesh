"""Unit tests for issue #1293 Python follow-ups.

Item 1 — the untyped single-parameter injection heuristic:
  * a real consumer tool with an untyped single param still warns, now with
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
# Item 1 — real consumer tool still warns (deprecation wording) + injects
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
