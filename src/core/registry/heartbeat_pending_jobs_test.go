package registry

// HTTP-level coverage for the X-Mesh-Pending-Jobs header on
// HEAD /heartbeat/{agent_id}. Uses the same real-service test env as
// the jobs endpoint tests so the header value reflects the production
// CountPendingJobsForAgent path end-to-end.
//
// The capability scoping rule under test (per MESHJOB_DESIGN.org > Key
// Decisions > "Pending-jobs scoping: per-agent capability set"): the
// header reflects ONLY jobs whose capability is served by replicas of
// the target agent's group (= same agent_name); a pending job for a
// capability the agent does not serve must NOT trigger the header.

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// newHeartbeatTestEnv reuses newAuditTestEnv (real EntService over an
// in-memory Ent client) and wires the production handlers so HEAD
// /heartbeat/{agent_id} hits CountPendingJobsForAgent.
func newHeartbeatTestEnv(t *testing.T) (*httptest.Server, *EntService, *ent.Client, func()) {
	t.Helper()
	client, service, cleanup := newAuditTestEnv(t)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)

	return srv, service, client, func() {
		srv.Close()
		cleanup()
	}
}

// seedAgentWithCapability registers a healthy agent that serves a single
// capability. Mirrors the seedProducer helper in audit_resolver_test.go
// but with a configurable name so the test can drive the agent_name
// scoping rule explicitly (group = agents sharing a name, NOT instance
// IDs).
func seedAgentWithCapability(t *testing.T, client *ent.Client, agentID, agentName, capabilityName string) {
	t.Helper()
	ctx := context.Background()
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentName).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "create agent %s", agentID)

	_, err = client.Capability.Create().
		SetCapability(capabilityName).
		SetFunctionName("do_thing").
		SetVersion("1.0.0").
		SetTags([]string{}).
		SetAgentID(agentID).
		Save(ctx)
	require.NoError(t, err, "create capability for %s", agentID)
}

// seedPendingJob inserts a working job with no owner and capability cap.
// The MaxRetries default is 3 so the orphan/exhausted edge isn't hit.
func seedPendingJob(t *testing.T, service *EntService, id, capabilityName string) {
	t.Helper()
	_, err := service.CreateJob(context.Background(), &CreateJobInput{
		ID:               id,
		Capability:       capabilityName,
		SubmittedBy:      "test-submitter",
		SubmittedPayload: map[string]interface{}{"k": "v"},
		MaxRetries:       3,
	})
	require.NoError(t, err, "create pending job %s", id)
}

func TestFastHeartbeat_PendingJobsHeader_Present(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	seedPendingJob(t, service, "job-1", "render_report")

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, "1", resp.Header.Get("X-Mesh-Pending-Jobs"))
}

func TestFastHeartbeat_PendingJobsHeader_AbsentWhenZero(t *testing.T) {
	srv, _, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	// No jobs inserted.

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Empty(t, resp.Header.Get("X-Mesh-Pending-Jobs"), "header should be absent when there are zero pending jobs")
}

// Capability scoping: a pending job in a capability the target agent's
// group does NOT serve must not trigger the header. This is the
// difference between "tell every agent in the mesh" and "tell only the
// replicas that can actually serve this work."
func TestFastHeartbeat_PendingJobsHeader_CapabilityNotServed(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	// Pending job in a different capability, which "render-agent" does NOT serve.
	seedPendingJob(t, service, "job-other", "translate_text")

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Empty(t, resp.Header.Get("X-Mesh-Pending-Jobs"), "header must NOT appear for capabilities the agent does not serve")
}

// Counts must reflect every claimable job in the served capability set,
// not just one row.
func TestFastHeartbeat_PendingJobsHeader_MultiPendingCount(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	seedPendingJob(t, service, "job-a", "render_report")
	seedPendingJob(t, service, "job-b", "render_report")
	seedPendingJob(t, service, "job-c", "render_report")

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, "3", resp.Header.Get("X-Mesh-Pending-Jobs"))
}

// Pending-jobs hint must also appear on the 202 response path (topology
// changed) — both signals can co-occur per the design doc.
func TestFastHeartbeat_PendingJobsHeader_OnTopologyChange(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	seedPendingJob(t, service, "job-1", "render_report")

	// Force last_full_refresh into the deep past, then emit a fresh
	// register event so HasTopologyChanges() sees a change. Using direct
	// Ent so this stays insulated from RegisterAgent's setting of
	// last_full_refresh.
	ctx := context.Background()
	_, err := client.Agent.UpdateOneID("render-agent-1").
		SetLastFullRefresh(time.Now().Add(-1 * time.Hour)).
		Save(ctx)
	require.NoError(t, err)
	_, err = client.RegistryEvent.Create().
		SetEventType("register").
		SetAgentID("render-agent-1").
		SetTimestamp(time.Now()).
		SetData(map[string]interface{}{}).
		Save(ctx)
	require.NoError(t, err)

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusAccepted, resp.StatusCode)
	assert.Equal(t, "1", resp.Header.Get("X-Mesh-Pending-Jobs"))
}

// Counts above pendingJobsHeaderCap (100) must clip to exactly the cap.
// Mirrors the OpenAPI X-Mesh-Pending-Jobs schema (maximum: 100).
func TestFastHeartbeat_PendingJobsHeader_CappedAt100(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	for i := 0; i < pendingJobsHeaderCap+5; i++ {
		seedPendingJob(t, service, "job-"+strconv.Itoa(i), "render_report")
	}

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, strconv.Itoa(pendingJobsHeaderCap), resp.Header.Get("X-Mesh-Pending-Jobs"))
}

// Group scoping: a sibling replica (different instance ID, same
// agent_name) sharing the served capability must also see the header.
// This is the "claude-provider-replica-{1,2,3}" example from the design
// doc — the group is identified by agent_name, not instance ID.
func TestFastHeartbeat_PendingJobsHeader_AcrossReplicaGroup(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	// Two replicas of the same agent_name, both serving render_report.
	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")
	seedAgentWithCapability(t, client, "render-agent-2", "render-agent", "render_report")
	seedPendingJob(t, service, "job-1", "render_report")

	for _, id := range []string{"render-agent-1", "render-agent-2"} {
		req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/"+id, nil)
		require.NoError(t, err)
		resp, err := (&http.Client{}).Do(req)
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, resp.StatusCode, "agent %s", id)
		assert.Equal(t, "1", resp.Header.Get("X-Mesh-Pending-Jobs"), "agent %s: header should reflect group-scoped count", id)
		resp.Body.Close()
	}
}

// A claimed job (owner_instance_id non-NULL) must NOT count toward the
// header — the header is for unclaimed work only.
func TestFastHeartbeat_PendingJobsHeader_ClaimedExcluded(t *testing.T) {
	srv, service, client, cleanup := newHeartbeatTestEnv(t)
	defer cleanup()

	seedAgentWithCapability(t, client, "render-agent-1", "render-agent", "render_report")

	// One claimable, one already owned.
	seedPendingJob(t, service, "job-pending", "render_report")
	owner := "some-other-replica"
	_, err := service.CreateJob(context.Background(), &CreateJobInput{
		ID:               "job-claimed",
		Capability:       "render_report",
		SubmittedBy:      "test-submitter",
		SubmittedPayload: map[string]interface{}{"k": "v"},
		OwnerInstanceID:  &owner,
		MaxRetries:       3,
	})
	require.NoError(t, err)

	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/render-agent-1", nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	require.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, "1", resp.Header.Get("X-Mesh-Pending-Jobs"), "claimed jobs must be excluded from the count")
}
