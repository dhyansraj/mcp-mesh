package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/dependencyresolution"

	_ "github.com/mattn/go-sqlite3"
)

// TestStoreDependencyResolutions_ResolvedDependency tests storing a resolved dependency
func TestStoreDependencyResolutions_ResolvedDependency(t *testing.T) {
	service := setupTestService(t)
	ctx := context.Background()

	// Register provider agent (system-agent)
	providerReq := &AgentRegistrationRequest{
		AgentID: "system-agent-test",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "system-agent",
			"http_host":  "127.0.0.1",
			"http_port":  9091,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "get_current_time",
					"capability":    "date_service",
					"version":       "1.0.0",
					"tags":          []interface{}{"system", "time"},
					"description":   "Get current time",
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	_, err := service.RegisterAgent(providerReq)
	if err != nil {
		t.Fatalf("Failed to register provider agent: %v", err)
	}

	// Register consumer agent with dependency
	consumerReq := &AgentRegistrationRequest{
		AgentID: "consumer-agent-test",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "consumer-agent",
			"http_host":  "127.0.0.1",
			"http_port":  8080,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "analyze_data",
					"capability":    "analysis",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability": "date_service",
							"tags":       []interface{}{"system", "time"},
							"version":    "",
							"namespace":  "default",
						},
					},
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	resp, err := service.RegisterAgent(consumerReq)
	if err != nil {
		t.Fatalf("Failed to register consumer agent: %v", err)
	}

	// Verify dependency was resolved in response
	if len(resp.DependenciesResolved) == 0 {
		t.Fatal("Expected dependencies_resolved in response")
	}
	if deps, ok := resp.DependenciesResolved["analyze_data"]; !ok || len(deps) == 0 {
		t.Fatal("Expected resolved dependency for analyze_data function")
	}

	// TEST: Query dependency_resolutions table to verify persistence
	resolutions, err := service.entDB.DependencyResolution.
		Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer-agent-test")).
		All(ctx)

	if err != nil {
		t.Fatalf("Failed to query dependency resolutions: %v", err)
	}

	if len(resolutions) == 0 {
		t.Fatal("Expected dependency resolution to be stored in database")
	}

	resolution := resolutions[0]

	// Verify resolution details
	if resolution.ConsumerFunctionName != "analyze_data" {
		t.Errorf("Expected function_name 'analyze_data', got %s", resolution.ConsumerFunctionName)
	}
	if resolution.CapabilityRequired != "date_service" {
		t.Errorf("Expected capability 'date_service', got %s", resolution.CapabilityRequired)
	}
	if resolution.Status != dependencyresolution.StatusAvailable {
		t.Errorf("Expected status 'available', got %s", resolution.Status)
	}
	if resolution.ProviderAgentID == nil || *resolution.ProviderAgentID != "system-agent-test" {
		t.Errorf("Expected provider_agent_id 'system-agent-test', got %v", resolution.ProviderAgentID)
	}
	if resolution.ProviderFunctionName == nil || *resolution.ProviderFunctionName != "get_current_time" {
		t.Errorf("Expected provider_function_name 'get_current_time', got %v", resolution.ProviderFunctionName)
	}
	if resolution.Endpoint == nil {
		t.Error("Expected endpoint to be set")
	}
}

// TestStoreDependencyResolutions_UnresolvedDependency tests storing an unresolved dependency
func TestStoreDependencyResolutions_UnresolvedDependency(t *testing.T) {
	service := setupTestService(t)
	ctx := context.Background()

	// Register consumer agent with dependency that cannot be resolved
	consumerReq := &AgentRegistrationRequest{
		AgentID: "consumer-agent-test",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "consumer-agent",
			"http_host":  "127.0.0.1",
			"http_port":  8080,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "analyze_data",
					"capability":    "analysis",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability": "weather_service", // This doesn't exist
							"tags":       []interface{}{"weather"},
							"version":    "",
							"namespace":  "default",
						},
					},
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	_, err := service.RegisterAgent(consumerReq)
	if err != nil {
		t.Fatalf("Failed to register consumer agent: %v", err)
	}

	// TEST: Query dependency_resolutions table
	resolutions, err := service.entDB.DependencyResolution.
		Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer-agent-test")).
		All(ctx)

	if err != nil {
		t.Fatalf("Failed to query dependency resolutions: %v", err)
	}

	if len(resolutions) == 0 {
		t.Fatal("Expected unresolved dependency to be stored in database")
	}

	resolution := resolutions[0]

	// Verify unresolved dependency details
	if resolution.ConsumerFunctionName != "analyze_data" {
		t.Errorf("Expected function_name 'analyze_data', got %s", resolution.ConsumerFunctionName)
	}
	if resolution.CapabilityRequired != "weather_service" {
		t.Errorf("Expected capability 'weather_service', got %s", resolution.CapabilityRequired)
	}
	if resolution.Status != dependencyresolution.StatusUnresolved {
		t.Errorf("Expected status 'unresolved', got %s", resolution.Status)
	}
	if resolution.ProviderAgentID != nil {
		t.Errorf("Expected provider_agent_id to be NULL for unresolved, got %v", resolution.ProviderAgentID)
	}
	if resolution.ProviderFunctionName != nil {
		t.Errorf("Expected provider_function_name to be NULL for unresolved, got %v", resolution.ProviderFunctionName)
	}
	if resolution.Endpoint != nil {
		t.Errorf("Expected endpoint to be NULL for unresolved, got %v", resolution.Endpoint)
	}
}

// TestTopologyChange_AgentOffline tests updating dependency status when provider goes offline
func TestTopologyChange_AgentOffline(t *testing.T) {
	service := setupTestService(t)
	ctx := context.Background()

	// Register provider
	providerReq := &AgentRegistrationRequest{
		AgentID: "provider-agent",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "provider",
			"http_host":  "127.0.0.1",
			"http_port":  9091,
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "provide_service",
					"capability":    "service",
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	_, err := service.RegisterAgent(providerReq)
	if err != nil {
		t.Fatalf("Failed to register provider: %v", err)
	}

	// Register consumer with dependency
	consumerReq := &AgentRegistrationRequest{
		AgentID: "consumer-agent",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "consumer",
			"http_host":  "127.0.0.1",
			"http_port":  8080,
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "use_service",
					"capability":    "user",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability": "service",
						},
					},
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	_, err = service.RegisterAgent(consumerReq)
	if err != nil {
		t.Fatalf("Failed to register consumer: %v", err)
	}

	// Verify dependency is available
	resolutions, err := service.entDB.DependencyResolution.
		Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer-agent")).
		All(ctx)
	if err != nil || len(resolutions) == 0 {
		t.Fatal("Expected dependency resolution")
	}
	if resolutions[0].Status != dependencyresolution.StatusAvailable {
		t.Fatal("Expected status 'available'")
	}

	// TEST: Mark provider as offline and update dependency status
	err = service.UpdateDependencyStatusOnAgentOffline(ctx, "provider-agent")
	if err != nil {
		t.Fatalf("Failed to update dependency status: %v", err)
	}

	// Verify dependency status changed to unavailable
	resolutions, err = service.entDB.DependencyResolution.
		Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer-agent")).
		All(ctx)
	if err != nil || len(resolutions) == 0 {
		t.Fatal("Expected dependency resolution")
	}
	if resolutions[0].Status != dependencyresolution.StatusUnavailable {
		t.Errorf("Expected status 'unavailable', got %s", resolutions[0].Status)
	}
}

// TestCapabilityDependenciesPersisted_RegisterPath verifies that the per-tool
// `dependencies` payload (including schema-match fields like
// expected_schema_hash) is written to capabilities.dependencies, not just
// counted. Regression for the schema browser inverse index (issue #971): the
// meshui ListSchemaUsage endpoint reads cap.Dependencies[i]["expected_schema_hash"]
// to find consumers of a given hash; if this column is NULL the consumers
// array is always empty.
func TestCapabilityDependenciesPersisted_RegisterPath(t *testing.T) {
	service := setupTestService(t)
	ctx := context.Background()

	expectedHash := "sha256:" +
		"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

	req := &AgentRegistrationRequest{
		AgentID: "consumer-with-schema-dep",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "weather-consumer",
			"http_host":  "127.0.0.1",
			"http_port":  8080,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "summarize",
					"capability":    "summarization",
					"version":       "1.0.0",
					// Mirrors what ent_handlers.go produces after the camelCase ->
					// snake_case normalization at the wire boundary.
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability":                "weather_report",
							"namespace":                 "default",
							"match_mode":                "subset",
							"expected_schema_hash":      expectedHash,
							"expected_schema_canonical": map[string]interface{}{"type": "object"},
						},
					},
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	if _, err := service.RegisterAgent(req); err != nil {
		t.Fatalf("RegisterAgent failed: %v", err)
	}

	caps, err := service.entDB.Capability.
		Query().
		Where(capability.HasAgentWith(agent.IDEQ("consumer-with-schema-dep"))).
		All(ctx)
	if err != nil {
		t.Fatalf("Failed to query capabilities: %v", err)
	}
	if len(caps) != 1 {
		t.Fatalf("Expected 1 capability, got %d", len(caps))
	}

	deps := caps[0].Dependencies
	if len(deps) == 0 {
		t.Fatal("Expected capabilities.dependencies to be populated, got empty")
	}
	if deps[0]["capability"] != "weather_report" {
		t.Errorf("Expected dep capability 'weather_report', got %v", deps[0]["capability"])
	}
	if deps[0]["expected_schema_hash"] != expectedHash {
		t.Errorf("Expected expected_schema_hash=%q, got %v", expectedHash, deps[0]["expected_schema_hash"])
	}
	if deps[0]["match_mode"] != "subset" {
		t.Errorf("Expected match_mode='subset', got %v", deps[0]["match_mode"])
	}
}

// TestCapabilityDependenciesPersisted_HeartbeatPath verifies the same
// plumbing on the heartbeat-with-tools code path (which is what running
// agents actually hit after their initial registration).
func TestCapabilityDependenciesPersisted_HeartbeatPath(t *testing.T) {
	service := setupTestService(t)
	ctx := context.Background()

	// Initial registration with no deps.
	regReq := &AgentRegistrationRequest{
		AgentID: "consumer-hb",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "weather-consumer-hb",
			"http_host":  "127.0.0.1",
			"http_port":  8081,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "summarize",
					"capability":    "summarization",
					"version":       "1.0.0",
				},
			},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
	if _, err := service.RegisterAgent(regReq); err != nil {
		t.Fatalf("RegisterAgent failed: %v", err)
	}

	expectedHash := "sha256:" +
		"abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

	// Heartbeat WITH tools (falls back to full re-registration path).
	hbReq := &HeartbeatRequest{
		AgentID: "consumer-hb",
		Status:  "healthy",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "weather-consumer-hb",
			"http_host":  "127.0.0.1",
			"http_port":  8081,
			"namespace":  "default",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "summarize",
					"capability":    "summarization",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability":           "weather_report",
							"match_mode":           "subset",
							"expected_schema_hash": expectedHash,
						},
					},
				},
			},
		},
	}
	resp, err := service.UpdateHeartbeat(hbReq)
	if err != nil {
		t.Fatalf("UpdateHeartbeat failed: %v", err)
	}
	if resp.Status != "success" {
		t.Fatalf("Expected heartbeat success, got %s: %s", resp.Status, resp.Message)
	}

	caps, err := service.entDB.Capability.
		Query().
		Where(capability.HasAgentWith(agent.IDEQ("consumer-hb"))).
		All(ctx)
	if err != nil {
		t.Fatalf("Failed to query capabilities: %v", err)
	}
	if len(caps) != 1 {
		t.Fatalf("Expected 1 capability, got %d", len(caps))
	}
	deps := caps[0].Dependencies
	if len(deps) == 0 {
		t.Fatal("Expected capabilities.dependencies to be populated after heartbeat-with-tools, got empty")
	}
	if deps[0]["expected_schema_hash"] != expectedHash {
		t.Errorf("Expected expected_schema_hash=%q, got %v", expectedHash, deps[0]["expected_schema_hash"])
	}
}
