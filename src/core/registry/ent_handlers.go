package registry

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/generated"
)

// Package-level proxy configuration parsed once at init (#769)
var (
	proxyPropagateHeaderEntries []string
	proxyDefaultTimeout         = 60 * time.Second
)

func init() {
	// Parse MCP_MESH_PROPAGATE_HEADERS. Each comma-separated entry is either an
	// exact header name (e.g., "authorization") or a prefix with trailing "*"
	// (e.g., "x-trace-*"). Matching is performed in proxyRequest below.
	//
	// Baked-in defaults (always forwarded, regardless of this env var):
	//   X-Trace-ID, X-Parent-Span, X-Mesh-Timeout, X-Mesh-Job-Id
	// MCP_MESH_PROPAGATE_HEADERS is purely *additive* on top of the defaults.
	// TODO(test): extract this parser into a pure helper so it can be unit-tested
	// without env-var mutation. Coverage today is via integration tests.
	if raw := os.Getenv("MCP_MESH_PROPAGATE_HEADERS"); raw != "" {
		entries := strings.Split(raw, ",")
		for _, e := range entries {
			e = strings.TrimSpace(strings.ToLower(e))
			if e == "" {
				continue
			}
			// Reject zero-length prefix matchers (e.g. "*" alone) which would match
			// every header and re-introduce the credential leakage class #790 was
			// meant to prevent.
			if strings.TrimSuffix(e, "*") == "" {
				log.Printf("[propagate-headers] ignoring entry %q: zero-length prefix would match all headers", e)
				continue
			}
			proxyPropagateHeaderEntries = append(proxyPropagateHeaderEntries, e)
		}
	}
	if envTimeout := os.Getenv("MCP_MESH_PROXY_TIMEOUT"); envTimeout != "" {
		if secs, err := strconv.Atoi(envTimeout); err == nil && secs > 0 {
			if secs > 600 {
				secs = 600 // Cap at 10 minutes
			}
			proxyDefaultTimeout = time.Duration(secs) * time.Second
		}
	}
}

// EntBusinessLogicHandlers implements the generated server interface using EntService
//
// Lifecycle/shutdown coordination
// -------------------------------
// Some handlers spawn best-effort background goroutines (notably
// ``forwardCancelToOwner`` in ``ent_handlers_jobs.go``) that outlive the
// inbound request. Those goroutines pull their context from
// ``shutdownCtx`` and register their lifetime on ``shutdownWG`` so the
// registry's graceful-shutdown path (``Server.Stop``) can:
//
//  1. Cancel ``shutdownCtx`` — in-flight HTTP forwards observe the
//     cancellation on their ``http.Request`` context and return promptly
//     instead of running to their per-call timeout.
//  2. Wait on ``shutdownWG`` — the shutdown sequence either drains the
//     forwards or surfaces the wait-timeout in the log (so an operator
//     sees that some forwards were abandoned), rather than letting them
//     run on a background goroutine after the process is supposedly
//     stopped.
//
// When the handlers are constructed via ``NewEntBusinessLogicHandlers``
// (no shutdown context provided — used by tests and older callers), the
// background goroutines fall back to ``context.Background()`` and a
// no-op WaitGroup so the existing best-effort behaviour is preserved.
type EntBusinessLogicHandlers struct {
	entService *EntService
	startTime  time.Time

	// shutdownCtx, when non-nil, gates background goroutines spawned
	// from request handlers (cancel-forward, etc). It is cancelled by
	// ``Server.Stop`` and the goroutines pass it as the request context
	// for outbound HTTP calls so a registry shutdown cleanly aborts
	// in-flight forwards.
	shutdownCtx context.Context
	// shutdownWG tracks those goroutines so ``Server.Stop`` can wait for
	// them to drain (or log the ones that didn't). Always non-nil so
	// handlers can call ``Add``/``Done`` unconditionally; when no
	// shutdown coordination is wired in (tests), it's a fresh local
	// WaitGroup and ``Wait`` is never called.
	shutdownWG *sync.WaitGroup
}

// NewEntBusinessLogicHandlers creates a new handler instance using EntService
//
// Background goroutines spawned by handlers fall back to a detached
// ``context.Background()`` and a private WaitGroup — i.e. NO shutdown
// coordination. Production code paths should prefer
// :func:`NewEntBusinessLogicHandlersWithShutdown` which wires the
// registry's graceful-shutdown context in. This constructor is kept for
// the test suite (where the registry never calls ``Stop``) and to
// preserve the legacy zero-arg surface.
func NewEntBusinessLogicHandlers(entService *EntService) *EntBusinessLogicHandlers {
	return &EntBusinessLogicHandlers{
		entService: entService,
		startTime:  time.Now().UTC(),
		shutdownWG: &sync.WaitGroup{},
	}
}

// NewEntBusinessLogicHandlersWithShutdown is the production constructor
// that wires the registry's graceful-shutdown context and WaitGroup
// into the handlers. Background goroutines (``forwardCancelToOwner``)
// derive their HTTP-request context from ``shutdownCtx`` so a server
// shutdown cancels in-flight forwards cleanly, and they register on
// ``shutdownWG`` so the shutdown sequence can wait for them to drain.
//
// ``shutdownCtx`` MUST be the context produced by the caller's shutdown
// machinery (typically ``context.WithCancel`` whose ``cancel`` is
// invoked from ``Server.Stop``). ``shutdownWG`` MUST be the same
// WaitGroup the shutdown sequence calls ``Wait`` on.
func NewEntBusinessLogicHandlersWithShutdown(
	entService *EntService,
	shutdownCtx context.Context,
	shutdownWG *sync.WaitGroup,
) *EntBusinessLogicHandlers {
	if shutdownWG == nil {
		shutdownWG = &sync.WaitGroup{}
	}
	return &EntBusinessLogicHandlers{
		entService:  entService,
		startTime:   time.Now().UTC(),
		shutdownCtx: shutdownCtx,
		shutdownWG:  shutdownWG,
	}
}

// GetHealth implements GET /health
func (h *EntBusinessLogicHandlers) GetHealth(c *gin.Context) {
	uptime := time.Since(h.startTime).Seconds()

	response := generated.HealthResponse{
		Status:        "healthy",
		Version:       "1.0.0",
		UptimeSeconds: int(uptime),
		Timestamp:     time.Now().UTC(),
		Service:       "mcp-mesh-registry",
	}

	c.JSON(http.StatusOK, response)
}

// HeadHealth implements HEAD /health
func (h *EntBusinessLogicHandlers) HeadHealth(c *gin.Context) {
	uptime := time.Since(h.startTime).Seconds()

	// Set the same headers as GET /health but without response body
	c.Header("Content-Type", "application/json")
	// Optional: Add custom headers that indicate health status
	c.Header("X-Health-Status", "healthy")
	c.Header("X-Service-Version", "1.0.0")
	c.Header("X-Uptime-Seconds", fmt.Sprintf("%d", int(uptime)))

	c.Status(http.StatusOK)
}

// GetRoot implements GET /
func (h *EntBusinessLogicHandlers) GetRoot(c *gin.Context) {
	endpoints := []string{"/health", "/heartbeat", "/agents"}

	response := generated.RootResponse{
		Service:   "mcp-mesh-registry",
		Version:   "1.0.0",
		Status:    "running",
		Endpoints: endpoints,
	}

	c.JSON(http.StatusOK, response)
}

// SendHeartbeat implements POST /heartbeat using EntService
func (h *EntBusinessLogicHandlers) SendHeartbeat(c *gin.Context) {
	var req generated.MeshAgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Convert to heartbeat request format (lighter than full registration)
	metadata := ConvertMeshAgentRegistrationToMap(req)
	heartbeatReq := &HeartbeatRequest{
		AgentID:  req.AgentId,
		Status:   "healthy", // Default status
		Metadata: metadata,
	}

	// Extract entity_id from TLS verification (set by TLSVerifyMiddleware)
	if entityID, exists := c.Get("entity_id"); exists {
		if eid, ok := entityID.(string); ok && eid != "" {
			heartbeatReq.EntityID = eid
		}
	}

	// Call lightweight heartbeat service method using EntService
	serviceResp, err := h.entService.UpdateHeartbeat(heartbeatReq)
	if err != nil {
		status := http.StatusBadRequest
		msg := err.Error()
		if errors.Is(err, ErrEntityIDMismatch) {
			status = http.StatusForbidden
			msg = "entity_id mismatch: agent owned by another entity" // sanitized — full detail in server log
		}
		c.JSON(status, generated.ErrorResponse{
			Error:     msg,
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Convert service response to API response
	var status generated.MeshRegistrationResponseStatus
	if serviceResp.Status == "success" {
		status = generated.MeshRegistrationResponseStatusSuccess
	} else {
		status = generated.MeshRegistrationResponseStatusError
	}

	// The generated MeshRegistrationResponse now carries a kwargs field on each
	// resolved dependency entry, so the typed struct serializes the producer's
	// @mesh.tool kwargs back to the consumer's proxy (issue #850 / #645 bug 2).
	response := generated.MeshRegistrationResponse{
		AgentId:   req.AgentId,
		Status:    status,
		Timestamp: time.Now().UTC(),
		Message:   serviceResp.Message,
	}

	// Include dependency resolution if available (heartbeat with tools should return dependencies)
	if serviceResp.DependenciesResolved != nil {
		depsMap := make(map[string][]struct {
			AgentId      string                                                       `json:"agent_id"`
			Capability   string                                                       `json:"capability"`
			Endpoint     string                                                       `json:"endpoint"`
			FunctionName string                                                       `json:"function_name"`
			Kwargs       *map[string]interface{}                                      `json:"kwargs,omitempty"`
			Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
		})

		for functionName, deps := range serviceResp.DependenciesResolved {
			if len(deps) > 0 {
				depsList := make([]struct {
					AgentId      string                                                       `json:"agent_id"`
					Capability   string                                                       `json:"capability"`
					Endpoint     string                                                       `json:"endpoint"`
					FunctionName string                                                       `json:"function_name"`
					Kwargs       *map[string]interface{}                                      `json:"kwargs,omitempty"`
					Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
				}, len(deps))
				for i, dep := range deps {
					var kwargs *map[string]interface{}
					if len(dep.Kwargs) > 0 {
						k := dep.Kwargs
						kwargs = &k
					}
					depsList[i] = struct {
						AgentId      string                                                       `json:"agent_id"`
						Capability   string                                                       `json:"capability"`
						Endpoint     string                                                       `json:"endpoint"`
						FunctionName string                                                       `json:"function_name"`
						Kwargs       *map[string]interface{}                                      `json:"kwargs,omitempty"`
						Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
					}{
						AgentId:      dep.AgentID,
						Capability:   dep.Capability,
						Endpoint:     dep.Endpoint,
						FunctionName: dep.FunctionName,
						Kwargs:       kwargs,
						Status:       generated.MeshRegistrationResponseDependenciesResolvedStatus(dep.Status),
					}
				}
				depsMap[functionName] = depsList
			}
		}
		response.DependenciesResolved = &depsMap
	}

	// Include LLM tools if available
	if serviceResp.LLMTools != nil {
		llmToolsMap := make(map[string][]generated.LLMToolInfo)

		for functionName, tools := range serviceResp.LLMTools {
			// IMPORTANT: Always add function key, even if tools array is empty.
			// This supports standalone LLM agents (filter=None case) that don't need tools.
			// The Python client needs to receive {"function_name": []} to create
			// a MeshLlmAgent with empty tools (answers using only model + system prompt).
			generatedTools := make([]generated.LLMToolInfo, len(tools))
			for i, tool := range tools {
				// Convert registry.LLMToolInfo to generated.LLMToolInfo
				generatedTools[i] = generated.LLMToolInfo{
					Name:        tool.Name,
					Capability:  tool.Capability,
					Description: tool.Description,
					Endpoint:    tool.Endpoint,
					InputSchema: tool.InputSchema,
					Tags:        &tool.Tags,
					Version:     &tool.Version,
				}
			}
			llmToolsMap[functionName] = generatedTools
		}
		// Always include llmToolsMap in response (even if empty)
		// This enables LLM agents to receive {"function_name": []} for standalone agents
		response.LlmTools = &llmToolsMap
	}

	// Include LLM providers if available (v0.6.1 mesh delegation)
	if serviceResp.LLMProviders != nil && len(serviceResp.LLMProviders) > 0 {
		llmProvidersMap := make(map[string]generated.ResolvedLLMProvider)
		for functionName, provider := range serviceResp.LLMProviders {
			if provider != nil {
				llmProvidersMap[functionName] = *provider
			}
		}
		response.LlmProviders = &llmProvidersMap
	}

	// Include A2A surfaces with stamped FQDNs when present (issue #903).
	// Triggers the warn-once if MCP_MESH_PUBLIC_URL_PREFIX is unset for an
	// a2a registration so operators see the misconfiguration.
	if len(serviceResp.A2ASurfaces) > 0 {
		h.maybeWarnPublicURLPrefixUnset()
		if surfacesResp := buildA2ASurfaceResponses(serviceResp.A2ASurfaces); surfacesResp != nil {
			response.Surfaces = &surfacesResp
		}
	}

	// Surface non-fatal advisories from the registry (issue #969). Currently
	// only used for description-truncation warnings; the slice stays absent
	// from the wire when empty (omitempty semantics via field skip).
	if len(serviceResp.Warnings) > 0 {
		response.Warnings = &serviceResp.Warnings
	}

	c.JSON(http.StatusOK, response)
}

// ListAgents implements GET /agents using EntService
func (h *EntBusinessLogicHandlers) ListAgents(c *gin.Context) {
	// Parse query parameters
	var params AgentQueryParams
	if err := c.ShouldBindQuery(&params); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid query parameters: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Call service method to get agents using EntService
	serviceResp, err := h.entService.ListAgents(&params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Service response is already in the correct format
	response := *serviceResp

	c.JSON(http.StatusOK, response)
}

// derefStringOr returns the dereferenced string pointer value, or the fallback if nil.
func derefStringOr(p *string, fallback string) string {
	if p != nil {
		return *p
	}
	return fallback
}

// derefStringType returns the string value of a typed pointer, or the fallback if nil.
// Used for generated enum types that have an underlying string type.
func derefStringType[T ~string](p *T, fallback string) string {
	if p != nil {
		return string(*p)
	}
	return fallback
}

// ConvertMeshAgentRegistrationToMap converts generated.MeshAgentRegistration to map[string]interface{}
// for compatibility with the service layer
func ConvertMeshAgentRegistrationToMap(reg generated.MeshAgentRegistration) map[string]interface{} {
	result := make(map[string]interface{})

	// Basic agent information
	result["name"] = derefStringOr(reg.Name, reg.AgentId)
	result["agent_type"] = derefStringType(reg.AgentType, "mcp_agent")
	if reg.Namespace != nil {
		result["namespace"] = *reg.Namespace
	}
	if reg.Version != nil {
		result["version"] = *reg.Version
	}
	if reg.Description != nil {
		result["description"] = *reg.Description
	}
	// Issue #972: forward A2A producer/consumer flags. These pointers may be
	// nil from old-SDK clients that don't set them — the downstream
	// extractAgentMetadata uses the `hasA2a*` guards so absence is a no-op.
	if reg.A2aProducer != nil {
		result["a2a_producer"] = *reg.A2aProducer
	}
	if reg.A2aConsumer != nil {
		result["a2a_consumer"] = *reg.A2aConsumer
	}
	if reg.Runtime != nil {
		result["runtime"] = string(*reg.Runtime)
	}
	if reg.HttpHost != nil {
		result["http_host"] = *reg.HttpHost
	}
	if reg.HttpPort != nil {
		result["http_port"] = *reg.HttpPort
	}

	// Store tools information for potential future use
	var toolsData []interface{}
	if reg.Tools != nil {
		toolsData = make([]interface{}, len(reg.Tools))
		for i, tool := range reg.Tools {
		toolData := map[string]interface{}{
			"function_name": tool.FunctionName,
			"capability":    tool.Capability,
		}
		if tool.Description != nil {
			toolData["description"] = *tool.Description
		}
		if tool.Version != nil {
			toolData["version"] = *tool.Version
		}
		if tool.Tags != nil {
			toolData["tags"] = *tool.Tags
		}
		if tool.InputSchema != nil {
			toolData["inputSchema"] = *tool.InputSchema
		}
		// Schema-aware filtering inputs (issue #547). Forwarded to ent_service
		// upsertSchemaEntry; absence preserves legacy behavior (no canonical stored).
		if tool.OutputSchema != nil {
			toolData["outputSchema"] = *tool.OutputSchema
		}
		if tool.InputSchemaCanonical != nil {
			toolData["inputSchemaCanonical"] = *tool.InputSchemaCanonical
		}
		if tool.InputSchemaHash != nil {
			toolData["inputSchemaHash"] = *tool.InputSchemaHash
		}
		if tool.OutputSchemaCanonical != nil {
			toolData["outputSchemaCanonical"] = *tool.OutputSchemaCanonical
		}
		if tool.OutputSchemaHash != nil {
			toolData["outputSchemaHash"] = *tool.OutputSchemaHash
		}
		if tool.SchemaWarnings != nil {
			toolData["schemaWarnings"] = *tool.SchemaWarnings
		}
		if tool.LlmFilter != nil {
			toolData["llm_filter"] = *tool.LlmFilter
		}
		if tool.LlmProvider != nil {
			toolData["llm_provider"] = *tool.LlmProvider
		}
		if tool.Dependencies != nil {
			deps := make([]map[string]interface{}, len(*tool.Dependencies))
			for j, dep := range *tool.Dependencies {
				depData := map[string]interface{}{
					"capability": dep.Capability,
				}
				if dep.Namespace != nil {
					depData["namespace"] = *dep.Namespace
				}
				if dep.Tags != nil {
					// Convert union type items to actual values (string or []string for OR alternatives)
					tags := make([]interface{}, len(*dep.Tags))
					for k, tagItem := range *dep.Tags {
						// Try to extract as string first
						if str, err := tagItem.AsMeshToolDependencyRegistrationTags0(); err == nil {
							tags[k] = str
						} else if arr, err := tagItem.AsMeshToolDependencyRegistrationTags1(); err == nil {
							// OR alternative: convert []string to []interface{} for parseDependencySpec
							arrInterface := make([]interface{}, len(arr))
							for m, s := range arr {
								arrInterface[m] = s
							}
							tags[k] = arrInterface
						}
					}
					depData["tags"] = tags
				}
				if dep.Version != nil {
					depData["version"] = *dep.Version
				}
				// Schema-aware filtering inputs (issue #547). Forwarded to the
				// resolver's schema stage; absence keeps the stage a pass-through.
				if dep.MatchMode != nil {
					depData["match_mode"] = string(*dep.MatchMode)
				}
				if dep.ExpectedSchemaHash != nil {
					depData["expected_schema_hash"] = *dep.ExpectedSchemaHash
				}
				if dep.ExpectedSchemaCanonical != nil {
					depData["expected_schema_canonical"] = *dep.ExpectedSchemaCanonical
				}
				deps[j] = depData
			}
			toolData["dependencies"] = deps
		}
		if tool.Kwargs != nil {
			toolData["kwargs"] = *tool.Kwargs
		}
			toolsData[i] = toolData
		}
	}
	result["tools"] = toolsData

	// A2A surfaces (issue #903 / A2A_SURFACE_DESIGN.org). Forwarded as
	// []map[string]interface{} so the service layer can persist directly to
	// the Ent JSON field. Omitted entirely when not present.
	if reg.Surfaces != nil {
		surfaces := make([]map[string]interface{}, 0, len(*reg.Surfaces))
		for _, s := range *reg.Surfaces {
			entry := map[string]interface{}{
				"path":     s.Path,
				"skill_id": s.SkillId,
			}
			if s.Name != nil {
				entry["name"] = *s.Name
			}
			if s.Description != nil {
				entry["description"] = *s.Description
			}
			if s.InputModes != nil {
				entry["input_modes"] = *s.InputModes
			}
			if s.OutputModes != nil {
				entry["output_modes"] = *s.OutputModes
			}
			if s.Tags != nil {
				entry["tags"] = *s.Tags
			}
			surfaces = append(surfaces, entry)
		}
		result["surfaces"] = surfaces
	}

	return result
}

// FastHeartbeatCheck implements HEAD /heartbeat/{agent_id}
func (h *EntBusinessLogicHandlers) FastHeartbeatCheck(c *gin.Context, agentId string) {
	// Check if agent exists in registry
	agentEntity, err := h.entService.GetAgent(c.Request.Context(), agentId)
	if err != nil || agentEntity == nil {
		// Unknown agent - please register with POST heartbeat
		c.Status(http.StatusGone) // 410
		return
	}

	// Issue #955: an agent marked unhealthy by startup cleanup or the
	// health monitor must re-register via POST /heartbeat before it can
	// transition back to healthy. Allowing a bare HEAD ping to revive it
	// bypasses metadata refresh and lets orphans from a prior session
	// (with stale endpoint / capabilities) silently re-claim a healthy
	// row forever. The SDK clients (Rust core / Python) already map 410
	// to AGENT_UNKNOWN → requires_full_heartbeat() → POST re-register.
	if agentEntity.Status == agent.StatusUnhealthy {
		c.Status(http.StatusGone) // 410 — please re-register via POST
		return
	}

	// Update agent timestamp to indicate recent activity (prevents health monitor eviction).
	// Unhealthy→Healthy transitions are NOT handled here — see the 410 short-circuit above (#955).
	err = h.entService.UpdateAgentHeartbeatTimestamp(c.Request.Context(), agentId)
	if err != nil {
		// Service error - back off and retry
		c.Status(http.StatusServiceUnavailable) // 503
		return
	}

	// Check for topology changes since last full refresh
	hasChanges, err := h.entService.HasTopologyChanges(c.Request.Context(), agentId, agentEntity.LastFullRefresh)
	if err != nil {
		// Service error - back off and retry
		c.Status(http.StatusServiceUnavailable) // 503
		return
	}

	// Capability-scoped pending-jobs hint (MESHJOB_DESIGN.org > Wire
	// Protocol > HEAD heartbeat extension). Best-effort: a query failure
	// here must not break the heartbeat — the producer will discover the
	// pending work on the next tick. Header is set BEFORE c.Status(...)
	// because Gin commits headers when the status line is written.
	if pending, perr := h.entService.CountPendingJobsForAgent(c.Request.Context(), agentId); perr == nil && pending > 0 {
		c.Header("X-Mesh-Pending-Jobs", strconv.Itoa(pending))
	}

	if hasChanges {
		// Topology changed - please send full POST heartbeat
		c.Status(http.StatusAccepted) // 202
		return
	}

	// No changes - keep sending HEAD requests
	c.Status(http.StatusOK) // 200
}

// UnregisterAgent implements DELETE /agents/{agent_id}
func (h *EntBusinessLogicHandlers) UnregisterAgent(c *gin.Context, agentId string) {
	err := h.entService.UnregisterAgent(c.Request.Context(), agentId)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Return 204 No Content - successfully unregistered (idempotent)
	c.Status(http.StatusNoContent)
}

// ListEvents implements GET /events
// Returns recent registry events with optional filters by event type, agent ID,
// and function name. Used by `meshctl audit` to surface dependency-resolution
// decisions; lifecycle events are also queryable through this endpoint.
func (h *EntBusinessLogicHandlers) ListEvents(c *gin.Context, params generated.ListEventsParams) {
	limit := 50
	if params.Limit != nil {
		limit = *params.Limit
		if limit < 1 {
			limit = 1
		}
		if limit > 500 {
			limit = 500
		}
	}

	eventType := ""
	if params.Type != nil {
		eventType = string(*params.Type)
	}
	agentID := ""
	if params.AgentId != nil {
		agentID = *params.AgentId
	}
	functionName := ""
	if params.FunctionName != nil {
		functionName = *params.FunctionName
	}

	events, err := h.entService.ListRecentEventsFiltered(limit, eventType, agentID, functionName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to query events: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	eventInfos := make([]generated.RegistryEventInfo, 0, len(events))
	for _, e := range events {
		info := generated.RegistryEventInfo{
			EventType: generated.RegistryEventInfoEventType(e.EventType),
			AgentId:   e.AgentID,
			Timestamp: e.Timestamp,
		}
		if e.AgentName != "" {
			name := e.AgentName
			info.AgentName = &name
		}
		if e.FunctionName != "" {
			fn := e.FunctionName
			info.FunctionName = &fn
		}
		if len(e.Data) > 0 {
			data := e.Data
			info.Data = &data
		}
		eventInfos = append(eventInfos, info)
	}

	c.JSON(http.StatusOK, generated.EventsHistoryResponse{
		Count:  len(eventInfos),
		Events: eventInfos,
	})
}

// ProxyMcpRequest implements POST /proxy/{target}
// Acts as a reverse proxy for MCP requests to internal agents
func (h *EntBusinessLogicHandlers) ProxyMcpRequest(c *gin.Context, target string) {
	h.proxyRequest(c, target, "POST")
}

// ProxyMcpGetRequest implements GET /proxy/{target}
// Acts as a reverse proxy for MCP GET requests to internal agents
func (h *EntBusinessLogicHandlers) ProxyMcpGetRequest(c *gin.Context, target string) {
	h.proxyRequest(c, target, "GET")
}

// proxyRequest handles the actual proxying logic for both GET and POST
func (h *EntBusinessLogicHandlers) proxyRequest(c *gin.Context, target string, method string) {
	// Parse target: expected format is {host}:{port}/mcp/...
	// Example: hello-world-agent:8080/mcp/v1/tools/call

	// Find the first / to split host:port from path
	slashIdx := strings.Index(target, "/")
	if slashIdx == -1 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Invalid target format: missing path. Expected format: {host}:{port}/mcp/{path}",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	hostPort := target[:slashIdx]
	path := target[slashIdx:] // Includes the leading /

	// Security: Only allow /mcp or /mcp/* paths
	if path != "/mcp" && !strings.HasPrefix(path, "/mcp/") {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Only /mcp/* paths are allowed for proxying",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Security: Validate target is a registered agent
	isRegistered, scheme, endpointHost, err := h.isRegisteredAgentEndpoint(c.Request.Context(), hostPort)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to validate agent: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	if !isRegistered {
		c.JSON(http.StatusForbidden, generated.ErrorResponse{
			Error:     fmt.Sprintf("Target host '%s' is not a registered agent", hostPort),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Build target URL using the matched replica's actual registered endpoint host
	// when available. Falls back to the user-supplied hostPort if the registered
	// endpoint host could not be determined (direct host:port match path is a no-op
	// since endpointHost == hostPort there).
	dialHost := endpointHost
	if dialHost == "" {
		dialHost = hostPort
	}
	targetURL := fmt.Sprintf("%s://%s%s", scheme, dialHost, path)

	// Create the proxied request
	var reqBody io.Reader
	if method == "POST" {
		reqBody = c.Request.Body
	}

	proxyReq, err := http.NewRequestWithContext(c.Request.Context(), method, targetURL, reqBody)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to create proxy request: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Copy relevant headers
	proxyReq.Header.Set("Content-Type", c.Request.Header.Get("Content-Type"))
	if accept := c.Request.Header.Get("Accept"); accept != "" {
		proxyReq.Header.Set("Accept", accept)
	}

	// Forward trace headers for distributed tracing (Issue #310)
	if traceID := c.Request.Header.Get("X-Trace-ID"); traceID != "" {
		proxyReq.Header.Set("X-Trace-ID", traceID)
	}
	if parentSpan := c.Request.Header.Get("X-Parent-Span"); parentSpan != "" {
		proxyReq.Header.Set("X-Parent-Span", parentSpan)
	}

	// Forward X-Mesh-Timeout so downstream agents can propagate it further (#769)
	if meshTimeout := c.Request.Header.Get("X-Mesh-Timeout"); meshTimeout != "" {
		proxyReq.Header.Set("X-Mesh-Timeout", meshTimeout)
	}

	// Forward X-Mesh-Job-Id so the producer's tool wrapper can bind the
	// MeshJob controller to the correct job row. Treated as a baked-in
	// default header (like trace + timeout) so installations work out of the
	// box without setting MCP_MESH_PROPAGATE_HEADERS. See MESHJOB_DESIGN.org
	// "Wire Protocol / Headers".
	if meshJobID := c.Request.Header.Get("X-Mesh-Job-Id"); meshJobID != "" {
		proxyReq.Header.Set("X-Mesh-Job-Id", meshJobID)
	}

	// Names already set explicitly above — don't duplicate via propagation.
	// MCP_MESH_PROPAGATE_HEADERS is additive on top of these baked-in defaults;
	// the env var does not need to (and should not) re-list them.
	explicitlySet := map[string]bool{
		"content-type":   true,
		"accept":         true,
		"x-trace-id":     true,
		"x-parent-span":  true,
		"x-mesh-timeout": true,
		"x-mesh-job-id":  true,
	}

	// Forward headers matching MCP_MESH_PROPAGATE_HEADERS allowlist (#769, #790).
	// Entries are exact matches by default; a trailing "*" denotes a prefix.
	if len(proxyPropagateHeaderEntries) > 0 {
		for headerName, values := range c.Request.Header {
			lowerName := strings.ToLower(headerName)
			if explicitlySet[lowerName] {
				continue
			}
			for _, entry := range proxyPropagateHeaderEntries {
				matches := false
				if strings.HasSuffix(entry, "*") {
					matches = strings.HasPrefix(lowerName, strings.TrimSuffix(entry, "*"))
				} else {
					matches = lowerName == entry
				}
				if matches {
					for _, v := range values {
						proxyReq.Header.Add(headerName, v)
					}
					break
				}
			}
		}
	}

	// Respect client timeout if provided via X-Mesh-Timeout header (#656)
	proxyTimeout := proxyDefaultTimeout
	if timeoutHeader := c.Request.Header.Get("X-Mesh-Timeout"); timeoutHeader != "" {
		if secs, err := strconv.Atoi(timeoutHeader); err == nil && secs > 0 {
			if secs > 600 {
				secs = 600 // Cap at 10 minutes
			}
			proxyTimeout = time.Duration(secs) * time.Second
		}
	}
	// http.Client is cheap to build per request; the expensive part (the
	// Transport with its connection pool + TLS material) is shared. Plain
	// HTTP rides http.DefaultTransport's pool; HTTPS uses the cached mTLS
	// transport below. Client.Timeout covers the full exchange including the
	// streamed body, preserving the X-Mesh-Timeout cap.
	client := &http.Client{
		Timeout: proxyTimeout,
	}

	// Configure TLS transport for HTTPS targets (mTLS proxy support).
	// The transport is built once and cached; it is rebuilt automatically if
	// the CA/cert/key files change on disk (mtime/size check per request).
	if scheme == "https" {
		// Require the full mTLS bundle for HTTPS proxy calls.
		caPath := os.Getenv("MCP_MESH_TLS_CA")
		certPath := os.Getenv("MCP_MESH_TLS_CERT")
		keyPath := os.Getenv("MCP_MESH_TLS_KEY")
		if caPath == "" || certPath == "" || keyPath == "" {
			log.Printf("ERROR: HTTPS proxy requires MCP_MESH_TLS_CA, MCP_MESH_TLS_CERT, MCP_MESH_TLS_KEY (ca=%q, cert=%q, key=%q)", caPath, certPath, keyPath)
			c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
				Error:     "Proxy TLS misconfiguration: missing required TLS environment variables for HTTPS proxy",
				Timestamp: time.Now().UTC(),
			})
			return
		}

		transport, err := getProxyTLSTransport(caPath, certPath, keyPath)
		if err != nil {
			log.Printf("ERROR: %v", err)
			// Sanitize response: full detail (paths, OS errors) stays in server log only (#794).
			c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
				Error:     "Proxy TLS misconfiguration",
				Timestamp: time.Now().UTC(),
			})
			return
		}
		client.Transport = transport
	}

	resp, err := client.Do(proxyReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to reach target agent: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	defer resp.Body.Close()

	// Copy response headers (Add, not Set, to preserve multi-value headers).
	for key, values := range resp.Header {
		for _, value := range values {
			c.Writer.Header().Add(key, value)
		}
	}
	c.Status(resp.StatusCode)

	// Stream the body instead of buffering it whole: large tool results don't
	// balloon registry memory, and SSE responses reach the client as they are
	// produced. Flush after every chunk so streamed (SSE) responses aren't
	// held back by the response writer's buffer; gin's ResponseWriter
	// implements http.Flusher.
	buf := make([]byte, 32*1024)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := c.Writer.Write(buf[:n]); werr != nil {
				// Client went away — nothing useful left to do.
				return
			}
			c.Writer.Flush()
		}
		if rerr != nil {
			if rerr != io.EOF {
				log.Printf("WARNING: proxy stream from %s ended early: %v", targetURL, rerr)
			}
			return
		}
	}
}

// proxyTLSCacheEntry holds the cached mTLS transport for the proxy along with
// the on-disk identity (path + mtime + size) of the material it was built
// from, so cert rotation is picked up without restarting the registry.
type proxyTLSCacheEntry struct {
	transport *http.Transport
	caPath    string
	certPath  string
	keyPath   string
	caStamp   fileStamp
	certStamp fileStamp
	keyStamp  fileStamp
}

type fileStamp struct {
	modTime time.Time
	size    int64
}

var (
	proxyTLSCacheMu sync.Mutex
	proxyTLSCache   *proxyTLSCacheEntry
)

func stampFile(path string) (fileStamp, error) {
	fi, err := os.Stat(path)
	if err != nil {
		return fileStamp{}, err
	}
	return fileStamp{modTime: fi.ModTime(), size: fi.Size()}, nil
}

// getProxyTLSTransport returns the shared mTLS transport for /proxy/* HTTPS
// calls, building it on first use and rebuilding it if any of the CA, cert,
// or key files change (path or content stamp). The per-request cost is three
// os.Stat calls instead of reading + parsing the full PEM material.
//
// Hostname verification is intentionally skipped because --tls-auto generates
// certs with SANs for 127.0.0.1/::1 only, while agents in K8s bind to pod
// IPs. We still verify the peer cert chain against our mesh CA so only certs
// issued by the same CA are accepted. Target legitimacy is already enforced
// by isRegisteredAgentEndpoint().
func getProxyTLSTransport(caPath, certPath, keyPath string) (*http.Transport, error) {
	caStamp, err := stampFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("failed to stat CA cert %s: %w", caPath, err)
	}
	certStamp, err := stampFile(certPath)
	if err != nil {
		return nil, fmt.Errorf("failed to stat client cert %s: %w", certPath, err)
	}
	keyStamp, err := stampFile(keyPath)
	if err != nil {
		return nil, fmt.Errorf("failed to stat client key %s: %w", keyPath, err)
	}

	proxyTLSCacheMu.Lock()
	defer proxyTLSCacheMu.Unlock()

	if e := proxyTLSCache; e != nil &&
		e.caPath == caPath && e.certPath == certPath && e.keyPath == keyPath &&
		e.caStamp == caStamp && e.certStamp == certStamp && e.keyStamp == keyStamp {
		return e.transport, nil
	}

	caCert, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read CA cert %s: %w", caPath, err)
	}
	caCertPool := x509.NewCertPool()
	if !caCertPool.AppendCertsFromPEM(caCert) {
		return nil, fmt.Errorf("failed to parse CA cert from %s (empty or malformed PEM)", caPath)
	}

	clientCert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("failed to load client cert/key (%s, %s): %w", certPath, keyPath, err)
	}

	// Skip hostname check but verify the cert chain against our CA.
	tlsConfig := &tls.Config{
		InsecureSkipVerify: true,
		Certificates:       []tls.Certificate{clientCert},
		VerifyConnection: func(cs tls.ConnectionState) error {
			if len(cs.PeerCertificates) == 0 {
				return fmt.Errorf("no peer certificates presented")
			}
			opts := x509.VerifyOptions{
				Roots:         caCertPool,
				Intermediates: x509.NewCertPool(),
			}
			for _, cert := range cs.PeerCertificates[1:] {
				opts.Intermediates.AddCert(cert)
			}
			_, err := cs.PeerCertificates[0].Verify(opts)
			return err
		},
	}

	// Close idle connections of the transport we're replacing so a rotation
	// doesn't leave stale TLS sessions pooled forever.
	if proxyTLSCache != nil && proxyTLSCache.transport != nil {
		proxyTLSCache.transport.CloseIdleConnections()
	}

	proxyTLSCache = &proxyTLSCacheEntry{
		transport: &http.Transport{TLSClientConfig: tlsConfig},
		caPath:    caPath,
		certPath:  certPath,
		keyPath:   keyPath,
		caStamp:   caStamp,
		certStamp: certStamp,
		keyStamp:  keyStamp,
	}
	return proxyTLSCache.transport, nil
}

// isRegisteredAgentEndpoint checks if the given host:port is a registered agent.
// Returns (isRegistered, scheme, endpointHost, error) where scheme is "http" or
// "https" and endpointHost is the matched replica's actual registered endpoint
// host (e.g., K8s service DNS) — used by the proxy to dial the real endpoint
// rather than the user-supplied hostPort when matching via Id/Name fallback.
func (h *EntBusinessLogicHandlers) isRegisteredAgentEndpoint(ctx context.Context, hostPort string) (bool, string, string, error) {
	// Parse host and port
	parts := strings.Split(hostPort, ":")
	if len(parts) != 2 {
		return false, "", "", nil // Invalid format
	}

	host := parts[0]
	portInt, err := strconv.Atoi(parts[1])
	if err != nil || portInt <= 0 {
		return false, "", "", nil // Invalid port
	}

	// Narrow query instead of loading ALL agents with four eager edges per
	// proxy call: only agents on the requested port whose HTTP host, ID, or
	// name matches the requested host can possibly satisfy the checks below.
	candidates, err := h.entService.entDB.Client.Agent.
		Query().
		Where(
			agent.HTTPPortEQ(portInt),
			agent.HTTPHostNEQ(""),
			agent.Or(
				agent.HTTPHostEQ(host),
				agent.IDEQ(host),
				agent.NameEQ(host),
			),
		).
		All(ctx)
	if err != nil {
		return false, "", "", err
	}

	// Prefer the direct host:port match, mirroring the historical behavior of
	// "exact endpoint match wins over ID/Name fallback".
	//
	// Scheme derivation matches ListAgents: https when the agent registered
	// with a TLS entity identity, http otherwise.
	schemeFor := func(a *ent.Agent) string {
		if a.EntityID != nil && *a.EntityID != "" {
			return "https"
		}
		return "http"
	}
	for _, a := range candidates {
		if a.HTTPHost == host {
			return true, schemeFor(a), fmt.Sprintf("%s:%d", a.HTTPHost, a.HTTPPort), nil
		}
	}

	// Match by agent ID (primary: callers use full agent IDs like "fortuna-abc12345").
	// Also match by agent Name as a fallback for future base-name proxying
	// (e.g., /proxy/fortuna:8080 -> any replica named "fortuna") and to stay
	// backward-compatible with old SDK versions that sent Name == ID.
	//
	// Matching by Name as a fallback is intentional — it routes to an
	// arbitrary replica when multiple share a base name. The registry
	// proxy is a dev/test convenience and replica targeting is not a
	// dev concern; to target a specific replica, port-forward to it
	// directly.
	for _, a := range candidates {
		if a.ID == host || a.Name == host {
			return true, schemeFor(a), fmt.Sprintf("%s:%d", a.HTTPHost, a.HTTPPort), nil
		}
	}

	return false, "", "", nil
}
