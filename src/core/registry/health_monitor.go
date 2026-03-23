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
	cancel           context.CancelFunc
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
	ctx, cancel := context.WithCancel(context.Background())
	h.cancel = cancel
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
			case <-ctx.Done():
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
	h.cancel()
	h.wg.Wait()
	h.logger.Info("✅ Agent health monitor stopped successfully")
}

// checkUnhealthyAgents marks stale agents as unhealthy using a single batch query
func (h *AgentHealthMonitor) checkUnhealthyAgents() {
	ctx := context.Background()
	threshold := time.Now().UTC().Add(-h.heartbeatTimeout)

	// Single query: get agents that need status change (for logging + preserving timestamps)
	agentsToUpdate, err := h.entService.entDB.Client.Agent.
		Query().
		Where(
			agent.UpdatedAtLT(threshold),
			agent.StatusNEQ(agent.StatusUnhealthy),
		).
		All(ctx)

	if err != nil {
		h.logger.Error("Failed to query agents for health update: %v", err)
		return
	}

	if len(agentsToUpdate) == 0 {
		return
	}

	// Update each agent while preserving their original updated_at timestamp.
	// Individual updates needed because Ent's UpdateDefault(time.Now) would
	// auto-bump updated_at in a batch update, making agents appear recently seen.
	var agentsUpdated int
	for _, a := range agentsToUpdate {
		_, err := h.entService.entDB.Client.Agent.
			Update().
			Where(agent.IDEQ(a.ID)).
			SetStatus(agent.StatusUnhealthy).
			SetUpdatedAt(a.UpdatedAt).
			Save(ctx)
		if err != nil {
			h.logger.Error("Failed to mark agent %s as unhealthy: %v", a.ID, err)
			continue
		}
		agentsUpdated++
	}

	h.logger.Info("Health monitor: marked %d agents as unhealthy", agentsUpdated)
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
