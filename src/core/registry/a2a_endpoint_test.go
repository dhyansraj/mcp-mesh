// A2A surface tests (issue #903 / Phase 1A).
//
// Covers:
//   - Registration of an a2a-typed agent with `surfaces` array persists
//     A2aSurfaces JSON on the agent record.
//   - Heartbeat returns the surfaces back with stamped public_url +
//     agent_card_url derived from MCP_MESH_PUBLIC_URL_PREFIX.
//   - GET /a2a/agents flattens every a2a-typed agent's surfaces into a
//     single response with FQDN-stamped URLs.
//   - When MCP_MESH_PUBLIC_URL_PREFIX is unset, public_url / agent_card_url
//     are emitted as empty (not as relative paths) — operator visibility
//     comes via warn-once log, not via response shape.

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
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// a2aRegistrationFixture returns a minimal but realistic a2a-typed agent
// registration request with two surfaces. Mirrors the canonical Python
// example in A2A_SURFACE_DESIGN.org so tests stay aligned with the
// design-time semantics.
func a2aRegistrationFixture(agentID string) *AgentRegistrationRequest {
	return &AgentRegistrationRequest{
		AgentID: agentID,
		Metadata: map[string]interface{}{
			"agent_type": "a2a",
			"name":       agentID,
			"http_host":  "0.0.0.0",
			"http_port":  float64(9100),
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "report_generator_a2a",
					"capability":    "a2a.report-generator",
				},
			},
			"surfaces": []interface{}{
				map[string]interface{}{
					"path":         "/agents/report-generator",
					"skill_id":     "generate-report",
					"name":         "Report Generator",
					"description":  "Generate a long-form report",
					"input_modes":  []interface{}{"application/json"},
					"output_modes": []interface{}{"application/json"},
					"tags":         []interface{}{"reporting"},
				},
				map[string]interface{}{
					"path":     "/agents/lookup",
					"skill_id": "quick-lookup",
					"name":     "Quick Lookup",
				},
			},
		},
	}
}

func TestA2ARegistrationPersistsSurfaces(t *testing.T) {
	service := setupTestService(t)

	req := a2aRegistrationFixture("a2a-test-agent")
	_, err := service.RegisterAgent(req)
	require.NoError(t, err)

	// Read back via Ent and verify a2a_surfaces JSON survived the round-trip.
	a, err := service.entDB.Agent.Query().
		Where(agent.IDEQ("a2a-test-agent")).
		Only(context.Background())
	require.NoError(t, err)
	assert.Equal(t, "a2a", a.AgentType.String())
	require.Len(t, a.A2aSurfaces, 2)
	assert.Equal(t, "/agents/report-generator", a.A2aSurfaces[0]["path"])
	assert.Equal(t, "generate-report", a.A2aSurfaces[0]["skill_id"])
	assert.Equal(t, "Report Generator", a.A2aSurfaces[0]["name"])
	assert.Equal(t, "/agents/lookup", a.A2aSurfaces[1]["path"])
	assert.Equal(t, "quick-lookup", a.A2aSurfaces[1]["skill_id"])
}

func TestA2AHeartbeatReturnsStampedURLs(t *testing.T) {
	t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "https://agents.acme.com")

	service := setupTestService(t)

	// Register first.
	regReq := a2aRegistrationFixture("a2a-stamp-agent")
	_, err := service.RegisterAgent(regReq)
	require.NoError(t, err)

	// Heartbeat should echo surfaces back with stamped URLs.
	hbReq := &HeartbeatRequest{
		AgentID:  "a2a-stamp-agent",
		Status:   "healthy",
		Metadata: regReq.Metadata,
	}
	hbResp, err := service.UpdateHeartbeat(hbReq)
	require.NoError(t, err)
	require.NotNil(t, hbResp)
	require.Len(t, hbResp.A2ASurfaces, 2)

	// Build the wire-shape (mirrors what SendHeartbeat does) and assert the
	// FQDN stamping.
	stamped := buildA2ASurfaceResponses(hbResp.A2ASurfaces)
	require.Len(t, stamped, 2)

	assert.Equal(t, "/agents/report-generator", stamped[0].Path)
	assert.Equal(t, "generate-report", stamped[0].SkillId)
	require.NotNil(t, stamped[0].PublicUrl)
	require.NotNil(t, stamped[0].AgentCardUrl)
	assert.Equal(t, "https://agents.acme.com/agents/report-generator", *stamped[0].PublicUrl)
	assert.Equal(t,
		"https://agents.acme.com/agents/report-generator/.well-known/agent.json",
		*stamped[0].AgentCardUrl)
}

func TestA2AHeartbeatWithoutPublicURLPrefix(t *testing.T) {
	// Explicitly clear the env var to test the unset path. The warn-once
	// behavior is process-lifetime; we don't assert on the log line here
	// (no test logger plumb yet) — just confirm the URL fields stay empty
	// rather than collapsing to relative paths or panicking.
	t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "")

	service := setupTestService(t)

	regReq := a2aRegistrationFixture("a2a-unset-prefix-agent")
	_, err := service.RegisterAgent(regReq)
	require.NoError(t, err)

	hbReq := &HeartbeatRequest{
		AgentID:  "a2a-unset-prefix-agent",
		Status:   "healthy",
		Metadata: regReq.Metadata,
	}
	hbResp, err := service.UpdateHeartbeat(hbReq)
	require.NoError(t, err)
	require.Len(t, hbResp.A2ASurfaces, 2)

	stamped := buildA2ASurfaceResponses(hbResp.A2ASurfaces)
	require.Len(t, stamped, 2)
	// Path + skill_id always echoed.
	assert.Equal(t, "/agents/report-generator", stamped[0].Path)
	// URL fields nil-pointer when prefix is empty (omitted from JSON).
	assert.Nil(t, stamped[0].PublicUrl)
	assert.Nil(t, stamped[0].AgentCardUrl)
}

// TestA2AListAgentsEndpoint exercises the GET /a2a/agents discovery
// endpoint via a real gin router so the wire shape is validated end-to-end
// (not just the in-process service-layer call).
func TestA2AListAgentsEndpoint(t *testing.T) {
	t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "https://agents.acme.com/")

	service := setupTestService(t)
	handlers := NewEntBusinessLogicHandlers(service)

	// Register one a2a agent and one mcp_agent — the discovery endpoint
	// should only surface the a2a agent.
	_, err := service.RegisterAgent(a2aRegistrationFixture("a2a-discovery-agent"))
	require.NoError(t, err)
	_, err = service.RegisterAgent(&AgentRegistrationRequest{
		AgentID: "regular-mesh-agent",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "regular-mesh-agent",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "say_hi",
					"capability":    "greet",
				},
			},
		},
	})
	require.NoError(t, err)

	// Wire the handler into a real gin router so we exercise the
	// generated.RegisterHandlers path too.
	gin.SetMode(gin.TestMode)
	router := gin.New()
	generated.RegisterHandlers(router, handlers)

	w := httptest.NewRecorder()
	httpReq, err := http.NewRequest(http.MethodGet, "/a2a/agents", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	router.ServeHTTP(w, httpReq)
	require.Equal(t, http.StatusOK, w.Code)

	var resp generated.A2AAgentsListResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	require.Len(t, resp.Surfaces, 2, "only the two a2a surfaces should be listed")

	// Spot-check stamped URLs (trailing-slash on prefix is trimmed).
	paths := map[string]generated.A2ASurfaceResponse{}
	for _, s := range resp.Surfaces {
		paths[s.Path] = s
	}
	report, ok := paths["/agents/report-generator"]
	require.True(t, ok)
	require.NotNil(t, report.PublicUrl)
	assert.Equal(t, "https://agents.acme.com/agents/report-generator", *report.PublicUrl)
	require.NotNil(t, report.AgentCardUrl)
	assert.Equal(t,
		"https://agents.acme.com/agents/report-generator/.well-known/agent.json",
		*report.AgentCardUrl)
	assert.Equal(t, "generate-report", report.SkillId)

	lookup, ok := paths["/agents/lookup"]
	require.True(t, ok)
	assert.Equal(t, "quick-lookup", lookup.SkillId)
}

// TestA2AListAgentsEndpointEmpty verifies the endpoint returns an empty
// (non-nil) surfaces array when no a2a agents are registered. This matches
// the OpenAPI required-field contract.
func TestA2AListAgentsEndpointEmpty(t *testing.T) {
	service := setupTestService(t)
	handlers := NewEntBusinessLogicHandlers(service)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	generated.RegisterHandlers(router, handlers)

	w := httptest.NewRecorder()
	httpReq, err := http.NewRequest(http.MethodGet, "/a2a/agents", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	router.ServeHTTP(w, httpReq)
	require.Equal(t, http.StatusOK, w.Code)

	var resp generated.A2AAgentsListResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.NotNil(t, resp.Surfaces)
	assert.Len(t, resp.Surfaces, 0)
}

// TestExtractSurfacesFromMetadata sanity-checks the input-shape tolerance
// of extractSurfacesFromMetadata. Inbound surfaces can arrive as either
// []interface{} (typical JSON unmarshal path) or []map[string]interface{}
// (if the caller pre-shaped them); both must work.
func TestExtractSurfacesFromMetadata(t *testing.T) {
	t.Run("absent", func(t *testing.T) {
		assert.Nil(t, extractSurfacesFromMetadata(map[string]interface{}{}))
	})
	t.Run("nil", func(t *testing.T) {
		assert.Nil(t, extractSurfacesFromMetadata(map[string]interface{}{"surfaces": nil}))
	})
	t.Run("interface_slice", func(t *testing.T) {
		out := extractSurfacesFromMetadata(map[string]interface{}{
			"surfaces": []interface{}{
				map[string]interface{}{"path": "/x", "skill_id": "s1"},
			},
		})
		require.Len(t, out, 1)
		assert.Equal(t, "/x", out[0]["path"])
	})
	t.Run("map_slice", func(t *testing.T) {
		out := extractSurfacesFromMetadata(map[string]interface{}{
			"surfaces": []map[string]interface{}{
				{"path": "/y", "skill_id": "s2"},
			},
		})
		require.Len(t, out, 1)
		assert.Equal(t, "/y", out[0]["path"])
	})
}

// TestComputeA2ASurfaceURLs covers the URL-stamping helper in isolation:
// trailing-slash trimming, prefix-unset behavior, and missing-leading-slash
// path normalization.
func TestComputeA2ASurfaceURLs(t *testing.T) {
	t.Run("with_trailing_slash_in_prefix", func(t *testing.T) {
		t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "https://agents.acme.com/")
		pub, card := computeA2ASurfaceURLs("/agents/x")
		assert.Equal(t, "https://agents.acme.com/agents/x", pub)
		assert.Equal(t, "https://agents.acme.com/agents/x/.well-known/agent.json", card)
	})
	t.Run("path_missing_leading_slash", func(t *testing.T) {
		t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "https://agents.acme.com")
		pub, _ := computeA2ASurfaceURLs("agents/y")
		assert.Equal(t, "https://agents.acme.com/agents/y", pub)
	})
	t.Run("prefix_unset", func(t *testing.T) {
		t.Setenv("MCP_MESH_PUBLIC_URL_PREFIX", "")
		pub, card := computeA2ASurfaceURLs("/agents/z")
		assert.Equal(t, "", pub)
		assert.Equal(t, "", card)
	})
}
