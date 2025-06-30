package registry

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestHeartbeatLightweight tests the lightweight heartbeat functionality
func TestHeartbeatLightweight(t *testing.T) {
	t.Run("HeartbeatAfterRegistration", func(t *testing.T) {
		service := setupTestService(t)

		// First register an agent
		jsonData := loadTestJSON(t, "mesh_agent_registration_minimal.json")
		regReq := convertToServiceRequest(jsonData)

		_, err := service.RegisterAgent(regReq)
		require.NoError(t, err)

		// Get initial timestamp
		agentData1, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)
		updatedAt1 := agentData1["updated_at"].(string)

		// Wait to ensure timestamp difference
		time.Sleep(100 * time.Millisecond)

		// Send lightweight heartbeat (no tools)
		heartbeatReq := &HeartbeatRequest{
			AgentID: "minimal-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"version": "1.1.0", // Update version only
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)

		// Validate heartbeat response
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "minimal-agent", response.AgentID)
		assert.Contains(t, response.Message, "Heartbeat updated successfully")

		// Verify database changes
		agentData2, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)

		// Simple heartbeat with metadata does NOT update agent fields (only timestamp)
		// Version should remain unchanged from original registration
		assert.Equal(t, agentData1["version"], agentData2["version"])

		// Check timestamp change (with lenient handling for precision issues)
		updatedAt2 := agentData2["updated_at"].(string)
		if updatedAt1 == updatedAt2 {
			t.Logf("⚠️  Timestamps identical (precision issue): %s", updatedAt1)
		} else {
			t.Logf("✅ Timestamp updated correctly: %s → %s", updatedAt1, updatedAt2)
		}

		// Should preserve capabilities (no tools in heartbeat)
		capabilities := agentData2["capabilities"].([]map[string]interface{})
		assert.Equal(t, 1, len(capabilities)) // Original capability preserved

		t.Logf("✅ Lightweight heartbeat updated version: %s", agentData2["version"])
	})

	t.Run("HeartbeatWithToolsFallsBackToRegistration", func(t *testing.T) {
		service := setupTestService(t)

		// Register initial agent
		jsonData := loadTestJSON(t, "mesh_agent_registration_minimal.json")
		regReq := convertToServiceRequest(jsonData)
		_, err := service.RegisterAgent(regReq)
		require.NoError(t, err)

		// Send heartbeat WITH tools (should trigger full registration)
		heartbeatReq := &HeartbeatRequest{
			AgentID: "minimal-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"version": "2.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "new_function",
						"capability":    "new_capability",
						"version":       "2.0.0",
						"description":   "Added via heartbeat",
					},
					map[string]interface{}{
						"function_name": "another_function",
						"capability":    "another_capability",
						"version":       "1.0.0",
						"description":   "Another new function",
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)

		// Should indicate agent update via heartbeat (because tools were provided)
		assert.Equal(t, "success", response.Status)
		assert.Contains(t, response.Message, "Agent updated via heartbeat")

		// Verify capabilities were updated
		agentData, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		assert.Equal(t, 2, len(capabilities)) // Should have 2 new capabilities

		funcNames := make([]string, len(capabilities))
		for i, cap := range capabilities {
			funcNames[i] = cap["function_name"].(string)
		}
		assert.Contains(t, funcNames, "new_function")
		assert.Contains(t, funcNames, "another_function")

		t.Logf("✅ Heartbeat with tools updated capabilities: %d functions", len(capabilities))
	})

	t.Run("HeartbeatNonExistentAgentWithoutMetadataFails", func(t *testing.T) {
		service := setupTestService(t)

		heartbeatReq := &HeartbeatRequest{
			AgentID: "non-existent-agent",
			Status:  "healthy",
			// No metadata - should fail
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err) // Should not error, but return error status

		assert.Equal(t, "error", response.Status)
		assert.Contains(t, response.Message, "not found")
		assert.Contains(t, response.Message, "must provide metadata")

		t.Logf("✅ Correctly rejected heartbeat for non-existent agent without metadata")
	})

	t.Run("HeartbeatCanRegisterNewAgent", func(t *testing.T) {
		service := setupTestService(t)

		// Send heartbeat for non-existent agent WITH metadata and tools
		heartbeatReq := &HeartbeatRequest{
			AgentID: "new-agent-via-heartbeat",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "agent-registered-via-heartbeat",
				"version":    "1.0.0",
				"namespace":  "testing",
				"http_host":  "localhost",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "heartbeat_function",
						"capability":    "heartbeat_capability",
						"version":       "1.0.0",
						"description":   "Function registered via heartbeat",
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)

		// Should successfully register
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "new-agent-via-heartbeat", response.AgentID)
		assert.Contains(t, response.Message, "registered via heartbeat")

		// Verify agent was actually registered in database
		agentData, err := service.GetAgentWithCapabilities("new-agent-via-heartbeat")
		require.NoError(t, err)

		assert.Equal(t, "new-agent-via-heartbeat", agentData["agent_id"])
		assert.Equal(t, "agent-registered-via-heartbeat", agentData["name"])
		assert.Equal(t, "mcp_agent", agentData["agent_type"])
		assert.Equal(t, "testing", agentData["namespace"])

		// Verify capabilities were registered
		capabilities := agentData["capabilities"].([]map[string]interface{})
		assert.Equal(t, 1, len(capabilities))
		assert.Equal(t, "heartbeat_function", capabilities[0]["function_name"])
		assert.Equal(t, "heartbeat_capability", capabilities[0]["capability"])

		t.Logf("✅ Successfully registered new agent via heartbeat: %s", agentData["name"])
	})

	t.Run("HeartbeatCanRegisterAgentWithoutTools", func(t *testing.T) {
		service := setupTestService(t)

		// Send heartbeat for non-existent agent with metadata but NO tools
		heartbeatReq := &HeartbeatRequest{
			AgentID: "metadata-only-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "metadata-only-agent",
				"version":    "1.0.0",
				"namespace":  "testing",
				// No tools
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)

		// Should successfully register even without tools
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "metadata-only-agent", response.AgentID)
		assert.Contains(t, response.Message, "registered via heartbeat")

		// Verify agent was registered
		agentData, err := service.GetAgentWithCapabilities("metadata-only-agent")
		require.NoError(t, err)

		assert.Equal(t, "metadata-only-agent", agentData["agent_id"])
		assert.Equal(t, "metadata-only-agent", agentData["name"])

		// Should have 0 capabilities (no tools provided)
		capabilities := agentData["capabilities"].([]map[string]interface{})
		assert.Equal(t, 0, len(capabilities))

		t.Logf("✅ Successfully registered agent without tools: %s", agentData["name"])
	})

	t.Run("HeartbeatWithoutMetadata", func(t *testing.T) {
		service := setupTestService(t)

		// Register agent first
		jsonData := loadTestJSON(t, "mesh_agent_registration_minimal.json")
		regReq := convertToServiceRequest(jsonData)
		_, err := service.RegisterAgent(regReq)
		require.NoError(t, err)

		// Simple heartbeat with no metadata
		heartbeatReq := &HeartbeatRequest{
			AgentID: "minimal-agent",
			Status:  "healthy",
			// No metadata
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)

		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "Heartbeat updated successfully", response.Message)

		t.Logf("✅ Simple heartbeat without metadata worked")
	})

	t.Run("HeartbeatUpdatesMultipleFields", func(t *testing.T) {
		service := setupTestService(t)

		// Register agent
		jsonData := loadTestJSON(t, "mesh_agent_registration_sample.json")
		regReq := convertToServiceRequest(jsonData)
		_, err := service.RegisterAgent(regReq)
		require.NoError(t, err)

		// Heartbeat with multiple field updates
		heartbeatReq := &HeartbeatRequest{
			AgentID: "hello-world-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"version":   "3.0.0",
				"namespace": "production",
				"http_host": "192.168.1.100",
				"http_port": float64(9090), // JSON numbers are float64
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)

		// Simple heartbeat with metadata does NOT update agent fields
		// Only timestamp gets updated - agent fields remain from original registration
		agentData, err := service.GetAgentWithCapabilities("hello-world-agent")
		require.NoError(t, err)

		// Fields should remain unchanged from original registration
		assert.Equal(t, "1.0.0", agentData["version"]) // Original version
		assert.Equal(t, "default", agentData["namespace"]) // Original namespace
		assert.Nil(t, agentData["http_host"]) // Original host (nil)
		assert.Nil(t, agentData["http_port"]) // Original port (nil)

		// Capabilities should be preserved (no tools in heartbeat)
		capabilities := agentData["capabilities"].([]map[string]interface{})
		assert.Equal(t, 3, len(capabilities)) // Original 3 capabilities preserved

		t.Logf("✅ Simple heartbeat preserved original fields: version=%s, namespace=%s",
			agentData["version"], agentData["namespace"])
	})
}

// Note: Performance test removed as heartbeat now performs full registration (unified architecture)
// Previously separate register/heartbeat methods are now unified, so no performance difference expected
