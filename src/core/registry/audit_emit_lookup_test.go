package registry

// Coverage for #1582 — the audit emitter's prior-trace lookups.
//
// Before the fix, emitAuditEventIfInteresting issued TWO queries per
// dependency (last resolved event, then last event of either kind), each
// pulling the newest 64 registry_events rows and decoding their JSON payloads
// in Go. A full heartbeat from an agent with N dependencies therefore paid 2N
// unindexed scans of a table capped at 100k rows — on the path that every 202
// triggers fleet-wide.
//
// Both lookups are always for the same (consumer, function) and differ only in
// their event-type filter, so each now runs ONCE per function and is bucketed
// by dep_index for every dependency of that function: 2N queries per
// dependency became 2 per function. They stay separate queries because they
// need separate LIMIT windows — a merged window is scoped to
// (consumer, function), not to dep_index, so sibling deps' unresolved events
// could evict a slot's own last resolved event and swallow a producer flip.
// The gating semantics that depend on the distinction (flip detection uses the
// newest *resolved* event; dedupe and the unresolved→resolved transition use
// the newest event of either kind) are covered by audit_resolver_test.go.

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	entsql "entgo.io/ent/dialect/sql"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
)

// newInstrumentedAuditEnv is newAuditTestEnv plus a statement recorder.
func newInstrumentedAuditEnv(t *testing.T) (*ent.Client, *EntService, *stmtRecorder, func()) {
	t.Helper()

	dsn := "file:auditq_" + t.Name() + "?mode=memory&cache=shared&_fk=1&_busy_timeout=5000"
	drv, err := entsql.Open("sqlite3", dsn)
	require.NoError(t, err, "open test sqlite driver")
	db := drv.DB()
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	rec := &stmtRecorder{}
	client := enttest.NewClient(t, enttest.WithOptions(
		ent.Driver(drv),
		ent.Log(rec.log),
		ent.Debug(),
	))
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	service := NewEntService(&database.EntDatabase{Client: client}, nil, testLogger)
	service.DisableStatusChangeHooks()

	return client, service, rec, func() { client.Close() }
}

// metadataForDeps builds a single-function tool metadata block carrying
// several dependencies, so one StoreDependencyResolutions call exercises the
// N-dependencies-per-function shape the fix targets.
func metadataForDeps(functionName string, caps ...string) map[string]interface{} {
	deps := make([]interface{}, 0, len(caps))
	for _, c := range caps {
		deps = append(deps, map[string]interface{}{"capability": c})
	}
	return map[string]interface{}{
		"tools": []interface{}{
			map[string]interface{}{
				"function_name": functionName,
				"dependencies":  deps,
			},
		},
	}
}

// TestAudit_PriorTraceLookup_TwoQueriesPerFunction pins the query count: three
// dependencies on one function must produce exactly two registry_events reads
// (one per event-type set), not six.
func TestAudit_PriorTraceLookup_TwoQueriesPerFunction(t *testing.T) {
	client, service, rec, cleanup := newInstrumentedAuditEnv(t)
	defer cleanup()
	ctx := context.Background()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p-a", "cap_a", "1.0.0", nil)
	seedProducer(t, client, "p-b", "cap_b", "1.0.0", nil)
	seedProducer(t, client, "p-c", "cap_c", "1.0.0", nil)

	meta := metadataForDeps("consume", "cap_a", "cap_b", "cap_c")
	res := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res, 3, "all three deps must reach the emitter")

	rec.start()
	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res))
	stmts := rec.stop()

	reads := countMatching(stmts, "FROM `registry_events`")
	assert.Len(t, reads, 2,
		"the prior-trace lookups must run once per (consumer, function) each, not "+
			"twice per dependency (#1582); got:\n%s", strings.Join(reads, "\n"))

	// Both event-type sets must still be queried separately — a merged window
	// would let sibling deps evict a slot's last resolved event.
	assert.Len(t, countMatching(stmts, "FROM `registry_events`", "`event_type` = ?"), 1,
		"the resolved-only lookup must keep its own LIMIT window")
	assert.Len(t, countMatching(stmts, "FROM `registry_events`", "`event_type` IN (?, ?)"), 1,
		"the both-types lookup must keep its own LIMIT window")
}

// TestAudit_PriorTraceLookup_PerFunctionNotPerAgent is the counterpart: the
// memo is keyed by function, so two functions get their own pair of lookups
// (the queries are function-scoped and cannot be shared across functions) —
// four reads for two functions with two deps each, not eight.
func TestAudit_PriorTraceLookup_PerFunctionNotPerAgent(t *testing.T) {
	client, service, rec, cleanup := newInstrumentedAuditEnv(t)
	defer cleanup()
	ctx := context.Background()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p-a", "cap_a", "1.0.0", nil)
	seedProducer(t, client, "p-b", "cap_b", "1.0.0", nil)

	meta := map[string]interface{}{
		"tools": []interface{}{
			map[string]interface{}{
				"function_name": "consume_one",
				"dependencies": []interface{}{
					map[string]interface{}{"capability": "cap_a"},
					map[string]interface{}{"capability": "cap_b"},
				},
			},
			map[string]interface{}{
				"function_name": "consume_two",
				"dependencies": []interface{}{
					map[string]interface{}{"capability": "cap_a"},
					map[string]interface{}{"capability": "cap_b"},
				},
			},
		},
	}
	res := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res, 4)

	rec.start()
	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res))
	stmts := rec.stop()

	reads := countMatching(stmts, "FROM `registry_events`")
	assert.Len(t, reads, 4,
		"two prior-trace lookups per function, not per dependency (#1582); got:\n%s",
		strings.Join(reads, "\n"))
}

// seedAuditEvent inserts an audit event row directly so a test can construct a
// specific prior-emission history without driving resolution N times.
func seedAuditEvent(
	t *testing.T,
	client *ent.Client,
	consumerID, functionName string,
	depIndex int,
	eventType registryevent.EventType,
	chosenAgentID string,
	ts time.Time,
) {
	t.Helper()
	trace := &AuditTrace{
		Consumer: consumerID,
		DepIndex: depIndex,
		Spec:     AuditSpec{Capability: "cap_0", SchemaMode: "none"},
		Stages:   []AuditStage{{Stage: StageHealth, Kept: []string{chosenAgentID + ":do_thing"}}},
	}
	if chosenAgentID != "" {
		trace.Chosen = &AuditChosen{AgentID: chosenAgentID, FunctionName: "do_thing"}
	}
	raw, err := json.Marshal(trace)
	require.NoError(t, err)
	var data map[string]interface{}
	require.NoError(t, json.Unmarshal(raw, &data))

	_, err = client.RegistryEvent.Create().
		SetEventType(eventType).
		SetAgentID(consumerID).
		SetFunctionName(functionName).
		SetTimestamp(ts).
		SetData(data).
		Save(context.Background())
	require.NoError(t, err, "seed audit event dep=%d type=%s", depIndex, eventType)
}

// TestAudit_SiblingUnresolvedFloodDoesNotHideFlip is the regression test for
// the reason the two lookups stay separate.
//
// A merged LIMIT-64 window is scoped to (consumer, function), NOT to
// dep_index. On a function whose other dep slots are unresolved and flapping,
// their events push dep 0's last `dependency_resolved` out of the shared
// window. dep 0 then resolves to a different producer with a single candidate:
// `IsInteresting()` is false, so the emission hinges entirely on the flip
// check. With a merged window there is no prior chosen AND no surviving dep-0
// event to spot an unresolved→resolved transition with, so the A→B flip — the
// single most important thing this trail records — is silently dropped.
// Querying the resolved-only set separately keeps its own window and finds A.
func TestAudit_SiblingUnresolvedFloodDoesNotHideFlip(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	seedConsumer(t, client, "consumer-1")

	base := time.Now().UTC().Add(-time.Hour)
	// dep 0 was last resolved to producer A — the oldest event of the set.
	seedAuditEvent(t, client, "consumer-1", "consume", 0,
		registryevent.EventTypeDependencyResolved, "prod-a", base)
	// Sibling dep slots flap unresolved, filling far more than one LIMIT-64
	// window with newer rows that belong to other dep_index values.
	for i := 0; i < 70; i++ {
		seedAuditEvent(t, client, "consumer-1", "consume", 1+(i%9),
			registryevent.EventTypeDependencyUnresolved, "",
			base.Add(time.Duration(i+1)*time.Second))
	}

	// dep 0 now resolves to a different producer, single candidate.
	seedProducer(t, client, "prod-b", "cap_0", "1.0.0", nil)
	res := service.ResolveAllDependenciesIndexed(metadataForDeps("consume", "cap_0"))
	require.Len(t, res, 1)
	require.NotNil(t, res[0].Resolution)
	require.Equal(t, "prod-b", res[0].Resolution.AgentID)
	require.False(t, res[0].Trace.IsInteresting(),
		"test premise: a single candidate must not be interesting on its own")

	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res))

	// The flip must have been emitted, carrying A as the prior choice.
	events := listAuditEventsFor(t, client, "consumer-1")
	var flips []AuditTrace
	for _, e := range events {
		if e.DepIndex == 0 && e.Chosen != nil && e.Chosen.AgentID == "prod-b" {
			flips = append(flips, e)
		}
	}
	require.Len(t, flips, 1,
		"the prod-a → prod-b flip must still be emitted when sibling dep slots "+
			"flood the audit log (#1582 must not narrow resolved-event history)")
	assert.Equal(t, "prod-a", flips[0].PriorChosen,
		"the emitted flip must name the producer it replaced")
}

// TestAudit_DuplicateFunctionNameSlotSeesOwnEmission covers the one case where
// the per-call memo introduced by #1582 can hand back a stale snapshot.
//
// ResolveAllDependenciesIndexed derives (function_name, dep_index) from the
// agent-supplied tools list and does not deduplicate it, so an agent that
// registers two tools under the same function_name produces the SAME slot
// twice in one StoreDependencyResolutions call. The pre-#1582 code re-queried
// per dependency and therefore saw the first occurrence's just-written event
// as the second's prior; a naively memoized lookup would serve the
// pre-emission snapshot instead and lose the flip.
//
// Here the first occurrence emits (two candidates for cap_a, chosen prod-a1)
// and the second occurrence resolves the same slot to prod-b with a single
// candidate — so its emission hinges entirely on the flip check against the
// first occurrence's event.
func TestAudit_DuplicateFunctionNameSlotSeesOwnEmission(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "prod-a1", "cap_a", "1.0.0", nil)
	seedProducer(t, client, "prod-a2", "cap_a", "1.0.0", nil)
	seedProducer(t, client, "prod-b", "cap_b", "1.0.0", nil)

	// Two tools, one function_name, each with a dependency at index 0.
	meta := map[string]interface{}{
		"tools": []interface{}{
			map[string]interface{}{
				"function_name": "consume",
				"dependencies": []interface{}{
					map[string]interface{}{"capability": "cap_a"},
				},
			},
			map[string]interface{}{
				"function_name": "consume",
				"dependencies": []interface{}{
					map[string]interface{}{"capability": "cap_b"},
				},
			},
		},
	}

	res := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, res, 2, "both tools must reach the emitter")
	require.Equal(t, 0, res[0].DepIndex)
	require.Equal(t, 0, res[1].DepIndex,
		"test premise: the duplicate function_name collides on the same slot")
	require.True(t, res[0].Trace.IsInteresting(),
		"test premise: the first occurrence must emit on its own merits")
	require.False(t, res[1].Trace.IsInteresting(),
		"test premise: the second occurrence must emit only via the flip check")
	require.NotNil(t, res[1].Resolution)
	require.Equal(t, "prod-b", res[1].Resolution.AgentID)

	require.NoError(t, service.StoreDependencyResolutions(ctx, "consumer-1", res))

	events := listAuditEventsFor(t, client, "consumer-1")
	require.Len(t, events, 2,
		"the second occurrence of a repeated (function, dep_index) slot must see "+
			"the first occurrence's event as its prior and emit the flip; the "+
			"per-call memo must not serve it the pre-emission snapshot")

	firstChosen := events[0].Chosen
	require.NotNil(t, firstChosen)
	assert.Equal(t, "prod-b", events[1].Chosen.AgentID)
	assert.Equal(t, firstChosen.AgentID, events[1].PriorChosen,
		"the flip must name the producer the first occurrence chose")
}
