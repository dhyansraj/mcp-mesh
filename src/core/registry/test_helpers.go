package registry

import (
	"sync"
	"time"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/registryevent"
)

// MockEntService provides a test double for EntService
type MockEntService struct {
	mu              sync.RWMutex
	agents          map[string]*ent.Agent
	events          []*ent.RegistryEvent
	topologyChanges map[string]bool
	serviceError    bool
}

// NOTE: Using real ent.Agent and ent.RegistryEvent types instead of custom types

func NewMockEntService() *MockEntService {
	return &MockEntService{
		agents:          make(map[string]*ent.Agent),
		events:          make([]*ent.RegistryEvent, 0),
		topologyChanges: make(map[string]bool),
		serviceError:    false,
	}
}

// Agent management methods
func (m *MockEntService) SetAgent(agentID string, agent *ent.Agent) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.agents[agentID] = agent
}

func (m *MockEntService) GetAgent(agentID string) *ent.Agent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.agents[agentID]
}

func (m *MockEntService) DeleteAgent(agentID string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.agents, agentID)
}

func (m *MockEntService) GetAllAgents() []*ent.Agent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	agents := make([]*ent.Agent, 0, len(m.agents))
	for _, agent := range m.agents {
		agents = append(agents, agent)
	}
	return agents
}

// Event management methods
func (m *MockEntService) AddEvent(event *ent.RegistryEvent) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.events = append(m.events, event)
}

func (m *MockEntService) GetEvents() []*ent.RegistryEvent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	// Return a copy to avoid race conditions
	events := make([]*ent.RegistryEvent, len(m.events))
	copy(events, m.events)
	return events
}

func (m *MockEntService) ClearEvents() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.events = m.events[:0]
}

// Topology change simulation methods
func (m *MockEntService) SetTopologyChanges(agentID string, hasChanges bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.topologyChanges[agentID] = hasChanges
}

func (m *MockEntService) GetTopologyChanges(agentID string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.topologyChanges[agentID]
}

// Service error simulation methods
func (m *MockEntService) SetServiceError(hasError bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.serviceError = hasError
}

func (m *MockEntService) HasServiceError() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.serviceError
}

// LoadTestData loads realistic test data from our captured payloads
func (m *MockEntService) LoadTestData() {
	m.mu.Lock()
	defer m.mu.Unlock()

	// FastMCP Agent from real data
	fastmcpAgent := &ent.Agent{
		ID:        "fastmcp-service-3a65d884",
		Name:      "fastmcp-service-3a65d884",
		AgentType: agent.AgentTypeMcpAgent,
		Version:   "1.0.0",
		HTTPHost:  "10.211.55.3",
		HTTPPort:  9092,
		Namespace: "default",
		Status:    agent.StatusHealthy,
		LastFullRefresh: time.Now().Add(-5 * time.Minute),
		UpdatedAt:       time.Now().Add(-30 * time.Second),
		CreatedAt:       time.Now().Add(-10 * time.Minute),
	}
	m.agents[fastmcpAgent.ID] = fastmcpAgent

	// Dependent Agent from real data
	dependentAgent := &ent.Agent{
		ID:        "dependent-service-00d6169a",
		Name:      "dependent-service-00d6169a",
		AgentType: agent.AgentTypeMcpAgent,
		Version:   "1.0.0",
		HTTPHost:  "10.211.55.3",
		HTTPPort:  9093,
		Namespace: "default",
		Status:    agent.StatusHealthy,
		LastFullRefresh: time.Now().Add(-3 * time.Minute),
		UpdatedAt:       time.Now().Add(-15 * time.Second),
		CreatedAt:       time.Now().Add(-8 * time.Minute),
	}
	m.agents[dependentAgent.ID] = dependentAgent

	// Add some historical events
	m.events = append(m.events, &ent.RegistryEvent{
		ID:        1,
		EventType: registryevent.EventTypeRegister,
		Timestamp: time.Now().Add(-10 * time.Minute),
		Data:      map[string]interface{}{"reason": "startup"},
	})

	m.events = append(m.events, &ent.RegistryEvent{
		ID:        2,
		EventType: registryevent.EventTypeRegister,
		Timestamp: time.Now().Add(-8 * time.Minute),
		Data:      map[string]interface{}{"reason": "startup"},
	})
}

// HealthMonitor interface for testing
type HealthMonitorInterface interface {
	CheckUnhealthyAgents()
	MarkAgentUnhealthy(agentID string, reason string)
}

// HealthMonitor implementation for testing
type HealthMonitor struct {
	service         *MockEntService
	heartbeatTimeout time.Duration
}

func NewHealthMonitor(service *MockEntService, timeout time.Duration) *HealthMonitor {
	return &HealthMonitor{
		service:         service,
		heartbeatTimeout: timeout,
	}
}

func (h *HealthMonitor) CheckUnhealthyAgents() {
	h.service.mu.RLock()
	agents := make([]*ent.Agent, 0, len(h.service.agents))
	for _, agent := range h.service.agents {
		agents = append(agents, agent)
	}
	h.service.mu.RUnlock()

	now := time.Now()
	for _, agent := range agents {
		// Check if agent is unhealthy based on last update time
		timeSinceLastSeen := now.Sub(agent.UpdatedAt)
		if timeSinceLastSeen > h.heartbeatTimeout {
			h.MarkAgentUnhealthy(agent.ID, "heartbeat_timeout")
		}
	}
}

func (h *HealthMonitor) MarkAgentUnhealthy(agentID string, reason string) {
	h.service.mu.Lock()
	defer h.service.mu.Unlock()

	// Only create unhealthy event if agent exists
	agentEntity, exists := h.service.agents[agentID]
	if !exists {
		return
	}

	// Update agent status to unhealthy
	agentEntity.Status = agent.StatusUnhealthy

	// Create unhealthy event
	event := &ent.RegistryEvent{
		ID:        len(h.service.events) + 1,
		EventType: registryevent.EventTypeUnhealthy,
		Timestamp: time.Now(),
		Data:      map[string]interface{}{"reason": reason},
	}
	h.service.events = append(h.service.events, event)

	// Mark topology change for this agent (others should get 202 on HEAD checks)
	h.service.topologyChanges[agentID] = true
}

// RegisterAgent mock implementation
func (m *MockEntService) RegisterAgent(req *AgentRegistrationRequest) (*AgentRegistrationResponse, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Create new agent with healthy status
	agent := &ent.Agent{
		ID:              req.AgentID,
		Name:            req.AgentID,
		Status:          "healthy",
		AgentType:       agent.AgentTypeMcpAgent,
		Version:         "1.0.0",
		HTTPHost:        "localhost",
		HTTPPort:        8080,
		Namespace:       "default",
		LastFullRefresh: time.Now(),
		UpdatedAt:       time.Now(),
		CreatedAt:       time.Now(),
	}
	m.agents[req.AgentID] = agent

	// Create register event
	event := &ent.RegistryEvent{
		ID:        len(m.events) + 1,
		EventType: registryevent.EventTypeRegister,
		Timestamp: time.Now(),
		Data:      map[string]interface{}{"reason": "registration"},
	}
	m.events = append(m.events, event)

	return &AgentRegistrationResponse{
		Status:          "success",
		AgentID:         req.AgentID,
		ResourceVersion: "1",
		Timestamp:       time.Now().Format(time.RFC3339),
		Message:         "Agent registered successfully",
	}, nil
}

// UpdateHeartbeat mock implementation
func (m *MockEntService) UpdateHeartbeat(req *HeartbeatRequest) (*HeartbeatResponse, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	agentEntity, exists := m.agents[req.AgentID]
	if !exists {
		return &HeartbeatResponse{
			Status:    "error",
			Timestamp: time.Now().Format(time.RFC3339),
			Message:   "Agent not found",
		}, nil
	}

	now := time.Now()
	previousStatus := agentEntity.Status

	// If agent was unhealthy and this is a full heartbeat with metadata, restore to healthy
	if agentEntity.Status == agent.StatusUnhealthy && req.Metadata != nil {
		if _, hasTools := req.Metadata["tools"]; hasTools {
			agentEntity.Status = agent.StatusHealthy

			// Create register event (agent recovered)
			event := &ent.RegistryEvent{
				ID:        len(m.events) + 1,
				EventType: registryevent.EventTypeRegister,
				Timestamp: now,
				Data:      map[string]interface{}{"reason": "recovery", "recovery": true},
			}
			m.events = append(m.events, event)
		}
	}

	// Update agent timestamps
	agentEntity.UpdatedAt = now
	agentEntity.LastFullRefresh = now

	// Create heartbeat event
	event := &ent.RegistryEvent{
		ID:        len(m.events) + 1,
		EventType: registryevent.EventTypeHeartbeat,
		Timestamp: now,
		Data:      map[string]interface{}{"status": agentEntity.Status, "previous_status": previousStatus},
	}
	m.events = append(m.events, event)

	return &HeartbeatResponse{
		Status:    "success",
		Timestamp: now.Format(time.RFC3339),
		Message:   "Heartbeat updated successfully",
		AgentID:   req.AgentID,
	}, nil
}
