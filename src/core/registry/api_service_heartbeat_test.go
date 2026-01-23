package registry

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry/generated"
)

// makeStringTag creates a MeshToolDependencyRegistration_Tags_Item from a string
func makeStringTag(s string) generated.MeshToolDependencyRegistration_Tags_Item {
	var item generated.MeshToolDependencyRegistration_Tags_Item
	_ = item.FromMeshToolDependencyRegistrationTags0(s)
	return item
}

// makeStringTags creates a slice of MeshToolDependencyRegistration_Tags_Item from strings
func makeStringTags(tags ...string) *[]generated.MeshToolDependencyRegistration_Tags_Item {
	items := make([]generated.MeshToolDependencyRegistration_Tags_Item, len(tags))
	for i, tag := range tags {
		items[i] = makeStringTag(tag)
	}
	return &items
}

// setupTestRouter creates a test router with real handlers connected to EntService
func setupTestRouter(t *testing.T, service *EntService) *gin.Engine {
	gin.SetMode(gin.TestMode)
	router := gin.New()

	// Create handlers connected to the real service
	handlers := &EntBusinessLogicHandlers{entService: service}
	router.POST("/heartbeat", handlers.SendHeartbeat)

	return router
}

// TestAPIServiceHeartbeat tests heartbeat behavior for service_type="api"
func TestAPIServiceHeartbeat(t *testing.T) {
	gin.SetMode(gin.TestMode)

	t.Run("APIServiceHeartbeatDoesNotCreateAgent", func(t *testing.T) {
		// Setup test environment
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Create API service heartbeat request
		agentType := generated.MeshAgentRegistrationAgentTypeApi
		apiServiceRequest := generated.MeshAgentRegistration{
			AgentId:   "api-fastapi-test-123",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "api_route_handler_1",
					Capability:   "pdf-processing",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "pdf-extractor",
							Tags:       makeStringTags("processing"),
						},
					},
				},
				{
					FunctionName: "api_route_handler_2",
					Capability:   "user-management",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "user-service",
						},
					},
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(8080),
		}

		// Send heartbeat request
		jsonData, err := json.Marshal(apiServiceRequest)
		require.NoError(t, err)

		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")

		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)

		// Assert successful response
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(recorder.Body.Bytes(), &response)
		require.NoError(t, err)

		assert.Equal(t, "api-fastapi-test-123", response.AgentId)
		assert.Equal(t, generated.Success, response.Status)

		// CRITICAL: Verify agent was created in database (API services get saved but don't create events)
		agentsResponse, err := service.ListAgents(nil)
		require.NoError(t, err)
		assert.Len(t, agentsResponse.Agents, 1, "API service should create agent entry in database")
		assert.Equal(t, "api-fastapi-test-123", agentsResponse.Agents[0].Id)

		// CRITICAL: Verify NO events were created for API service
		events, err := service.entDB.Client.RegistryEvent.Query().All(context.Background())
		require.NoError(t, err)
		assert.Empty(t, events, "API service should NOT create registry events")

		t.Logf("✅ API service heartbeat successful, no agent created")
	})

	t.Run("APIServiceReceivesDependencyResolution", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// First, register a real agent that provides the required capability
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		agentRequest := generated.MeshAgentRegistration{
			AgentId:   "pdf-extractor-agent",
			AgentType: &agentType, // Default agent
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "extract_text",
					Capability:   "pdf-extractor",
					Description:  stringPtr("Extract text from PDF files"),
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(9000),
		}

		// Register the agent
		jsonData, err := json.Marshal(agentRequest)
		require.NoError(t, err)
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Now send API service heartbeat
		apiAgentType := generated.MeshAgentRegistrationAgentTypeApi
		apiServiceRequest := generated.MeshAgentRegistration{
			AgentId:   "api-fastapi-service-456",
			AgentType: &apiAgentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "api_pdf_handler",
					Capability:   "pdf-api-endpoint",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "pdf-extractor",
						},
					},
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(8080),
		}

		jsonData, err = json.Marshal(apiServiceRequest)
		require.NoError(t, err)

		req, err = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")

		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)

		// Assert successful response
		assert.Equal(t, http.StatusOK, recorder.Code)

		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(recorder.Body.Bytes(), &response)
		require.NoError(t, err)

		// CRITICAL: API service should receive dependency resolution
		require.NotNil(t, response.DependenciesResolved)
		dependenciesMap := *response.DependenciesResolved

		// Should have resolved pdf-extractor dependency for api_pdf_handler function
		assert.Contains(t, dependenciesMap, "api_pdf_handler")
		pdfDeps := dependenciesMap["api_pdf_handler"]
		assert.NotEmpty(t, pdfDeps)
		assert.Equal(t, "pdf-extractor-agent", pdfDeps[0].AgentId)
		assert.Equal(t, "pdf-extractor", pdfDeps[0].Capability)

		// Verify both agents exist in database (agent + API service)
		agentsResponse, err := service.ListAgents(nil)
		require.NoError(t, err)
		assert.Len(t, agentsResponse.Agents, 2) // pdf-extractor-agent + api service

		// Find each agent by ID
		var pdfAgent, apiService *generated.AgentInfo
		for _, agent := range agentsResponse.Agents {
			if agent.Id == "pdf-extractor-agent" {
				pdfAgent = &agent
			} else if agent.Id == "api-fastapi-service-456" {
				apiService = &agent
			}
		}
		require.NotNil(t, pdfAgent, "PDF extractor agent should exist")
		require.NotNil(t, apiService, "API service should exist in database")

		t.Logf("✅ API service received dependency resolution without creating agent")
	})

	t.Run("APIServiceDoesNotTriggerTopologyNotifications", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Register a regular agent first
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		agentRequest := generated.MeshAgentRegistration{
			AgentId:   "notification-listener-agent",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "listen_notifications",
					Capability:   "notification-listener",
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(9001),
		}

		jsonData, err := json.Marshal(agentRequest)
		require.NoError(t, err)
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Get initial agent state
		agentsResponse, err := service.ListAgents(nil)
		require.NoError(t, err)
		require.Len(t, agentsResponse.Agents, 1)

		// Wait a bit to ensure timestamp difference
		time.Sleep(10 * time.Millisecond)

		// Now register an API service
		apiAgentType := generated.MeshAgentRegistrationAgentTypeApi
		apiServiceRequest := generated.MeshAgentRegistration{
			AgentId:   "api-should-not-notify",
			AgentType: &apiAgentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "api_handler",
					Capability:   "api-endpoint",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "some-dependency",
						},
					},
				},
			},
		}

		jsonData, err = json.Marshal(apiServiceRequest)
		require.NoError(t, err)
		req, err = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// CRITICAL: Verify both services exist in database now (API service gets saved)
		agentsResponse, err = service.ListAgents(nil)
		require.NoError(t, err)
		require.Len(t, agentsResponse.Agents, 2) // Both the original agent and API service

		// Find the original agent
		var originalAgent *generated.AgentInfo
		for _, agent := range agentsResponse.Agents {
			if agent.Id == "notification-listener-agent" {
				originalAgent = &agent
				break
			}
		}
		require.NotNil(t, originalAgent, "Original agent should still exist")

		// CRITICAL: Verify no registry events created by API service (topology notifications work via events)
		events, err := service.entDB.Client.RegistryEvent.Query().All(context.Background())
		require.NoError(t, err)

		// Should only have 1 event from the original agent registration, not from API service
		assert.Len(t, events, 1, "Only original agent should create events, not API service")
		eventAgent, err := events[0].QueryAgent().Only(context.Background())
		require.NoError(t, err)
		assert.Equal(t, "notification-listener-agent", eventAgent.ID)
		assert.Equal(t, "register", events[0].EventType.String())

		t.Logf("✅ API service registration did not trigger topology notifications")
	})

	t.Run("MixedAgentAndAPIServiceScenario", func(t *testing.T) {
		service := setupTestService(t)
		router := setupTestRouter(t, service)

		// Step 1: Register agent providing capability
		agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		providerAgent := generated.MeshAgentRegistration{
			AgentId:   "provider-agent",
			AgentType: &agentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "process_data",
					Capability:   "data-processor",
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(9002),
		}

		jsonData, err := json.Marshal(providerAgent)
		require.NoError(t, err)
		req, err := http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Step 2: Register agent consumer (should trigger topology notifications)
		consumerAgentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
		consumerAgent := generated.MeshAgentRegistration{
			AgentId:   "consumer-agent",
			AgentType: &consumerAgentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "analyze",
					Capability:   "analyzer",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "data-processor",
						},
					},
				},
			},
			HttpHost: stringPtr("127.0.0.1"),
			HttpPort: intPtr(9003),
		}

		jsonData, err = json.Marshal(consumerAgent)
		require.NoError(t, err)
		req, err = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Step 3: Register API service consumer (should NOT trigger topology notifications)
		apiAgentType := generated.MeshAgentRegistrationAgentTypeApi
		apiConsumer := generated.MeshAgentRegistration{
			AgentId:   "api-consumer-service",
			AgentType: &apiAgentType,
			Tools: []generated.MeshToolRegistration{
				{
					FunctionName: "api_data_endpoint",
					Capability:   "data-api",
					Dependencies: &[]generated.MeshToolDependencyRegistration{
						{
							Capability: "data-processor",
						},
					},
				},
			},
		}

		jsonData, err = json.Marshal(apiConsumer)
		require.NoError(t, err)
		req, err = http.NewRequest("POST", "/heartbeat", bytes.NewBuffer(jsonData))
		require.NoError(t, err)
		req.Header.Set("Content-Type", "application/json")
		recorder = httptest.NewRecorder()
		router.ServeHTTP(recorder, req)
		assert.Equal(t, http.StatusOK, recorder.Code)

		// Verify final state - all services exist in database
		agentsResponse, err := service.ListAgents(nil)
		require.NoError(t, err)
		assert.Len(t, agentsResponse.Agents, 3) // All 3 services (2 agents + 1 API service)

		agentIDs := make([]string, len(agentsResponse.Agents))
		for i, agent := range agentsResponse.Agents {
			agentIDs[i] = agent.Id
		}
		assert.Contains(t, agentIDs, "provider-agent")
		assert.Contains(t, agentIDs, "consumer-agent")
		assert.Contains(t, agentIDs, "api-consumer-service")

		// API service should still get dependency resolution
		var response generated.MeshRegistrationResponse
		err = json.Unmarshal(recorder.Body.Bytes(), &response)
		require.NoError(t, err)
		require.NotNil(t, response.DependenciesResolved)
		dependenciesMap := *response.DependenciesResolved
		assert.Contains(t, dependenciesMap, "api_data_endpoint")
		assert.NotEmpty(t, dependenciesMap["api_data_endpoint"])

		// CRITICAL: Verify event count - only 2 events from agents, not from API service
		events, err := service.entDB.Client.RegistryEvent.Query().All(context.Background())
		require.NoError(t, err)
		assert.Len(t, events, 2, "Only agents should create events, not API services")

		// Check event sources
		eventAgentIDs := make([]string, len(events))
		for i, event := range events {
			eventAgent, err := event.QueryAgent().Only(context.Background())
			require.NoError(t, err)
			eventAgentIDs[i] = eventAgent.ID
		}
		assert.Contains(t, eventAgentIDs, "provider-agent")
		assert.Contains(t, eventAgentIDs, "consumer-agent")
		assert.NotContains(t, eventAgentIDs, "api-consumer-service")

		t.Logf("✅ Mixed scenario: 2 agents registered, API service gets dependencies but not registered")
	})
}
