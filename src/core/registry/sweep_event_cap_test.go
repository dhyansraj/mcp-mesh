package registry

import (
	"context"
	"math"
	"testing"
	"time"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/logger"
)

// waitForEventCount polls the registry_events row count until it reaches want
// or the deadline expires, returning the last observed count. Used because the
// sweep's startup tick runs in its own goroutine.
func waitForEventCount(t *testing.T, job *SweepJob, want int, timeout time.Duration) int {
	t.Helper()
	deadline := time.Now().Add(timeout)
	last := -1
	for time.Now().Before(deadline) {
		n, err := job.entDB.Client.RegistryEvent.Query().Count(context.Background())
		if err != nil {
			t.Fatalf("count events: %v", err)
		}
		last = n
		if n == want {
			return n
		}
		time.Sleep(10 * time.Millisecond)
	}
	return last
}

// TestEventCapEnforcedWithRetentionZero is issue #1425.
//
// BEFORE: SweepJob.Start returned immediately when Retention <= 0, so
// enforceEventCap — which only ever ran inside runOnce, inside the sweep loop
// — never executed. Disabling the agent/schema sweep silently unbounded
// registry_events.
//
// AFTER: Start launches a cap-only tick, so the row cap holds regardless of
// the retention setting. This test fails against the pre-fix code (the row
// count stays at 5).
func TestEventCapEnforcedWithRetentionZero(t *testing.T) {
	now := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 0} // sweep disabled — the forensic escape hatch
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	job.eventMaxRows = 3

	seedAgent(t, client, "host", agent.StatusHealthy, now)
	for i := 0; i < 5; i++ {
		seedEvent(t, client, "host", now.Add(-time.Duration(5-i)*time.Minute))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	job.Start(ctx)
	defer job.Stop()

	if got := waitForEventCount(t, job, 3, 3*time.Second); got != 3 {
		t.Fatalf("registry_events count = %d, want 3: the row cap is not enforced with MCP_MESH_RETENTION=0", got)
	}

	// The agent purge must remain OFF — the operator asked for that.
	agents, err := client.Agent.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count agents: %v", err)
	}
	if agents != 1 {
		t.Fatalf("agent count = %d, want 1: the cap-only tick must not purge agents", agents)
	}
}

// TestEventCapOnlyTickLeavesStaleAgentsAlone proves the cap-only path really
// is cap-only: a stale unhealthy agent that the full sweep WOULD purge must
// survive, because the operator disabled that on purpose.
func TestEventCapOnlyTickLeavesStaleAgentsAlone(t *testing.T) {
	now := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 0}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	job.eventMaxRows = 2

	// Long-dead unhealthy agent — prime purge material for the real sweep.
	seedAgent(t, client, "long-dead", agent.StatusUnhealthy, now.Add(-30*24*time.Hour))
	for i := 0; i < 6; i++ {
		seedEvent(t, client, "long-dead", now.Add(-time.Duration(6-i)*time.Minute))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	job.Start(ctx)
	defer job.Stop()

	if got := waitForEventCount(t, job, 2, 3*time.Second); got != 2 {
		t.Fatalf("registry_events count = %d, want 2", got)
	}

	agents, err := client.Agent.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count agents: %v", err)
	}
	if agents != 1 {
		t.Fatalf("agent count = %d, want 1: a 30-day-stale agent was purged despite MCP_MESH_RETENTION=0", agents)
	}
}

// TestSweepFullyDisabledWhenBothBoundsOff verifies the only remaining no-op
// path: both knobs explicitly off. Nothing runs, and (checked by reading the
// code path, logged as a Warning) the operator is told both bounds are gone.
func TestSweepFullyDisabledWhenBothBoundsOff(t *testing.T) {
	now := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 0, EventMaxRows: EventCapDisabled}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	if job.eventMaxRows != 0 {
		t.Fatalf("eventMaxRows = %d, want 0 for the EventCapDisabled sentinel", job.eventMaxRows)
	}

	seedAgent(t, client, "host", agent.StatusHealthy, now)
	for i := 0; i < 5; i++ {
		seedEvent(t, client, "host", now.Add(-time.Duration(5-i)*time.Minute))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	job.Start(ctx)
	defer job.Stop()

	time.Sleep(200 * time.Millisecond)

	n, err := client.RegistryEvent.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count events: %v", err)
	}
	if n != 5 {
		t.Fatalf("registry_events count = %d, want 5: nothing should run with both bounds off", n)
	}

	job.mu.Lock()
	running := job.running
	job.mu.Unlock()
	if running {
		t.Error("sweep goroutine started even though both bounds are disabled")
	}
}

// TestEnforceEventCapDisabledDoesNotDeleteEverything is the guard against the
// obvious way to get this wrong: with the cap at 0, "count > cap" would be
// true for every row and the excess would be the whole table.
func TestEnforceEventCapDisabledDoesNotDeleteEverything(t *testing.T) {
	now := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: time.Hour, EventMaxRows: EventCapDisabled}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	seedAgent(t, client, "host", agent.StatusHealthy, now)
	for i := 0; i < 5; i++ {
		seedEvent(t, client, "host", now.Add(-time.Duration(5-i)*time.Minute))
	}

	res, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.eventsPurged != 0 {
		t.Errorf("eventsPurged = %d, want 0 with the cap disabled", res.eventsPurged)
	}

	n, err := client.RegistryEvent.Query().Count(context.Background())
	if err != nil {
		t.Fatalf("count events: %v", err)
	}
	if n != 5 {
		t.Fatalf("registry_events count = %d, want 5: a disabled cap deleted rows", n)
	}
}

// TestNewSweepJobEventMaxRowsResolution pins the zero-vs-sentinel semantics:
// a zero-valued struct field must NOT be able to silently remove the bound.
func TestNewSweepJobEventMaxRowsResolution(t *testing.T) {
	cases := []struct {
		name string
		cfg  int
		want int
	}{
		{"unset_uses_default", 0, defaultEventMaxRows},
		{"explicit_value", 42, 42},
		{"sentinel_disables", EventCapDisabled, 0},
		// A stray negative must NOT unbound the table. Only the -1 sentinel
		// disables the cap; every other negative is a typo and falls back to
		// the default (warned, not silently corrected).
		{"non_sentinel_negative_falls_back", -2, defaultEventMaxRows},
		{"large_negative_falls_back", -100_000, defaultEventMaxRows},
		{"min_int_negative_falls_back", math.MinInt, defaultEventMaxRows},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			now := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
			_, _, job, cleanup := newSweepTestEnv(t, SweepConfig{Retention: time.Hour, EventMaxRows: tc.cfg}, now)
			defer cleanup()
			if job.eventMaxRows != tc.want {
				t.Fatalf("eventMaxRows = %d, want %d", job.eventMaxRows, tc.want)
			}
		})
	}
}

// TestLoadSweepConfigEventMaxRowsFromEnv covers the MCP_MESH_EVENT_MAX_ROWS
// knob, including that a bad value falls back to the default instead of
// silently unbounding the table.
func TestLoadSweepConfigEventMaxRowsFromEnv(t *testing.T) {
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})

	cases := []struct {
		name string
		env  string
		want int
	}{
		{"unset_uses_default", "", defaultEventMaxRows},
		{"positive_override", "5000", 5000},
		{"zero_disables", "0", EventCapDisabled},
		{"negative_falls_back", "-1", defaultEventMaxRows},
		{"garbage_falls_back", "many", defaultEventMaxRows},
		{"float_falls_back", "1e5", defaultEventMaxRows},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("MCP_MESH_EVENT_MAX_ROWS", tc.env)
			cfg := LoadSweepConfigFromEnv(testLogger)
			if cfg.EventMaxRows != tc.want {
				t.Fatalf("EventMaxRows = %d, want %d", cfg.EventMaxRows, tc.want)
			}
		})
	}
}

// TestRetentionZeroDoesNotChangeEventCapConfig is the acceptance criterion
// stated in #1425: "Disabling the agent/schema sweep does not change whether
// registry_events is capped."
func TestRetentionZeroDoesNotChangeEventCapConfig(t *testing.T) {
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})

	t.Setenv("MCP_MESH_EVENT_MAX_ROWS", "")

	t.Setenv("MCP_MESH_RETENTION", "1h")
	withSweep := LoadSweepConfigFromEnv(testLogger)

	t.Setenv("MCP_MESH_RETENTION", "0")
	withoutSweep := LoadSweepConfigFromEnv(testLogger)

	if withoutSweep.Retention != 0 {
		t.Fatalf("Retention = %s, want 0", withoutSweep.Retention)
	}
	if withoutSweep.EventMaxRows != withSweep.EventMaxRows {
		t.Fatalf("MCP_MESH_RETENTION=0 changed the event cap: %d vs %d",
			withoutSweep.EventMaxRows, withSweep.EventMaxRows)
	}
}
