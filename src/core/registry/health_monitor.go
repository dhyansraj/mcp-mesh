package registry

import (
	"context"
	"fmt"
	"sync"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
)

// AgentHealthMonitor monitors agent health and creates unhealthy events
type AgentHealthMonitor struct {
	entService       *EntService
	logger           *logger.Logger
	heartbeatTimeout time.Duration
	checkInterval    time.Duration
	stopChan         chan struct{}
	wg               sync.WaitGroup
	mu               sync.RWMutex
	running          bool
}

// NewAgentHealthMonitor creates a new health monitor instance
func NewAgentHealthMonitor(entService *EntService, logger *logger.Logger, heartbeatTimeout, checkInterval time.Duration) *AgentHealthMonitor {
	return &AgentHealthMonitor{
		entService:       entService,
		logger:           logger,
		heartbeatTimeout: heartbeatTimeout,
		checkInterval:    checkInterval,
		stopChan:         make(chan struct{}),
		running:          false,
	}
}

// Start begins the background health monitoring
func (h *AgentHealthMonitor) Start() {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.running {
		h.logger.Warning("Health monitor is already running")
		return
	}

	h.running = true
	h.wg.Add(1)

	go func() {
		defer h.wg.Done()
		h.logger.Info("🔍 Starting agent health monitor (timeout: %v, interval: %v)", h.heartbeatTimeout, h.checkInterval)

		ticker := time.NewTicker(h.checkInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				h.checkUnhealthyAgents()
			case <-h.stopChan:
				h.logger.Info("🛑 Agent health monitor stopped")
				return
			}
		}
	}()
}

// Stop gracefully stops the health monitor
func (h *AgentHealthMonitor) Stop() {
	h.mu.Lock()
	defer h.mu.Unlock()

	if !h.running {
		return
	}

	h.running = false
	close(h.stopChan)
	h.wg.Wait()
	h.logger.Info("✅ Agent health monitor stopped successfully")
}

// checkUnhealthyAgents scans all agents and marks unhealthy ones
func (h *AgentHealthMonitor) checkUnhealthyAgents() {
	ctx := context.Background()
	now := time.Now()
	threshold := now.Add(-h.heartbeatTimeout)

	// Query agents that haven't been updated within the threshold
	unhealthyAgents, err := h.entService.entDB.Client.Agent.
		Query().
		Where(agent.UpdatedAtLT(threshold)).
		All(ctx)

	if err != nil {
		h.logger.Error("Failed to query unhealthy agents: %v", err)
		return
	}

	if len(unhealthyAgents) == 0 {
		h.logger.Debug("Health monitor: all agents are healthy")
		return
	}

	h.logger.Info("Health monitor: found %d unhealthy agents", len(unhealthyAgents))

	// Mark each unhealthy agent and create events
	for _, agent := range unhealthyAgents {
		timeSinceLastSeen := now.Sub(agent.UpdatedAt)
		h.logger.Warning("Agent %s is unhealthy (last seen: %v ago)", agent.ID, timeSinceLastSeen)

		err := h.markAgentUnhealthy(ctx, agent.ID, "heartbeat_timeout")
		if err != nil {
			h.logger.Error("Failed to mark agent %s as unhealthy: %v", agent.ID, err)
		}
	}
}

// markAgentUnhealthy creates an unhealthy event and updates agent status
func (h *AgentHealthMonitor) markAgentUnhealthy(ctx context.Context, agentID, reason string) error {
	// Update agent status to unhealthy atomically
	agentUpdated, err := h.entService.entDB.Client.Agent.
		Update().
		Where(agent.IDEQ(agentID)).
		SetStatus(agent.StatusUnhealthy).
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to update agent %s status to unhealthy: %w", agentID, err)
	}

	if agentUpdated == 0 {
		h.logger.Warning("Agent %s not found when marking unhealthy, skipping event creation", agentID)
		return nil // Agent doesn't exist, no need to create event
	}

	// Create unhealthy event
	eventData := map[string]interface{}{
		"reason":          reason,
		"detected_at":     time.Now().Format(time.RFC3339),
		"heartbeat_timeout": h.heartbeatTimeout.String(),
	}

	_, err = h.entService.entDB.Client.RegistryEvent.Create().
		SetEventType(registryevent.EventTypeUnhealthy).
		SetAgentID(agentID).
		SetTimestamp(time.Now()).
		SetData(eventData).
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to create unhealthy event for agent %s: %w", agentID, err)
	}

	h.logger.Info("Marked agent %s as unhealthy and created event (reason: %s)", agentID, reason)
	return nil
}

// IsRunning returns whether the health monitor is currently running
func (h *AgentHealthMonitor) IsRunning() bool {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.running
}

// GetUnhealthyAgents returns a list of agents that are currently unhealthy
func (h *AgentHealthMonitor) GetUnhealthyAgents(ctx context.Context) ([]*ent.Agent, error) {
	threshold := time.Now().Add(-h.heartbeatTimeout)

	return h.entService.entDB.Client.Agent.
		Query().
		Where(agent.UpdatedAtLT(threshold)).
		All(ctx)
}
