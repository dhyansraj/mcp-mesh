package registry

// Coverage for MeshJob claim gating on the transitive required-dependency
// predicate (issue #1249 follow-up scope). A claim worker must not claim a job
// for a capability that is currently UNAVAILABLE under the required-deps
// predicate — otherwise a purely topological outage (a required dep down) burns
// max_retries as the handler fails on the missing dep. A gated claim leaves the
// job queued (owner=NULL, attempt_count unchanged, no lease) so it self-heals on
// a later poll once the dependency recovers.
//
// Reuses newJobsEndpointTestEnvWithService + seedJob (ent_handlers_jobs_extended_test.go)
// and regAgent / setAgentStatus / getCap (availability_test.go).

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/job"
)

// ---------- gate: unresolved required dep blocks the claim ----------

func TestClaimNextJob_GatedByUnresolvedRequiredDep(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	// Producer of "render" declares a REQUIRED dep on "weather", which no agent
	// provides yet → "render" is unavailable under the predicate.
	regAgent(t, service, "worker", "render", depSpec("weather", true))
	seed := seedJob(t, service, "job-gated", "render", nil)

	// Claim is gated: no job returned, and the row is left completely untouched.
	claimed, err := service.ClaimNextJob(ctx, "render", "worker")
	require.NoError(t, err)
	assert.Nil(t, claimed, "claim must be gated while the required dep is unresolved")

	after, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusWorking, after.Status, "gated job stays queued (working)")
	assert.Nil(t, after.OwnerInstanceID, "gated job keeps owner=NULL")
	assert.Equal(t, 0, after.AttemptCount, "gated claim must NOT burn an attempt")
	assert.Equal(t, int64(0), after.ClaimEpoch, "gated claim must NOT mint an epoch")
	assert.Nil(t, after.LeaseExpiresAt, "gated claim must NOT set a lease")

	// The dependency recovers: a provider of "weather" registers. The claim
	// worker polls again (its next tick) and now claims normally — self-healing
	// via the existing poll cadence, no operator intervention.
	regAgent(t, service, "weather-agent", "weather")

	claimed2, err := service.ClaimNextJob(ctx, "render", "worker")
	require.NoError(t, err)
	require.NotNil(t, claimed2, "claim must succeed once the required dep resolves")
	assert.Equal(t, seed.ID, claimed2.ID)
	assert.Equal(t, 1, claimed2.AttemptCount, "the recovering claim is the FIRST attempt")
	assert.Equal(t, int64(1), claimed2.ClaimEpoch, "first successful claim mints epoch 1")
}

// ---------- gate: required dep provider goes unhealthy mid-life ----------

func TestClaimNextJob_GatedWhenRequiredProviderUnhealthy(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	regAgent(t, service, "dep-agent", "weather")
	regAgent(t, service, "worker", "render", depSpec("weather", true))
	seed := seedJob(t, service, "job-provider-down", "render", nil)

	// Provider healthy → claim proceeds.
	claimed := claimVia(t, service, "render", "worker")
	assert.Equal(t, seed.ID, claimed.ID)

	// Reset the row to pending and take the required provider unhealthy.
	_, err := service.entDB.Job.UpdateOneID(seed.ID).
		ClearOwnerInstanceID().
		SetStatus(job.StatusWorking).
		SetAttemptCount(0).
		Save(ctx)
	require.NoError(t, err)
	setAgentStatus(t, service, "dep-agent", agent.StatusUnhealthy)

	blocked, err := service.ClaimNextJob(ctx, "render", "worker")
	require.NoError(t, err)
	assert.Nil(t, blocked, "claim must be gated while the required provider is unhealthy")

	after, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, 0, after.AttemptCount, "gated claim leaves attempt_count untouched")
}

// ---------- byte-identical: capability with no required edges ----------

func TestClaimNextJob_NoRequiredEdges_ClaimsNormally(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	// Registered producer of "render" with NO required deps → the gate short-
	// circuits (no provider resolution) and the claim behaves exactly as before.
	regAgent(t, service, "worker", "render")
	seed := seedJob(t, service, "job-plain", "render", nil)

	claimed, err := service.ClaimNextJob(ctx, "render", "worker")
	require.NoError(t, err)
	require.NotNil(t, claimed)
	assert.Equal(t, seed.ID, claimed.ID)
	assert.Equal(t, 1, claimed.AttemptCount)
	assert.Equal(t, int64(1), claimed.ClaimEpoch)
	require.NotNil(t, claimed.OwnerInstanceID)
	assert.Equal(t, "worker", *claimed.OwnerInstanceID)
	assert.NotNil(t, claimed.LeaseExpiresAt)
}

// ---------- byte-identical: unowned/anonymous claimer is never gated ----------

func TestClaimNextJob_UnownedCapability_NotGated(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	// No agent/capability registered for "render" at all: the claimer owns no
	// matching capability row, so there are no required edges to evaluate and
	// the pre-#1249 claim behavior is preserved byte-for-byte.
	seed := seedJob(t, service, "job-anon", "render", nil)

	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed, "an unowned capability must not be gated")
	assert.Equal(t, seed.ID, claimed.ID)
	assert.Equal(t, 1, claimed.AttemptCount)
}

// ---------- fail-open: a gate-query error must not block the claim ----------

func TestCapabilityUnavailableForClaim_QueryError_FailsOpen(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// render has an unresolved REQUIRED dep, so it is genuinely gated...
	regAgent(t, service, "worker", "render", depSpec("weather", true))
	live := service.capabilityUnavailableForClaim(context.Background(), "worker", "render", newAvailEval())
	require.NotEmpty(t, live, "precondition: render must be gated while weather is unresolved")

	// ...but a failed gate query (forced here via an already-cancelled context)
	// must FAIL OPEN — return "" so the live worker degrades to pre-#1249 ungated
	// behavior rather than being starved by a transient DB error.
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	got := service.capabilityUnavailableForClaim(cancelled, "worker", "render", newAvailEval())
	assert.Equal(t, "", got, "a gate-query error must fail open (ungated)")
}

// ---------- memoization across the transitive DAG in one gate eval ----------

// The claimed capability sits atop a diamond of required deps (render→B,
// render→C, B→D, C→D). One gate evaluation shares a single availEval, so the
// tail D is evaluated exactly once — the O(paths) → O(nodes) collapse, mirroring
// TestAvailability_MemoEvaluatesEachNodeOnce for the claim path.
func TestCapabilityUnavailableForClaim_MemoizesDiamond(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	regAgent(t, service, "agent-d", "capD")
	regAgent(t, service, "agent-b", "capB", depSpec("capD", true))
	regAgent(t, service, "agent-c", "capC", depSpec("capD", true))
	regAgent(t, service, "worker", "render", depSpec("capB", true), depSpec("capC", true))

	eval := newAvailEval()
	reason := service.capabilityUnavailableForClaim(ctx, "worker", "render", eval)
	assert.Equal(t, "", reason, "render should be available while the whole diamond is healthy")

	for _, k := range []string{
		availKey("worker", "render"),
		availKey("agent-b", "capB"),
		availKey("agent-c", "capC"),
		availKey("agent-d", "capD"),
	} {
		_, ok := eval.memo[k]
		assert.Truef(t, ok, "expected memo entry for %q", k)
	}
	assert.Equalf(t, 4, len(eval.memo),
		"expected exactly 4 memoized nodes (tail capD evaluated once), got %d: %v", len(eval.memo), eval.memo)

	// Break the shared tail: render must now be gated, naming a broken edge.
	setAgentStatus(t, service, "agent-d", agent.StatusUnhealthy)
	broken := service.capabilityUnavailableForClaim(ctx, "worker", "render", newAvailEval())
	require.NotEmpty(t, broken, "render must be gated when the shared tail capD is down")
	assert.True(t, strings.Contains(broken, "capB") || strings.Contains(broken, "capC"),
		"gate reason should name a broken required edge, got %q", broken)
}
