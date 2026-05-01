package registry

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// newAuditEndpointTestEnv spins up a real Gin router wired to the production
// EntBusinessLogicHandlers. This lets us exercise GET /events as a real HTTP
// surface rather than mocking the handler signature.
func newAuditEndpointTestEnv(t *testing.T) (*httptest.Server, *EntService, *ent.Client, func()) {
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

// httpGetEvents calls GET /events on the test server with the given raw query
// string and decodes the EventsHistoryResponse envelope.
func httpGetEvents(t *testing.T, baseURL, rawQuery string) generated.EventsHistoryResponse {
	t.Helper()
	url := baseURL + "/events"
	if rawQuery != "" {
		url += "?" + rawQuery
	}
	resp, err := http.Get(url)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, 200, resp.StatusCode, "GET %s should return 200", url)

	var envelope generated.EventsHistoryResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&envelope))
	return envelope
}

// TestAuditEndpoint_FlipScenario simulates the full operator-facing scenario
// from issue #836:
//   - Spawn a consumer + 2 producers (one matches, one fails on tags)
//   - Resolve once → audit event recorded with chosen=p-good and evicted=p-bad
//   - Knock the original winner offline, add a third producer (p-better)
//   - Resolve again → flip with prior_chosen=p-good
//   - Verify GET /events returns the persisted history with prior_chosen set
func TestAuditEndpoint_FlipScenario(t *testing.T) {
	srv, service, client, cleanup := newAuditEndpointTestEnv(t)
	defer cleanup()

	// Set up: consumer + 2 producers, only one matches the consumer's tags.
	seedConsumer(t, client, "consumer-1")
	seedProducer(t, client, "p-good", "do_thing", "1.0.0", []string{"api"})
	seedProducer(t, client, "p-bad", "do_thing", "1.0.0", []string{"internal"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "do_thing",
		"tags":       []interface{}{"api"},
	})

	// Wire 1: choose p-good, evict p-bad on MissingTag.
	res := service.ResolveAllDependenciesIndexed(meta)
	require.NotNil(t, res[0].Resolution)
	require.Equal(t, "p-good", res[0].Resolution.AgentID)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	// Hit GET /events?agent_id=consumer-1 — should see one resolved event.
	body := httpGetEvents(t, srv.URL, "agent_id=consumer-1")
	require.Equal(t, 1, body.Count)
	require.Len(t, body.Events, 1)
	first := body.Events[0]
	assert.Equal(t, "dependency_resolved", string(first.EventType))
	assert.Equal(t, "consumer-1", first.AgentId)

	// Decode the embedded trace and verify shape.
	require.NotNil(t, first.Data)
	traceJSON, _ := json.Marshal(*first.Data)
	var tr AuditTrace
	require.NoError(t, json.Unmarshal(traceJSON, &tr))
	require.NotNil(t, tr.Chosen)
	assert.Equal(t, "p-good", tr.Chosen.AgentID)

	// MissingTag eviction must be present somewhere in the trace.
	foundMissingTag := false
	for _, s := range tr.Stages {
		for _, e := range s.Evicted {
			if e.Reason == ReasonMissingTag {
				foundMissingTag = true
			}
		}
	}
	assert.True(t, foundMissingTag, "MissingTag eviction should appear in the trace stages")
	assert.Empty(t, tr.PriorChosen, "first emission has no prior_chosen")

	// Wire 2 — flip: knock p-good unhealthy, add a new winner. Resolver
	// should pick p-better on the next resolution.
	seedProducer(t, client, "p-better", "do_thing", "1.0.0", []string{"api"})
	_, err := client.Agent.UpdateOneID("p-good").SetStatus(agent.StatusUnhealthy).Save(context.Background())
	require.NoError(t, err)

	res2 := service.ResolveAllDependenciesIndexed(meta)
	require.NotNil(t, res2[0].Resolution)
	assert.Equal(t, "p-better", res2[0].Resolution.AgentID)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res2))

	// GET /events?agent_id=consumer-1&limit=10 — should see two events now.
	body2 := httpGetEvents(t, srv.URL, "agent_id=consumer-1&limit=10")
	require.GreaterOrEqual(t, body2.Count, 2)

	// Most recent event (events are ordered DESC by timestamp) should record
	// the flip with prior_chosen=p-good.
	latest := body2.Events[0]
	assert.Equal(t, "dependency_resolved", string(latest.EventType))
	require.NotNil(t, latest.Data)
	latestJSON, _ := json.Marshal(*latest.Data)
	var latestTrace AuditTrace
	require.NoError(t, json.Unmarshal(latestJSON, &latestTrace))
	require.NotNil(t, latestTrace.Chosen)
	assert.Equal(t, "p-better", latestTrace.Chosen.AgentID)
	assert.Equal(t, "p-good", latestTrace.PriorChosen, "latest trace should record the flipped-from agent")
}

// TestAuditEndpoint_TypeFilter checks the type query parameter narrows results.
func TestAuditEndpoint_TypeFilter(t *testing.T) {
	srv, service, client, cleanup := newAuditEndpointTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	// Two producers that both fail tag check → unresolved with non-empty trace.
	seedProducer(t, client, "wrong-1", "ping", "1.0.0", []string{"foo"})
	seedProducer(t, client, "wrong-2", "ping", "1.0.0", []string{"foo"})

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"required"},
	})
	res := service.ResolveAllDependenciesIndexed(meta)
	require.Nil(t, res[0].Resolution)
	require.NoError(t, service.StoreDependencyResolutions(context.Background(), "consumer-1", res))

	// Without filter — should see 1 unresolved event.
	body := httpGetEvents(t, srv.URL, "agent_id=consumer-1")
	require.Equal(t, 1, body.Count)
	assert.Equal(t, "dependency_unresolved", string(body.Events[0].EventType))

	// With type=dependency_unresolved — same.
	body = httpGetEvents(t, srv.URL, "agent_id=consumer-1&type=dependency_unresolved")
	require.Equal(t, 1, body.Count)

	// With type=dependency_resolved — empty.
	body = httpGetEvents(t, srv.URL, "agent_id=consumer-1&type=dependency_resolved")
	assert.Equal(t, 0, body.Count)
	assert.Empty(t, body.Events)
}

// TestAuditEndpoint_LimitClamp exercises the limit boundaries (min 1, max 500).
func TestAuditEndpoint_LimitClamp(t *testing.T) {
	srv, _, _, cleanup := newAuditEndpointTestEnv(t)
	defer cleanup()

	// Limit too low: handler clamps to 1; query for nonexistent agent → empty
	// envelope (we just verify no error path).
	body := httpGetEvents(t, srv.URL, "agent_id=nobody&limit=0")
	assert.Equal(t, 0, body.Count)

	// Limit too high: handler clamps to 500; should still return empty.
	body = httpGetEvents(t, srv.URL, "agent_id=nobody&limit=999999")
	assert.Equal(t, 0, body.Count)
}
