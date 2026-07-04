"""Issue #1268: claim dispatch must gate on locally-resolved required deps.

Two defenses, both exercised here:

1. Pre-claim local skip — the dispatcher must NOT POST /jobs/claim while a
   ``required=True`` dependency slot is unresolved locally (its injected proxy
   is ``None``/absent). The job stays queued with no attempt burned.
2. Pre-invoke guard — if a required slot is still unresolved at claim-invoke
   time, the handler must NOT run; the lease is released (retryable), never a
   terminal fail().

Optional deps (no required flag) keep their None-passthrough behaviour — the
handler still runs.
"""

import asyncio

import pytest
from _mcp_mesh.engine import dependency_injector as di_module
from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

_FUNC_ID = "some.module.my_task"


def _make_dispatcher(
    handler, required_deps=None, func_id=_FUNC_ID
) -> PythonClaimDispatcher:
    return PythonClaimDispatcher(
        capability="test_cap",
        instance_id="test-instance",
        registry_url="http://registry:8000",
        handler=handler,
        func_id=func_id,
        required_deps=required_deps,
    )


@pytest.fixture
def clean_injector():
    """Reset the global injector's resolved-proxy cache around each test."""
    injector = di_module.get_global_injector()
    saved = dict(injector._dependencies)
    injector._dependencies.clear()
    try:
        yield injector
    finally:
        injector._dependencies.clear()
        injector._dependencies.update(saved)


class TestRequiredDepPredicate:
    def test_no_required_deps_is_noop(self, clean_injector):
        d = _make_dispatcher(handler=None, required_deps=[])
        assert d._first_unresolved_required() is None

    def test_unresolved_required_returns_capability(self, clean_injector):
        d = _make_dispatcher(handler=None, required_deps=[(0, "cap_a")])
        # Nothing registered for f"{func_id}:dep_0" → unresolved.
        assert d._first_unresolved_required() == "cap_a"

    def test_resolved_required_returns_none(self, clean_injector):
        clean_injector._dependencies[f"{_FUNC_ID}:dep_0"] = object()
        d = _make_dispatcher(handler=None, required_deps=[(0, "cap_a")])
        assert d._first_unresolved_required() is None

    def test_first_of_many_unresolved_wins(self, clean_injector):
        clean_injector._dependencies[f"{_FUNC_ID}:dep_0"] = object()
        # dep_1 (cap_b) is the first unresolved.
        d = _make_dispatcher(
            handler=None, required_deps=[(0, "cap_a"), (1, "cap_b")]
        )
        assert d._first_unresolved_required() == "cap_b"


class TestPreInvokeGuard:
    @pytest.mark.asyncio
    async def test_unresolved_required_releases_lease_not_fail(
        self, clean_injector
    ):
        called: list = []

        async def handler(**kwargs):
            called.append(kwargs)

        d = _make_dispatcher(handler=handler, required_deps=[(0, "cap_a")])

        released: list = []
        failed: list = []

        async def fake_release(job_id, capability, claim_epoch=None):
            released.append((job_id, capability))

        async def fake_fail(job_id, error, claim_epoch=None):
            failed.append((job_id, error))

        d._release_lease = fake_release
        d._report_terminal_fail = fake_fail

        await d._dispatch({"id": "job-1", "submitted_payload": {}})

        assert called == [], "handler must NOT run with an unresolved required dep"
        assert released == [("job-1", "cap_a")], "lease must be released"
        assert failed == [], "guard must NEVER terminal-fail the job"

    @pytest.mark.asyncio
    async def test_resolved_required_invokes_handler(self, clean_injector):
        clean_injector._dependencies[f"{_FUNC_ID}:dep_0"] = object()
        called: list = []

        async def handler(**kwargs):
            called.append(kwargs)

        d = _make_dispatcher(handler=handler, required_deps=[(0, "cap_a")])

        released: list = []
        d._release_lease = lambda *a, **k: released.append(a)

        await d._dispatch({"id": "job-1", "submitted_payload": {"x": 1}})

        assert called == [{"x": 1}], "handler must run when required dep resolved"
        assert released == []

    @pytest.mark.asyncio
    async def test_optional_dep_none_invokes_handler(self, clean_injector):
        """Regression: a tool with NO required deps runs even with null slots."""
        called: list = []

        async def handler(**kwargs):
            called.append(kwargs)

        # No required deps declared → optional None-passthrough preserved.
        d = _make_dispatcher(handler=handler, required_deps=[])

        released: list = []
        d._release_lease = lambda *a, **k: released.append(a)

        await d._dispatch({"id": "job-2", "submitted_payload": {}})

        assert called == [{}], "optional-dep handler must still be invoked"
        assert released == []


class TestMeshJobDepExcludedFromGate:
    """A required dep paired with the MeshJob slot is a locally-constructed
    MeshJobSubmitter — never a resolved proxy — so the gate must ignore it,
    else the claim loop deadlocks forever (issue #1268 review; matches TS's
    meshJobDepIndex / Java's structural exclusion)."""

    def test_discover_excludes_meshjob_paired_required_dep(self):
        from mesh.types import MeshJob
        from _mcp_mesh.engine.claim_dispatcher import discover_task_handlers
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        saved = DecoratorRegistry.get_mesh_tools()
        try:
            # MeshJob param at position 1 → eligible {1} → dep_index 0 is the
            # MeshJob submitter slot. Its dependency is declared required.
            async def task_with_submitter(x: int, submit: MeshJob = None):
                return x

            DecoratorRegistry.register_mesh_tool(
                task_with_submitter,
                {
                    "task": True,
                    "capability": "gate_meshjob_cap",
                    "dependencies": [
                        {"capability": "downstream", "required": True},
                    ],
                },
            )

            dispatchers = discover_task_handlers("inst", "http://r:8000")
            match = [
                d for d in dispatchers if d.capability == "gate_meshjob_cap"
            ]
            assert len(match) == 1
            # The MeshJob-paired required dep (dep_index 0) is excluded, so the
            # gate has nothing to hold on and the predicate is a no-op.
            assert match[0]._required_deps == []
            assert match[0]._first_unresolved_required() is None
        finally:
            DecoratorRegistry._mesh_tools.clear()
            DecoratorRegistry._mesh_tools.update(saved)

    def test_discover_keeps_non_meshjob_required_dep(self):
        from mesh.types import McpMeshTool, MeshJob
        from _mcp_mesh.engine.claim_dispatcher import discover_task_handlers
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        saved = DecoratorRegistry.get_mesh_tools()
        try:
            # dep_0 → McpMeshTool proxy (pos 1, required); dep_1 → MeshJob
            # submitter (pos 2). Only dep_0 must be gated.
            async def task_mixed(
                x: int, proxy: McpMeshTool = None, submit: MeshJob = None
            ):
                return x

            DecoratorRegistry.register_mesh_tool(
                task_mixed,
                {
                    "task": True,
                    "capability": "gate_mixed_cap",
                    "dependencies": [
                        {"capability": "real_proxy", "required": True},
                        {"capability": "downstream", "required": True},
                    ],
                },
            )

            dispatchers = discover_task_handlers("inst", "http://r:8000")
            match = [d for d in dispatchers if d.capability == "gate_mixed_cap"]
            assert len(match) == 1
            # Only the McpMeshTool required dep (index 0) is gated; the MeshJob
            # submitter (index 1) is excluded.
            assert match[0]._required_deps == [(0, "real_proxy")]
        finally:
            DecoratorRegistry._mesh_tools.clear()
            DecoratorRegistry._mesh_tools.update(saved)


class TestPreClaimSkip:
    @pytest.mark.asyncio
    async def test_run_loop_skips_claim_while_required_unresolved(
        self, clean_injector
    ):
        claim_calls: list = []

        async def fake_claim_once():
            claim_calls.append(True)
            return []

        async def handler(**kwargs):
            pass

        d = _make_dispatcher(handler=handler, required_deps=[(0, "cap_a")])
        d._claim_once = fake_claim_once

        d.start()
        # Give the loop several poll cadences to run; it must skip every time
        # because f"{func_id}:dep_0" is unresolved.
        await asyncio.sleep(0.2)
        await d.stop(drain_timeout=0)

        assert claim_calls == [], (
            "dispatcher must not POST /jobs/claim while a required dep is "
            "unresolved locally"
        )

    @pytest.mark.asyncio
    async def test_run_loop_claims_when_required_resolved(self, clean_injector):
        clean_injector._dependencies[f"{_FUNC_ID}:dep_0"] = object()
        claim_calls: list = []

        async def fake_claim_once():
            claim_calls.append(True)
            return []

        async def handler(**kwargs):
            pass

        d = _make_dispatcher(handler=handler, required_deps=[(0, "cap_a")])
        d._claim_once = fake_claim_once

        d.start()
        await asyncio.sleep(0.2)
        await d.stop(drain_timeout=0)

        assert len(claim_calls) >= 1, (
            "dispatcher must claim once required deps are resolved"
        )
