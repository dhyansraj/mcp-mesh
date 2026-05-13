package ui

// Tests for the dashboard event plumbing (issue #982).
//
// Two surfaces are exercised here:
//
//  1. mapRegistryEventToSSEType — the SSE-backfill mapping that translates a
//     persisted registry event_type into the dashboard SSE event name.
//     Regression guard for #982 Part A: "rotate" used to fall through the
//     default case and never reach the live stream.
//
//  2. enrichEventReason — the live poller's hook that copies `data.reason`
//     from the most recent matching registry event onto the diff-derived
//     DashboardEvent so the live stream matches the F5/backfill payload
//     (#982 Part B).

import (
	"context"
	"testing"
	"time"

	"entgo.io/ent/dialect/sql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	_ "github.com/mattn/go-sqlite3"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry"
)

// TestMapRegistryEventToSSEType_AllCases pins down every event_type the
// registry can persist (see ent/schema/registryevent.go enum) onto the SSE
// name the dashboard expects. Issue #982 Part A added "rotate" — keep this
// test exhaustive so future enum additions land here as a failure rather
// than a silently-dropped event in the live feed.
func TestMapRegistryEventToSSEType_AllCases(t *testing.T) {
	cases := []struct {
		name      string
		eventType string
		data      map[string]interface{}
		want      string
	}{
		{"register", "register", nil, "agent_registered"},
		{"unregister", "unregister", nil, "agent_deregistered"},
		{"unhealthy", "unhealthy", nil, "agent_unhealthy"},
		{"rotate", "rotate", nil, "agent_rotated"},
		{"update_to_healthy", "update", map[string]interface{}{"new_status": "healthy"}, "agent_healthy"},
		{"update_to_unhealthy", "update", map[string]interface{}{"new_status": "unhealthy"}, ""},
		{"update_no_status", "update", nil, ""},
		{"heartbeat_dropped", "heartbeat", nil, ""},
		{"expire_dropped", "expire", nil, ""},
		{"dependency_resolved_dropped", "dependency_resolved", nil, ""},
		{"dependency_unresolved_dropped", "dependency_unresolved", nil, ""},
		{"unknown_event_type", "completely_made_up", nil, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := mapRegistryEventToSSEType(tc.eventType, tc.data)
			assert.Equal(t, tc.want, got,
				"SSE type for registry event_type=%q (data=%v)", tc.eventType, tc.data)
		})
	}
}

// newPollerTestEnv spins up an in-memory Ent client wired into a real
// EntService so we can persist registry events and exercise the lookup path
// in enrichEventReason end-to-end. Status hooks are disabled so direct Ent
// writes don't fire side-effect events that would confuse the test fixture.
func newPollerTestEnv(t *testing.T) (*ent.Client, *registry.EntService, func()) {
	t.Helper()

	dsn := "file:poller_" + t.Name() + "?mode=memory&cache=shared&_fk=1&_busy_timeout=5000"
	drv, err := sql.Open("sqlite3", dsn)
	require.NoError(t, err, "open test sqlite driver")
	db := drv.DB()
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	client := enttest.NewClient(t, enttest.WithOptions(ent.Driver(drv)))
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	svc := registry.NewEntService(entDB, nil, testLogger)
	svc.DisableStatusChangeHooks()

	cleanup := func() { client.Close() }
	return client, svc, cleanup
}

func seedPollerAgent(t *testing.T, client *ent.Client, id string) {
	t.Helper()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetRuntime(agent.RuntimePython).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(context.Background())
	require.NoError(t, err, "seed agent %s", id)
}

func seedRegistryEvent(t *testing.T, client *ent.Client, agentID string, eventType registryevent.EventType, data map[string]interface{}, ts time.Time) {
	t.Helper()
	_, err := client.RegistryEvent.Create().
		SetEventType(eventType).
		SetAgentID(agentID).
		SetTimestamp(ts).
		SetData(data).
		Save(context.Background())
	require.NoError(t, err, "seed %s event for %s", eventType, agentID)
}

// TestEnrichEventReason_UnhealthyCopiesReasonFromRegistry — the canonical
// regression for #982 Part B. The status-change hook persists an unhealthy
// registry event with `reason: health_degradation` (status_hooks.go:204).
// When the next poller tick observes the same status flip via the snapshot
// diff, the live event must carry that same reason — otherwise EventFeed
// renders a generic "Agent Unhealthy" while history-backfill renders the
// correctly-classified row, and the user sees them as inconsistent.
func TestEnrichEventReason_UnhealthyCopiesReasonFromRegistry(t *testing.T) {
	client, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	const agentID = "weather-svc"
	seedPollerAgent(t, client, agentID)
	seedRegistryEvent(t, client, agentID, registryevent.EventTypeUnhealthy, map[string]interface{}{
		"reason":      "health_degradation",
		"old_status":  "healthy",
		"new_status":  "unhealthy",
		"description": "Agent became unhealthy",
	}, time.Now().UTC())

	ev := DashboardEvent{
		Type:      "agent_unhealthy",
		AgentID:   agentID,
		AgentName: agentID,
		Status:    "unhealthy",
		Data:      map[string]interface{}{"previous_status": "healthy"},
		Timestamp: time.Now().UTC(),
	}

	enrichEventReason(svc, &ev)

	require.NotNil(t, ev.Data, "data map preserved")
	assert.Equal(t, "health_degradation", ev.Data["reason"],
		"reason copied from the latest persisted unhealthy event")
	assert.Equal(t, "healthy", ev.Data["previous_status"],
		"existing data fields preserved alongside the enrichment")
}

// TestEnrichEventReason_DeregisteredCopiesReasonFromRegistry covers the
// graceful-shutdown variant: UnregisterAgent in ent_service.go writes an
// unregister registry event with `reason: graceful_shutdown`. The live
// stream's agent_deregistered diff event must surface that same reason so
// the EventFeed shows "Agent Stopped" (slate dot) rather than the generic
// red "Agent Deregistered" used for unexpected drops.
func TestEnrichEventReason_DeregisteredCopiesReasonFromRegistry(t *testing.T) {
	client, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	const agentID = "shutdown-svc"
	seedPollerAgent(t, client, agentID)
	seedRegistryEvent(t, client, agentID, registryevent.EventTypeUnregister, map[string]interface{}{
		"reason": "graceful_shutdown",
	}, time.Now().UTC())

	ev := DashboardEvent{
		Type:      "agent_deregistered",
		AgentID:   agentID,
		AgentName: agentID,
		Timestamp: time.Now().UTC(),
	}

	enrichEventReason(svc, &ev)

	require.NotNil(t, ev.Data, "data map allocated when reason is found")
	assert.Equal(t, "graceful_shutdown", ev.Data["reason"])
}

// TestEnrichEventReason_TakesMostRecentEvent — when an agent has multiple
// historical unhealthy events, only the latest one's reason should ride
// along on the live event. ListRecentEventsFiltered orders by timestamp
// DESC and we ask for limit=1, so this is really a contract test on that
// query shape.
func TestEnrichEventReason_TakesMostRecentEvent(t *testing.T) {
	client, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	const agentID = "flapping-svc"
	seedPollerAgent(t, client, agentID)

	now := time.Now().UTC()
	// Earlier event first
	seedRegistryEvent(t, client, agentID, registryevent.EventTypeUnhealthy,
		map[string]interface{}{"reason": "stale_on_startup"}, now.Add(-1*time.Hour))
	// Later event wins
	seedRegistryEvent(t, client, agentID, registryevent.EventTypeUnhealthy,
		map[string]interface{}{"reason": "health_degradation"}, now)

	ev := DashboardEvent{Type: "agent_unhealthy", AgentID: agentID, Timestamp: now}
	enrichEventReason(svc, &ev)

	assert.Equal(t, "health_degradation", ev.Data["reason"],
		"most recent unhealthy event's reason wins")
}

// TestEnrichEventReason_PreservesExistingReason — if the diff path is ever
// extended to set its own `data.reason` (e.g. computed from the transition
// context), enrichment must not stomp it. The early-return on
// `_, alreadySet := ev.Data["reason"]` guards this.
func TestEnrichEventReason_PreservesExistingReason(t *testing.T) {
	client, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	const agentID = "preset-svc"
	seedPollerAgent(t, client, agentID)
	seedRegistryEvent(t, client, agentID, registryevent.EventTypeUnhealthy,
		map[string]interface{}{"reason": "health_degradation"}, time.Now().UTC())

	ev := DashboardEvent{
		Type:    "agent_unhealthy",
		AgentID: agentID,
		Data:    map[string]interface{}{"reason": "preset_by_caller"},
	}
	enrichEventReason(svc, &ev)

	assert.Equal(t, "preset_by_caller", ev.Data["reason"],
		"caller-supplied reason is not overwritten")
}

// TestEnrichEventReason_NoMatchingEventLeavesEventAlone — when there is no
// persisted registry event for the agent (race window, hooks disabled, in-
// memory-only state), enrichment must be a no-op rather than corrupt the
// event with a nil-map write or an empty-string reason.
func TestEnrichEventReason_NoMatchingEventLeavesEventAlone(t *testing.T) {
	_, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	ev := DashboardEvent{
		Type:    "agent_unhealthy",
		AgentID: "ghost-svc",
		// Data deliberately nil to confirm we don't allocate it on miss
	}
	enrichEventReason(svc, &ev)

	assert.Nil(t, ev.Data, "no allocation on miss — event ships exactly as the diff produced it")
}

// TestEnrichEventReason_IgnoresUnrelatedEventTypes — only the two transition
// types we map (agent_unhealthy, agent_deregistered) get enriched. Healthy /
// registered / dependency events must not trigger a DB query (they have
// different lifecycle metadata that doesn't include a `reason`).
func TestEnrichEventReason_IgnoresUnrelatedEventTypes(t *testing.T) {
	_, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	for _, evType := range []string{
		"agent_registered",
		"agent_healthy",
		"dependency_resolved",
		"dependency_lost",
		"connected",
		"snapshot",
	} {
		ev := DashboardEvent{Type: evType, AgentID: "any"}
		enrichEventReason(svc, &ev)
		assert.Nil(t, ev.Data, "type=%s must not allocate Data via enrichment", evType)
	}
}

// TestEnrichEventReason_EmptyAgentIDIsNoop — defensive: a connected/snapshot
// frame with no agent_id must not run a registry lookup. `ListRecent
// EventsFiltered` with agent_id="" would return cross-agent rows and we'd
// attach a meaningless reason.
func TestEnrichEventReason_EmptyAgentIDIsNoop(t *testing.T) {
	_, svc, cleanup := newPollerTestEnv(t)
	defer cleanup()

	ev := DashboardEvent{Type: "agent_unhealthy", AgentID: ""}
	enrichEventReason(svc, &ev)
	assert.Nil(t, ev.Data, "empty agent_id short-circuits before the DB query")
}
