package registry

import (
	"context"
	"sync"
	"testing"
	"time"

	entgo "entgo.io/ent"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

// newHealthMonitorHookedEnv is newHealthMonitorTestEnv with the status change
// hooks left ENABLED, so registry events are produced exactly as in
// production.
func newHealthMonitorHookedEnv(t *testing.T) (*ent.Client, *EntService, *AgentHealthMonitor) {
	t.Helper()

	client := enttest.Open(t, "sqlite3", "file:healthmon_hooked_"+t.Name()+"?mode=memory&cache=shared&_fk=1")
	t.Cleanup(func() { client.Close() })
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	service := NewEntService(&database.EntDatabase{Client: client}, nil, testLogger)

	monitor := NewAgentHealthMonitor(service, testLogger, time.Minute, time.Minute)
	return client, service, monitor
}

// injectHeartbeatBeforeUnhealthyUpdate registers an Agent hook that runs
// INSIDE the status change hook (hooks registered later wrap closer to the
// SQL), so it fires after the status hook has read the agent's old status and
// before the monitor's conditional UPDATE executes. It simulates a heartbeat
// landing in exactly that window, once.
func injectHeartbeatBeforeUnhealthyUpdate(client *ent.Client, agentID string, heartbeatTime time.Time) {
	var once sync.Once
	client.Agent.Use(func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			am, ok := m.(*ent.AgentMutation)
			if ok && am.Op() == ent.OpUpdate {
				if st, exists := am.Status(); exists && st == agent.StatusUnhealthy {
					var hbErr error
					once.Do(func() {
						_, hbErr = client.Agent.UpdateOneID(agentID).
							SetUpdatedAt(heartbeatTime).
							Save(ctx)
					})
					if hbErr != nil {
						return nil, hbErr
					}
				}
			}
			return next.Mutate(ctx, m)
		})
	})
}

// TestHealthMonitorRaceLostWritesNoEvent is the #1641 regression: a heartbeat
// lands after the status hook has seen the agent as healthy but before the
// monitor's conditional update runs. The update affects 0 rows, so no
// unhealthy event may be recorded and topology must not report a change.
func TestHealthMonitorRaceLostWritesNoEvent(t *testing.T) {
	client, service, monitor := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	lastRefresh := time.Now().UTC().Add(-time.Second)
	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "racer", agent.StatusHealthy, staleTime)
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())
	seedProviderResolutions(t, client, "consumer", "racer")

	snapshot, err := client.Agent.Get(ctx, "racer")
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}

	heartbeatTime := time.Now().UTC().Truncate(time.Millisecond)
	injectHeartbeatBeforeUnhealthyUpdate(client, "racer", heartbeatTime)

	won, err := monitor.markAgentUnhealthyIfUnchanged(ctx, snapshot)
	if err != nil {
		t.Fatalf("markAgentUnhealthyIfUnchanged: %v", err)
	}
	if won {
		t.Fatal("conditional update must lose the race against the injected heartbeat")
	}

	got, err := client.Agent.Get(ctx, "racer")
	if err != nil {
		t.Fatalf("reload agent: %v", err)
	}
	if got.Status != agent.StatusHealthy {
		t.Errorf("agent status = %s, want healthy", got.Status)
	}
	if !got.UpdatedAt.Equal(heartbeatTime) {
		t.Errorf("agent updated_at = %v, want heartbeat time %v", got.UpdatedAt, heartbeatTime)
	}

	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 0 {
		t.Errorf("race-lost update recorded %d registry event(s) (first: %s), want 0", len(events), events[0].EventType)
	}

	changed, err := service.HasTopologyChanges(ctx, "consumer", lastRefresh)
	if err != nil {
		t.Fatalf("HasTopologyChanges: %v", err)
	}
	if changed {
		t.Error("HasTopologyChanges = true after a race-lost update, want false")
	}

	assertProviderResolutionStatuses(t, client, "consumer", true)
}

// TestHealthMonitorRaceWonWritesOneEvent: when the conditional update lands,
// exactly one unhealthy event is recorded and topology reports the change.
func TestHealthMonitorRaceWonWritesOneEvent(t *testing.T) {
	client, service, monitor := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	lastRefresh := time.Now().UTC().Add(-time.Second)
	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "provider", agent.StatusHealthy, staleTime)
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())

	monitor.checkUnhealthyAgents()

	got, err := client.Agent.Get(ctx, "provider")
	if err != nil {
		t.Fatalf("reload provider: %v", err)
	}
	if got.Status != agent.StatusUnhealthy {
		t.Errorf("provider status = %s, want unhealthy", got.Status)
	}
	if !got.UpdatedAt.Equal(staleTime) {
		t.Errorf("provider updated_at = %v, want preserved %v", got.UpdatedAt, staleTime)
	}

	events, err := client.RegistryEvent.Query().WithAgent().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("registry events = %d, want exactly 1", len(events))
	}
	if events[0].EventType != registryevent.EventTypeUnhealthy {
		t.Errorf("event type = %s, want unhealthy", events[0].EventType)
	}
	if events[0].Edges.Agent == nil || events[0].Edges.Agent.ID != "provider" {
		t.Errorf("event agent = %v, want provider", events[0].Edges.Agent)
	}

	changed, err := service.HasTopologyChanges(ctx, "consumer", lastRefresh)
	if err != nil {
		t.Fatalf("HasTopologyChanges: %v", err)
	}
	if !changed {
		t.Error("HasTopologyChanges = false after an agent went unhealthy, want true")
	}
}

// TestUnregisterWithHooksWritesOnlyUnregisterEvent guards the graceful
// shutdown suppression: the explicit unregister event is written inside the
// unregister transaction, and the status hook must see it and not add a
// second (unhealthy) event for the same transition.
func TestUnregisterWithHooksWritesOnlyUnregisterEvent(t *testing.T) {
	client, service, _ := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	seedAgent(t, client, "leaving", agent.StatusHealthy, time.Now().UTC())

	if err := service.UnregisterAgent(ctx, "leaving", ""); err != nil {
		t.Fatalf("UnregisterAgent: %v", err)
	}

	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("registry events = %d, want exactly 1", len(events))
	}
	if events[0].EventType != registryevent.EventTypeUnregister {
		t.Errorf("event type = %s, want unregister", events[0].EventType)
	}
}

// TestStatusHookBulkUpdateCountMismatchWritesNoPhantom: a bulk conditional
// update targets a healthy mcp agent and a healthy api agent. The mcp agent
// heartbeats after the hook has read both rows, so only the api agent's row
// matches. affected (1) then equals the number of pending events (1, since api
// agents produce none) by coincidence; the hook must not take that as proof
// that the mcp agent changed.
func TestStatusHookBulkUpdateCountMismatchWritesNoPhantom(t *testing.T) {
	client, _, _ := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "bulk-mcp", agent.StatusHealthy, staleTime)
	if _, err := client.Agent.Create().
		SetID("bulk-api").
		SetName("bulk-api").
		SetAgentType(agent.AgentTypeAPI).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(staleTime).
		Save(ctx); err != nil {
		t.Fatalf("seed api agent: %v", err)
	}

	injectHeartbeatBeforeUnhealthyUpdate(client, "bulk-mcp", time.Now().UTC().Truncate(time.Millisecond))

	affected, err := client.Agent.Update().
		Where(
			agent.IDIn("bulk-mcp", "bulk-api"),
			agent.UpdatedAtLT(time.Now().UTC().Add(-time.Minute)),
		).
		SetStatus(agent.StatusUnhealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("bulk update: %v", err)
	}
	if affected != 1 {
		t.Fatalf("bulk update affected %d rows, want 1 (only the api agent)", affected)
	}

	mcp, err := client.Agent.Get(ctx, "bulk-mcp")
	if err != nil {
		t.Fatalf("reload mcp agent: %v", err)
	}
	if mcp.Status != agent.StatusHealthy {
		t.Errorf("mcp agent status = %s, want healthy", mcp.Status)
	}
	api, err := client.Agent.Get(ctx, "bulk-api")
	if err != nil {
		t.Fatalf("reload api agent: %v", err)
	}
	if api.Status != agent.StatusUnhealthy {
		t.Errorf("api agent status = %s, want unhealthy", api.Status)
	}

	events, err := client.RegistryEvent.Query().WithAgent().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	for _, ev := range events {
		t.Errorf("unexpected %s event for agent %v", ev.EventType, ev.Edges.Agent)
	}
}

// TestHealthMonitorEventTimestampNotBeforeUpdate: the unhealthy event's
// timestamp must not predate the status update. A consumer that full-refreshes
// before the update lands records a LastFullRefresh earlier than the event,
// so HasTopologyChanges still reports the withdrawal to it.
func TestHealthMonitorEventTimestampNotBeforeUpdate(t *testing.T) {
	client, _, monitor := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "withdrawn", agent.StatusHealthy, staleTime)

	// Registered after the status hook, so it wraps the SQL more tightly:
	// updateDone is taken once the UPDATE has executed, before the status
	// hook regains control.
	var updateDone time.Time
	client.Agent.Use(func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			v, err := next.Mutate(ctx, m)
			if am, ok := m.(*ent.AgentMutation); ok && am.Op() == ent.OpUpdate {
				if st, exists := am.Status(); exists && st == agent.StatusUnhealthy {
					updateDone = time.Now().UTC()
				}
			}
			return v, err
		})
	})

	monitor.checkUnhealthyAgents()

	if updateDone.IsZero() {
		t.Fatal("health monitor did not run the unhealthy update")
	}
	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("registry events = %d, want exactly 1", len(events))
	}
	if events[0].Timestamp.Before(updateDone) {
		t.Errorf("event timestamp %v predates the status update (%v)",
			events[0].Timestamp.Format(time.RFC3339Nano), updateDone.Format(time.RFC3339Nano))
	}
}
