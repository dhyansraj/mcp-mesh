package registry

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/enttest"
	_ "github.com/mattn/go-sqlite3"
)

// TestCapabilityInputSchemaStorage tests storing and retrieving input_schema in Capability entity
func TestCapabilityInputSchemaStorage(t *testing.T) {
	tests := []struct {
		name        string
		inputSchema map[string]interface{}
		expectNil   bool
	}{
		{
			name: "valid_json_schema",
			inputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"file_path": map[string]interface{}{
						"type":        "string",
						"description": "Path to the PDF file",
					},
					"extract_images": map[string]interface{}{
						"type":        "boolean",
						"description": "Whether to extract images",
						"default":     false,
					},
				},
				"required": []string{"file_path"},
			},
			expectNil: false,
		},
		{
			name:        "null_input_schema",
			inputSchema: nil,
			expectNil:   true,
		},
		{
			name:        "empty_input_schema",
			inputSchema: map[string]interface{}{},
			expectNil:   false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup: Create in-memory SQLite database
			client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
			defer client.Close()

			ctx := context.Background()

			// Create test agent
			agent, err := client.Agent.Create().
				SetID("test-agent").
				SetName("Test Agent").
				SetNamespace("default").
				Save(ctx)
			require.NoError(t, err)

			// Create capability with input_schema
			capabilityBuilder := client.Capability.Create().
				SetFunctionName("extract_pdf").
				SetCapability("pdf_extractor").
				SetDescription("Extract text from PDF files").
				SetAgent(agent)

			if tt.inputSchema != nil {
				capabilityBuilder.SetInputSchema(tt.inputSchema)
			}

			capability, err := capabilityBuilder.Save(ctx)
			require.NoError(t, err)

			// Retrieve and verify
			retrieved, err := client.Capability.Get(ctx, capability.ID)
			require.NoError(t, err)

			if tt.expectNil {
				assert.Nil(t, retrieved.InputSchema, "Expected nil input_schema")
			} else {
				assert.NotNil(t, retrieved.InputSchema, "Expected non-nil input_schema")
				if tt.inputSchema != nil {
					// Verify schema matches
					expectedJSON, _ := json.Marshal(tt.inputSchema)
					actualJSON, _ := json.Marshal(retrieved.InputSchema)
					assert.JSONEq(t, string(expectedJSON), string(actualJSON))
				}
			}
		})
	}
}

// TestCapabilityLLMFilterStorage tests storing and retrieving llm_filter in Capability entity
func TestCapabilityLLMFilterStorage(t *testing.T) {
	tests := []struct {
		name      string
		llmFilter map[string]interface{}
		expectNil bool
	}{
		{
			name: "valid_llm_filter_with_multiple_filters",
			llmFilter: map[string]interface{}{
				"filter": []interface{}{
					map[string]interface{}{
						"capability": "document",
						"tags":       []string{"pdf", "advanced"},
					},
					"web_search",
					map[string]interface{}{
						"capability": "command_executor",
						"tags":       []string{"local"},
					},
				},
				"filter_mode":  "all",
				"inject_param": "llm_tools",
			},
			expectNil: false,
		},
		{
			name: "simple_filter_wildcard",
			llmFilter: map[string]interface{}{
				"filter":       []interface{}{"*"},
				"filter_mode":  "*",
				"inject_param": "llm_tools",
			},
			expectNil: false,
		},
		{
			name:      "null_llm_filter",
			llmFilter: nil,
			expectNil: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup
			client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
			defer client.Close()

			ctx := context.Background()

			// Create test agent
			agent, err := client.Agent.Create().
				SetID("llm-agent").
				SetName("LLM Agent").
				SetNamespace("default").
				Save(ctx)
			require.NoError(t, err)

			// Create capability with llm_filter
			capabilityBuilder := client.Capability.Create().
				SetFunctionName("chat").
				SetCapability("chat").
				SetDescription("Chat with LLM").
				SetAgent(agent)

			if tt.llmFilter != nil {
				capabilityBuilder.SetLlmFilter(tt.llmFilter)
			}

			capability, err := capabilityBuilder.Save(ctx)
			require.NoError(t, err)

			// Retrieve and verify
			retrieved, err := client.Capability.Get(ctx, capability.ID)
			require.NoError(t, err)

			if tt.expectNil {
				assert.Nil(t, retrieved.LlmFilter, "Expected nil llm_filter")
			} else {
				assert.NotNil(t, retrieved.LlmFilter, "Expected non-nil llm_filter")
				if tt.llmFilter != nil {
					expectedJSON, _ := json.Marshal(tt.llmFilter)
					actualJSON, _ := json.Marshal(retrieved.LlmFilter)
					assert.JSONEq(t, string(expectedJSON), string(actualJSON))
				}
			}
		})
	}
}

// TestCapabilityWithBothInputSchemaAndLLMFilter tests tools with both fields
func TestCapabilityWithBothInputSchemaAndLLMFilter(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Create test agent
	agent, err := client.Agent.Create().
		SetID("hybrid-agent").
		SetName("Hybrid Agent").
		SetNamespace("default").
		Save(ctx)
	require.NoError(t, err)

	inputSchema := map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"message": map[string]interface{}{
				"type": "string",
			},
		},
		"required": []string{"message"},
	}

	llmFilter := map[string]interface{}{
		"filter": []interface{}{
			map[string]interface{}{
				"capability": "document",
				"tags":       []string{"pdf"},
			},
		},
		"filter_mode":  "all",
		"inject_param": "llm_tools",
	}

	// Create capability with both fields
	capability, err := client.Capability.Create().
		SetFunctionName("chat").
		SetCapability("chat").
		SetDescription("Chat function with LLM and input schema").
		SetInputSchema(inputSchema).
		SetLlmFilter(llmFilter).
		SetAgent(agent).
		Save(ctx)
	require.NoError(t, err)

	// Retrieve and verify both fields
	retrieved, err := client.Capability.Get(ctx, capability.ID)
	require.NoError(t, err)

	assert.NotNil(t, retrieved.InputSchema)
	assert.NotNil(t, retrieved.LlmFilter)

	// Verify input_schema
	expectedInputJSON, _ := json.Marshal(inputSchema)
	actualInputJSON, _ := json.Marshal(retrieved.InputSchema)
	assert.JSONEq(t, string(expectedInputJSON), string(actualInputJSON))

	// Verify llm_filter
	expectedFilterJSON, _ := json.Marshal(llmFilter)
	actualFilterJSON, _ := json.Marshal(retrieved.LlmFilter)
	assert.JSONEq(t, string(expectedFilterJSON), string(actualFilterJSON))
}

// TestInputSchemaPersistenceAcrossDatabases tests JSON handling in both SQLite and PostgreSQL
func TestInputSchemaPersistenceAcrossDatabases(t *testing.T) {
	// Note: This test focuses on SQLite since it's available in test env
	// PostgreSQL tests would require Docker/real DB instance

	t.Run("sqlite_persistence", func(t *testing.T) {
		client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
		defer client.Close()

		ctx := context.Background()

		agent, err := client.Agent.Create().
			SetID("persist-agent").
			SetName("Persist Agent").
			SetNamespace("default").
			Save(ctx)
		require.NoError(t, err)

		complexSchema := map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"nested": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"field": map[string]interface{}{
							"type": "array",
							"items": map[string]interface{}{
								"type": "string",
							},
						},
					},
				},
			},
		}

		capability, err := client.Capability.Create().
			SetFunctionName("complex_func").
			SetCapability("complex").
			SetInputSchema(complexSchema).
			SetAgent(agent).
			Save(ctx)
		require.NoError(t, err)

		// Verify complex nested structure persists correctly
		retrieved, err := client.Capability.Get(ctx, capability.ID)
		require.NoError(t, err)

		expectedJSON, _ := json.Marshal(complexSchema)
		actualJSON, _ := json.Marshal(retrieved.InputSchema)
		assert.JSONEq(t, string(expectedJSON), string(actualJSON))
	})
}
