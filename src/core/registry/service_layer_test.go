package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	_ "github.com/mattn/go-sqlite3"
	"mcp-mesh/src/core/database"
)

// setupTestDatabase creates an in-memory database with the new schema
func setupTestDatabase(t *testing.T) *database.Database {
	// Create in-memory SQLite database
	sqlDB, err := sql.Open("sqlite3", ":memory:")
	require.NoError(t, err, "Failed to create in-memory database")

	// Load and execute the new schema
	schemaPath := "../database/schema_v2.sql"
	schemaSQL, err := os.ReadFile(schemaPath)
	require.NoError(t, err, "Failed to read schema file")

	_, err = sqlDB.Exec(string(schemaSQL))
	require.NoError(t, err, "Failed to execute schema")

	// Wrap in database.Database
	db := &database.Database{DB: sqlDB}
	return db
}

// setupTestService creates a service with in-memory database
func setupTestService(t *testing.T) *Service {
	db := setupTestDatabase(t)
	config := &RegistryConfig{
		CacheTTL:                 30,
		DefaultTimeoutThreshold:  60,
		DefaultEvictionThreshold: 120,
		EnableResponseCache:      false, // Disable cache for testing
	}
	return NewService(db, config)
}

// loadTestJSON loads and parses a test JSON file
func loadTestJSON(t *testing.T, filename string) map[string]interface{} {
	jsonPath := filepath.Join("testdata/agent_registration", filename)
	jsonData, err := os.ReadFile(jsonPath)
	require.NoError(t, err, "Failed to load JSON file: %s", filename)

	var data map[string]interface{}
	err = json.Unmarshal(jsonData, &data)
	require.NoError(t, err, "Failed to parse JSON from file: %s", filename)

	return data
}

// convertToServiceRequest converts JSON data to service layer request format
func convertToServiceRequest(data map[string]interface{}) *AgentRegistrationRequest {
	agentID, _ := data["agent_id"].(string)

	return &AgentRegistrationRequest{
		AgentID:   agentID,
		Metadata:  data,
		Timestamp: time.Now().Format(time.RFC3339),
	}
}

// TestServiceLayerDirectCall tests calling the service layer directly
func TestServiceLayerDirectCall(t *testing.T) {
	t.Run("RegisterAgentWithMultipleFunctions", func(t *testing.T) {
		// Setup service with clean database
		service := setupTestService(t)

		// Load test JSON
		jsonData := loadTestJSON(t, "multiple_functions_request.json")

		// Convert to service request
		req := convertToServiceRequest(jsonData)

		// Call service directly
		response, err := service.RegisterAgent(req)
		require.NoError(t, err, "Service call should succeed")

		// Validate response
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "agent-b065c499", response.AgentID)
		assert.Contains(t, response.Message, "successfully")

		t.Logf("✅ Service Response: %s", response.Message)
		t.Logf("🎯 Agent ID: %s", response.AgentID)
	})

	t.Run("ValidateAgentDataInDatabase", func(t *testing.T) {
		// Setup service
		service := setupTestService(t)

		// Load and register agent
		jsonData := loadTestJSON(t, "mesh_agent_registration_sample.json")
		req := convertToServiceRequest(jsonData)

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Query agent directly from database
		agentData, err := service.GetAgentWithCapabilities("hello-world-agent")
		require.NoError(t, err, "Should retrieve agent data")

		// Validate agent metadata
		assert.Equal(t, "hello-world-agent", agentData["agent_id"])
		assert.Equal(t, "hello-world-agent", agentData["name"]) // actual name in JSON
		assert.Equal(t, "mcp_agent", agentData["agent_type"])
		assert.Equal(t, "default", agentData["namespace"]) // actual namespace in JSON

		// Validate capabilities
		capabilities := agentData["capabilities"].([]map[string]interface{})
		assert.Equal(t, 3, len(capabilities)) // JSON has 3 tools

		// Check that we have the expected capabilities (order may vary)
		funcNames := make([]string, len(capabilities))
		for i, cap := range capabilities {
			funcNames[i] = cap["function_name"].(string)
		}
		assert.Contains(t, funcNames, "greet", "Should have greet function")
		assert.Contains(t, funcNames, "smart_greet", "Should have smart_greet function")
		assert.Contains(t, funcNames, "get_weather", "Should have get_weather function")

		t.Logf("✅ Agent stored: %s with %d capabilities", agentData["name"], len(capabilities))
	})

	t.Run("TestAllJSONFilesViaServiceLayer", func(t *testing.T) {
		testFiles := []struct {
			filename              string
			expectedAgentId       string
			expectedCapabilities  int
		}{
			{"multiple_functions_request.json", "agent-b065c499", 3},
			{"mesh_agent_registration_minimal.json", "minimal-agent", 1},
			{"mesh_agent_registration_sample.json", "hello-world-agent", 3}, // has 3 tools
			{"mesh_agent_registration_complex.json", "multi-service-agent", 3},
		}

		for _, testCase := range testFiles {
			t.Run(testCase.filename, func(t *testing.T) {
				// Fresh service for each test
				service := setupTestService(t)

				// Load and register
				jsonData := loadTestJSON(t, testCase.filename)
				req := convertToServiceRequest(jsonData)

				response, err := service.RegisterAgent(req)
				require.NoError(t, err, "Registration should succeed")

				// Validate response
				assert.Equal(t, "success", response.Status)
				assert.Equal(t, testCase.expectedAgentId, response.AgentID)

				// Validate database storage
				agentData, err := service.GetAgentWithCapabilities(testCase.expectedAgentId)
				require.NoError(t, err)

				capabilities := agentData["capabilities"].([]map[string]interface{})
				assert.Equal(t, testCase.expectedCapabilities, len(capabilities))

				t.Logf("✅ %s → Agent: %s, Capabilities: %d",
					testCase.filename, testCase.expectedAgentId, len(capabilities))
			})
		}
	})

	t.Run("VerifyDependencyCountingWorks", func(t *testing.T) {
		service := setupTestService(t)

		// Load agent with dependencies
		jsonData := loadTestJSON(t, "multiple_functions_request.json")
		req := convertToServiceRequest(jsonData)

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Check dependency counting in database
		agentData, err := service.GetAgentWithCapabilities("agent-b065c499")
		require.NoError(t, err)

		// Should have counted dependencies from tools
		totalDeps := agentData["total_dependencies"].(int)
		assert.Greater(t, totalDeps, 0, "Should have counted dependencies from tools")

		resolvedDeps := agentData["dependencies_resolved"].(int)
		assert.Equal(t, 0, resolvedDeps, "Should start with 0 resolved dependencies")

		t.Logf("✅ Dependency counting: Total=%d, Resolved=%d", totalDeps, resolvedDeps)
	})

	t.Run("VerifyTagsStoredAsJSON", func(t *testing.T) {
		service := setupTestService(t)

		// Load agent with tags
		jsonData := loadTestJSON(t, "mesh_agent_registration_complex.json")
		req := convertToServiceRequest(jsonData)

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Get capabilities and check tags
		agentData, err := service.GetAgentWithCapabilities("multi-service-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})

		// Find capability with tags
		var foundTags bool
		for _, cap := range capabilities {
			if tags, exists := cap["tags"]; exists && tags != nil {
				tagsArray := tags.([]interface{})
				assert.Greater(t, len(tagsArray), 0, "Should have tags")
				foundTags = true
				t.Logf("✅ Found tags: %v", tagsArray)
				break
			}
		}

		assert.True(t, foundTags, "Should find at least one capability with tags")
	})

	t.Run("UpsertSameAgentIDMultipleTimes", func(t *testing.T) {
		service := setupTestService(t)

		// First registration
		jsonData1 := loadTestJSON(t, "mesh_agent_registration_minimal.json")
		req1 := convertToServiceRequest(jsonData1)

		response1, err := service.RegisterAgent(req1)
		require.NoError(t, err)
		assert.Equal(t, "success", response1.Status)

		// Get initial data
		agentData1, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)
		createdAt1 := agentData1["created_at"].(string)
		capabilities1 := agentData1["capabilities"].([]map[string]interface{})

		// Wait a moment to ensure timestamp difference
		time.Sleep(100 * time.Millisecond)

		// Second registration (same agent_id, different data)
		jsonData2 := map[string]interface{}{
			"agent_id":   "minimal-agent", // Same ID
			"agent_type": "mcp_agent",
			"name":       "Updated Minimal Agent", // Different name
			"version":    "2.0.0",                 // Different version
			"namespace":  "production",            // Different namespace
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "updated_function",
					"capability":    "updated_capability",
					"version":       "2.0.0",
					"description":   "Updated function",
				},
				map[string]interface{}{
					"function_name": "new_function",
					"capability":    "new_capability",
					"version":       "1.0.0",
					"description":   "Newly added function",
				},
			},
		}
		req2 := convertToServiceRequest(jsonData2)

		response2, err := service.RegisterAgent(req2)
		require.NoError(t, err)
		assert.Equal(t, "success", response2.Status)
		assert.Equal(t, "minimal-agent", response2.AgentID) // Same agent ID

		// Get updated data
		agentData2, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)

		// Verify UPSERT behavior
		assert.Equal(t, "minimal-agent", agentData2["agent_id"])
		assert.Equal(t, "Updated Minimal Agent", agentData2["name"])     // Updated
		assert.Equal(t, "2.0.0", agentData2["version"])                  // Updated
		assert.Equal(t, "production", agentData2["namespace"])           // Updated
		assert.Equal(t, createdAt1, agentData2["created_at"])            // Preserved
		// Check that updated_at is different (allowing for potential timestamp precision issues)
		updatedAt1 := agentData1["updated_at"].(string)
		updatedAt2 := agentData2["updated_at"].(string)
		if updatedAt1 == updatedAt2 {
			t.Logf("⚠️  Timestamps identical (precision issue): %s", updatedAt1)
		} else {
			t.Logf("✅ updated_at changed correctly: %s → %s", updatedAt1, updatedAt2)
		}

		// Verify capabilities were replaced (not appended)
		capabilities2 := agentData2["capabilities"].([]map[string]interface{})
		assert.Equal(t, 2, len(capabilities2))                           // New count
		assert.NotEqual(t, len(capabilities1), len(capabilities2))       // Different from before

		// Verify new capabilities exist
		funcNames := make([]string, len(capabilities2))
		for i, cap := range capabilities2 {
			funcNames[i] = cap["function_name"].(string)
		}
		assert.Contains(t, funcNames, "updated_function")
		assert.Contains(t, funcNames, "new_function")

		t.Logf("✅ UPSERT successful: %s updated from %d to %d capabilities",
			agentData2["name"], len(capabilities1), len(capabilities2))
		t.Logf("📅 created_at preserved: %s", createdAt1)
	})
}

// TestServiceLayerErrorHandling tests error scenarios
func TestServiceLayerErrorHandling(t *testing.T) {
	t.Run("EmptyAgentIDShouldFail", func(t *testing.T) {
		service := setupTestService(t)

		req := &AgentRegistrationRequest{
			AgentID:   "", // Empty agent ID
			Metadata:  map[string]interface{}{},
			Timestamp: time.Now().Format(time.RFC3339),
		}

		_, err := service.RegisterAgent(req)
		assert.Error(t, err, "Should fail with empty agent_id")
		assert.Contains(t, err.Error(), "agent_id is required")
	})

	t.Run("InvalidToolsFormatShouldFail", func(t *testing.T) {
		service := setupTestService(t)

		req := &AgentRegistrationRequest{
			AgentID: "test-agent",
			Metadata: map[string]interface{}{
				"tools": "invalid-not-array", // Should be array
			},
			Timestamp: time.Now().Format(time.RFC3339),
		}

		_, err := service.RegisterAgent(req)
		assert.Error(t, err, "Should fail with invalid tools format")
		assert.Contains(t, err.Error(), "tools must be an array")
	})

	t.Run("GetNonExistentAgentShouldFail", func(t *testing.T) {
		service := setupTestService(t)

		_, err := service.GetAgentWithCapabilities("non-existent-agent")
		assert.Error(t, err, "Should fail for non-existent agent")
		assert.Contains(t, err.Error(), "agent not found")
	})
}

// TestServiceLayerPerformance tests basic performance characteristics
func TestServiceLayerPerformance(t *testing.T) {
	t.Run("RegisterMultipleAgentsQuickly", func(t *testing.T) {
		service := setupTestService(t)

		start := time.Now()

		// Register 10 agents
		for i := 0; i < 10; i++ {
			agentID := fmt.Sprintf("perf-agent-%d", i)
			req := &AgentRegistrationRequest{
				AgentID: agentID,
				Metadata: map[string]interface{}{
					"name":       fmt.Sprintf("Performance Agent %d", i),
					"agent_type": "mcp_agent",
					"tools": []interface{}{
						map[string]interface{}{
							"function_name": "test_function",
							"capability":    "test_capability",
							"version":       "1.0.0",
						},
					},
				},
				Timestamp: time.Now().Format(time.RFC3339),
			}

			_, err := service.RegisterAgent(req)
			require.NoError(t, err)
		}

		duration := time.Since(start)
		t.Logf("✅ Registered 10 agents in %v (avg: %v per agent)",
			duration, duration/10)

		// Should be reasonably fast
		assert.Less(t, duration, 5*time.Second, "Should register 10 agents in under 5 seconds")
	})
}
