"""Issue #1548 — ``from __future__ import annotations`` must not change how
mesh classifies a parameter.

**This module carries the future import on purpose.** PEP 563 is a per-module
compile flag: it stringifies every annotation in the file, including those on
functions defined inside the test methods below. A string literal written into
one annotation by hand is NOT the same thing (it stringifies the annotations
the author remembered, not all of them), so a module that actually opts in is
the only faithful way to exercise the bug. The "without the future import" half
of each parity assertion lives in the sibling module
``_1548_plain_annotations.py``, which deliberately does not opt in.

Headline case: ``@mesh.llm`` compared ``param.annotation`` to the
``MeshLlmAgent`` class, which is never equal to the string
``"mesh.MeshLlmAgent"``, so a correctly declared parameter was rejected with an
error naming the one thing that was not wrong. The other injectables
(``McpMeshTool``, ``McpMeshAgent``, ``MeshJob``) already resolved their hints
before comparing — the parity cases here pin that down so the two
implementations of the check cannot drift apart again.

A few cases need a namespace the import system cannot produce (a name that is
importable only under ``if TYPE_CHECKING:``). Those use ``exec`` with
``__future__.annotations.compiler_flag``, which gives the compiled function
exactly the PEP 563 semantics this module has.
"""

from __future__ import annotations
import __future__

import asyncio
import os
from typing import Optional

import pytest
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine import settle
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.signature_analyzer import (
    analyze_mesh_job_signature,
    get_llm_agent_parameter_names,
    get_mesh_agent_parameter_names,
    get_mesh_agent_positions,
)
from mesh.types import McpMeshAgent, McpMeshTool, MeshJob, MeshLlmAgent

from . import _1548_plain_annotations as plain

PEP563_FLAG = __future__.annotations.compiler_flag


def compile_pep563(source: str, namespace: dict) -> dict:
    """Execute ``source`` with PEP 563 semantics in a caller-supplied namespace.

    Lets a test build a module scope that lacks a name the annotation uses —
    the ``if TYPE_CHECKING:`` shape — which cannot be expressed by importing a
    fixture module.
    """
    exec(compile(source, "<pep563>", "exec", flags=PEP563_FLAG), namespace)
    return namespace


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


class FakeProxy:
    """Mirrors ``UnifiedMCPProxy.__call__(*args, **kwargs)``."""

    def __init__(self, name):
        self.name = name

    async def __call__(self, *args, **kwargs):
        return {"served": self.name}


class Reply(BaseModel):
    text: str


# ===========================================================================
# Parity: the same declaration, classified the same, with and without PEP 563
# ===========================================================================


class TestClassificationParity:
    """Every injection type, both worlds, identical verdicts.

    Each ``pep563_*`` local is the byte-for-byte twin of the same-named
    function in ``_1548_plain_annotations``; only the module's future import
    differs.
    """

    def test_mcp_mesh_tool_parity(self):
        def pep563_tool_dep(x: str, dep: McpMeshTool = None) -> str:
            return x

        assert get_mesh_agent_positions(pep563_tool_dep) == [1]
        assert get_mesh_agent_parameter_names(pep563_tool_dep) == ["dep"]
        assert get_mesh_agent_positions(pep563_tool_dep) == get_mesh_agent_positions(
            plain.tool_dep
        )

    def test_deprecated_mcp_mesh_agent_parity(self):
        def pep563_agent_dep(x: str, dep: McpMeshAgent = None) -> str:
            return x

        assert get_mesh_agent_positions(pep563_agent_dep) == [1]
        assert get_mesh_agent_positions(pep563_agent_dep) == get_mesh_agent_positions(
            plain.agent_dep
        )

    def test_mesh_llm_agent_parity(self):
        def pep563_llm_param(x: str, llm: MeshLlmAgent = None) -> str:
            return x

        assert get_llm_agent_parameter_names(pep563_llm_param) == ["llm"]
        assert get_llm_agent_parameter_names(
            pep563_llm_param
        ) == get_llm_agent_parameter_names(plain.llm_param)

    def test_mesh_job_parity(self):
        def pep563_job_param(x: str, job: MeshJob = None) -> str:
            return x

        resolution = analyze_mesh_job_signature(pep563_job_param)
        assert (resolution.mesh_job_param_index, resolution.mesh_job_param_name) == (
            1,
            "job",
        )
        assert resolution == analyze_mesh_job_signature(plain.job_param)

    def test_module_qualified_spelling_parity(self):
        """``mesh.McpMeshTool`` — the spelling the docs and the error message
        use — stringifies to a dotted name, not a bare one."""

        def pep563_qualified(
            x: str,
            dep: mesh.McpMeshTool = None,
            job: mesh.MeshJob = None,
            llm: mesh.MeshLlmAgent = None,
        ) -> str:
            return x

        assert get_mesh_agent_positions(pep563_qualified) == [1]
        assert get_llm_agent_parameter_names(pep563_qualified) == ["llm"]
        assert analyze_mesh_job_signature(pep563_qualified).mesh_job_param_name == "job"

        assert get_mesh_agent_positions(pep563_qualified) == get_mesh_agent_positions(
            plain.qualified
        )
        assert get_llm_agent_parameter_names(
            pep563_qualified
        ) == get_llm_agent_parameter_names(plain.qualified)
        assert (
            analyze_mesh_job_signature(pep563_qualified).mesh_job_param_name
            == analyze_mesh_job_signature(plain.qualified).mesh_job_param_name
        )

    def test_optional_and_union_forms_parity(self):
        # ``Optional`` is imported at MODULE scope on purpose: PEP 563 strings
        # are evaluated against the module globals, so a function-local import
        # would make the annotation genuinely unresolvable and the test would
        # be exercising the name-matching fallback instead of resolution.
        def pep563_optional_forms(
            a: Optional[McpMeshTool] = None,  # noqa: UP045 - both spellings on purpose
            b: MeshJob | None = None,
            c: MeshLlmAgent | None = None,
        ) -> str:
            return "x"

        assert get_mesh_agent_positions(pep563_optional_forms) == [0]
        assert analyze_mesh_job_signature(
            pep563_optional_forms
        ).mesh_job_param_name == ("b")
        assert get_llm_agent_parameter_names(pep563_optional_forms) == ["c"]

        assert get_mesh_agent_positions(
            pep563_optional_forms
        ) == get_mesh_agent_positions(plain.optional_forms)
        assert get_llm_agent_parameter_names(
            pep563_optional_forms
        ) == get_llm_agent_parameter_names(plain.optional_forms)

    def test_return_annotation_parity(self):
        """The return annotation feeds the ``@mesh.llm`` output type; under
        PEP 563 it arrived as the string ``'Reply'``."""
        # Imported here, not at module scope: this helper is new in the #1548
        # fix, and a module-level import would turn every test in the file into
        # a collection error when the file is run against the unfixed runtime.
        from _mcp_mesh.engine.signature_analyzer import resolve_return_annotation

        def pep563_structured(x: str, llm: MeshLlmAgent = None) -> Reply:
            return Reply(text=x)

        assert resolve_return_annotation(pep563_structured) is Reply
        assert resolve_return_annotation(plain.structured) is plain.Reply


# ===========================================================================
# The headline case: @mesh.llm decoration
# ===========================================================================


class TestLlmDecoratorUnderPep563:
    def test_llm_decorator_accepts_the_declared_parameter(self):
        """The repro: this decoration raised 'must have at least one parameter
        of type mesh.MeshLlmAgent' on a function that has exactly that."""

        @mesh.llm(provider={"capability": "llm"})
        @mesh.tool(capability="ask")
        def ask(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
            return "x"

        agents = list(DecoratorRegistry.get_mesh_llm_agents().values())
        assert [a.param_name for a in agents] == ["llm"]

    def test_llm_output_type_resolves_to_the_model_class(self):
        """``output_type`` drives structured-output validation. A string here
        is silently wrong: it is not a BaseModel subclass, so the schema the
        provider is asked for never matches the model."""

        @mesh.llm(provider={"capability": "llm"})
        @mesh.tool(capability="structured")
        def structured(prompt: str, llm: mesh.MeshLlmAgent = None) -> Reply:
            return Reply(text="x")

        agent = next(iter(DecoratorRegistry.get_mesh_llm_agents().values()))
        assert agent.output_type is Reply

    def test_llm_parameter_hidden_from_the_tool_schema(self):
        """Detection drives the signature rewrite too — an undetected
        parameter would leak into the MCP input schema."""
        import inspect

        @mesh.llm(provider={"capability": "llm"})
        @mesh.tool(capability="hide_llm")
        def hide_llm(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
            return "x"

        assert list(inspect.signature(hide_llm).parameters.keys()) == ["prompt"]

    def test_llm_alongside_a_mesh_tool_dependency(self):
        """Both injection types on one function, both string-annotated."""

        @mesh.llm(provider={"capability": "llm"})
        @mesh.tool(capability="combined", dependencies=["audit"])
        def combined(
            prompt: str,
            audit: mesh.McpMeshTool = None,
            llm: mesh.MeshLlmAgent = None,
        ) -> str:
            return "x"

        agent = next(iter(DecoratorRegistry.get_mesh_llm_agents().values()))
        assert agent.param_name == "llm"
        assert get_mesh_agent_parameter_names(combined) == ["audit"]

    def test_unresolvable_sibling_annotation_does_not_break_the_llm_scan(self):
        """``get_type_hints`` is all-or-nothing: one TYPE_CHECKING-only
        annotation anywhere on the function used to take the whole scan down
        with it. Per-parameter resolution must rescue the llm parameter."""
        ns: dict = {"mesh": mesh}
        compile_pep563(
            "def ask(payload: OnlyForTypeCheckers, llm: mesh.MeshLlmAgent = None)"
            " -> str:\n    return 'x'\n",
            ns,
        )
        assert get_llm_agent_parameter_names(ns["ask"]) == ["llm"]

    def test_unresolvable_llm_annotation_still_binds_by_name(self):
        """``if TYPE_CHECKING: from mesh.types import MeshLlmAgent`` — a real
        pattern, and unresolvable at runtime by construction. The last rung of
        the ladder matches the name so the agent still starts."""
        ns: dict = {}
        compile_pep563(
            "def ask(prompt: str, llm: MeshLlmAgent = None) -> str:\n    return 'x'\n",
            ns,
        )
        assert get_llm_agent_parameter_names(ns["ask"]) == ["llm"]

    def test_missing_parameter_still_raises_the_documented_error(self):
        """The check must not become permissive: a function with no
        MeshLlmAgent parameter at all is still refused, with the unchanged
        message and no misleading resolution note appended."""
        with pytest.raises(ValueError) as exc:

            @mesh.llm(provider={"capability": "llm"})
            def no_param(prompt: str) -> str:
                return "x"

        message = str(exc.value)
        assert "must have at least one parameter" in message
        assert "mesh.MeshLlmAgent" in message
        assert "could not be resolved" not in message

    def test_error_names_an_unresolvable_annotation_instead_of_the_requirement(
        self,
    ):
        """An aliased type mesh cannot recognise (``LlmAlias``, imported only
        under TYPE_CHECKING) genuinely has no MeshLlmAgent parameter mesh can
        see. The error must say the annotation did not resolve rather than
        restate a requirement the developer believes they met."""
        ns: dict = {"mesh": mesh}
        with pytest.raises(ValueError) as exc:
            compile_pep563(
                "@mesh.llm(provider={'capability': 'llm'})\n"
                "def ask(prompt: str, llm: LlmAlias = None) -> str:\n"
                "    return 'x'\n",
                ns,
            )

        message = str(exc.value)
        assert "could not be resolved" in message
        assert "'LlmAlias'" in message
        assert "TYPE_CHECKING" in message


# ===========================================================================
# End to end: the value actually arrives at call time
# ===========================================================================


class TestInjectionUnderPep563:
    def test_mesh_tool_dependency_is_injected(self):
        """Detection is not the contract — arrival is. An undetected parameter
        produces no error anywhere; the tool just receives ``None``."""

        @mesh.tool(capability="consume", dependencies=["audit"])
        async def consume(x: str, audit: mesh.McpMeshTool = None) -> dict:
            assert audit is not None, "dependency was not injected"
            return await audit()

        consume._mesh_update_dependency(0, FakeProxy("audit"))
        assert asyncio.run(consume(x="v"))["served"] == "audit"

    def test_deprecated_mesh_agent_dependency_is_injected(self):
        @mesh.tool(capability="consume_legacy", dependencies=["audit"])
        async def consume_legacy(x: str, audit: mesh.McpMeshAgent = None) -> dict:
            assert audit is not None, "dependency was not injected"
            return await audit()

        consume_legacy._mesh_update_dependency(0, FakeProxy("legacy"))
        assert asyncio.run(consume_legacy(x="v"))["served"] == "legacy"

    def test_mesh_job_slot_is_declared_and_positioned(self):
        """A MeshJob parameter takes a positional dependency slot shared with
        McpMeshTool; missing it would shift every slot after it."""

        @mesh.tool(capability="submit", dependencies=["audit", "worker"])
        async def submit(
            x: str,
            audit: mesh.McpMeshTool = None,
            job: mesh.MeshJob = None,
        ) -> str:
            return x

        resolution = analyze_mesh_job_signature(submit)
        assert resolution.mesh_tool_positions == [1]
        assert resolution.mesh_job_param_index == 2
        assert resolution.mesh_job_param_name == "job"

    def test_dependency_slot_count_validates(self):
        """``validate_mesh_dependencies`` gates whether a tool is advertised at
        all. Under-counting the typed slots silently drops the tool from the
        heartbeat."""
        from _mcp_mesh.engine.signature_analyzer import validate_mesh_dependencies

        @mesh.tool(capability="counted", dependencies=["audit", "worker"])
        async def counted(
            x: str,
            audit: mesh.McpMeshTool = None,
            job: mesh.MeshJob = None,
        ) -> str:
            return x

        is_valid, message = validate_mesh_dependencies(
            counted, [{"capability": "audit"}, {"capability": "worker"}]
        )
        assert is_valid, message
