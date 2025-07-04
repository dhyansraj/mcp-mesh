package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestKwargsInHeartbeatRegistration tests that kwargs are properly stored and retrieved
// when sent via heartbeat registration requests
func TestKwargsInHeartbeatRegistration(t *testing.T) {
	t.Run("RegisterAgentWithKwargs", func(t *testing.T) {
		service := setupTestService(t)

		// Load test data with kwargs
		jsonData := loadTestJSON(t, "mesh_agent_registration_with_kwargs.json")
		regReq := convertToServiceRequest(jsonData)

		// Register agent with kwargs
		response, err := service.RegisterAgent(regReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "enhanced-kwargs-agent", response.AgentID)

		// Verify agent was registered with capabilities including kwargs
		agentData, err := service.GetAgentWithCapabilities("enhanced-kwargs-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		require.Equal(t, 3, len(capabilities))

		// Find the enhanced_api_call capability
		var enhancedCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "enhanced_api_call" {
				enhancedCap = cap
				break
			}
		}
		require.NotNil(t, enhancedCap, "enhanced_api_call capability not found")

		// Verify kwargs are stored correctly
		kwargs, ok := enhancedCap["kwargs"].(map[string]interface{})
		require.True(t, ok, "kwargs should be a map")
		require.NotNil(t, kwargs, "kwargs should not be nil")

		// Test specific kwargs values
		assert.Equal(t, float64(45), kwargs["timeout"])
		assert.Equal(t, float64(3), kwargs["retry_count"])
		assert.Equal(t, true, kwargs["streaming"])
		assert.Equal(t, true, kwargs["auth_required"])
		assert.Equal(t, float64(1048576), kwargs["max_payload_size"])
		assert.Equal(t, false, kwargs["enable_compression"])

		// Test nested custom_headers
		headers, ok := kwargs["custom_headers"].(map[string]interface{})
		require.True(t, ok, "custom_headers should be a map")
		assert.Equal(t, "v2", headers["X-API-Version"])
		assert.Equal(t, "enhanced-agent", headers["X-Client-ID"])

		t.Logf("✅ Enhanced capability kwargs verified: %+v", kwargs)

		// Find the quick_operation capability
		var quickCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "quick_operation" {
				quickCap = cap
				break
			}
		}
		require.NotNil(t, quickCap, "quick_operation capability not found")

		// Verify minimal kwargs
		quickKwargs, ok := quickCap["kwargs"].(map[string]interface{})
		require.True(t, ok, "quick_operation kwargs should be a map")
		assert.Equal(t, float64(5), quickKwargs["timeout"])
		assert.Equal(t, true, quickKwargs["cache_enabled"])

		// Find the no_kwargs_function capability
		var standardCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "no_kwargs_function" {
				standardCap = cap
				break
			}
		}
		require.NotNil(t, standardCap, "no_kwargs_function capability not found")

		// Verify kwargs field is nil or empty for function without kwargs
		standardKwargs := standardCap["kwargs"]
		assert.True(t, standardKwargs == nil || len(standardKwargs.(map[string]interface{})) == 0,
			"kwargs should be nil or empty for function without kwargs")

		t.Logf("✅ All kwargs variations verified correctly")
	})

	t.Run("HeartbeatWithKwargsUpdatesCapabilities", func(t *testing.T) {
		service := setupTestService(t)

		// First register a minimal agent
		jsonData := loadTestJSON(t, "mesh_agent_registration_minimal.json")
		regReq := convertToServiceRequest(jsonData)
		_, err := service.RegisterAgent(regReq)
		require.NoError(t, err)

		// Send heartbeat with tools that have kwargs
		heartbeatReq := &HeartbeatRequest{
			AgentID: "minimal-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"version": "2.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "streaming_processor",
						"capability":    "streaming_processing",
						"version":       "1.0.0",
						"description":   "Real-time streaming processor",
						"kwargs": map[string]interface{}{
							"timeout":       float64(120),
							"retry_count":   float64(5),
							"streaming":     true,
							"buffer_size":   float64(8192),
							"compression":   "gzip",
							"custom_headers": map[string]interface{}{
								"X-Stream-Type": "realtime",
								"X-Buffer-Size": "8192",
							},
						},
					},
					map[string]interface{}{
						"function_name": "batch_processor",
						"capability":    "batch_processing",
						"version":       "2.0.0",
						"description":   "Heavy batch processing",
						"kwargs": map[string]interface{}{
							"timeout":          float64(300),
							"retry_count":      float64(1),
							"streaming":        false,
							"max_batch_size":   float64(1000),
							"parallel_workers": float64(4),
							"memory_limit":     "2GB",
						},
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)
		assert.Contains(t, response.Message, "Agent updated via heartbeat")

		// Verify capabilities were updated with kwargs
		agentData, err := service.GetAgentWithCapabilities("minimal-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		require.Equal(t, 2, len(capabilities)) // Should have 2 new capabilities

		// Find streaming processor capability
		var streamingCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "streaming_processor" {
				streamingCap = cap
				break
			}
		}
		require.NotNil(t, streamingCap, "streaming_processor capability not found")

		// Verify streaming processor kwargs
		streamingKwargs, ok := streamingCap["kwargs"].(map[string]interface{})
		require.True(t, ok, "streaming kwargs should be a map")
		assert.Equal(t, float64(120), streamingKwargs["timeout"])
		assert.Equal(t, float64(5), streamingKwargs["retry_count"])
		assert.Equal(t, true, streamingKwargs["streaming"])
		assert.Equal(t, float64(8192), streamingKwargs["buffer_size"])
		assert.Equal(t, "gzip", streamingKwargs["compression"])

		// Verify nested headers
		streamHeaders, ok := streamingKwargs["custom_headers"].(map[string]interface{})
		require.True(t, ok, "streaming custom_headers should be a map")
		assert.Equal(t, "realtime", streamHeaders["X-Stream-Type"])
		assert.Equal(t, "8192", streamHeaders["X-Buffer-Size"])

		// Find batch processor capability
		var batchCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "batch_processor" {
				batchCap = cap
				break
			}
		}
		require.NotNil(t, batchCap, "batch_processor capability not found")

		// Verify batch processor kwargs
		batchKwargs, ok := batchCap["kwargs"].(map[string]interface{})
		require.True(t, ok, "batch kwargs should be a map")
		assert.Equal(t, float64(300), batchKwargs["timeout"])
		assert.Equal(t, float64(1), batchKwargs["retry_count"])
		assert.Equal(t, false, batchKwargs["streaming"])
		assert.Equal(t, float64(1000), batchKwargs["max_batch_size"])
		assert.Equal(t, float64(4), batchKwargs["parallel_workers"])
		assert.Equal(t, "2GB", batchKwargs["memory_limit"])

		t.Logf("✅ Heartbeat with kwargs updated capabilities successfully")
	})

	t.Run("HeartbeatRegistrationWithKwargsFromTestdata", func(t *testing.T) {
		service := setupTestService(t)

		// Register agent via heartbeat using structured request
		heartbeatReq := &HeartbeatRequest{
			AgentID: "heartbeat-kwargs-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "heartbeat-kwargs-agent",
				"version":    "1.0.0",
				"namespace":  "default",
				"http_host":  "localhost",
				"http_port":  float64(8081),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "streaming_processor",
						"capability":    "streaming_processing",
						"version":       "1.0.0",
						"tags":          []interface{}{"streaming", "realtime"},
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "message_queue",
								"tags":       []interface{}{"kafka", "streaming"},
								"version":    ">=3.0.0",
								"namespace":  "default",
							},
						},
						"description": "Real-time streaming processor",
						"kwargs": map[string]interface{}{
							"timeout":              float64(120),
							"retry_count":          float64(5),
							"streaming":            true,
							"buffer_size":          float64(8192),
							"compression":          "gzip",
							"enable_checkpointing": true,
							"custom_headers": map[string]interface{}{
								"X-Stream-Type":  "realtime",
								"X-Buffer-Size":  "8192",
							},
						},
					},
					map[string]interface{}{
						"function_name": "batch_processor",
						"capability":    "batch_processing",
						"version":       "2.0.0",
						"tags":          []interface{}{"batch", "heavy"},
						"dependencies":  []interface{}{},
						"description":   "Heavy batch processing with custom timeouts",
						"kwargs": map[string]interface{}{
							"timeout":          float64(300),
							"retry_count":      float64(1),
							"streaming":        false,
							"max_batch_size":   float64(1000),
							"parallel_workers": float64(4),
							"memory_limit":     "2GB",
						},
					},
				},
			},
		}

		// Register agent via heartbeat with kwargs
		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "heartbeat-kwargs-agent", response.AgentID)
		assert.Contains(t, response.Message, "registered via heartbeat")

		// Verify agent was registered
		agentData, err := service.GetAgentWithCapabilities("heartbeat-kwargs-agent")
		require.NoError(t, err)
		assert.Equal(t, "heartbeat-kwargs-agent", agentData["agent_id"])
		assert.Equal(t, "heartbeat-kwargs-agent", agentData["name"])

		// Verify capabilities with kwargs
		capabilities := agentData["capabilities"].([]map[string]interface{})
		require.Equal(t, 2, len(capabilities))

		// Check streaming processor
		var streamingCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "streaming_processor" {
				streamingCap = cap
				break
			}
		}
		require.NotNil(t, streamingCap)

		streamingKwargsInterface := streamingCap["kwargs"]
		require.NotNil(t, streamingKwargsInterface, "streaming_processor kwargs should not be nil")
		streamingKwargs, ok := streamingKwargsInterface.(map[string]interface{})
		require.True(t, ok, "streaming kwargs should be a map")
		assert.Equal(t, float64(120), streamingKwargs["timeout"])
		assert.Equal(t, "gzip", streamingKwargs["compression"])
		assert.Equal(t, true, streamingKwargs["enable_checkpointing"])

		// Verify nested custom headers
		headersInterface := streamingKwargs["custom_headers"]
		require.NotNil(t, headersInterface, "custom_headers should not be nil")
		headers, ok := headersInterface.(map[string]interface{})
		require.True(t, ok, "custom_headers should be a map")
		assert.Equal(t, "realtime", headers["X-Stream-Type"])
		assert.Equal(t, "8192", headers["X-Buffer-Size"])

		// Check batch processor
		var batchCap map[string]interface{}
		for _, cap := range capabilities {
			if cap["function_name"].(string) == "batch_processor" {
				batchCap = cap
				break
			}
		}
		require.NotNil(t, batchCap)

		batchKwargsInterface := batchCap["kwargs"]
		require.NotNil(t, batchKwargsInterface, "batch_processor kwargs should not be nil")
		batchKwargs, ok := batchKwargsInterface.(map[string]interface{})
		require.True(t, ok, "batch kwargs should be a map")
		assert.Equal(t, float64(300), batchKwargs["timeout"])
		assert.Equal(t, "2GB", batchKwargs["memory_limit"])

		t.Logf("✅ Heartbeat registration with complex kwargs successful")
	})
}

// TestKwargsDataTypes tests that various data types in kwargs are handled correctly
func TestKwargsDataTypes(t *testing.T) {
	t.Run("ComplexKwargsDataTypes", func(t *testing.T) {
		service := setupTestService(t)

		// Test with various data types in kwargs
		heartbeatReq := &HeartbeatRequest{
			AgentID: "complex-kwargs-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "complex-kwargs-agent",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "complex_function",
						"capability":    "complex_capability",
						"kwargs": map[string]interface{}{
							// Primitive types
							"string_val":  "test_string",
							"int_val":     float64(42),
							"float_val":   3.14159,
							"bool_val":    true,
							"null_val":    nil,

							// Arrays
							"string_array": []interface{}{"a", "b", "c"},
							"number_array": []interface{}{float64(1), float64(2), float64(3)},
							"mixed_array":  []interface{}{"string", float64(123), true},

							// Nested objects
							"config": map[string]interface{}{
								"timeout": float64(30),
								"retries": float64(3),
								"options": map[string]interface{}{
									"debug": true,
									"level": "info",
								},
							},

							// Complex nested structure
							"endpoints": []interface{}{
								map[string]interface{}{
									"url":     "https://api1.example.com",
									"timeout": float64(5),
									"auth":    true,
								},
								map[string]interface{}{
									"url":     "https://api2.example.com",
									"timeout": float64(10),
									"auth":    false,
								},
							},
						},
					},
				},
			},
		}

		// Register via heartbeat
		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)

		// Retrieve and verify all data types
		agentData, err := service.GetAgentWithCapabilities("complex-kwargs-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		require.Equal(t, 1, len(capabilities))

		kwargs := capabilities[0]["kwargs"].(map[string]interface{})

		// Verify primitive types
		assert.Equal(t, "test_string", kwargs["string_val"])
		assert.Equal(t, float64(42), kwargs["int_val"])
		assert.InDelta(t, 3.14159, kwargs["float_val"], 0.00001)
		assert.Equal(t, true, kwargs["bool_val"])
		assert.Nil(t, kwargs["null_val"])

		// Verify arrays
		stringArray := kwargs["string_array"].([]interface{})
		assert.Equal(t, []interface{}{"a", "b", "c"}, stringArray)

		numberArray := kwargs["number_array"].([]interface{})
		assert.Equal(t, []interface{}{float64(1), float64(2), float64(3)}, numberArray)

		// Verify nested objects
		config := kwargs["config"].(map[string]interface{})
		assert.Equal(t, float64(30), config["timeout"])
		assert.Equal(t, float64(3), config["retries"])

		options := config["options"].(map[string]interface{})
		assert.Equal(t, true, options["debug"])
		assert.Equal(t, "info", options["level"])

		// Verify complex nested arrays
		endpoints := kwargs["endpoints"].([]interface{})
		require.Equal(t, 2, len(endpoints))

		endpoint1 := endpoints[0].(map[string]interface{})
		assert.Equal(t, "https://api1.example.com", endpoint1["url"])
		assert.Equal(t, float64(5), endpoint1["timeout"])
		assert.Equal(t, true, endpoint1["auth"])

		endpoint2 := endpoints[1].(map[string]interface{})
		assert.Equal(t, "https://api2.example.com", endpoint2["url"])
		assert.Equal(t, float64(10), endpoint2["timeout"])
		assert.Equal(t, false, endpoint2["auth"])

		t.Logf("✅ All complex data types in kwargs verified correctly")
	})
}

// TestKwargsWithoutValues tests edge cases where kwargs might be empty or nil
func TestKwargsEdgeCases(t *testing.T) {
	t.Run("EmptyKwargs", func(t *testing.T) {
		service := setupTestService(t)

		heartbeatReq := &HeartbeatRequest{
			AgentID: "empty-kwargs-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "empty-kwargs-agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "empty_kwargs_function",
						"capability":    "empty_kwargs_capability",
						"kwargs":        map[string]interface{}{}, // Empty kwargs
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)

		// Verify empty kwargs are stored
		agentData, err := service.GetAgentWithCapabilities("empty-kwargs-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		kwargs := capabilities[0]["kwargs"].(map[string]interface{})
		assert.Equal(t, 0, len(kwargs))

		t.Logf("✅ Empty kwargs handled correctly")
	})

	t.Run("NilKwargs", func(t *testing.T) {
		service := setupTestService(t)

		heartbeatReq := &HeartbeatRequest{
			AgentID: "nil-kwargs-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "nil-kwargs-agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "nil_kwargs_function",
						"capability":    "nil_kwargs_capability",
						"kwargs":        nil, // Explicit nil kwargs
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)

		// Verify nil kwargs don't cause issues
		agentData, err := service.GetAgentWithCapabilities("nil-kwargs-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		kwargs := capabilities[0]["kwargs"]
		// kwargs should be nil or empty
		assert.True(t, kwargs == nil || len(kwargs.(map[string]interface{})) == 0)

		t.Logf("✅ Nil kwargs handled correctly")
	})

	t.Run("MissingKwargsField", func(t *testing.T) {
		service := setupTestService(t)

		heartbeatReq := &HeartbeatRequest{
			AgentID: "missing-kwargs-agent",
			Status:  "healthy",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "missing-kwargs-agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "missing_kwargs_function",
						"capability":    "missing_kwargs_capability",
						// No kwargs field at all
					},
				},
			},
		}

		response, err := service.UpdateHeartbeat(heartbeatReq)
		require.NoError(t, err)
		assert.Equal(t, "success", response.Status)

		// Verify missing kwargs field doesn't cause issues
		agentData, err := service.GetAgentWithCapabilities("missing-kwargs-agent")
		require.NoError(t, err)

		capabilities := agentData["capabilities"].([]map[string]interface{})
		kwargs := capabilities[0]["kwargs"]
		// kwargs should be nil when field is missing
		assert.True(t, kwargs == nil || len(kwargs.(map[string]interface{})) == 0)

		t.Logf("✅ Missing kwargs field handled correctly")
	})
}
