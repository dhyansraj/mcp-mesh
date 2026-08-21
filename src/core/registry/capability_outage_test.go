package registry

import (
	"bytes"
	"context"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/logger"
)

// RFC #1515 open question 1. A health check that withdraws its agent is
// per-agent; the CONDITION it reports usually is not. When a shared failure
// takes every provider of a capability out within one TTL, mesh does NOT keep a
// floor — see capability_outage.go for why — but it must not do that silently
// either. These tests pin the detection: it fires exactly when a capability has
// gone from served to unserved, and stays quiet on every neighbouring case that
// looks similar.

// seedCapabilityFor attaches one capability row to an existing agent.
func seedCapabilityFor(t *testing.T, client *ent.Client, agentID, capName, fnName string) {
	t.Helper()
	_, err := client.Capability.Create().
		SetAgentID(agentID).
		SetFunctionName(fnName).
		SetCapability(capName).
		SetVersion("1.0.0").
		SetTags([]string{}).
		Save(context.Background())
	if err != nil {
		t.Fatalf("seed capability %s on %s: %v", capName, agentID, err)
	}
}

// The shared-failure case the RFC names: both providers of a capability report
// unhealthy in the same window, so it drops to zero providers.
func TestCapabilityOutage_ReportsWhenLastProviderWithdraws(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	now := time.Now().UTC()
	seedAgent(t, client, "provider-a", agent.StatusHealthy, now)
	seedAgent(t, client, "provider-b", agent.StatusHealthy, now)
	seedCapabilityFor(t, client, "provider-a", "llm", "chat")
	seedCapabilityFor(t, client, "provider-b", "llm", "chat")

	// Both withdrawn (the state the health monitor leaves behind).
	for _, id := range []string{"provider-a", "provider-b"} {
		if err := client.Agent.UpdateOneID(id).SetStatus(agent.StatusUnhealthy).Exec(ctx); err != nil {
			t.Fatalf("withdraw %s: %v", id, err)
		}
	}

	unserved, err := service.capabilitiesLeftWithoutHealthyProvider(ctx, []string{"provider-a", "provider-b"})
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if len(unserved) != 1 || unserved[0] != "llm" {
		t.Errorf("unserved = %v, want [llm] — every provider of 'llm' withdrew, "+
			"so the capability is advertised by nothing and consumers resolve to "+
			"no candidate", unserved)
	}
}

// A PARTIAL outage is the case a floor would have been for, and it is exactly
// the case that must stay silent: one provider left is a working mesh.
func TestCapabilityOutage_SilentWhileAnyProviderSurvives(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	now := time.Now().UTC()
	seedAgent(t, client, "provider-a", agent.StatusHealthy, now)
	seedAgent(t, client, "provider-b", agent.StatusHealthy, now)
	seedCapabilityFor(t, client, "provider-a", "llm", "chat")
	seedCapabilityFor(t, client, "provider-b", "llm", "chat")

	if err := client.Agent.UpdateOneID("provider-a").SetStatus(agent.StatusUnhealthy).Exec(ctx); err != nil {
		t.Fatalf("withdraw provider-a: %v", err)
	}

	unserved, err := service.capabilitiesLeftWithoutHealthyProvider(ctx, []string{"provider-a"})
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if len(unserved) != 0 {
		t.Errorf("unserved = %v, want none — provider-b still serves 'llm', so "+
			"failover is doing its job and there is nothing to report", unserved)
	}
}

// An agent withdrawing several capabilities loses each independently, and the
// report names only the ones nothing else covers.
func TestCapabilityOutage_ReportsOnlyTheUncoveredCapabilities(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	now := time.Now().UTC()
	seedAgent(t, client, "multi", agent.StatusHealthy, now)
	seedAgent(t, client, "backup", agent.StatusHealthy, now)
	seedCapabilityFor(t, client, "multi", "alpha", "do_alpha")
	seedCapabilityFor(t, client, "multi", "beta", "do_beta")
	seedCapabilityFor(t, client, "backup", "beta", "do_beta")

	if err := client.Agent.UpdateOneID("multi").SetStatus(agent.StatusUnhealthy).Exec(ctx); err != nil {
		t.Fatalf("withdraw multi: %v", err)
	}

	unserved, err := service.capabilitiesLeftWithoutHealthyProvider(ctx, []string{"multi"})
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if len(unserved) != 1 || unserved[0] != "alpha" {
		t.Errorf("unserved = %v, want [alpha] — 'beta' is still served by backup", unserved)
	}
}

// No withdrawal, no query, no report: the steady-state mesh must pay nothing
// for this diagnostic.
func TestCapabilityOutage_NoWithdrawalIsANoOp(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()

	seedAgent(t, client, "provider-a", agent.StatusHealthy, time.Now().UTC())
	seedCapabilityFor(t, client, "provider-a", "llm", "chat")

	unserved, err := service.capabilitiesLeftWithoutHealthyProvider(context.Background(), nil)
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if unserved != nil {
		t.Errorf("unserved = %v, want nil for an empty withdrawal set", unserved)
	}
}

// runSweepCapturingWarnings runs one staleness sweep and returns everything the
// monitor's logger wrote.
//
// The redirect wraps CONSTRUCTION as well as the run: logger.New binds
// os.Stdout at construction, so a swap made afterwards would capture nothing.
// The level is WARNING rather than the ERROR the other tests use, because the
// line under test is a warning — the outage report is the registry TELLING an
// operator, and a test that cannot see it can only assert on the helper the
// monitor is assumed to call.
func runSweepCapturingWarnings(
	t *testing.T,
	heartbeatTimeout time.Duration,
	seed func(client *ent.Client),
) string {
	t.Helper()

	orig := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	os.Stdout = w

	captured := make(chan string, 1)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		captured <- buf.String()
	}()

	func() {
		defer func() {
			_ = w.Close()
			os.Stdout = orig
		}()

		client := enttest.Open(t, "sqlite3", "file:capoutage_"+t.Name()+"?mode=memory&cache=shared&_fk=1")
		defer client.Close()

		testLogger := logger.New(&config.Config{LogLevel: "WARNING"})
		service := NewEntService(&database.EntDatabase{Client: client}, nil, testLogger)
		service.DisableStatusChangeHooks()
		monitor := NewAgentHealthMonitor(service, testLogger, heartbeatTimeout, time.Minute)

		seed(client)
		monitor.checkUnhealthyAgents()
	}()

	return <-captured
}

// End-to-end through the monitor, asserted on what the monitor EMITS.
//
// The earlier version of this test called capabilitiesLeftWithoutHealthyProvider
// itself, which made it a second test of the detection rather than a test of
// the wiring: deleting the reportCapabilitiesLeftWithoutProvider call from
// checkUnhealthyAgents — the whole feature — left it green. The warning is the
// only thing the feature produces, so it is the only thing that can fail when
// the feature is removed.
func TestCapabilityOutage_WiredIntoTheStalenessSweep(t *testing.T) {
	stale := time.Now().UTC().Add(-2 * time.Minute)

	output := runSweepCapturingWarnings(t, time.Minute, func(client *ent.Client) {
		seedAgent(t, client, "only-provider", agent.StatusHealthy, stale)
		seedCapabilityFor(t, client, "only-provider", "llm", "chat")
	})

	if !strings.Contains(output, "No healthy provider remains") {
		t.Fatalf("the sweep withdrew the only provider of 'llm' and said nothing.\n"+
			"An operator learns about a total outage from consumer errors one layer "+
			"removed from the cause unless the registry reports it.\ngot:\n%s", output)
	}
	if !strings.Contains(output, "llm") {
		t.Errorf("the report must NAME the capability — that is what makes it "+
			"searchable.\ngot:\n%s", output)
	}
}

// The neighbouring case, through the same surface: a surviving provider means
// the sweep says nothing. Without this, a report that fired unconditionally on
// every withdrawal would pass the test above.
func TestCapabilityOutage_SweepIsSilentWhileAProviderSurvives(t *testing.T) {
	stale := time.Now().UTC().Add(-2 * time.Minute)

	output := runSweepCapturingWarnings(t, time.Minute, func(client *ent.Client) {
		seedAgent(t, client, "provider-a", agent.StatusHealthy, stale)
		seedAgent(t, client, "provider-b", agent.StatusHealthy, time.Now().UTC())
		seedCapabilityFor(t, client, "provider-a", "llm", "chat")
		seedCapabilityFor(t, client, "provider-b", "llm", "chat")
	})

	if strings.Contains(output, "No healthy provider remains") {
		t.Errorf("provider-b still serves 'llm' — failover is doing its job and "+
			"there is nothing to report.\ngot:\n%s", output)
	}
}

// A race lost to a concurrent heartbeat must not be reported as an outage: the
// monitor only passes on the agents it actually flipped, and that agent is still
// healthy and still serving.
func TestCapabilityOutage_RaceLostAgentIsNotReported(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()

	seedAgent(t, client, "provider-a", agent.StatusHealthy, time.Now().UTC())
	seedCapabilityFor(t, client, "provider-a", "llm", "chat")

	// The agent is still healthy — exactly the state a race-loser is left in.
	unserved, err := service.capabilitiesLeftWithoutHealthyProvider(context.Background(), []string{"provider-a"})
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if len(unserved) != 0 {
		t.Errorf("unserved = %v, want none — the agent won its heartbeat race and "+
			"is still serving 'llm'", unserved)
	}
}
