package registry

import (
	"context"
	"fmt"
	"time"

	entgo "entgo.io/ent"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
)

// StatusChangeHookConfig holds configuration for status change hooks
type StatusChangeHookConfig struct {
	Logger  *logger.Logger
	Enabled bool
}

// CreateAgentStatusChangeHook creates a hook that monitors agent status changes
// and automatically creates registry events when the status field changes
func CreateAgentStatusChangeHook(config *StatusChangeHookConfig) entgo.Hook {
	return func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			// Only handle agent mutations
			agentMutation, ok := m.(*ent.AgentMutation)
			if !ok {
				return next.Mutate(ctx, m)
			}

			// Only process updates that include the status field
			if agentMutation.Op() != ent.OpUpdate && agentMutation.Op() != ent.OpUpdateOne {
				// Not an update operation, proceed with normal mutation
				return next.Mutate(ctx, m)
			}

			// Check if status field is being updated
			if _, exists := agentMutation.Status(); !exists {
				// Status field not being updated, proceed with normal mutation
				return next.Mutate(ctx, m)
			}

			// Handle the status change before the mutation
			_, err := handleAgentStatusChange(ctx, agentMutation, config)
			if err != nil {
				config.Logger.Warning("Status change hook failed: %v", err)
				// Don't fail the mutation if hook fails
			}

			// Continue with the normal mutation
			return next.Mutate(ctx, m)
		})
	}
}

// handleAgentStatusChange processes agent status changes and creates appropriate events
func handleAgentStatusChange(ctx context.Context, m *ent.AgentMutation, config *StatusChangeHookConfig) (ent.Value, error) {
	if !config.Enabled {
		// Hook is disabled, proceed with normal mutation
		return nil, nil
	}

	// Get the new status value
	newStatus, exists := m.Status()
	if !exists {
		// Status field isn't being updated, shouldn't happen due to condition but safety check
		return nil, nil
	}

	// Get the agent IDs (handles both single and bulk operations)
	agentIDs, err := m.IDs(ctx)
	if err != nil {
		config.Logger.Error("Failed to get agent IDs for status change hook: %v", err)
		return nil, nil
	}

	if len(agentIDs) == 0 {
		config.Logger.Warning("Agent status change hook triggered but no agent IDs found")
		return nil, nil
	}

	// Handle each agent that will be affected by this status change
	for _, agentID := range agentIDs {
		// Get the old status by querying the current agent
		// Note: This happens before the mutation is applied, so we get the current state
		oldAgent, err := m.Client().Agent.Get(ctx, agentID)
		if err != nil {
			if ent.IsNotFound(err) {
				// Agent doesn't exist yet, this might be a create operation
				// But our condition should prevent this, so log and continue
				config.Logger.Debug("Agent %s not found during status change hook, skipping event creation", agentID)
				continue
			}
			config.Logger.Error("Failed to get current agent %s status: %v", agentID, err)
			continue
		}

		oldStatus := oldAgent.Status

		// Check if status actually changed
		if oldStatus == newStatus {
			config.Logger.Debug("Agent %s status unchanged (%s), skipping event creation", agentID, newStatus)
			continue
		}

		// Log the status transition
		config.Logger.Info("Agent %s status changing: %s → %s", agentID, oldStatus, newStatus)

		// Check if this is a graceful shutdown scenario (healthy → unhealthy)
		// and if an explicit unregister event already exists
		if oldStatus == agent.StatusHealthy && newStatus == agent.StatusUnhealthy {
			// Check for recent unregister events (within last 5 seconds)
			recentThreshold := time.Now().UTC().Add(-5 * time.Second)
			recentUnregisterExists, err := m.Client().RegistryEvent.Query().
				Where(registryevent.HasAgentWith(agent.IDEQ(agentID))).
				Where(registryevent.EventTypeEQ(registryevent.EventTypeUnregister)).
				Where(registryevent.TimestampGT(recentThreshold)).
				Exist(ctx)
			if err != nil {
				config.Logger.Warning("Failed to check for recent unregister events for agent %s: %v", agentID, err)
			} else if recentUnregisterExists {
				config.Logger.Debug("Agent %s has recent unregister event, skipping hook-based event creation", agentID)
				continue
			}
		}

		// Create the appropriate registry event in the same transaction (skip for API services)
		if oldAgent.AgentType.String() != "api" {
			eventType := getEventTypeForStatusChange(oldStatus, newStatus)
			eventData := createEventDataForStatusChange(oldStatus, newStatus)

			// Create the registry event in the same transaction
			_, err = m.Client().RegistryEvent.Create().
				SetEventType(eventType).
				SetAgentID(agentID).
				SetTimestamp(time.Now().UTC()).
				SetData(eventData).
				Save(ctx)

			if err != nil {
				config.Logger.Error("Failed to create registry event for agent %s status change (%s → %s): %v",
					agentID, oldStatus, newStatus, err)
				// Don't fail the mutation if event creation fails
				// This ensures the status update still happens even if audit fails
			} else {
				config.Logger.Info("Created %s event for agent %s status change (%s → %s)",
					eventType, agentID, oldStatus, newStatus)
			}
		}
	}

	// Return nil to continue with the normal mutation
	return nil, nil
}

// getEventTypeForStatusChange determines the appropriate event type for a status transition
func getEventTypeForStatusChange(oldStatus, newStatus agent.Status) registryevent.EventType {
	switch {
	case oldStatus != agent.StatusHealthy && newStatus == agent.StatusHealthy:
		// Agent is recovering to healthy state
		return registryevent.EventTypeRegister
	case oldStatus == agent.StatusHealthy && newStatus == agent.StatusUnhealthy:
		// Agent is becoming unhealthy
		return registryevent.EventTypeUnhealthy
	case oldStatus == agent.StatusHealthy && newStatus == agent.StatusUnknown:
		// Agent status is becoming unknown
		return registryevent.EventTypeUnhealthy
	case oldStatus == agent.StatusUnknown && newStatus == agent.StatusHealthy:
		// Agent is recovering from unknown state
		return registryevent.EventTypeRegister
	case oldStatus == agent.StatusUnknown && newStatus == agent.StatusUnhealthy:
		// Agent is transitioning from unknown to unhealthy
		return registryevent.EventTypeUnhealthy
	case oldStatus == agent.StatusUnhealthy && newStatus == agent.StatusUnknown:
		// Agent is transitioning from unhealthy to unknown
		return registryevent.EventTypeUpdate
	default:
		// Generic update for any other transitions
		return registryevent.EventTypeUpdate
	}
}

// createEventDataForStatusChange creates the event data payload for status changes
func createEventDataForStatusChange(oldStatus, newStatus agent.Status) map[string]interface{} {
	eventData := map[string]interface{}{
		"reason":           "status_change",
		"old_status":       oldStatus.String(),
		"new_status":       newStatus.String(),
		"detected_at":      time.Now().UTC().Format(time.RFC3339),
		"source":           "status_change_hook",
		"transition_type":  fmt.Sprintf("%s_to_%s", oldStatus.String(), newStatus.String()),
	}

	// Add specific reason based on transition type
	switch {
	case oldStatus != agent.StatusHealthy && newStatus == agent.StatusHealthy:
		eventData["reason"] = "recovery"
		eventData["description"] = "Agent recovered to healthy status"
	case oldStatus == agent.StatusHealthy && newStatus == agent.StatusUnhealthy:
		eventData["reason"] = "health_degradation"
		eventData["description"] = "Agent became unhealthy"
	case oldStatus == agent.StatusHealthy && newStatus == agent.StatusUnknown:
		eventData["reason"] = "status_unknown"
		eventData["description"] = "Agent status became unknown"
	default:
		eventData["reason"] = "status_transition"
		eventData["description"] = fmt.Sprintf("Agent status changed from %s to %s", oldStatus.String(), newStatus.String())
	}

	return eventData
}

// AgentStatusChangeHookManager manages the lifecycle of status change hooks
type AgentStatusChangeHookManager struct {
	config *StatusChangeHookConfig
	hooks  []entgo.Hook
}

// NewAgentStatusChangeHookManager creates a new hook manager
func NewAgentStatusChangeHookManager(logger *logger.Logger, enabled bool) *AgentStatusChangeHookManager {
	return &AgentStatusChangeHookManager{
		config: &StatusChangeHookConfig{
			Logger:  logger,
			Enabled: enabled,
		},
		hooks: make([]ent.Hook, 0),
	}
}

// GetHooks returns the list of hooks for registration with the Ent client
func (m *AgentStatusChangeHookManager) GetHooks() []entgo.Hook {
	if len(m.hooks) == 0 {
		m.hooks = append(m.hooks, CreateAgentStatusChangeHook(m.config))
	}
	return m.hooks
}

// Enable enables the status change hooks
func (m *AgentStatusChangeHookManager) Enable() {
	m.config.Enabled = true
	m.config.Logger.Info("Agent status change hooks enabled")
}

// Disable disables the status change hooks
func (m *AgentStatusChangeHookManager) Disable() {
	m.config.Enabled = false
	m.config.Logger.Info("Agent status change hooks disabled")
}

// IsEnabled returns whether the hooks are currently enabled
func (m *AgentStatusChangeHookManager) IsEnabled() bool {
	return m.config.Enabled
}
