package registry

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"entgo.io/ent/dialect/sql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

// newAuditTestEnv mirrors newSweepTestEnv from sweep_test.go: a fresh in-memory
// Ent client + EntService with status hooks disabled so the only events in the
// table are the audit events we explicitly emit.
func newAuditTestEnv(t *testing.T) (*ent.Client, *EntService, func()) {
	t.Helper()
	client := enttest.Open(t, "sqlite3", "file:audit_"+t.Name()+"?mode=memory&cache=shared&_fk=1")
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	service := NewEntService(entDB, nil, testLogger)
	service.DisableStatusChangeHooks()
	cleanup := func() { client.Close() }
	return client, service, cleanup
}

// seedProducer registers a healthy producer with the given capability/version/tags.
func seedProducer(t *testing.T, client *ent.Client, id string, capabilityName, version string, tags []string) {
	t.Helper()
	ctx := context.Background()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "create agent")

	_, err = client.Capability.Create().
		SetCapability(capabilityName).
		SetFunctionName("do_thing").
		SetVersion(version).
		SetTags(tags).
		SetAgentID(id).
		Save(ctx)
	require.NoError(t, err, "create capability")
}

// seedConsumer registers an empty consumer agent so dependency-resolution rows
// can hang off it via FK without status-hook interference.
func seedConsumer(t *testing.T, client *ent.Client, id string) {
	t.Helper()
	ctx := context.Background()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "create consumer agent")
}

// listAuditEventsFor returns all dependency_resolved/dependency_unresolved events
// for a given consumer, oldest-first, decoded back into AuditTrace.
func listAuditEventsFor(t *testing.T, client *ent.Client, consumerID string) []AuditTrace {
	t.Helper()
	ctx := context.Background()
	events, err := client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ(consumerID))).
		Where(registryevent.EventTypeIn(
			registryevent.EventTypeDependencyResolved,
			registryevent.EventTypeDependencyUnresolved,
		)).
		Order(registryevent.ByTimestamp(sql.OrderAsc())).
		All(ctx)
	require.NoError(t, err)

	out := make([]AuditTrace, 0, len(events))
	for _, e := range events {
		raw, err := json.Marshal(e.Data)
		require.NoError(t, err)
		var tr AuditTrace
		require.NoError(t, json.Unmarshal(raw, &tr))
		out = append(out, tr)
	}
	return out
}

func metadataForDep(spec map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{
		"tools": []interface{}{
			map[string]interface{}{
				"function_name": "consume",
				"dependencies": []interface{}{
					spec,
				},
			},
		},
	}
}

// TestAudit_FourCandidatesMixed exercises the full pipeline: 4 candidates,
// version drops 1, tags drop 1 → expect a 6-stage trace, 1 chosen, 2 evictions
// with correct typed reasons + details.
func TestAudit_FourCandidatesMixed(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "hr-v1", "employee", "1.4.0", []string{"api"})       // version fail
	seedProducer(t, client, "hr-v2", "employee", "2.0.1", []string{"api"})       // winner
	seedProducer(t, client, "legacy-emp", "employee", "2.5.0", []string{"api"})  // candidate
	seedProducer(t, client, "test-emp", "employee", "2.0.0", []string{"sample"}) // tag fail

	meta := metadataForDep(map[string]interface{}{
		"capability": "employee",
		"tags":       []interface{}{"api"},
		"version":    ">=2.0",
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution, "expected a resolution")
	require.NotNil(t, resolutions[0].Trace, "expected a trace")

	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", resolutions))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1, "should emit exactly one audit event")

	tr := events[0]
	assert.Equal(t, "consumer-1", tr.Consumer)
	assert.Equal(t, 0, tr.DepIndex)
	assert.NotNil(t, tr.Chosen)
	assert.Equal(t, "employee", tr.Spec.Capability)
	assert.Equal(t, ">=2.0", tr.Spec.VersionConstraint)
	assert.Equal(t, "none", tr.Spec.SchemaMode)
	assert.Empty(t, tr.PriorChosen, "first emission has no prior_chosen")

	// 6 stages: health, capability_match, tags, version, schema, tiebreaker
	require.Len(t, tr.Stages, 6, "expected 6 stages")
	assert.Equal(t, StageHealth, tr.Stages[0].Stage)
	assert.Equal(t, StageCapabilityMatch, tr.Stages[1].Stage)
	assert.Equal(t, StageTags, tr.Stages[2].Stage)
	assert.Equal(t, StageVersion, tr.Stages[3].Stage)
	assert.Equal(t, StageSchema, tr.Stages[4].Stage)
	assert.Equal(t, StageTiebreaker, tr.Stages[5].Stage)

	// Tag stage evicted test-emp with MissingTag.
	require.Len(t, tr.Stages[2].Evicted, 1)
	tagEv := tr.Stages[2].Evicted[0]
	assert.Equal(t, "test-emp:do_thing", tagEv.ID)
	assert.Equal(t, ReasonMissingTag, tagEv.Reason)

	// Version stage evicted hr-v1 with VersionConstraintFailed.
	require.Len(t, tr.Stages[3].Evicted, 1)
	verEv := tr.Stages[3].Evicted[0]
	assert.Equal(t, "hr-v1:do_thing", verEv.ID)
	assert.Equal(t, ReasonVersionConstraintFailed, verEv.Reason)
	assert.Equal(t, "1.4.0", verEv.Details["version"])
	assert.Equal(t, ">=2.0", verEv.Details["constraint"])

	// Tiebreaker names the algorithm. Chosen carries the colon-form
	// "<agent_id>:<function_name>" identifier matching tr.Chosen.AgentID +
	// tr.Chosen.FunctionName.
	tieb := tr.Stages[5]
	assert.NotEmpty(t, tieb.Chosen)
	assert.Equal(t, TiebreakerHighestScoreFirst, tieb.Reason)
	assert.Equal(t, tr.Chosen.AgentID+":"+tr.Chosen.FunctionName, tieb.Chosen)
}

// TestAudit_SingleCandidate_NoEmit asserts gating: a single candidate with no
// flip means no event is emitted.
func TestAudit_SingleCandidate_NoEmit(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "lonely", "ping", "1.0.0", nil)

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
	})
	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", resolutions))

	events := listAuditEventsFor(t, client, "consumer-1")
	assert.Empty(t, events, "single-candidate forced choice should not emit")
}

// TestAudit_SameOutcomeTwice asserts the second identical resolution is gated
// out by the canonical-hash dedupe step. The first multi-candidate decision
// emits; the second one — same chosen, same evicted set, same kept set — is
// suppressed so the steady-state heartbeat loop doesn't fill the audit log.
func TestAudit_SameOutcomeTwice(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p1", "ping", "1.0.0", []string{"api"})
	seedProducer(t, client, "p2", "ping", "1.0.0", []string{"api"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"api"},
	})

	// First call: 2 candidates, multi-candidate gate fires → emit.
	res := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	// Second call: identical state → canonical hash matches the prior trace, so
	// emission is suppressed. Total events stays at 1.
	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res2))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1, "identical second emission must be deduped")
}

// TestAudit_OutcomeFlips asserts a producer flip causes prior_chosen to populate.
func TestAudit_OutcomeFlips(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	// v1 is the only producer → first resolution picks it, but is single-candidate so doesn't emit.
	seedProducer(t, client, "v1", "ping", "1.0.0", nil)

	meta := metadataForDep(map[string]interface{}{"capability": "ping"})
	res := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	// Now add v2; v2 outscores v1 because of an alphabetical-ish or first-registered
	// tiebreaker — actually they tie at score 0, but resolveSingle picks the
	// top of the sorted-by-score list which is stable. To force a flip, take v1
	// out of healthy state.
	ctx := context.Background()
	_, err := client.Agent.UpdateOneID("v1").SetStatus(agent.StatusUnhealthy).Save(ctx)
	require.NoError(t, err)
	seedProducer(t, client, "v2", "ping", "1.0.0", nil)

	// Resolve again — v1 unhealthy, v2 picked. Two candidates entered → emit.
	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.NotNil(t, res2[0].Resolution)
	assert.Equal(t, "v2", res2[0].Resolution.AgentID)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res2))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.NotEmpty(t, events)
	last := events[len(events)-1]
	assert.Equal(t, "v2", last.Chosen.AgentID)
	// v1 had its eviction recorded in the health stage (now first).
	healthStage := last.Stages[0]
	require.Equal(t, StageHealth, healthStage.Stage)
	require.Len(t, healthStage.Evicted, 1)
	assert.Equal(t, "v1:do_thing", healthStage.Evicted[0].ID)
	assert.Equal(t, ReasonUnhealthy, healthStage.Evicted[0].Reason)
}

// TestAudit_NoCandidatesUnresolved asserts unresolved events get emitted with
// a partial trace when at least one stage saw candidates that were filtered out.
func TestAudit_NoCandidatesUnresolved(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	// Two producers, both with the wrong tag — every candidate gets evicted.
	seedProducer(t, client, "wrong1", "ping", "1.0.0", []string{"foo"})
	seedProducer(t, client, "wrong2", "ping", "1.0.0", []string{"foo"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"required"},
	})
	res := service.ResolveAllDependenciesIndexed(meta)
	require.Nil(t, res[0].Resolution)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1)

	tr := events[0]
	assert.Nil(t, tr.Chosen, "unresolved trace must not have chosen")

	// Find the corresponding event row to assert event_type.
	ctx := context.Background()
	all, err := client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ("consumer-1"))).
		All(ctx)
	require.NoError(t, err)
	require.Len(t, all, 1)
	assert.Equal(t, registryevent.EventTypeDependencyUnresolved, all[0].EventType)
}

// TestAudit_SingleCandidateEvictedEmitsUnresolved asserts that when exactly one
// producer enters the pipeline and gets evicted, an unresolved event is emitted
// even though IsInteresting()=false (only a single candidate). This is the
// canonical operator-debugging signal: "I had a candidate but it didn't pass
// [stage]". Suppressing it would leave operators with no audit trail of why
// their dependency stayed unresolved.
func TestAudit_SingleCandidateEvictedEmitsUnresolved(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	// Single producer with the wrong tag → evicted at the tag stage. Only one
	// candidate enters the pipeline, so IsInteresting() returns false.
	seedProducer(t, client, "rogue", "ping", "1.0.0", []string{"foo"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"required"},
	})

	res := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res, 1)
	require.Nil(t, res[0].Resolution, "single rogue candidate should not resolve")

	// Sanity check: trace must show the eviction but NOT be IsInteresting()
	// (the new gating rule is what carries the day here, not the existing
	// multi-candidate path).
	require.NotNil(t, res[0].Trace)
	assert.False(t, res[0].Trace.IsInteresting(),
		"precondition: single-candidate trace must not be IsInteresting() for this test to exercise the new gating")

	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1, "single-candidate eviction must still emit an unresolved event for operator visibility")

	tr := events[0]
	assert.Nil(t, tr.Chosen, "unresolved trace must not have chosen")

	// The eviction details must be present so the operator can diagnose.
	foundEviction := false
	for _, st := range tr.Stages {
		if len(st.Evicted) > 0 {
			foundEviction = true
			break
		}
	}
	assert.True(t, foundEviction, "trace must record at least one eviction")

	// And the persisted row's event_type must be dependency_unresolved.
	ctx := context.Background()
	rows, err := client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ("consumer-1"))).
		All(ctx)
	require.NoError(t, err)
	require.Len(t, rows, 1)
	assert.Equal(t, registryevent.EventTypeDependencyUnresolved, rows[0].EventType)
}

// TestAuditTrace_RoundTrip asserts AuditTrace serializes and deserializes cleanly.
func TestAuditTrace_RoundTrip(t *testing.T) {
	in := AuditTrace{
		Consumer: "c1",
		DepIndex: 2,
		Spec: AuditSpec{
			Capability:        "thing",
			Tags:              []string{"api", "+fast"},
			VersionConstraint: ">=1.0",
			SchemaMode:        "none",
		},
		Stages: []AuditStage{
			{
				Stage: StageCapabilityMatch,
				Kept:  []string{"a", "b", "c"},
			},
			{
				Stage: StageTags,
				Kept:  []string{"a", "b"},
				Evicted: []AuditEvicted{
					{ID: "c", Reason: ReasonMissingTag, Details: map[string]interface{}{"missing": []string{"api"}}},
				},
			},
			{
				Stage:  StageTiebreaker,
				Kept:   []string{"a", "b"},
				Chosen: "a",
				Reason: TiebreakerHighestScoreFirst,
			},
		},
		Chosen: &AuditChosen{
			AgentID:      "a",
			Endpoint:     "http://a:8080",
			FunctionName: "do_it",
		},
		PriorChosen: "b",
	}

	raw, err := json.Marshal(in)
	require.NoError(t, err)
	var out AuditTrace
	require.NoError(t, json.Unmarshal(raw, &out))

	assert.Equal(t, in.Consumer, out.Consumer)
	assert.Equal(t, in.DepIndex, out.DepIndex)
	assert.Equal(t, in.Spec, out.Spec)
	require.Len(t, out.Stages, 3)
	assert.Equal(t, ReasonMissingTag, out.Stages[1].Evicted[0].Reason)
	assert.Equal(t, "a", out.Chosen.AgentID)
	assert.Equal(t, "b", out.PriorChosen)
	assert.True(t, in.IsInteresting())
}

// TestAuditTrace_IsInteresting_GatingMath sanity-checks the gating predicate.
func TestAuditTrace_IsInteresting_GatingMath(t *testing.T) {
	cases := []struct {
		name string
		tr   AuditTrace
		want bool
	}{
		{
			name: "empty",
			tr:   AuditTrace{},
			want: false,
		},
		{
			name: "single_candidate_through_all_stages",
			tr: AuditTrace{
				Stages: []AuditStage{
					{Stage: StageCapabilityMatch, Kept: []string{"a"}},
					{Stage: StageTiebreaker, Kept: []string{"a"}, Chosen: "a"},
				},
			},
			want: false,
		},
		{
			name: "two_candidates_at_capability_match",
			tr: AuditTrace{
				Stages: []AuditStage{
					{Stage: StageCapabilityMatch, Kept: []string{"a", "b"}},
				},
			},
			want: true,
		},
		{
			name: "one_kept_one_evicted",
			tr: AuditTrace{
				Stages: []AuditStage{
					{Stage: StageTags, Kept: []string{"a"}, Evicted: []AuditEvicted{{ID: "b"}}},
				},
			},
			want: true,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.want, tc.tr.IsInteresting())
		})
	}
}

// --- canonical-hash dedupe tests --------------------------------------------

// makeBaseTrace returns a 6-stage trace with one eviction and a chosen
// producer. Used as the seed for hash-equivalence assertions. Per-stage
// candidate identifiers use the "<agent_id>:<function_name>" format.
func makeBaseTrace() AuditTrace {
	return AuditTrace{
		Consumer: "consumer-1",
		DepIndex: 0,
		Spec: AuditSpec{
			Capability:        "employee",
			Tags:              []string{"api"},
			VersionConstraint: ">=2.0",
			SchemaMode:        "none",
		},
		Stages: []AuditStage{
			{Stage: StageCapabilityMatch, Kept: []string{"hr-v2:do_thing", "legacy-emp:do_thing", "test-emp:do_thing"}},
			{
				Stage: StageTags,
				Kept:  []string{"hr-v2:do_thing", "legacy-emp:do_thing"},
				Evicted: []AuditEvicted{
					{ID: "test-emp:do_thing", Reason: ReasonMissingTag, Details: map[string]interface{}{"missing": []string{"api"}}},
				},
			},
			{Stage: StageVersion, Kept: []string{"hr-v2:do_thing", "legacy-emp:do_thing"}},
			{Stage: StageSchema, Kept: []string{"hr-v2:do_thing", "legacy-emp:do_thing"}},
			{Stage: StageHealth, Kept: []string{"hr-v2:do_thing", "legacy-emp:do_thing"}},
			{
				Stage:  StageTiebreaker,
				Kept:   []string{"hr-v2:do_thing", "legacy-emp:do_thing"},
				Chosen: "hr-v2:do_thing",
				Reason: TiebreakerHighestScoreFirst,
			},
		},
		Chosen: &AuditChosen{
			AgentID:      "hr-v2",
			Endpoint:     "http://hr-v2:8080",
			FunctionName: "do_thing",
		},
	}
}

// TestCanonicalTraceHash_Stable: hashing the same trace twice yields the same
// hex digest. Sanity check on determinism (Go's encoding/json must be
// repeatable across calls in the same process).
func TestCanonicalTraceHash_Stable(t *testing.T) {
	tr := makeBaseTrace()
	h1, err := canonicalTraceHash(&tr)
	require.NoError(t, err)
	h2, err := canonicalTraceHash(&tr)
	require.NoError(t, err)
	assert.Equal(t, h1, h2)
	assert.Len(t, h1, 64, "sha256 hex digest must be 64 chars")
}

// TestCanonicalTraceHash_OrderInsensitive: Kept and Evicted lists in different
// orders canonicalize to the same hash. The resolver normally emits stable
// ordering but we shouldn't depend on that.
func TestCanonicalTraceHash_OrderInsensitive(t *testing.T) {
	a := makeBaseTrace()
	b := makeBaseTrace()
	// Swap kept ordering in tiebreak stage.
	b.Stages[5].Kept = []string{"legacy-emp:do_thing", "hr-v2:do_thing"}
	// Swap tag ordering on the spec.
	a.Spec.Tags = []string{"api"}
	b.Spec.Tags = []string{"api"}

	ha, err := canonicalTraceHash(&a)
	require.NoError(t, err)
	hb, err := canonicalTraceHash(&b)
	require.NoError(t, err)
	assert.Equal(t, ha, hb, "kept-order swap must not change hash")
}

// TestCanonicalTraceHash_PriorChosenIgnored: PriorChosen is metadata and must
// not affect the hash. Otherwise repeated emissions would never dedupe (every
// emission's PriorChosen reflects the previous emission's Chosen).
func TestCanonicalTraceHash_PriorChosenIgnored(t *testing.T) {
	a := makeBaseTrace()
	b := makeBaseTrace()
	b.PriorChosen = "some-old-id"

	ha, err := canonicalTraceHash(&a)
	require.NoError(t, err)
	hb, err := canonicalTraceHash(&b)
	require.NoError(t, err)
	assert.Equal(t, ha, hb)
}

// TestCanonicalTraceHash_DifferentChosen: changing the Chosen producer must
// produce a different hash so the dedupe step doesn't suppress flips.
func TestCanonicalTraceHash_DifferentChosen(t *testing.T) {
	a := makeBaseTrace()
	b := makeBaseTrace()
	b.Chosen.AgentID = "legacy-emp"
	b.Stages[5].Chosen = "legacy-emp:do_thing"

	ha, err := canonicalTraceHash(&a)
	require.NoError(t, err)
	hb, err := canonicalTraceHash(&b)
	require.NoError(t, err)
	assert.NotEqual(t, ha, hb)
}

// TestCanonicalTraceHash_DifferentEvictedSet: changing the evicted set (e.g.,
// because a producer just appeared or disappeared) must change the hash.
func TestCanonicalTraceHash_DifferentEvictedSet(t *testing.T) {
	a := makeBaseTrace()
	b := makeBaseTrace()
	b.Stages[1].Evicted = append(b.Stages[1].Evicted, AuditEvicted{
		ID: "new-bad:do_thing", Reason: ReasonMissingTag,
	})

	ha, err := canonicalTraceHash(&a)
	require.NoError(t, err)
	hb, err := canonicalTraceHash(&b)
	require.NoError(t, err)
	assert.NotEqual(t, ha, hb)
}

// TestAudit_DedupeSuppressesIdenticalFlip exercises the full emission path:
// after a flip, a second identical re-resolution should NOT emit. The first
// flip produces an event whose Chosen=newWinner; the second resolution
// produces an identical trace, so dedupe kicks in.
func TestAudit_DedupeSuppressesIdenticalFlip(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p1", "ping", "1.0.0", []string{"api"})
	seedProducer(t, client, "p2", "ping", "1.0.0", []string{"api"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"api"},
	})

	// First resolution: 2 candidates → emit.
	res1 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res1))

	// Second resolution: same world state → dedupe.
	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res2))

	// Third resolution: still the same → dedupe.
	res3 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res3))

	events := listAuditEventsFor(t, client, "consumer-1")
	assert.Len(t, events, 1, "only the first multi-candidate decision should be persisted; identical re-runs are deduped")
}

// TestAudit_DedupeAllowsRealChange asserts that a *real* change in the trace
// (e.g., a new producer appears and gets evicted) bypasses dedupe.
func TestAudit_DedupeAllowsRealChange(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p1", "ping", "1.0.0", []string{"api"})
	seedProducer(t, client, "p2", "ping", "1.0.0", []string{"api"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"api"},
	})

	// First emission.
	res1 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res1))

	// New producer appears with the wrong tag — gets evicted, eviction set
	// changes, hash changes, dedupe should NOT suppress.
	seedProducer(t, client, "p3-bad", "ping", "1.0.0", []string{"internal"})

	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res2))

	events := listAuditEventsFor(t, client, "consumer-1")
	assert.Len(t, events, 2, "new evicted producer must change the hash and produce a fresh event")

	// And the latest event records the eviction.
	last := events[len(events)-1]
	tagStage := last.Stages[2]
	require.Equal(t, StageTags, tagStage.Stage)
	require.NotEmpty(t, tagStage.Evicted)
	foundBad := false
	for _, ev := range tagStage.Evicted {
		if ev.ID == "p3-bad:do_thing" {
			foundBad = true
			break
		}
	}
	assert.True(t, foundBad, "p3-bad:do_thing should appear in the second event's tag-stage evictions")
}

// TestAudit_DisambiguatesFunctionsOnSameAgent reproduces the issue #836
// display-bug scenario: a single agent has two functions that both provide
// the same capability with different tags; a consumer dep matches only one.
// The trace must show distinct "<agent>:<func>" identifiers in the kept and
// evicted lists, not the bare agent ID for both.
func TestAudit_DisambiguatesFunctionsOnSameAgent(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")

	ctx := context.Background()
	// Single agent with two functions providing capability "info".
	_, err := client.Agent.Create().
		SetID("system-agent").
		SetName("system-agent").
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err)

	_, err = client.Capability.Create().
		SetCapability("info").
		SetFunctionName("fetch_system_overview").
		SetVersion("1.0.0").
		SetTags([]string{"system", "general", "monitoring"}).
		SetAgentID("system-agent").
		Save(ctx)
	require.NoError(t, err)

	_, err = client.Capability.Create().
		SetCapability("info").
		SetFunctionName("analyze_storage_and_os").
		SetVersion("1.0.0").
		SetTags([]string{"system", "disk", "os"}).
		SetAgentID("system-agent").
		Save(ctx)
	require.NoError(t, err)

	// Consumer needs [system, disk] — only analyze_storage_and_os matches.
	meta := metadataForDep(map[string]interface{}{
		"capability": "info",
		"tags":       []interface{}{"system", "disk"},
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution, "expected analyze_storage_and_os to resolve")
	assert.Equal(t, "system-agent", resolutions[0].Resolution.AgentID)
	assert.Equal(t, "analyze_storage_and_os", resolutions[0].Resolution.FunctionName)

	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", resolutions))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1)
	tr := events[0]

	// Tag stage: kept=analyze_storage_and_os, evicted=fetch_system_overview.
	// Both refer to the same agent — only the function-name suffix
	// distinguishes them, which is the whole point of the fix.
	tagStage := tr.Stages[2]
	assert.Equal(t, StageTags, tagStage.Stage)
	require.Len(t, tagStage.Kept, 1, "exactly one function survives the tag filter")
	assert.Equal(t, "system-agent:analyze_storage_and_os", tagStage.Kept[0])
	require.Len(t, tagStage.Evicted, 1, "exactly one function is evicted")
	assert.Equal(t, "system-agent:fetch_system_overview", tagStage.Evicted[0].ID)
	assert.Equal(t, ReasonMissingTag, tagStage.Evicted[0].Reason)

	// Tiebreaker chosen carries the colon-form too.
	tieb := tr.Stages[5]
	assert.Equal(t, "system-agent:analyze_storage_and_os", tieb.Chosen)

	// Top-level Chosen.AgentID stays bare (consumer-facing producer ID).
	assert.Equal(t, "system-agent", tr.Chosen.AgentID)
	assert.Equal(t, "analyze_storage_and_os", tr.Chosen.FunctionName)
}

// TestAudit_UnresolvedToResolved_EmitsEvenWithSingleCandidate covers the gap
// where a dep slot transitions from "no providers" to "exactly one provider":
// without explicit handling, the resolved-branch gating would short-circuit
// (single candidate is not "interesting", priorChosen is "" because no prior
// *resolved* event exists). Operators want to see this transition, so the
// emitter must consult the most recent event of either type and treat
// unresolved→resolved as a flip.
func TestAudit_UnresolvedToResolved_EmitsEvenWithSingleCandidate(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	ctx := context.Background()
	seedConsumer(t, client, "consumer-1")

	// Step 1: seed two producers with the wrong tag. Both enter the pipeline,
	// both get evicted at the tag stage → IsInteresting=true on the unresolved
	// branch, so a dependency_unresolved event lands in the table.
	seedProducer(t, client, "wrong1", "ping", "1.0.0", []string{"foo"})
	seedProducer(t, client, "wrong2", "ping", "1.0.0", []string{"foo"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"required"},
	})

	res1 := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res1, 1)
	require.Nil(t, res1[0].Resolution, "no candidate should resolve")
	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res1))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1, "first resolution should emit one unresolved event")

	// Confirm the seeded event is indeed unresolved (the row, not just the trace).
	rows, err := client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ("consumer-1"))).
		Order(registryevent.ByTimestamp(sql.OrderAsc())).
		All(ctx)
	require.NoError(t, err)
	require.Len(t, rows, 1)
	require.Equal(t, registryevent.EventTypeDependencyUnresolved, rows[0].EventType)

	// Step 2: drop the bad-tag producers and add a single producer that matches.
	// Resolution will see exactly one candidate that survives every stage, so
	// IsInteresting()=false and there's no prior *resolved* event for this dep
	// slot — without the unresolved→resolved flip handling, the emit would
	// short-circuit and the operator would never see the dep flip back to OK.
	_, err = client.Capability.Delete().
		Where(capability.HasAgentWith(agent.IDIn("wrong1", "wrong2"))).
		Exec(ctx)
	require.NoError(t, err)
	_, err = client.Agent.Delete().Where(agent.IDIn("wrong1", "wrong2")).Exec(ctx)
	require.NoError(t, err)

	seedProducer(t, client, "good", "ping", "1.0.0", []string{"required"})

	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res2, 1)
	require.NotNil(t, res2[0].Resolution, "single matching candidate should resolve")
	assert.Equal(t, "good", res2[0].Resolution.AgentID)
	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res2))

	// Confirm: a resolved event is now persisted on top of the unresolved one.
	rows, err = client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ("consumer-1"))).
		Order(registryevent.ByTimestamp(sql.OrderAsc())).
		All(ctx)
	require.NoError(t, err)
	require.Len(t, rows, 2, "unresolved→resolved must emit, even with a single candidate")
	assert.Equal(t, registryevent.EventTypeDependencyUnresolved, rows[0].EventType)
	assert.Equal(t, registryevent.EventTypeDependencyResolved, rows[1].EventType)
}

// TestAudit_UnresolvedFloodIsDeduped guards against the audit-log flooding
// scenario described in #547 review B1: with the relaxed `hasEvictions`
// gating rule, a transient unhealthy producer in the capability query results
// becomes a stage-eviction on every heartbeat. Without the canonical-hash
// dedupe also covering unresolved→unresolved sequences, every heartbeat would
// emit a fresh dependency_unresolved event.
//
// Setup: a single rogue producer, evicted at the tag stage, no resolution.
// Run resolve+store N times. Expect exactly ONE unresolved event in the
// audit log — the first one — with all N-1 follow-ups suppressed by dedupe.
func TestAudit_UnresolvedFloodIsDeduped(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	// Single producer with the wrong tag → evicted at the tag stage.
	// hasEvictions=true so the gating allows emit; without dedupe the same
	// trace would emit on every heartbeat.
	seedProducer(t, client, "rogue", "ping", "1.0.0", []string{"foo"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"required"},
	})

	ctx := context.Background()

	// Heartbeat #1: emits the first unresolved event.
	res1 := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res1, 1)
	require.Nil(t, res1[0].Resolution)
	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res1))

	// Heartbeats #2..#5: identical world state → identical trace → dedupe.
	for i := 0; i < 4; i++ {
		resN := service.ResolveAllDependenciesIndexed(meta)
		require.Len(t, resN, 1)
		require.Nil(t, resN[0].Resolution)
		require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", resN))
	}

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 1,
		"unresolved-flood guard: only the first identical unresolved trace should be persisted; heartbeats with the same trace must be deduped")

	// Confirm the persisted event is unresolved (not accidentally resolved).
	rows, err := client.RegistryEvent.Query().
		Where(registryevent.HasAgentWith(agent.IDEQ("consumer-1"))).
		Order(registryevent.ByTimestamp(sql.OrderAsc())).
		All(ctx)
	require.NoError(t, err)
	require.Len(t, rows, 1)
	assert.Equal(t, registryevent.EventTypeDependencyUnresolved, rows[0].EventType)
}
