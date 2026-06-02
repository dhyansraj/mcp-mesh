package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/schemaentry"

	_ "github.com/mattn/go-sqlite3"
)

// TestSyncCapabilitiesSchemaEntry drives the extracted syncCapabilities helper
// through its issue #547 branch: a tool carrying inputSchemaHash +
// inputSchemaCanonical must persist the hash on the Capability row and upsert a
// content-addressed schema_entries row. Covered for both the RegisterAgent and
// the UpdateHeartbeat write paths (both now share syncCapabilities).
func TestSyncCapabilitiesSchemaEntry(t *testing.T) {
	const inputHash = "sha256:deadbeefcafe"
	canonical := map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"city": map[string]interface{}{"type": "string"},
		},
	}

	toolWithSchema := func(fn string) map[string]interface{} {
		return map[string]interface{}{
			"function_name":        fn,
			"capability":           "weather_report",
			"version":              "1.0.0",
			"description":          "Returns weather",
			"inputSchemaHash":      inputHash,
			"inputSchemaCanonical": canonical,
		}
	}

	t.Run("RegisterAgentPath", func(t *testing.T) {
		service := setupTestService(t)
		ctx := context.Background()

		req := &AgentRegistrationRequest{
			AgentID: "schema-reg-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "schema-reg-agent",
				"version":    "1.0.0",
				"tools": []interface{}{
					toolWithSchema("get_weather"),
				},
			},
			Timestamp: time.Now().Format(time.RFC3339),
		}
		if _, err := service.RegisterAgent(req); err != nil {
			t.Fatalf("RegisterAgent failed: %v", err)
		}

		assertSchemaPersisted(t, service, ctx, "schema-reg-agent", inputHash)
	})

	t.Run("HeartbeatPath", func(t *testing.T) {
		service := setupTestService(t)
		ctx := context.Background()

		// Register first with no tools so the heartbeat is the path that
		// ingests the schema-bearing capability.
		regReq := &AgentRegistrationRequest{
			AgentID: "schema-hb-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "schema-hb-agent",
				"version":    "1.0.0",
			},
			Timestamp: time.Now().Format(time.RFC3339),
		}
		if _, err := service.RegisterAgent(regReq); err != nil {
			t.Fatalf("RegisterAgent failed: %v", err)
		}

		hbReq := &HeartbeatRequest{
			AgentID: "schema-hb-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"version": "1.0.0",
				"tools": []interface{}{
					toolWithSchema("get_weather"),
				},
			},
		}
		resp, err := service.UpdateHeartbeat(hbReq)
		if err != nil {
			t.Fatalf("UpdateHeartbeat failed: %v", err)
		}
		if resp.Status != "success" {
			t.Fatalf("Expected heartbeat status success, got %q", resp.Status)
		}

		assertSchemaPersisted(t, service, ctx, "schema-hb-agent", inputHash)
	})
}

func assertSchemaPersisted(t *testing.T, service *EntService, ctx context.Context, agentID, inputHash string) {
	t.Helper()

	caps, err := service.entDB.Capability.
		Query().
		Where(capability.HasAgentWith(agent.IDEQ(agentID))).
		All(ctx)
	if err != nil {
		t.Fatalf("Failed to query capabilities: %v", err)
	}
	if len(caps) != 1 {
		t.Fatalf("Expected 1 capability, got %d", len(caps))
	}
	if caps[0].InputSchemaHash == nil {
		t.Fatalf("Expected InputSchemaHash to be set, got nil")
	}
	if *caps[0].InputSchemaHash != inputHash {
		t.Errorf("Expected InputSchemaHash=%q, got %q", inputHash, *caps[0].InputSchemaHash)
	}

	exists, err := service.entDB.SchemaEntry.
		Query().
		Where(schemaentry.HashEQ(inputHash)).
		Exist(ctx)
	if err != nil {
		t.Fatalf("Failed to query schema_entries: %v", err)
	}
	if !exists {
		t.Errorf("Expected a schema_entries row for hash %q (upsertSchemaEntry side effect), found none", inputHash)
	}
}
