package registry

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
	_ "github.com/mattn/go-sqlite3"
)

// TestResolveLLMProvider tests the core provider resolution logic for LLM mesh delegation
func TestResolveLLMProvider(t *testing.T) {
	// Setup: Create database with test data
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Create LLM provider agents
	claudeAgent, _ := client.Agent.Create().
		SetID("claude-provider").
		SetName("Claude Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9020).
		Save(ctx)

	gptAgent, _ := client.Agent.Create().
		SetID("gpt-provider").
		SetName("GPT Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9021).
		Save(ctx)

	budgetAgent, _ := client.Agent.Create().
		SetID("budget-llm-provider").
		SetName("Budget LLM Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9022).
		Save(ctx)

	// Create LLM provider capabilities
	// Claude provider with advanced tags
	client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("Claude Sonnet LLM provider").
		SetTags([]string{"claude", "sonnet", "production"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(claudeAgent).
		Save(ctx)

	// GPT provider
	client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("GPT-4 LLM provider").
		SetTags([]string{"openai", "gpt4", "production"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(gptAgent).
		Save(ctx)

	// Budget provider
	client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("Budget LLM provider (GPT-3.5)").
		SetTags([]string{"openai", "budget", "test"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(budgetAgent).
		Save(ctx)

	tests := []struct {
		name             string
		providerSpec     map[string]interface{}
		expectMatch      bool
		expectedAgentID  string
		expectedEndpoint string
	}{
		{
			name: "match_by_capability_only",
			providerSpec: map[string]interface{}{
				"capability": "llm",
			},
			expectMatch:      true,
			expectedAgentID:  "claude-provider", // First match wins
			expectedEndpoint: "http://localhost:9020",
		},
		{
			name: "match_by_capability_and_tags",
			providerSpec: map[string]interface{}{
				"capability": "llm",
				"tags":       []interface{}{"claude", "sonnet"},
			},
			expectMatch:      true,
			expectedAgentID:  "claude-provider",
			expectedEndpoint: "http://localhost:9020",
		},
		{
			name: "match_gpt_with_tags",
			providerSpec: map[string]interface{}{
				"capability": "llm",
				"tags":       []interface{}{"openai", "gpt4"},
			},
			expectMatch:      true,
			expectedAgentID:  "gpt-provider",
			expectedEndpoint: "http://localhost:9021",
		},
		{
			name: "match_budget_provider",
			providerSpec: map[string]interface{}{
				"capability": "llm",
				"tags":       []interface{}{"budget"},
			},
			expectMatch:      true,
			expectedAgentID:  "budget-llm-provider",
			expectedEndpoint: "http://localhost:9022",
		},
		{
			name: "no_match_wrong_capability",
			providerSpec: map[string]interface{}{
				"capability": "nonexistent",
			},
			expectMatch: false,
		},
		{
			name: "no_match_wrong_tags",
			providerSpec: map[string]interface{}{
				"capability": "llm",
				"tags":       []interface{}{"nonexistent", "tag"},
			},
			expectMatch: false,
		},
		{
			name: "version_constraint_satisfied",
			providerSpec: map[string]interface{}{
				"capability": "llm",
				"version":    ">=1.0.0",
			},
			expectMatch:      true,
			expectedAgentID:  "claude-provider", // First match
			expectedEndpoint: "http://localhost:9020",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// This is the function we need to implement
			provider, err := ResolveProvider(ctx, client, tt.providerSpec)

			// Handle error case
			if err != nil && !tt.expectMatch {
				// Error is acceptable when no match expected
				return
			}
			require.NoError(t, err)

			if tt.expectMatch {
				require.NotNil(t, provider)

				assert.Equal(t, tt.expectedAgentID, provider.AgentId)
				assert.Equal(t, tt.expectedEndpoint, provider.Endpoint)
				assert.Equal(t, "process_chat", provider.Name)
				assert.Equal(t, "llm", provider.Capability)
				assert.Equal(t, generated.ResolvedLLMProviderStatusAvailable, provider.Status)
				assert.NotNil(t, provider.Tags)
				assert.NotNil(t, provider.Version)
			} else {
				// No match expected - should return nil or error
				assert.Nil(t, provider)
			}
		})
	}
}

// TestResolveLLMProvidersFromMetadata tests the integration with heartbeat metadata
func TestResolveLLMProvidersFromMetadata(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Create LLM provider agent
	providerAgent, _ := client.Agent.Create().
		SetID("claude-provider").
		SetName("Claude Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9020).
		Save(ctx)

	// Create provider capability
	client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("Claude provider").
		SetTags([]string{"claude", "production"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(providerAgent).
		Save(ctx)

	// Create a mock service with logger
	testConfig := &config.Config{LogLevel: "INFO"}
	testLog := logger.New(testConfig)
	service := &EntService{
		entDB:  &database.EntDatabase{Client: client},
		logger: testLog,
	}

	tests := []struct {
		name         string
		metadata     map[string]interface{}
		expectResult bool
		expectedKey  string
	}{
		{
			name: "tool_with_llm_provider_spec",
			metadata: map[string]interface{}{
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "chat",
						"capability":    "chat",
						"llm_provider": map[string]interface{}{
							"capability": "llm",
							"tags":       []interface{}{"claude"},
							"version":    "1.0.0",
						},
					},
				},
			},
			expectResult: true,
			expectedKey:  "chat",
		},
		{
			name: "tool_without_llm_provider",
			metadata: map[string]interface{}{
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "simple_tool",
						"capability":    "simple",
					},
				},
			},
			expectResult: false,
		},
		{
			name: "multiple_tools_mixed",
			metadata: map[string]interface{}{
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "simple_tool",
						"capability":    "simple",
					},
					map[string]interface{}{
						"function_name": "chat",
						"capability":    "chat",
						"llm_provider": map[string]interface{}{
							"capability": "llm",
							"tags":       []interface{}{"claude"},
						},
					},
				},
			},
			expectResult: true,
			expectedKey:  "chat",
		},
		{
			name:         "no_tools_in_metadata",
			metadata:     map[string]interface{}{},
			expectResult: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// This is the function we need to implement
			providers, err := service.ResolveLLMProvidersFromMetadata(ctx, "test-agent", tt.metadata)
			require.NoError(t, err)

			if tt.expectResult {
				assert.NotEmpty(t, providers)
				assert.Contains(t, providers, tt.expectedKey)

				provider := providers[tt.expectedKey]
				assert.Equal(t, "claude-provider", provider.AgentId)
				assert.Equal(t, "http://localhost:9020", provider.Endpoint)
				assert.Equal(t, "llm", provider.Capability)
				assert.Equal(t, generated.ResolvedLLMProviderStatusAvailable, provider.Status)
			} else {
				assert.Empty(t, providers)
			}
		})
	}
}

// TestResolveProvider_ReturnsKwargs_OnResolvedLLMProvider verifies that
// provider tool kwargs (e.g. stream_type=text from @mesh.llm_provider's
// auto-generated streaming variant) are surfaced on the ResolvedLLMProvider
// returned to the consumer. This is the registry-side half of the streaming
// kwargs plumbing for issue #849 Stage A.
func TestResolveProvider_ReturnsKwargs_OnResolvedLLMProvider(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	streamingAgent, err := client.Agent.Create().
		SetID("claude-streaming-provider").
		SetName("Claude Streaming Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9030).
		Save(ctx)
	require.NoError(t, err)

	// Provider capability with kwargs that mirror what @mesh.llm_provider
	// stamps onto the auto-generated streaming variant.
	_, err = client.Capability.Create().
		SetFunctionName("process_chat_stream").
		SetCapability("llm").
		SetDescription("Streaming Claude provider").
		SetTags([]string{"claude", "stream"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetKwargs(map[string]interface{}{
			"stream_type": "text",
			"vendor":      "anthropic",
		}).
		SetAgent(streamingAgent).
		Save(ctx)
	require.NoError(t, err)

	provider, err := ResolveProvider(ctx, client, map[string]interface{}{
		"capability": "llm",
		"tags":       []interface{}{"claude", "stream"},
	})
	require.NoError(t, err)
	require.NotNil(t, provider)

	require.NotNil(t, provider.Kwargs, "ResolvedLLMProvider.Kwargs must be populated when capability has kwargs")
	kwargs := *provider.Kwargs
	assert.Equal(t, "text", kwargs["stream_type"], "stream_type must round-trip through ResolveProvider")
	assert.Equal(t, "anthropic", kwargs["vendor"], "vendor must round-trip through ResolveProvider")
}

// TestResolveProvider_NoKwargs_OmitsKwargsField verifies the default case —
// when a provider capability has no kwargs, ResolvedLLMProvider.Kwargs stays
// nil. Important for forward-compat: older Rust core with `#[serde(default)]`
// on the new field won't choke on a missing key.
func TestResolveProvider_NoKwargs_OmitsKwargsField(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	bareAgent, err := client.Agent.Create().
		SetID("bare-provider").
		SetName("Bare Provider").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9031).
		Save(ctx)
	require.NoError(t, err)

	_, err = client.Capability.Create().
		SetFunctionName("process_chat").
		SetCapability("llm").
		SetDescription("Bare provider with no kwargs").
		SetTags([]string{"bare"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"messages": map[string]interface{}{"type": "array"},
			},
		}).
		SetAgent(bareAgent).
		Save(ctx)
	require.NoError(t, err)

	provider, err := ResolveProvider(ctx, client, map[string]interface{}{
		"capability": "llm",
		"tags":       []interface{}{"bare"},
	})
	require.NoError(t, err)
	require.NotNil(t, provider)
	assert.Nil(t, provider.Kwargs, "Kwargs must be nil when the provider capability ships no kwargs")
}
