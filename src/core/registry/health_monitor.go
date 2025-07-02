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
				h.logger.Debug("🔍 Health monitor timer triggered - checking agent health")
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
	startTime := time.Now().UTC()
	now := time.Now().UTC()
	threshold := now.Add(-h.heartbeatTimeout)

	h.logger.Debug("Health monitor check started (threshold: %v)", h.heartbeatTimeout)

	// First, get all agents to see what we're working with
	allAgents, err := h.entService.entDB.Client.Agent.Query().All(ctx)
	if err != nil {
		h.logger.Error("Failed to query all agents: %v", err)
		return
	}

	h.logger.Debug("Health monitor: checking %d total agents (now: %v, threshold: %v, heartbeat_timeout: %v)", len(allAgents), now, threshold, h.heartbeatTimeout)
	for _, agent := range allAgents {
		timeSinceUpdate := now.Sub(agent.UpdatedAt)
		isStale := agent.UpdatedAt.Before(threshold)
		h.logger.Debug("Agent %s: last_update=%v (%v ago), status=%s, is_stale=%v, threshold_comparison=%v", agent.ID, agent.UpdatedAt, timeSinceUpdate, agent.Status, isStale, agent.UpdatedAt.Unix() < threshold.Unix())
	}

	// Query agents that haven't been updated within the threshold AND are not already unhealthy
	h.logger.Debug("Health monitor: querying agents with UpdatedAt < %v AND Status != %s", threshold, agent.StatusUnhealthy)

	// Manual check - let's see if any agents meet the criteria
	for _, ag := range allAgents {
		if ag.UpdatedAt.Before(threshold) && ag.Status != agent.StatusUnhealthy {
			h.logger.Warning("Manual check: Agent %s should be marked unhealthy (last_update=%v, threshold=%v, status=%s)",
				ag.ID, ag.UpdatedAt, threshold, ag.Status)
		}
	}

	// Query agents that haven't been updated within the threshold AND are not already unhealthy
	unhealthyAgents, err := h.entService.entDB.Client.Agent.
		Query().
		Where(agent.UpdatedAtLT(threshold)).
		Where(agent.StatusNEQ(agent.StatusUnhealthy)).
		All(ctx)

	if err != nil {
		h.logger.Error("Failed to query unhealthy agents: %v", err)
		return
	}

	h.logger.Debug("Health monitor: query returned %d unhealthy agents", len(unhealthyAgents))

	if len(unhealthyAgents) == 0 {
		duration := time.Since(startTime)
		h.logger.Info("Health monitor check completed - all agents are healthy (took %v)", duration)
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

	duration := time.Since(startTime)
	h.logger.Debug("Health monitor check completed - processed %d unhealthy agents (took %v)", len(unhealthyAgents), duration)
}

// markAgentUnhealthy creates an unhealthy event and updates agent status
func (h *AgentHealthMonitor) markAgentUnhealthy(ctx context.Context, agentID, reason string) error {
	// Get the current agent to preserve its UpdatedAt timestamp
	currentAgent, err := h.entService.entDB.Client.Agent.
		Query().
		Where(agent.IDEQ(agentID)).
		Only(ctx)

	if err != nil {
		if ent.IsNotFound(err) {
			h.logger.Warning("Agent %s not found when marking unhealthy", agentID)
			return nil
		}
		return fmt.Errorf("failed to query agent %s: %w", agentID, err)
	}

	// Update agent status to unhealthy while preserving original UpdatedAt timestamp
	agentUpdated, err := h.entService.entDB.Client.Agent.
		Update().
		Where(agent.IDEQ(agentID)).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(currentAgent.UpdatedAt). // Preserve original timestamp
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
		"detected_at":     time.Now().UTC().Format(time.RFC3339),
		"heartbeat_timeout": h.heartbeatTimeout.String(),
	}

	_, err = h.entService.entDB.Client.RegistryEvent.Create().
		SetEventType(registryevent.EventTypeUnhealthy).
		SetAgentID(agentID).
		SetTimestamp(time.Now().UTC()).
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
	threshold := time.Now().UTC().Add(-h.heartbeatTimeout)

	return h.entService.entDB.Client.Agent.
		Query().
		Where(agent.UpdatedAtLT(threshold)).
		All(ctx)
}
