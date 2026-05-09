// A2A surface handlers and helpers.
//
// Phase 1A of issue #903 — see A2A_SURFACE_DESIGN.org. The Registry exposes
// A2A surfaces declared by a2a-typed agents (one entry per @mesh.a2a
// decorator). Two surfaces are exposed at this layer:
//
//   1. Persistence: a2a-typed agents send a `surfaces: [{path, skill_id, ...}]`
//      array on register/heartbeat. The handler stores the array as-is on the
//      agent's a2a_surfaces JSON field (Ent schema/agent.go).
//   2. Discovery: GET /a2a/agents returns every stored surface flattened with
//      registry-computed FQDNs (MCP_MESH_PUBLIC_URL_PREFIX + path).
//
// The actual A2A protocol envelope (agent card JSON, JSON-RPC tasks/* verbs,
// SSE) lives on the agent side (Phase 1B+). The registry is a discovery
// directory; nothing here knows about A2A wire shape beyond URL stamping.

package registry

import (
	"context"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// publicURLPrefixWarnOnce ensures we log the "MCP_MESH_PUBLIC_URL_PREFIX is
// unset" warning at most once per registry process, even if many a2a agents
// register before the operator notices the misconfiguration.
var publicURLPrefixWarnOnce sync.Once

// publicURLPrefix returns the configured MCP_MESH_PUBLIC_URL_PREFIX with any
// trailing slash trimmed. When unset, returns "" — callers treat empty as
// "no FQDN available; emit empty public_url / agent_card_url" rather than
// rejecting the registration. The first time this is observed during an a2a
// flow, ``warnIfMissing`` triggers a warn-once log via the supplied logger
// hook so operators see the misconfiguration without burying it.
func publicURLPrefix() string {
	return strings.TrimRight(os.Getenv("MCP_MESH_PUBLIC_URL_PREFIX"), "/")
}

// computeA2ASurfaceURLs returns (public_url, agent_card_url) for a single
// surface path. Both are empty when MCP_MESH_PUBLIC_URL_PREFIX is unset.
func computeA2ASurfaceURLs(path string) (string, string) {
	prefix := publicURLPrefix()
	if prefix == "" {
		return "", ""
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	publicURL := prefix + path
	cardURL := publicURL + "/.well-known/agent.json"
	return publicURL, cardURL
}

// extractSurfacesFromMetadata pulls the optional ``surfaces`` array out of a
// register/heartbeat metadata map and returns it in the canonical
// []map[string]interface{} shape expected by the Ent JSON field.
//
// Tolerant to absence and to slightly-different inbound shapes
// ([]interface{} vs []map[string]interface{}) so callers don't have to care
// whether the request came from the generated wrapper or a hand-built map.
func extractSurfacesFromMetadata(metadata map[string]interface{}) []map[string]interface{} {
	raw, ok := metadata["surfaces"]
	if !ok || raw == nil {
		return nil
	}

	switch arr := raw.(type) {
	case []map[string]interface{}:
		return arr
	case []interface{}:
		out := make([]map[string]interface{}, 0, len(arr))
		for _, item := range arr {
			if m, ok := item.(map[string]interface{}); ok {
				out = append(out, m)
			}
		}
		if len(out) == 0 {
			return nil
		}
		return out
	}
	return nil
}

// buildA2ASurfaceResponses converts the stored a2a_surfaces JSON shape
// (`[]map[string]interface{}`) into the wire response shape
// (`[]A2ASurfaceResponse`) with URLs stamped from MCP_MESH_PUBLIC_URL_PREFIX.
//
// Returns nil for a nil/empty input so callers can use the result directly
// in optional response fields.
func buildA2ASurfaceResponses(surfaces []map[string]interface{}) []generated.A2ASurfaceResponse {
	if len(surfaces) == 0 {
		return nil
	}
	out := make([]generated.A2ASurfaceResponse, 0, len(surfaces))
	for _, s := range surfaces {
		path, _ := s["path"].(string)
		skillID, _ := s["skill_id"].(string)
		if path == "" || skillID == "" {
			continue
		}
		publicURL, cardURL := computeA2ASurfaceURLs(path)
		entry := generated.A2ASurfaceResponse{
			Path:    path,
			SkillId: skillID,
		}
		if publicURL != "" {
			entry.PublicUrl = &publicURL
			entry.AgentCardUrl = &cardURL
		}
		out = append(out, entry)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// maybeWarnPublicURLPrefixUnset emits a single registry-lifetime warning when
// an a2a-typed agent registers without MCP_MESH_PUBLIC_URL_PREFIX configured.
// Called from the register/heartbeat path so the warning lands in the logs at
// the moment the misconfiguration becomes visible.
func (h *EntBusinessLogicHandlers) maybeWarnPublicURLPrefixUnset() {
	if publicURLPrefix() != "" {
		return
	}
	publicURLPrefixWarnOnce.Do(func() {
		if h.entService != nil && h.entService.logger != nil {
			h.entService.logger.Warning(
				"a2a-typed agent registered but MCP_MESH_PUBLIC_URL_PREFIX is unset; " +
					"public_url and agent_card_url will be empty until the operator sets it " +
					"(see A2A_SURFACE_DESIGN.org > Registry-Driven FQDN Discovery)")
		}
	})
}

// ListA2AAgents implements GET /a2a/agents — the external A2A client
// discovery endpoint. Walks every a2a-typed agent, flattens their
// a2a_surfaces JSON arrays, stamps FQDNs from MCP_MESH_PUBLIC_URL_PREFIX, and
// returns the result as a single ``surfaces`` list.
//
// Mesh-internal capability resolution stays untouched; this endpoint is the
// purely external face of the A2A discovery model.
func (h *EntBusinessLogicHandlers) ListA2AAgents(c *gin.Context) {
	ctx := c.Request.Context()

	agents, err := h.entService.entDB.Agent.Query().
		Where(agent.AgentTypeEQ(agent.AgentTypeA2a)).
		All(ctx)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     "failed to query a2a agents: " + err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	all := make([]generated.A2ASurfaceResponse, 0)
	for _, a := range agents {
		all = append(all, buildA2ASurfaceResponses(a.A2aSurfaces)...)
	}

	c.JSON(http.StatusOK, generated.A2AAgentsListResponse{
		Surfaces: all,
	})
}

// listA2ASurfacesForAgent fetches the a2a_surfaces JSON for a single agent.
// Used by the heartbeat-response path so the response carries the freshly-
// stamped surface URLs without re-querying through the typed Ent struct
// path. Returns (nil, nil) if the agent has no surfaces or doesn't exist.
func (s *EntService) listA2ASurfacesForAgent(ctx context.Context, agentID string) ([]map[string]interface{}, error) {
	a, err := s.entDB.Agent.Query().Where(agent.IDEQ(agentID)).Only(ctx)
	if err != nil {
		// Honour the doc contract: a missing agent is not an error to
		// the caller — return (nil, nil) so the heartbeat-response path
		// just emits no surfaces. The previous code returned the raw
		// not-found error, which conflated "row missing" with "DB
		// failure" and surfaced misleading 5xx-style errors upstream.
		if ent.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	return a.A2aSurfaces, nil
}
