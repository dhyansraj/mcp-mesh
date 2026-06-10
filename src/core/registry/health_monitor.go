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
	if h.cancel != nil {
		h.cancel()
	}
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
	var agentsUpdated, racesLost int
	for _, a := range agentsToUpdate {
		won, err := h.markAgentUnhealthyIfUnchanged(ctx, a)
		if err != nil {
			h.logger.Error("Failed to mark agent %s as unhealthy: %v", a.ID, err)
			continue
		}
		if !won {
			// Race lost: a concurrent heartbeat updated the row between our
			// query and this update. The agent is alive — leave it alone.
			racesLost++
			continue
		}
		agentsUpdated++

		// Flip all resolution rows that point at this now-offline provider to
		// unavailable so consumer-side state stays consistent (see
		// UpdateDependencyStatusOnAgentOffline). Only the race-winner gets
		// here, so a concurrently-heartbeating agent never has its rows
		// flipped. Best-effort: a failure here is logged, not fatal — the
		// sweep job's purge will eventually fix the rows.
		if err := h.entService.UpdateDependencyStatusOnAgentOffline(ctx, a.ID); err != nil {
			h.logger.Warning("Failed to mark resolutions unavailable for unhealthy agent %s: %v", a.ID, err)
		}
	}

	if racesLost > 0 {
		h.logger.Info("Health monitor: marked %d agents as unhealthy (%d skipped due to concurrent heartbeat)", agentsUpdated, racesLost)
	} else {
		h.logger.Info("Health monitor: marked %d agents as unhealthy", agentsUpdated)
	}
}

// markAgentUnhealthyIfUnchanged flips a single agent to unhealthy using an
// optimistic conditional update (same pattern as markAgentStaleAttempt): the
// WHERE clause re-checks that the row still has the status and updated_at we
// observed when we queried it. A concurrent heartbeat between the staleness
// query and this update changes updated_at (and possibly status), so the
// update affects 0 rows and we report the race as lost instead of overwriting
// the heartbeat and rolling the timestamp back.
//
// The original updated_at is deliberately preserved on success: that field is
// the agent's last-heartbeat timestamp from the sweep job's perspective
// (purgeStaleAgents filters on UpdatedAtLT(now-retention)); bumping it would
// make a long-silent agent survive sweeps it should not.
func (h *AgentHealthMonitor) markAgentUnhealthyIfUnchanged(ctx context.Context, a *ent.Agent) (bool, error) {
	affected, err := h.entService.entDB.Client.Agent.
		Update().
		Where(
			agent.IDEQ(a.ID),
			agent.UpdatedAtEQ(a.UpdatedAt),
			agent.StatusEQ(a.Status),
		).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(a.UpdatedAt).
		Save(ctx)
	if err != nil {
		return false, err
	}
	return affected > 0, nil
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
