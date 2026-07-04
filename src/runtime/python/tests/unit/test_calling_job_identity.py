"""Issue #1263: propagate the CALLING job's identity on outbound tool calls
via a dedicated header pair, and expose a provider-side accessor.

Carrier: ``x-mesh-calling-job-id`` / ``x-mesh-calling-claim-epoch`` — distinct
from the push-mode dispatch protocol's ``x-mesh-job-id`` / ``x-mesh-claim-epoch``
(x-mesh-job-id doubles as the dispatch discriminator and cannot carry calling
identity).

Covers:
- ``mesh.calling_job()`` reads the calling-* pair; ``None`` outside a job.
- The calling-* pair is always allowlisted; the dispatch pair is NOT (reverted).
- Outbound proxy overlay seeds the calling-* pair from the active job snapshot,
  REPLACING any inherited pair entirely (both-or-none).
- Inside a directly-claimed handler, ``calling_job()`` is ``None`` (the
  handler's own identity lives on ``current_job``).
"""

import pytest

import mesh
from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher
from _mcp_mesh.engine.job_context import CallingJob, calling_job
from _mcp_mesh.tracing.context import matches_propagate_header
from _mcp_mesh.tracing.context import TraceContext


class TestAllowlist:
    def test_calling_pair_is_always_propagated(self):
        assert matches_propagate_header("x-mesh-calling-job-id") is True
        assert matches_propagate_header("x-mesh-calling-claim-epoch") is True

    def test_dispatch_pair_is_not_allowlisted(self):
        # The push-dispatch protocol headers must NOT be in the propagate
        # allowlist (reverted): x-mesh-job-id is the dispatch discriminator.
        assert matches_propagate_header("x-mesh-job-id") is False
        assert matches_propagate_header("x-mesh-claim-epoch") is False

    def test_case_insensitive(self):
        assert matches_propagate_header("X-Mesh-Calling-Job-Id") is True
        assert matches_propagate_header("X-Mesh-Calling-Claim-Epoch") is True


class TestCallingJobAccessor:
    def teardown_method(self):
        TraceContext.set_propagated_headers({})

    def test_none_outside_job(self):
        TraceContext.set_propagated_headers({})
        assert calling_job() is None

    def test_none_when_no_calling_job_id(self):
        TraceContext.set_propagated_headers({"x-mesh-calling-claim-epoch": "7"})
        assert calling_job() is None

    def test_does_not_read_dispatch_pair(self):
        # The dispatch pair (job context) must NOT be surfaced as a calling job.
        TraceContext.set_propagated_headers(
            {"x-mesh-job-id": "job-self", "x-mesh-claim-epoch": "3"}
        )
        assert calling_job() is None

    def test_returns_calling_job_id_and_epoch(self):
        TraceContext.set_propagated_headers(
            {"x-mesh-calling-job-id": "job-abc", "x-mesh-calling-claim-epoch": "5"}
        )
        cj = calling_job()
        assert isinstance(cj, CallingJob)
        assert cj.job_id == "job-abc"
        assert cj.claim_epoch == 5

    def test_job_id_only_epoch_none(self):
        TraceContext.set_propagated_headers({"x-mesh-calling-job-id": "job-xyz"})
        cj = calling_job()
        assert cj is not None
        assert cj.job_id == "job-xyz"
        assert cj.claim_epoch is None

    def test_malformed_epoch_degrades_to_none(self):
        TraceContext.set_propagated_headers(
            {"x-mesh-calling-job-id": "job-1", "x-mesh-calling-claim-epoch": "nope"}
        )
        assert calling_job().claim_epoch is None

    def test_negative_epoch_rejected(self):
        TraceContext.set_propagated_headers(
            {"x-mesh-calling-job-id": "job-1", "x-mesh-calling-claim-epoch": "-3"}
        )
        assert calling_job().claim_epoch is None

    def test_exposed_via_mesh_package(self):
        assert mesh.calling_job is calling_job


class TestOutboundOverlay:
    """The outbound proxy seeds the calling-* pair from the active job
    snapshot, replacing any inherited pair entirely (both-or-none)."""

    def teardown_method(self):
        from _mcp_mesh.engine.job_context import CURRENT_JOB

        CURRENT_JOB.set(None)
        TraceContext.set_propagated_headers({})

    def _merged(self, arguments=None):
        from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool")
        _args, merged = proxy._inject_trace_into_args(arguments or {}, None)
        return merged

    def _set_job(self, job_id, claim_epoch):
        from _mcp_mesh.engine.job_context import CURRENT_JOB, JobContextSnapshot

        CURRENT_JOB.set(
            JobContextSnapshot(
                job_id=job_id, deadline_secs_remaining=None, claim_epoch=claim_epoch
            )
        )

    def test_no_active_job_leaves_headers_untouched(self):
        merged = self._merged()
        assert "x-mesh-calling-job-id" not in merged

    def test_seeds_both_from_snapshot(self):
        self._set_job("job-A", 4)
        merged = self._merged()
        assert merged["x-mesh-calling-job-id"] == "job-A"
        assert merged["x-mesh-calling-claim-epoch"] == "4"

    def test_seeds_id_only_when_no_epoch(self):
        self._set_job("job-A", None)
        merged = self._merged()
        assert merged["x-mesh-calling-job-id"] == "job-A"
        assert "x-mesh-calling-claim-epoch" not in merged

    def test_replaces_inherited_pair_no_stale_epoch(self):
        # Inherited calling-* pair from an upstream call, plus THIS handler's
        # own job with NO epoch → the stale inherited epoch must be dropped
        # (both-or-none), not ride along with the new job id.
        TraceContext.set_propagated_headers(
            {
                "x-mesh-calling-job-id": "job-OLD",
                "x-mesh-calling-claim-epoch": "99",
            }
        )
        self._set_job("job-NEW", None)
        merged = self._merged()
        assert merged["x-mesh-calling-job-id"] == "job-NEW"
        assert "x-mesh-calling-claim-epoch" not in merged

    def test_inherited_pair_passes_through_without_active_job(self):
        # No active job → transitive identity: inherited pair flows onward.
        TraceContext.set_propagated_headers(
            {
                "x-mesh-calling-job-id": "job-UP",
                "x-mesh-calling-claim-epoch": "2",
            }
        )
        merged = self._merged()
        assert merged["x-mesh-calling-job-id"] == "job-UP"
        assert merged["x-mesh-calling-claim-epoch"] == "2"


class TestClaimHandlerSeesNoCallingJob:
    """Inside a directly-claimed handler, calling_job() is None — the claim
    dispatcher seeds only the dispatch pair (job context), not calling-*."""

    def teardown_method(self):
        TraceContext.set_propagated_headers({})

    @pytest.mark.asyncio
    async def test_calling_job_none_inside_claim_handler(self):
        seen: dict = {}

        async def handler(**kwargs):
            seen["calling"] = calling_job()
            seen["headers"] = dict(TraceContext.get_propagated_headers())

        d = PythonClaimDispatcher(
            capability="cap",
            instance_id="inst",
            registry_url="http://r:8000",
            handler=handler,
        )
        await d._dispatch(
            {"id": "job-self", "submitted_payload": {}, "claim_epoch": 4}
        )
        # The claim dispatcher seeds the dispatch pair (job context)…
        assert seen["headers"].get("x-mesh-job-id") == "job-self"
        # …but calling_job() reads the calling-* pair → None here.
        assert seen["calling"] is None
