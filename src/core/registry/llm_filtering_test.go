package registry

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/enttest"
	_ "github.com/mattn/go-sqlite3"
)

// TestLLMToolFiltering tests the core filtering logic for LLM tool discovery
func TestLLMToolFiltering(t *testing.T) {
	// Setup: Create database with test data
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Create tool provider agents with various capabilities
	pdfAgent, _ := client.Agent.Create().
		SetID("pdf-agent").
		SetName("PDF Agent").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(8080).
		Save(ctx)

	webAgent, _ := client.Agent.Create().
		SetID("web-agent").
		SetName("Web Agent").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(8081).
		Save(ctx)

	cmdAgent, _ := client.Agent.Create().
		SetID("cmd-agent").
		SetName("Command Agent").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(8082).
		Save(ctx)

	// Create capabilities with input schemas
	pdfCap, _ := client.Capability.Create().
		SetFunctionName("extract_pdf").
		SetCapability("pdf_extractor").
		SetDescription("Extract text from PDF files").
		SetTags([]string{"document", "pdf", "advanced"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"file_path": map[string]interface{}{"type": "string"},
			},
			"required": []string{"file_path"},
		}).
		SetAgent(pdfAgent).
		Save(ctx)

	webCap, _ := client.Capability.Create().
		SetFunctionName("search_web").
		SetCapability("web_search").
		SetDescription("Search the web").
		SetTags([]string{"search", "web"}).
		SetVersion("2.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"query": map[string]interface{}{"type": "string"},
			},
			"required": []string{"query"},
		}).
		SetAgent(webAgent).
		Save(ctx)

	cmdCap, _ := client.Capability.Create().
		SetFunctionName("execute_cmd").
		SetCapability("command_executor").
		SetDescription("Execute shell commands").
		SetTags([]string{"command", "local"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"command": map[string]interface{}{"type": "string"},
			},
			"required": []string{"command"},
		}).
		SetAgent(cmdAgent).
		Save(ctx)

	tests := []struct {
		name           string
		filter         []interface{}
		filterMode     string
		expectedCount  int
		expectedNames  []string
	}{
		{
			name: "simple_capability_name_filter",
			filter: []interface{}{
				"pdf_extractor",
			},
			filterMode:    "all",
			expectedCount: 1,
			expectedNames: []string{"extract_pdf"},
		},
		{
			name: "tag_based_filter",
			filter: []interface{}{
				map[string]interface{}{
					"capability": "pdf_extractor",
					"tags":       []string{"document", "pdf"},
				},
			},
			filterMode:    "all",
			expectedCount: 1,
			expectedNames: []string{"extract_pdf"},
		},
		{
			name: "multiple_filters_all_mode",
			filter: []interface{}{
				"web_search",
				map[string]interface{}{
					"capability": "pdf_extractor",
					"tags":       []string{"document"},
				},
			},
			filterMode:    "all",
			expectedCount: 2,
			expectedNames: []string{"extract_pdf", "search_web"},
		},
		{
			name: "wildcard_filter",
			filter: []interface{}{
				"*",
			},
			filterMode:    "*",
			expectedCount: 3,
			expectedNames: []string{"extract_pdf", "search_web", "execute_cmd"},
		},
		{
			name: "tag_subset_matching",
			filter: []interface{}{
				map[string]interface{}{
					"capability": "pdf_extractor",
					"tags":       []string{"document"}, // Subset of ["document", "pdf", "advanced"]
				},
			},
			filterMode:    "all",
			expectedCount: 1,
			expectedNames: []string{"extract_pdf"},
		},
		{
			name: "no_matches",
			filter: []interface{}{
				"nonexistent_capability",
			},
			filterMode:    "all",
			expectedCount: 0,
			expectedNames: []string{},
		},
		{
			name: "best_match_mode_prefers_tags",
			filter: []interface{}{
				map[string]interface{}{
					"capability": "pdf_extractor",
					"tags":       []string{"advanced"},
				},
			},
			filterMode:    "best_match",
			expectedCount: 1,
			expectedNames: []string{"extract_pdf"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// This is the function we need to implement
			filtered, err := FilterToolsForLLM(ctx, client, tt.filter, tt.filterMode, "")
			require.NoError(t, err)

			assert.Equal(t, tt.expectedCount, len(filtered), "Expected %d tools, got %d", tt.expectedCount, len(filtered))

			if tt.expectedCount > 0 {
				actualNames := make([]string, len(filtered))
				for i, tool := range filtered {
					actualNames[i] = tool.Name
				}
				assert.ElementsMatch(t, tt.expectedNames, actualNames, "Tool names don't match")

				// Verify each tool has required fields
				for _, tool := range filtered {
					assert.NotEmpty(t, tool.Name)
					assert.NotEmpty(t, tool.Capability)
					assert.NotEmpty(t, tool.Description)
					assert.NotNil(t, tool.InputSchema, "InputSchema should not be nil")
					assert.NotEmpty(t, tool.Tags)
				}
			}
		})
	}

	// Verify actual capabilities exist for manual checking
	require.NotNil(t, pdfCap)
	require.NotNil(t, webCap)
	require.NotNil(t, cmdCap)
}

// TestLLMToolFilteringDuplicateFunctionNames tests that duplicate function names are deduplicated
// This follows the same pattern as mesh.tool dependency resolution: return first healthy match
func TestLLMToolFilteringDuplicateFunctionNames(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	// Create two agents that both provide a "chat" function with different capabilities
	agent1, _ := client.Agent.Create().
		SetID("agent1").
		SetName("Basic Chat Agent").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9001).
		Save(ctx)

	agent2, _ := client.Agent.Create().
		SetID("agent2").
		SetName("Advanced Chat Agent").
		SetNamespace("default").
		SetHTTPHost("localhost").
		SetHTTPPort(9002).
		Save(ctx)

	// Both agents provide a capability called "chat" but with different capability names
	client.Capability.Create().
		SetFunctionName("chat"). // Same function name
		SetCapability("basic_chat").
		SetDescription("Basic chat function").
		SetTags([]string{"chat", "basic"}).
		SetVersion("1.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"message": map[string]interface{}{"type": "string"},
			},
		}).
		SetAgent(agent1).
		Save(ctx)

	client.Capability.Create().
		SetFunctionName("chat"). // Same function name - DUPLICATE!
		SetCapability("advanced_chat").
		SetDescription("Advanced chat with tools").
		SetTags([]string{"chat", "advanced", "tools"}).
		SetVersion("2.0.0").
		SetInputSchema(map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"message": map[string]interface{}{"type": "string"},
			},
		}).
		SetAgent(agent2).
		Save(ctx)

	tests := []struct {
		name          string
		filter        []interface{}
		filterMode    string
		expectedCount int
		description   string
	}{
		{
			name: "wildcard_deduplicates_by_function_name",
			filter: []interface{}{
				"*",
			},
			filterMode:    "*",
			expectedCount: 1, // Should return only ONE "chat", not two
			description:   "Wildcard should deduplicate by function name (first match wins)",
		},
		{
			name: "all_mode_deduplicates_by_function_name",
			filter: []interface{}{
				"basic_chat",
				"advanced_chat",
			},
			filterMode:    "all",
			expectedCount: 1, // Both match different capabilities but same function name
			description:   "All mode should deduplicate by function name (first match wins)",
		},
		{
			name: "best_match_deduplicates_by_function_name",
			filter: []interface{}{
				map[string]interface{}{
					"tags": []string{"chat"}, // Both have "chat" tag
				},
			},
			filterMode:    "best_match",
			expectedCount: 1, // Should return only ONE "chat"
			description:   "Best match should deduplicate by function name",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			filtered, err := FilterToolsForLLM(ctx, client, tt.filter, tt.filterMode, "")
			require.NoError(t, err)

			assert.Equal(t, tt.expectedCount, len(filtered),
				"%s: Expected %d tools, got %d. Function names must be unique for LLM APIs.",
				tt.description, tt.expectedCount, len(filtered))

			// Verify the returned tool is named "chat"
			if len(filtered) > 0 {
				assert.Equal(t, "chat", filtered[0].FunctionName)
			}

			// Verify no duplicate function names in result
			functionNames := make(map[string]bool)
			for _, tool := range filtered {
				if functionNames[tool.Name] {
					t.Errorf("Duplicate function name found: %s. LLM APIs require unique function names.", tool.Name)
				}
				functionNames[tool.Name] = true
			}
		})
	}
}

// TestLLMToolFilteringWithVersionConstraints tests version-based filtering
func TestLLMToolFilteringWithVersionConstraints(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	ctx := context.Background()

	agent, _ := client.Agent.Create().
		SetID("versioned-agent").
		SetName("Versioned Agent").
		SetNamespace("default").
		Save(ctx)

	// Create multiple versions of same capability
	client.Capability.Create().
		SetFunctionName("service_v1").
		SetCapability("api_service").
		SetVersion("1.0.0").
		SetTags([]string{"api"}).
		SetInputSchema(map[string]interface{}{"type": "object"}).
		SetAgent(agent).
		Save(ctx)

	client.Capability.Create().
		SetFunctionName("service_v2").
		SetCapability("api_service").
		SetVersion("2.0.0").
		SetTags([]string{"api", "v2"}).
		SetInputSchema(map[string]interface{}{"type": "object"}).
		SetAgent(agent).
		Save(ctx)

	tests := []struct {
		name          string
		filter        []interface{}
		filterMode    string
		expectedCount int
		expectedName  string
	}{
		{
			name: "version_constraint_gte",
			filter: []interface{}{
				map[string]interface{}{
					"capability": "api_service",
					"version":    ">=2.0.0",
				},
			},
			filterMode:    "all",
			expectedCount: 1,
			expectedName:  "service_v2",
		},
		{
			name: "best_match_prefers_latest_version",
			filter: []interface{}{
				map[string]interface{}{
					"capability": "api_service",
				},
			},
			filterMode:    "best_match",
			expectedCount: 1,
			expectedName:  "service_v2", // Should pick latest version
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			filtered, err := FilterToolsForLLM(ctx, client, tt.filter, tt.filterMode, "")
			require.NoError(t, err)

			assert.Equal(t, tt.expectedCount, len(filtered))
			if tt.expectedCount > 0 {
				assert.Equal(t, tt.expectedName, filtered[0].FunctionName)
			}
		})
	}
}
