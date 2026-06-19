package registry

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/enttest"

	_ "github.com/mattn/go-sqlite3"
)

// seedVersionedLLMProvider creates a healthy LLM provider agent + capability at
// the given version, sharing the same capability name and tags as its siblings.
// The agent ID is keyed off the version so the resolved winner is unambiguous.
func seedVersionedLLMProvider(t *testing.T, ctx context.Context, client *ent.Client, version string, httpPort int) {
	t.Helper()
	a, err := client.Agent.Create().
		SetID("llm-provider-" + version).
		SetName("LLM Provider " + version).
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(httpPort).
		Save(ctx)
	require.NoError(t, err)

	_, err = client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("Claude Sonnet LLM provider " + version).
		SetTags([]string{"claude", "sonnet"}).
		SetVersion(version).
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(a).
		Save(ctx)
	require.NoError(t, err)
}

// TestResolveProvider_SelectsHighestSatisfyingVersion proves that the LLM
// provider resolver, driven through the real ent DB query + scoring pipeline,
// selects the HIGHEST satisfying version for a given constraint — not the
// first-registered or first-queried capability.
//
// All three providers share capability="llm" and tags=["claude","sonnet"], so
// tag score ties; the (version DESC, agentID ASC) tiebreaker is the only thing
// that can decide the winner. To prove the test exercises version ranking and
// not insertion luck, the providers are seeded in an order that would pick the
// WRONG answer for the omitted-version case if selection fell back to insertion
// order: 5.0.0 first, then 4.7.0, then 4.6.0 LAST. With agentID-ASC as the
// final tiebreaker (agent IDs sort 4.6.0 < 4.7.0 < 5.0.0), insertion order is
// irrelevant — only the version comparator can lift 5.0.0 to the top.
func TestResolveProvider_SelectsHighestSatisfyingVersion(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Seed in an order designed to defeat insertion-order shortcuts:
	// the eventual winner for the omitted-version case (5.0.0) is inserted
	// FIRST and the bare/tilde winner (4.6.0) is inserted LAST.
	seedVersionedLLMProvider(t, ctx, client, "5.0.0", 9050)
	seedVersionedLLMProvider(t, ctx, client, "4.7.0", 9047)
	seedVersionedLLMProvider(t, ctx, client, "4.6.0", 9046)

	tests := []struct {
		name            string
		version         string // provider spec "version"; empty = omitted
		expectedVersion string
		expectedAgentID string
	}{
		{
			name:            "omitted_version_picks_highest",
			version:         "",
			expectedVersion: "5.0.0",
			expectedAgentID: "llm-provider-5.0.0",
		},
		{
			name:            "caret_picks_highest_in_major",
			version:         "^4.6.0", // >=4.6.0 <5.0.0 -> 4.7.0
			expectedVersion: "4.7.0",
			expectedAgentID: "llm-provider-4.7.0",
		},
		{
			name:            "gte_picks_highest_overall",
			version:         ">=4.6.0", // -> 5.0.0
			expectedVersion: "5.0.0",
			expectedAgentID: "llm-provider-5.0.0",
		},
		{
			name:            "bare_is_exact",
			version:         "4.6.0", // bare = exact match, by design
			expectedVersion: "4.6.0",
			expectedAgentID: "llm-provider-4.6.0",
		},
		{
			name:            "tilde_only_patch_present",
			version:         "~4.6.0", // >=4.6.0 <4.7.0 -> only 4.6.0 qualifies
			expectedVersion: "4.6.0",
			expectedAgentID: "llm-provider-4.6.0",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			spec := map[string]interface{}{
				"capability": "llm",
				"tags":       []interface{}{"claude", "sonnet"},
			}
			if tt.version != "" {
				spec["version"] = tt.version
			}

			provider, err := ResolveProvider(ctx, client, spec)
			require.NoError(t, err)
			require.NotNil(t, provider, "expected a matching provider")
			require.NotNil(t, provider.Version, "resolved provider must carry a version")

			assert.Equal(t, tt.expectedVersion, *provider.Version,
				"resolver must select the highest satisfying version")
			assert.Equal(t, tt.expectedAgentID, provider.AgentId,
				"winning agent must correspond to the highest satisfying version")
		})
	}
}

// TestDependencyResolution_SelectsHighestSatisfyingVersion proves the same
// "highest satisfying version wins" behavior for the @mesh.tool dependency
// path, driven through the real RegisterAgent -> ResolveAllDependencies
// pipeline against a seeded ent DB.
//
// Three provider agents publish the SAME capability ("database_service") with
// the SAME tags (["data"]) at versions 4.6.0 / 4.7.0 / 5.0.0, each keyed to a
// distinct agent ID so the resolved winner is unambiguous from dep.AgentID.
// Providers are registered with 4.6.0 LAST so the test proves version ranking
// rather than registration order.
func TestDependencyResolution_SelectsHighestSatisfyingVersion(t *testing.T) {
	type providerSeed struct {
		agentID string
		version string
		host    string
		port    float64
	}
	// Registration order intentionally scrambled (highest first, lowest last).
	// Agent IDs use hyphens only (RegisterAgent validation forbids dots) but
	// still sort in version order so agentID-ASC cannot mask a comparator bug.
	providers := []providerSeed{
		{"db-provider-v5-0-0", "5.0.0", "db-5", 8050},
		{"db-provider-v4-7-0", "4.7.0", "db-47", 8047},
		{"db-provider-v4-6-0", "4.6.0", "db-46", 8046},
	}

	tests := []struct {
		name            string
		constraint      string // dependency version constraint; empty = omitted
		expectedAgentID string
	}{
		{"omitted_version_picks_highest", "", "db-provider-v5-0-0"},
		{"caret_picks_highest_in_major", "^4.6.0", "db-provider-v4-7-0"},
		{"gte_picks_highest_overall", ">=4.6.0", "db-provider-v5-0-0"},
		{"bare_is_exact", "4.6.0", "db-provider-v4-6-0"},
		{"tilde_only_patch_present", "~4.6.0", "db-provider-v4-6-0"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			service := setupTestService(t)

			for _, p := range providers {
				req := &AgentRegistrationRequest{
					AgentID: p.agentID,
					Metadata: map[string]interface{}{
						"agent_type": "mcp_agent",
						"name":       p.agentID,
						"version":    p.version,
						"http_host":  p.host,
						"http_port":  p.port,
						"tools": []interface{}{
							map[string]interface{}{
								"function_name": "query_db",
								"capability":    "database_service",
								"version":       p.version,
								"tags":          []string{"data"},
								"description":   "Query database",
							},
						},
					},
				}
				_, err := service.RegisterAgent(req)
				require.NoError(t, err, "provider %s registration should succeed", p.agentID)
			}

			dep := map[string]interface{}{
				"capability": "database_service",
				"tags":       []string{"data"},
			}
			if tt.constraint != "" {
				dep["version"] = tt.constraint
			}

			consumerReq := &AgentRegistrationRequest{
				AgentID: "db-consumer",
				Metadata: map[string]interface{}{
					"agent_type": "mcp_agent",
					"name":       "db-consumer",
					"version":    "1.0.0",
					"http_host":  "consumer",
					"http_port":  float64(9000),
					"tools": []interface{}{
						map[string]interface{}{
							"function_name": "use_db",
							"capability":    "app_service",
							"version":       "1.0.0",
							"dependencies":  []interface{}{dep},
							"description":   "Uses the database service",
						},
					},
				},
			}

			response, err := service.RegisterAgent(consumerReq)
			require.NoError(t, err, "consumer registration should succeed")

			deps := response.DependenciesResolved["use_db"]
			require.Len(t, deps, 1, "expected exactly one resolved dependency")
			assert.Equal(t, "available", deps[0].Status, "dependency should resolve")
			assert.Equal(t, tt.expectedAgentID, deps[0].AgentID,
				"resolver must select the agent providing the highest satisfying version")
		})
	}
}
