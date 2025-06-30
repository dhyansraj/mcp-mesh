package registry

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"mcp-mesh/src/core/registry/generated"
)

// mockHandler simulates the heartbeat handler for testing JSON parsing
func mockHeartbeatHandler(c *gin.Context) {
	// This handler tests the JSON parsing layer only
	var req generated.MeshAgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Invalid JSON payload: " + err.Error(),
			Timestamp: time.Now(),
		})
		return
	}

	// Test the conversion function (validates our conversion works)
	_ = ConvertMeshAgentRegistrationToMap(req)

	// Return success response with the parsed data
	response := generated.MeshRegistrationResponse{
		Status:    generated.Success,
		Timestamp: time.Now(),
		Message:   "Agent heartbeat parsed successfully",
		AgentId:   req.AgentId,
	}

	c.JSON(http.StatusOK, response)
}

// mockHealthHandler simulates the health handler
func mockHealthHandler(c *gin.Context) {
	response := generated.HealthResponse{
		Status:        generated.HealthResponseStatusHealthy,
		Version:       "1.0.0",
		UptimeSeconds: 100,
		Timestamp:     time.Now(),
		Service:       "mcp-mesh-registry",
	}
	c.JSON(http.StatusOK, response)
}

// setupMinimalServer creates a minimal test server just for JSON parsing
func setupMinimalServer() *gin.Engine {
	gin.SetMode(gin.TestMode)
	router := gin.New()

	// Register minimal handlers that focus on JSON parsing
	router.POST("/heartbeat", mockHeartbeatHandler)
	router.GET("/health", mockHealthHandler)

	return router
}

// TestMinimalHTTPJSONParsing tests pure JSON parsing via HTTP without service layer
func TestMinimalHTTPJSONParsing(t *testing.T) {
	t.Run("LoadJSONFileAndSendHTTPRequest", func(t *testing.T) {
		// Setup minimal server
		router := setupMinimalServer()

		// Load test JSON file
		jsonData, err := os.ReadFile("testdata/agent_registration/multiple_functions_request.json")
		require.NoError(t, err, "Failed to load test JSON file")

		// Create HTTP request
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err, "Failed to create HTTP request")
		req.Header.Set("Content-Type", "application/json")

		// Create response recorder
		w := httptest.NewRecorder()

		// Execute request
		router.ServeHTTP(w, req)

		// Validate response
		assert.Equal(t, http.StatusOK, w.Code, "Should return 200 OK")
		assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))

		// Parse response body
		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(w.Body.Bytes(), &response)
		require.NoError(t, err, "Should be able to parse response JSON")

		// Validate response content
		assert.Equal(t, "agent-b065c499", response.AgentId)
		assert.Equal(t, generated.Success, response.Status)
		assert.Contains(t, response.Message, "parsed successfully")

		t.Logf("✅ SUCCESS: HTTP POST /heartbeat with JSON file")
		t.Logf("📄 Loaded JSON file: multiple_functions_request.json")
		t.Logf("📨 HTTP Status: %d", w.Code)
		t.Logf("🎯 Response AgentId: %s", response.AgentId)
		t.Logf("✨ Response Status: %s", response.Status)
	})

	t.Run("TestAllJSONFilesViaHTTP", func(t *testing.T) {
		testFiles := []struct {
			filename        string
			expectedAgentId string
		}{
			{"multiple_functions_request.json", "agent-b065c499"},
			{"mesh_agent_registration_minimal.json", "minimal-agent"},
			{"mesh_agent_registration_sample.json", "hello-world-agent"},
			{"mesh_agent_registration_complex.json", "multi-service-agent"},
		}

		for _, testCase := range testFiles {
			t.Run(testCase.filename, func(t *testing.T) {
				// Setup fresh server
				router := setupMinimalServer()

				// Load test JSON file
				jsonData, err := os.ReadFile("testdata/agent_registration/" + testCase.filename)
				require.NoError(t, err, "Failed to load %s", testCase.filename)

				// Create HTTP request
				req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
				require.NoError(t, err, "Failed to create HTTP request")
				req.Header.Set("Content-Type", "application/json")

				// Create response recorder
				w := httptest.NewRecorder()

				// Execute request
				router.ServeHTTP(w, req)

				// Validate response
				assert.Equal(t, http.StatusOK, w.Code, "Should return 200 OK")

				// Parse response body
				var response generated.MeshRegistrationResponse
				err = json.Unmarshal(w.Body.Bytes(), &response)
				require.NoError(t, err, "Should parse response JSON")

				// Validate expected content
				assert.Equal(t, testCase.expectedAgentId, response.AgentId)
				assert.Equal(t, generated.Success, response.Status)

				t.Logf("✅ %s -> AgentId: %s", testCase.filename, response.AgentId)
			})
		}
	})

	t.Run("InvalidJSONReturns400", func(t *testing.T) {
		router := setupMinimalServer()

		// Create malformed JSON
		invalidJSON := `{"agent_id": "test", "tools": [`

		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBufferString(invalidJSON))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")

		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)

		// Should return 400 Bad Request
		assert.Equal(t, http.StatusBadRequest, w.Code)

		var errorResponse generated.ErrorResponse
		err = json.Unmarshal(w.Body.Bytes(), &errorResponse)
		require.NoError(t, err)

		assert.Contains(t, errorResponse.Error, "Invalid JSON payload")

		t.Logf("✅ Correctly rejected invalid JSON with 400 status")
	})

	t.Run("HealthEndpointWorks", func(t *testing.T) {
		router := setupMinimalServer()

		req, err := http.NewRequest("GET", "/health", nil)
		require.NoError(t, err)

		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var response generated.HealthResponse
		err = json.Unmarshal(w.Body.Bytes(), &response)
		require.NoError(t, err)

		assert.Equal(t, generated.HealthResponseStatusHealthy, response.Status)
		assert.Equal(t, "mcp-mesh-registry", response.Service)

		t.Logf("✅ Health endpoint returns: %s", response.Status)
	})
}

// TestJSONParsingDetails validates specific parsing behaviors
func TestJSONParsingDetails(t *testing.T) {
	t.Run("ParseMultipleFunctionsAndValidateContent", func(t *testing.T) {
		// Load the multiple functions JSON
		jsonData, err := os.ReadFile("testdata/agent_registration/multiple_functions_request.json")
		require.NoError(t, err)

		// Parse into Go struct
		var registration generated.MeshAgentRegistration
		err = json.Unmarshal(jsonData, &registration)
		require.NoError(t, err)

		// Validate parsed content matches expected structure
		assert.Equal(t, "agent-b065c499", registration.AgentId)
		assert.Equal(t, 3, len(registration.Tools))

		// Validate first tool
		tool1 := registration.Tools[0]
		assert.Equal(t, "smart_greet", tool1.FunctionName)
		assert.Equal(t, "personalized_greeting", tool1.Capability)
		assert.NotNil(t, tool1.Dependencies)
		assert.Equal(t, 1, len(*tool1.Dependencies))

		// Validate second tool has multiple dependencies
		tool2 := registration.Tools[1]
		assert.Equal(t, "get_weather_report", tool2.FunctionName)
		assert.Equal(t, "weather_report", tool2.Capability)
		assert.NotNil(t, tool2.Dependencies)
		assert.Equal(t, 2, len(*tool2.Dependencies))

		// Test service layer conversion
		metadata := ConvertMeshAgentRegistrationToMap(registration)
		tools := metadata["tools"].([]interface{})
		assert.Equal(t, 3, len(tools))

		// Extract capability names from tools
		capabilityNames := make([]string, 0)
		for _, tool := range tools {
			toolMap := tool.(map[string]interface{})
			capabilityNames = append(capabilityNames, toolMap["capability"].(string))
		}
		assert.Contains(t, capabilityNames, "personalized_greeting")
		assert.Contains(t, capabilityNames, "weather_report")
		assert.Contains(t, capabilityNames, "send_notification")

		t.Logf("✅ Parsed %d tools with %d total capabilities", len(registration.Tools), len(capabilityNames))

		// Now send via HTTP to validate full round-trip
		router := setupMinimalServer()
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")

		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(w.Body.Bytes(), &response)
		require.NoError(t, err)

		assert.Equal(t, registration.AgentId, response.AgentId)

		t.Logf("✅ Complete round-trip successful: JSON -> Go struct -> HTTP -> Response")
	})
}
