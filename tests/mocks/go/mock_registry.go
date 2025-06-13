// Package mocks provides mock implementations for testing
//
// 🤖 AI BEHAVIOR GUIDANCE:
// This mock registry is designed to simulate registry behavior for fast unit tests.
//
// DO NOT MODIFY TO MAKE TESTS PASS:
// - If your code breaks these mock behaviors, fix your code
// - These mocks implement the OpenAPI contract (api/mcp-mesh-registry.openapi.yaml)
// - Breaking changes here suggest API contract violations
//
// WHEN TO MODIFY:
// - Only when the user explicitly changes API requirements
// - When OpenAPI spec is updated with user approval
// - To add new mock features requested by user
//
// TEST METADATA:
// - requirement_type: TESTING_INFRASTRUCTURE
// - breaking_change_policy: DISCUSS_WITH_USER
// - contract_reference: api/mcp-mesh-registry.openapi.yaml

package mocks

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// MockRegistry provides a mock implementation of the MCP Mesh Registry
// for fast unit testing without spinning up a real registry service.
type MockRegistry struct {
	server   *httptest.Server
	agents   map[string]*MockAgent
	mu       sync.RWMutex
	requests []MockRequest
	config   MockRegistryConfig
}

// MockAgent represents a registered agent in the mock registry
type MockAgent struct {
	ID           string                 `json:"id"`
	Name         string                 `json:"name"`
	Status       string                 `json:"status"`
	Endpoint     string                 `json:"endpoint"`
	Capabilities []string               `json:"capabilities"`
	Dependencies []string               `json:"dependencies"`
	LastSeen     time.Time              `json:"last_seen"`
	Version      string                 `json:"version"`
	Metadata     map[string]interface{} `json:"metadata"`
}

// MockRequest tracks requests made to the mock registry for test verification
type MockRequest struct {
	Method    string                 `json:"method"`
	Path      string                 `json:"path"`
	Body      map[string]interface{} `json:"body,omitempty"`
	Timestamp time.Time              `json:"timestamp"`
}

// MockRegistryConfig configures mock registry behavior
type MockRegistryConfig struct {
	Port                int           `json:"port"`
	SimulateLatency     bool          `json:"simulate_latency"`
	LatencyMs           int           `json:"latency_ms"`
	FailureRate         float64       `json:"failure_rate"` // 0.0 to 1.0
	ReturnErrors        bool          `json:"return_errors"`
	EnableDependencies  bool          `json:"enable_dependencies"`
	MaxAgents           int           `json:"max_agents"`
	StartTime           time.Time     `json:"start_time"`
}

// NewMockRegistry creates a new mock registry with default configuration
//
// 🤖 AI USAGE PATTERN:
// mock := NewMockRegistry()
// defer mock.Close()
//
// // Your tests here
// client := NewRegistryClient(mock.GetURL())
func NewMockRegistry() *MockRegistry {
	return NewMockRegistryWithConfig(MockRegistryConfig{
		Port:               0, // Auto-assign port
		SimulateLatency:    false,
		LatencyMs:          0,
		FailureRate:        0.0,
		ReturnErrors:       false,
		EnableDependencies: true,
		MaxAgents:          100,
		StartTime:          time.Now(),
	})
}

// NewMockRegistryWithConfig creates a mock registry with custom configuration
func NewMockRegistryWithConfig(config MockRegistryConfig) *MockRegistry {
	mock := &MockRegistry{
		agents:   make(map[string]*MockAgent),
		requests: make([]MockRequest, 0),
		config:   config,
	}

	// Create Gin router
	gin.SetMode(gin.TestMode)
	router := gin.New()

	// Add middleware for request tracking and latency simulation
	router.Use(mock.trackRequests())
	if config.SimulateLatency && config.LatencyMs > 0 {
		router.Use(mock.simulateLatency())
	}

	// Setup routes matching OpenAPI spec
	mock.setupRoutes(router)

	// Start test server
	mock.server = httptest.NewServer(router)

	return mock
}

// trackRequests middleware tracks all incoming requests
func (m *MockRegistry) trackRequests() gin.HandlerFunc {
	return gin.HandlerFunc(func(c *gin.Context) {
		// Capture request body
		var body map[string]interface{}
		if c.Request.Body != nil {
			if err := c.ShouldBindJSON(&body); err == nil {
				// Re-bind for downstream handlers
				c.Set("request_body", body)
			}
		}

		// Track the request
		m.mu.Lock()
		m.requests = append(m.requests, MockRequest{
			Method:    c.Request.Method,
			Path:      c.Request.URL.Path,
			Body:      body,
			Timestamp: time.Now(),
		})
		m.mu.Unlock()

		c.Next()
	})
}

// simulateLatency middleware adds artificial latency
func (m *MockRegistry) simulateLatency() gin.HandlerFunc {
	return gin.HandlerFunc(func(c *gin.Context) {
		time.Sleep(time.Duration(m.config.LatencyMs) * time.Millisecond)
		c.Next()
	})
}

// setupRoutes configures all mock registry endpoints
func (m *MockRegistry) setupRoutes(router *gin.Engine) {
	// Health endpoints
	router.GET("/health", m.handleHealth)
	router.GET("/", m.handleRoot)

	// Agent endpoints
	router.POST("/agents/register", m.handleRegisterAgent)
	router.GET("/agents", m.handleListAgents)
	router.GET("/agents/:id", m.handleGetAgent)
	router.DELETE("/agents/:id", m.handleDeleteAgent)

	// Heartbeat endpoint
	router.POST("/heartbeat", m.handleHeartbeat)
}

// handleHealth implements GET /health
func (m *MockRegistry) handleHealth(c *gin.Context) {
	/*
	🤖 AI CONTRACT COMPLIANCE:
	This endpoint MUST match the OpenAPI spec for HealthResponse.
	Required fields: status, version, uptime_seconds, timestamp, service
	DO NOT modify without checking api/mcp-mesh-registry.openapi.yaml
	*/

	uptime := time.Since(m.config.StartTime).Seconds()

	response := gin.H{
		"status":         "healthy",
		"version":        "1.0.0",
		"uptime_seconds": int(uptime),
		"timestamp":      time.Now().Format(time.RFC3339),
		"service":        "mcp-mesh-registry",
	}

	c.JSON(http.StatusOK, response)
}

// handleRoot implements GET /
func (m *MockRegistry) handleRoot(c *gin.Context) {
	/*
	🤖 AI CONTRACT COMPLIANCE:
	This endpoint MUST match the OpenAPI spec for RootResponse.
	Required fields: service, version, status, endpoints
	*/

	response := gin.H{
		"service":   "mcp-mesh-registry",
		"version":   "1.0.0",
		"status":    "running",
		"endpoints": []string{"/health", "/heartbeat", "/agents", "/agents/register"},
	}

	c.JSON(http.StatusOK, response)
}

// handleRegisterAgent implements POST /agents/register
func (m *MockRegistry) handleRegisterAgent(c *gin.Context) {
	/*
	🤖 AI CONTRACT COMPLIANCE:
	This endpoint MUST match the OpenAPI spec for:
	- Request: AgentRegistration schema
	- Response: RegistrationResponse schema
	- Status codes: 201 (success), 400 (bad request)

	CRITICAL: This is the core registration endpoint used by Python runtime.
	Breaking changes here will break agent registration!
	*/

	// Simulate failure if configured
	if m.config.ReturnErrors && m.shouldSimulateFailure() {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     "Simulated registry failure",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	var req map[string]interface{}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Invalid JSON payload",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Extract agent_id
	agentID, ok := req["agent_id"].(string)
	if !ok || agentID == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Missing or invalid agent_id",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Extract metadata
	metadata, ok := req["metadata"].(map[string]interface{})
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Missing or invalid metadata",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Check agent limit
	m.mu.Lock()
	if len(m.agents) >= m.config.MaxAgents {
		m.mu.Unlock()
		c.JSON(http.StatusTooManyRequests, gin.H{
			"error":     "Maximum number of agents reached",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Create mock agent
	agent := &MockAgent{
		ID:           agentID,
		Name:         getStringFromMap(metadata, "name", agentID),
		Status:       "healthy",
		Endpoint:     getStringFromMap(metadata, "endpoint", "stdio://"+agentID),
		Capabilities: getStringSliceFromMap(metadata, "capabilities"),
		Dependencies: getStringSliceFromMap(metadata, "dependencies"),
		LastSeen:     time.Now(),
		Version:      getStringFromMap(metadata, "version", "1.0.0"),
		Metadata:     metadata,
	}

	// Store the agent
	m.agents[agentID] = agent
	m.mu.Unlock()

	// Build response with optional dependency resolution
	response := gin.H{
		"status":    "success",
		"timestamp": time.Now().Format(time.RFC3339),
		"message":   "Agent registered successfully",
		"agent_id":  agentID,
	}

	// Add dependency resolution if enabled and agent has dependencies
	if m.config.EnableDependencies && len(agent.Dependencies) > 0 {
		dependenciesResolved := m.resolveDependencies(agent.Dependencies)
		if len(dependenciesResolved) > 0 {
			response["dependencies_resolved"] = dependenciesResolved
		}
	}

	c.JSON(http.StatusCreated, response)
}

// handleHeartbeat implements POST /heartbeat
func (m *MockRegistry) handleHeartbeat(c *gin.Context) {
	/*
	🤖 AI CONTRACT COMPLIANCE:
	This endpoint MUST match the OpenAPI spec for:
	- Request: HeartbeatRequest schema
	- Response: HeartbeatResponse schema
	- Status codes: 200 (success), 400 (bad request)

	CRITICAL: Python runtime depends on this for health monitoring
	and dependency injection updates!
	*/

	var req map[string]interface{}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Invalid JSON payload",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	agentID, ok := req["agent_id"].(string)
	if !ok || agentID == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Missing or invalid agent_id",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Update agent's last seen time
	m.mu.Lock()
	agent, exists := m.agents[agentID]
	if exists {
		agent.LastSeen = time.Now()
		// Update status from heartbeat if provided
		if status, ok := req["status"].(string); ok {
			agent.Status = status
		}
	}
	m.mu.Unlock()

	if !exists {
		c.JSON(http.StatusNotFound, gin.H{
			"error":     "Agent not registered",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Build response
	response := gin.H{
		"status":    "success",
		"timestamp": time.Now().Format(time.RFC3339),
		"message":   "Heartbeat received",
	}

	// Add dependency resolution if agent has dependencies
	if m.config.EnableDependencies && len(agent.Dependencies) > 0 {
		dependenciesResolved := m.resolveDependencies(agent.Dependencies)
		if len(dependenciesResolved) > 0 {
			response["dependencies_resolved"] = dependenciesResolved
		}
	}

	c.JSON(http.StatusOK, response)
}

// handleListAgents implements GET /agents
func (m *MockRegistry) handleListAgents(c *gin.Context) {
	/*
	🤖 AI CONTRACT COMPLIANCE:
	This endpoint MUST match the OpenAPI spec for AgentsListResponse.
	Required fields: agents, count, timestamp
	Agent fields: id, name, status, endpoint, capabilities
	*/

	m.mu.RLock()
	agents := make([]gin.H, 0, len(m.agents))
	for _, agent := range m.agents {
		agents = append(agents, gin.H{
			"id":           agent.ID,
			"name":         agent.Name,
			"status":       agent.Status,
			"endpoint":     agent.Endpoint,
			"capabilities": agent.Capabilities,
			"dependencies": agent.Dependencies,
			"last_seen":    agent.LastSeen.Format(time.RFC3339),
			"version":      agent.Version,
		})
	}
	m.mu.RUnlock()

	response := gin.H{
		"agents":    agents,
		"count":     len(agents),
		"timestamp": time.Now().Format(time.RFC3339),
	}

	c.JSON(http.StatusOK, response)
}

// handleGetAgent implements GET /agents/:id
func (m *MockRegistry) handleGetAgent(c *gin.Context) {
	agentID := c.Param("id")

	m.mu.RLock()
	agent, exists := m.agents[agentID]
	m.mu.RUnlock()

	if !exists {
		c.JSON(http.StatusNotFound, gin.H{
			"error":     "Agent not found",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	response := gin.H{
		"id":           agent.ID,
		"name":         agent.Name,
		"status":       agent.Status,
		"endpoint":     agent.Endpoint,
		"capabilities": agent.Capabilities,
		"dependencies": agent.Dependencies,
		"last_seen":    agent.LastSeen.Format(time.RFC3339),
		"version":      agent.Version,
		"metadata":     agent.Metadata,
	}

	c.JSON(http.StatusOK, response)
}

// handleDeleteAgent implements DELETE /agents/:id
func (m *MockRegistry) handleDeleteAgent(c *gin.Context) {
	agentID := c.Param("id")

	m.mu.Lock()
	_, exists := m.agents[agentID]
	if exists {
		delete(m.agents, agentID)
	}
	m.mu.Unlock()

	if !exists {
		c.JSON(http.StatusNotFound, gin.H{
			"error":     "Agent not found",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"status":    "success",
		"message":   "Agent deregistered successfully",
		"timestamp": time.Now().Format(time.RFC3339),
	})
}

// resolveDependencies simulates dependency resolution
func (m *MockRegistry) resolveDependencies(dependencies []string) map[string]interface{} {
	resolved := make(map[string]interface{})

	m.mu.RLock()
	for _, depName := range dependencies {
		// Find agent that provides this dependency
		for _, agent := range m.agents {
			// Check if agent provides the capability
			for _, capability := range agent.Capabilities {
				if capability == depName || agent.ID == depName {
					resolved[depName] = gin.H{
						"agent_id":     agent.ID,
						"endpoint":     agent.Endpoint,
						"status":       "available",
						"capabilities": []string{capability},
						"version":      agent.Version,
					}
					break
				}
			}
		}
	}
	m.mu.RUnlock()

	return resolved
}

// shouldSimulateFailure determines if a failure should be simulated
func (m *MockRegistry) shouldSimulateFailure() bool {
	if m.config.FailureRate <= 0 {
		return false
	}
	// Simple pseudo-random based on current time
	return float64(time.Now().UnixNano()%1000)/1000.0 < m.config.FailureRate
}

// Utility functions for extracting data from maps
func getStringFromMap(m map[string]interface{}, key, defaultValue string) string {
	if value, ok := m[key].(string); ok {
		return value
	}
	return defaultValue
}

func getStringSliceFromMap(m map[string]interface{}, key string) []string {
	if value, ok := m[key].([]interface{}); ok {
		result := make([]string, 0, len(value))
		for _, v := range value {
			if str, ok := v.(string); ok {
				result = append(result, str)
			}
		}
		return result
	}
	return []string{}
}

// Public methods for test verification and control

// GetURL returns the mock registry URL
func (m *MockRegistry) GetURL() string {
	return m.server.URL
}

// Close shuts down the mock registry
func (m *MockRegistry) Close() {
	m.server.Close()
}

// GetRequests returns all requests made to the mock registry
func (m *MockRegistry) GetRequests() []MockRequest {
	m.mu.RLock()
	defer m.mu.RUnlock()
	// Return a copy to avoid race conditions
	requests := make([]MockRequest, len(m.requests))
	copy(requests, m.requests)
	return requests
}

// GetAgents returns all registered agents
func (m *MockRegistry) GetAgents() map[string]*MockAgent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	// Return a copy to avoid race conditions
	agents := make(map[string]*MockAgent)
	for k, v := range m.agents {
		agentCopy := *v
		agents[k] = &agentCopy
	}
	return agents
}

// ClearRequests clears the request history
func (m *MockRegistry) ClearRequests() {
	m.mu.Lock()
	m.requests = make([]MockRequest, 0)
	m.mu.Unlock()
}

// ClearAgents removes all registered agents
func (m *MockRegistry) ClearAgents() {
	m.mu.Lock()
	m.agents = make(map[string]*MockAgent)
	m.mu.Unlock()
}

// SetConfig updates the mock registry configuration
func (m *MockRegistry) SetConfig(config MockRegistryConfig) {
	m.mu.Lock()
	m.config = config
	m.mu.Unlock()
}

// GetConfig returns the current configuration
func (m *MockRegistry) GetConfig() MockRegistryConfig {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config
}

// SimulateAgentTimeout marks an agent as unhealthy due to timeout
func (m *MockRegistry) SimulateAgentTimeout(agentID string) {
	m.mu.Lock()
	if agent, exists := m.agents[agentID]; exists {
		agent.Status = "unhealthy"
		agent.LastSeen = time.Now().Add(-10 * time.Minute) // Simulate old last seen
	}
	m.mu.Unlock()
}

// AddAgent manually adds an agent (for test setup)
func (m *MockRegistry) AddAgent(agent *MockAgent) {
	m.mu.Lock()
	m.agents[agent.ID] = agent
	m.mu.Unlock()
}

// 🤖 AI TESTING PATTERNS:
//
// BASIC USAGE:
//   mock := NewMockRegistry()
//   defer mock.Close()
//   // Test your code against mock.GetURL()
//
// FAILURE SIMULATION:
//   config := MockRegistryConfig{FailureRate: 0.1, ReturnErrors: true}
//   mock := NewMockRegistryWithConfig(config)
//
// REQUEST VERIFICATION:
//   requests := mock.GetRequests()
//   // Assert expected requests were made
//
// AGENT STATE VERIFICATION:
//   agents := mock.GetAgents()
//   // Assert expected agents are registered
