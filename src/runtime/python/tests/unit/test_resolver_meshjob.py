"""DDDI resolver tests for the ``MeshJob`` injectable (Phase 1).

These tests are the Python instance of the cross-runtime test seam
specified in ``MESHJOB_DDDI_CONTRACT.md`` → "Equivalence across SDKs".
The same scenarios MUST be covered by the TypeScript and Java SDKs in
their corresponding files (``__tests__/resolver-meshjob.spec.ts`` and
``MeshJobResolverTest.java``).

If a behaviour here changes, update the contract first, then mirror the
change in the other two SDK test files. Each numbered scenario maps to
the checklist in the contract document.
"""

from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Imports under test — kept inside the test file so a typo or broken export
# fails fast as a test failure rather than silently masking the regression.
# ---------------------------------------------------------------------------
from _mcp_mesh.engine.signature_analyzer import (
    MeshJobResolution,
    analyze_mesh_job_signature,
)
from mesh import MeshJob
from mesh.types import McpMeshTool, MeshLlmAgent


# ===========================================================================
# Contract scenarios 1-5 (must mirror across all three SDK test seams)
# ===========================================================================


class TestResolverContractScenarios:
    """The five mandatory scenarios from MESHJOB_DDDI_CONTRACT.md."""

    def test_scenario_1_mesh_tool_only_unchanged(self):
        """Scenario 1: function with MeshTool only → unchanged behaviour.

        ``mesh_tool_positions`` reflects each McpMeshTool slot in
        declaration order; no MeshJob is recorded.
        """

        def fn(name: str, dep_a: McpMeshTool = None, dep_b: McpMeshTool = None):
            pass

        result = analyze_mesh_job_signature(fn)

        assert isinstance(result, MeshJobResolution)
        assert result.mesh_tool_positions == [1, 2]
        assert result.mesh_job_param_index is None
        assert result.mesh_job_param_name is None

    def test_scenario_2_mesh_job_only(self):
        """Scenario 2: function with MeshJob only → no tools, job index recorded."""

        async def fn(user_id: str, job: MeshJob = None):
            pass

        result = analyze_mesh_job_signature(fn)

        assert result.mesh_tool_positions == []
        assert result.mesh_job_param_index == 1
        assert result.mesh_job_param_name == "job"

    def test_scenario_3_both_mesh_job_in_middle(self):
        """Scenario 3: function with both, MeshJob in middle.

        The MeshTool positions MUST stay correct (sig pos 1 and 3),
        skipping the MeshJob at sig pos 2 — i.e. the resolver does NOT
        renumber tool slots when a MeshJob is interleaved.
        """

        async def plan_trip(
            user_id: str,                       # pos 0 — user arg
            weather_lookup: McpMeshTool = None, # pos 1 — MeshTool[0]
            job: MeshJob = None,                # pos 2 — MeshJob (orthogonal)
            flight_search: McpMeshTool = None,  # pos 3 — MeshTool[1]
        ):
            pass

        result = analyze_mesh_job_signature(plan_trip)

        # MeshTool positions are signature positions 1 and 3 — NOT 1 and 2.
        # If the resolver renumbered after consuming the MeshJob slot the
        # second tool would land at sig pos 2 and the runtime would inject
        # the proxy into the wrong parameter.
        assert result.mesh_tool_positions == [1, 3]
        assert result.mesh_job_param_index == 2
        assert result.mesh_job_param_name == "job"

    def test_scenario_4_neither(self):
        """Scenario 4: function with neither → no DDDI metadata."""

        def fn(a: str, b: int):
            pass

        result = analyze_mesh_job_signature(fn)

        assert result.mesh_tool_positions == []
        assert result.mesh_job_param_index is None
        assert result.mesh_job_param_name is None

    def test_scenario_5_mesh_job_trailing(self):
        """Scenario 5: function with MeshJob trailing → index = last sig pos."""

        async def fn(
            a: str,
            b: int,
            tool: McpMeshTool = None,
            job: MeshJob = None,
        ):
            pass

        result = analyze_mesh_job_signature(fn)

        assert result.mesh_tool_positions == [2]
        assert result.mesh_job_param_index == 3
        assert result.mesh_job_param_name == "job"


# ===========================================================================
# Contract edge cases
# ===========================================================================


class TestResolverEdgeCases:
    """Edge cases called out under "Edge cases (REQUIRED)" in the contract."""

    def test_multiple_mesh_job_raises_clear_error(self):
        """Multiple MeshJob params must raise at registration time."""

        async def fn(a: str, j1: MeshJob = None, j2: MeshJob = None):
            pass

        with pytest.raises(ValueError) as exc_info:
            analyze_mesh_job_signature(fn)

        msg = str(exc_info.value).lower()
        # Contract wording: "a tool function may declare at most one MeshJob parameter"
        assert "at most one" in msg
        assert "meshjob" in msg
        # Both offending names should appear so the developer can fix it.
        assert "j1" in msg
        assert "j2" in msg

    def test_mesh_job_first_position(self):
        """MeshJob can appear at any position — first is OK."""

        async def fn(job: MeshJob = None, a: str = "x"):
            pass

        result = analyze_mesh_job_signature(fn)

        assert result.mesh_tool_positions == []
        assert result.mesh_job_param_index == 0
        assert result.mesh_job_param_name == "job"

    def test_optional_mesh_job_classifies_as_mesh_job(self):
        """``Optional[MeshJob]`` must classify as MeshJob (not user arg)."""

        async def fn(a: str, job: Optional[MeshJob] = None):
            pass

        result = analyze_mesh_job_signature(fn)

        assert result.mesh_job_param_index == 1

    def test_pep604_union_mesh_job_or_none(self):
        """``MeshJob | None`` (PEP 604) must classify as MeshJob."""

        async def fn(a: str, job: "MeshJob | None" = None):
            pass

        # forward-ref annotation needs string form to be valid Python at
        # eval time on older versions; analyzer uses get_type_hints which
        # resolves forward refs in the function's module namespace.
        result = analyze_mesh_job_signature(fn)
        assert result.mesh_job_param_index == 1

    def test_mesh_job_without_default_value(self):
        """Default value is NOT required by the resolver."""

        async def fn(a: str, job: MeshJob):
            pass

        result = analyze_mesh_job_signature(fn)
        assert result.mesh_job_param_index == 1

    def test_mesh_llm_agent_param_does_not_disturb_classification(self):
        """MeshLlmAgent params live outside this resolver's scope; they
        must NOT be classified as MeshTool or MeshJob."""

        async def fn(
            msg: str,
            tool: McpMeshTool = None,
            llm: MeshLlmAgent = None,
            job: MeshJob = None,
        ):
            pass

        result = analyze_mesh_job_signature(fn)

        # MeshLlmAgent is at sig pos 2 — must not appear in either output.
        assert result.mesh_tool_positions == [1]
        assert result.mesh_job_param_index == 3


# ===========================================================================
# Surface tests — type marker + contextvar
# ===========================================================================


class TestMeshJobImports:
    """Smoke tests that the public surface is wired correctly."""

    def test_mesh_job_importable_from_mesh(self):
        """``from mesh import MeshJob`` must work (public API)."""
        from mesh import MeshJob as M

        assert M is MeshJob

    def test_mesh_job_has_pydantic_schema_marker(self):
        """MeshJob must declare the same Pydantic-schema escape hatch as
        McpMeshTool / MeshLlmAgent so FastMCP doesn't reject the param
        when generating the tool's input schema."""
        assert hasattr(MeshJob, "__get_pydantic_core_schema__")


class TestPythonJobContext:
    """The Python contextvar surface — sets up the next-dispatch wiring."""

    def test_current_job_returns_none_outside_active_job(self):
        from _mcp_mesh.engine.job_context import current_job, remaining_seconds

        assert current_job() is None
        assert remaining_seconds() is None

    def test_snapshot_dataclass_shape(self):
        from _mcp_mesh.engine.job_context import JobContextSnapshot

        snap = JobContextSnapshot(job_id="job-abc", deadline_secs_remaining=42.0)
        assert snap.job_id == "job-abc"
        assert snap.deadline_secs_remaining == 42.0

    def test_snapshot_with_no_deadline(self):
        from _mcp_mesh.engine.job_context import JobContextSnapshot

        snap = JobContextSnapshot(job_id="job-xyz")
        assert snap.deadline_secs_remaining is None

    def test_contextvar_set_visible_via_current_job(self):
        """Setting CURRENT_JOB explicitly should propagate to current_job()."""
        from _mcp_mesh.engine.job_context import (
            CURRENT_JOB,
            JobContextSnapshot,
            current_job,
            remaining_seconds,
        )

        snap = JobContextSnapshot(job_id="job-set", deadline_secs_remaining=12.5)
        token = CURRENT_JOB.set(snap)
        try:
            cur = current_job()
            assert cur is not None
            assert cur.job_id == "job-set"
            assert remaining_seconds() == 12.5
        finally:
            CURRENT_JOB.reset(token)

        assert current_job() is None


# ===========================================================================
# Decorator surface — task=True validation
# ===========================================================================


class TestTaskTrueDecorator:
    """``@mesh.tool(task=True)`` validation behaviour."""

    def test_task_true_on_async_function_works(self):
        import mesh

        @mesh.tool(capability="long_running", task=True)
        async def long_task(x: int) -> int:
            return x

        meta = getattr(long_task, "_mesh_tool_metadata", None)
        assert meta is not None
        assert meta.get("task") is True
        assert meta.get("capability") == "long_running"

    def test_task_true_on_sync_function_raises(self):
        import mesh

        with pytest.raises(ValueError) as exc_info:
            @mesh.tool(capability="bad", task=True)
            def sync_task(x: int) -> int:
                return x

        msg = str(exc_info.value).lower()
        assert "async" in msg
        assert "task=true" in msg

    def test_task_false_default(self):
        import mesh

        @mesh.tool(capability="quick")
        def quick(x: int) -> int:
            return x

        meta = getattr(quick, "_mesh_tool_metadata", None)
        assert meta is not None
        assert meta.get("task") is False

    def test_task_must_be_bool(self):
        import mesh

        with pytest.raises(ValueError) as exc_info:
            @mesh.tool(capability="x", task="yes")  # type: ignore[arg-type]
            async def x():
                pass

        assert "task" in str(exc_info.value).lower()
