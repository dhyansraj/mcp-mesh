package registry

// Regression coverage for #955: a registry restart leaves stdio agents (or any
// previously-registered agent the registry can't reach) as orphans. Startup
// cleanup correctly marks them unhealthy, but commit 032a9128 added an
// auto-recovery branch to UpdateAgentHeartbeatTimestamp that silently flipped
// any agent sending a HEAD heartbeat back to healthy and bumped updated_at.
// Net effect: the sweep job never got a window to evict the row, and orphans
// persisted forever as "healthy".
//
// The fix has two parts:
//
//  1. FastHeartbeatCheck (HEAD /heartbeat/{id}) now short-circuits to 410 Gone
//     for any unhealthy agent. The SDK clients map 410 → AGENT_UNKNOWN →
//     requires_full_heartbeat() and re-register via POST.
//  2. UpdateAgentHeartbeatTimestamp no longer touches status — it only bumps
//     updated_at for the (necessarily healthy) agent.
//
// Together: an unhealthy row stays unhealthy until a POST heartbeat arrives
// with full metadata, at which point RegisterAgent/UpdateHeartbeat handle the
// transition with the up-to-date endpoint / capability set.

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// TestFastHeartbeatCheck_UnhealthyAgentRequiresReregistration is the primary
// regression test for #955: a HEAD heartbeat to an unhealthy agent must
// return 410 Gone and must NOT mutate the row (no status flip, no
// updated_at bump). A subsequent POST /heartbeat with the full registration
// payload must then transition the agent back to healthy.
func TestFastHeartbeatCheck_UnhealthyAgentRequiresReregistration(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)
	defer srv.Close()

	ctx := context.Background()
	agentID := "orphan-agent-1"
	// Seed an agent that was marked unhealthy an hour ago — e.g. by
	// CleanupStaleAgentsOnStartup after a registry restart. updated_at is
	// deliberately stale so the assertion below can prove the HEAD call
	// did NOT touch it.
	staleTime := time.Now().UTC().Add(-1 * time.Hour).Truncate(time.Microsecond)
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(staleTime).
		Save(ctx)
	require.NoError(t, err, "seed unhealthy agent")
	// Re-write defensively in case the schema defaulted updated_at.
	_, err = client.Agent.UpdateOneID(agentID).SetUpdatedAt(staleTime).Save(ctx)
	require.NoError(t, err, "force stale updated_at")

	// Phase 1: HEAD heartbeat from the orphan must be rejected with 410 Gone.
	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusGone, resp.StatusCode,
		"unhealthy agent must receive 410 Gone on HEAD heartbeat (#955)")

	// Phase 2: the row must NOT have been auto-recovered or touched.
	got, err := client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusUnhealthy, got.Status,
		"HEAD heartbeat must NOT auto-promote unhealthy → healthy (#955)")
	assert.True(t, got.UpdatedAt.Equal(staleTime),
		"HEAD heartbeat must NOT bump updated_at on an unhealthy agent (#955); "+
			"got=%s want=%s",
		got.UpdatedAt.UTC().Format(time.RFC3339Nano),
		staleTime.Format(time.RFC3339Nano))

	// Phase 3: a POST /heartbeat with a full registration payload (the path
	// the SDK takes on 410) must transition the agent back to healthy and
	// bump updated_at. This is the architecture: unhealthy → healthy is a
	// POST-only operation that reconciles metadata.
	hb := &HeartbeatRequest{
		AgentID: agentID,
		Status:  "healthy",
		Metadata: map[string]interface{}{
			"agent_id":  agentID,
			"name":      agentID,
			"version":   "1.0.0",
			"namespace": "default",
			"endpoint":  "http://127.0.0.1:9999",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "do_thing",
					"capability":    "thing",
					"version":       "1.0.0",
				},
			},
		},
	}
	hbResp, err := service.UpdateHeartbeat(hb)
	require.NoError(t, err, "POST heartbeat after 410 must succeed")
	require.NotNil(t, hbResp)

	// Re-query: agent must now be healthy and updated_at recent.
	got, err = client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusHealthy, got.Status,
		"POST /heartbeat must transition unhealthy → healthy when full metadata is provided")
	assert.True(t, got.UpdatedAt.After(staleTime),
		"POST /heartbeat must bump updated_at; got=%s, stale=%s",
		got.UpdatedAt.UTC().Format(time.RFC3339Nano),
		staleTime.Format(time.RFC3339Nano))
}

// TestFastHeartbeatCheck_HealthyAgentBumpsTimestamp is the positive-case
// counterpart: a HEAD heartbeat to a healthy agent must return 200 OK and
// bump updated_at. This is the steady-state heartbeat path and must not
// regress under the #955 fix.
func TestFastHeartbeatCheck_HealthyAgentBumpsTimestamp(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)
	defer srv.Close()

	ctx := context.Background()
	agentID := "healthy-agent-1"
	// Seed a healthy agent with an old updated_at so the bump is observable.
	oldUpdatedAt := time.Now().UTC().Add(-5 * time.Minute).Truncate(time.Microsecond)
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(oldUpdatedAt).
		Save(ctx)
	require.NoError(t, err, "seed healthy agent")
	_, err = client.Agent.UpdateOneID(agentID).SetUpdatedAt(oldUpdatedAt).Save(ctx)
	require.NoError(t, err, "force old updated_at")

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode,
		"healthy agent must receive 200 OK on HEAD heartbeat")

	got, err := client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusHealthy, got.Status, "status must remain healthy")
	assert.True(t, got.UpdatedAt.After(oldUpdatedAt),
		"HEAD heartbeat must bump updated_at for healthy agents; got=%s old=%s",
		got.UpdatedAt.UTC().Format(time.RFC3339Nano),
		oldUpdatedAt.Format(time.RFC3339Nano))
}
