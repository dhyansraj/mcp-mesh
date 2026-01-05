package registry

import (
	"context"
	"sync"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/logger"
)

// AgentHealthMonitor monitors agent health and updates status - hooks handle events
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
				h.logger.Trace("🔍 Health monitor timer triggered - checking agent health")
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

	h.logger.Trace("Health monitor check started (threshold: %v)", h.heartbeatTimeout)

	// First, get all agents to see what we're working with
	allAgents, err := h.entService.entDB.Client.Agent.Query().All(ctx)
	if err != nil {
		h.logger.Error("Failed to query all agents: %v", err)
		return
	}

	h.logger.Trace("Health monitor: checking %d total agents (now: %v, threshold: %v, heartbeat_timeout: %v)", len(allAgents), now, threshold, h.heartbeatTimeout)
	for _, agent := range allAgents {
		timeSinceUpdate := now.Sub(agent.UpdatedAt)
		isStale := agent.UpdatedAt.Before(threshold)
		h.logger.Trace("Agent %s: last_update=%v (%v ago), status=%s, is_stale=%v, threshold_comparison=%v", agent.ID, agent.UpdatedAt, timeSinceUpdate, agent.Status, isStale, agent.UpdatedAt.Unix() < threshold.Unix())
	}

	// Use efficient batch update to mark stale agents as unhealthy
	// This will trigger status change hooks for each agent that actually changes status
	h.logger.Trace("Health monitor: batch updating agents with UpdatedAt < %v AND Status != %s", threshold, agent.StatusUnhealthy)

	// Get agents that need to be marked unhealthy first, to preserve their timestamps
	agentsToUpdate, err := h.entService.entDB.Client.Agent.
		Query().
		Where(agent.UpdatedAtLT(threshold)).
		Where(agent.StatusNEQ(agent.StatusUnhealthy)).
		All(ctx)

	if err != nil {
		h.logger.Error("Failed to query agents for health update: %v", err)
		return
	}

	if len(agentsToUpdate) == 0 {
		return
	}

	// Update each agent's status while preserving their original updated_at timestamp
	var agentsUpdated int
	for _, agentToUpdate := range agentsToUpdate {
		affected, err := h.entService.entDB.Client.Agent.
			Update().
			Where(agent.IDEQ(agentToUpdate.ID)).
			SetStatus(agent.StatusUnhealthy).
			SetUpdatedAt(agentToUpdate.UpdatedAt). // Preserve original timestamp
			Save(ctx)

		if err != nil {
			h.logger.Error("Failed to mark agent %s as unhealthy: %v", agentToUpdate.ID, err)
			continue
		}
		agentsUpdated += affected
	}

	h.logger.Info("Health monitor: marked %d agents as unhealthy", agentsUpdated)

	duration := time.Since(startTime)
	h.logger.Trace("Health monitor check completed - processed %d unhealthy agents (took %v)", agentsUpdated, duration)
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
