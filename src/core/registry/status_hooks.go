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
// and automatically creates registry events when the status field changes.
//
// The hook reads each agent's old status before the mutation runs (it cannot
// be recovered afterwards), runs the mutation, and only then writes events,
// and only for rows the mutation actually changed. A conditional update that
// loses a race (e.g. the health monitor's markAgentUnhealthyIfUnchanged
// against a concurrent heartbeat) affects 0 rows and so records nothing.
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

			if statusChangeEventsSuppressed(ctx) {
				return next.Mutate(ctx, m)
			}

			pending, matched := prepareStatusChangeEvents(ctx, agentMutation, config)

			value, err := next.Mutate(ctx, m)
			if err != nil || len(pending) == 0 {
				return value, err
			}

			// Event-write failures are logged inside and never fail the
			// mutation, which has already been applied at this point.
			writeStatusChangeEvents(ctx, agentMutation, value, pending, matched, config)
			return value, nil
		})
	}
}

type suppressStatusChangeEventsKey struct{}

// withoutStatusChangeEvents marks ctx so the status change hook writes no
// event for mutations run with it. For callers that record their own, richer
// event for the same transition in the same transaction (startup cleanup's
// stale_on_startup event), so the transition is recorded exactly once.
func withoutStatusChangeEvents(ctx context.Context) context.Context {
	return context.WithValue(ctx, suppressStatusChangeEventsKey{}, true)
}

func statusChangeEventsSuppressed(ctx context.Context) bool {
	suppressed, _ := ctx.Value(suppressStatusChangeEventsKey{}).(bool)
	return suppressed
}

// pendingStatusEvent is an event computed from the pre-mutation state, to be
// written only if the mutation actually changes the agent's row.
type pendingStatusEvent struct {
	agentID   string
	oldStatus agent.Status
	newStatus agent.Status
	eventType registryevent.EventType
}

// prepareStatusChangeEvents reads the current (pre-mutation) state of every
// agent the mutation targets and returns the events the status change would
// produce, plus the number of agents the mutation matched at this point.
// Nothing is written here.
func prepareStatusChangeEvents(ctx context.Context, m *ent.AgentMutation, config *StatusChangeHookConfig) ([]pendingStatusEvent, int) {
	if !config.Enabled {
		return nil, 0
	}

	// Get the new status value
	newStatus, exists := m.Status()
	if !exists {
		// Status field isn't being updated, shouldn't happen due to condition but safety check
		return nil, 0
	}

	// Get the agent IDs (handles both single and bulk operations)
	agentIDs, err := m.IDs(ctx)
	if err != nil {
		config.Logger.Error("Failed to get agent IDs for status change hook: %v", err)
		return nil, 0
	}

	if len(agentIDs) == 0 {
		config.Logger.Debug("Agent status change hook: mutation matches no agents, no events to create")
		return nil, 0
	}

	var pending []pendingStatusEvent
	for _, agentID := range agentIDs {
		// Read the old status. This runs before the mutation is applied, so
		// it is the current state.
		oldAgent, err := m.Client().Agent.Get(ctx, agentID)
		if err != nil {
			if ent.IsNotFound(err) {
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

		// Skip API services.
		// Note: a2a-typed agents still generate lifecycle events because they can hold
		// mesh capabilities alongside their A2A surfaces (see A2A_SURFACE_DESIGN.org —
		// "agent_type=a2a" is additive over mesh-tool handling).
		if oldAgent.AgentType.String() == "api" {
			continue
		}

		pending = append(pending, pendingStatusEvent{
			agentID:   agentID,
			oldStatus: oldStatus,
			newStatus: newStatus,
			eventType: getEventTypeForStatusChange(oldStatus, newStatus),
		})
	}

	return pending, len(agentIDs)
}

// writeStatusChangeEvents writes the pending events for the agents whose rows
// the mutation actually changed. value is the mutation's result: the updated
// entity for UpdateOne, the affected row count for Update. matched is the
// number of agents the mutation matched before it ran; it, not len(pending),
// is what the affected count is comparable to, because pending leaves out
// agents that produce no event (api agents, agents already at the target
// status, unregister-suppressed agents) while the update still counts them.
//
// The event timestamp is taken after the update has been applied. A consumer
// whose full refresh lands before that point saw the agent's old status and
// recorded a LastFullRefresh earlier than the event, so HasTopologyChanges
// (TimestampGT(LastFullRefresh)) still reports the change to it. A heartbeat
// that reverses the change can only observe the new status after this
// update, so its own event still sorts later.
//
// When the mutation runs in a transaction, m.Client() is tx-bound and the
// events commit or roll back with the status change. Otherwise each event is
// its own write, made after the status update has already committed.
func writeStatusChangeEvents(ctx context.Context, m *ent.AgentMutation, value entgo.Value, pending []pendingStatusEvent, matched int, config *StatusChangeHookConfig) {
	now := time.Now().UTC()

	applied := pending
	if m.Op() == ent.OpUpdate {
		affected, ok := value.(int)
		if !ok {
			config.Logger.Warning("Agent status change hook: unexpected bulk update result %T, skipping event creation", value)
			return
		}
		if affected == 0 {
			// The update's predicates no longer matched (e.g. a conditional
			// update lost a race). Nothing changed, so nothing to record.
			config.Logger.Debug("Agent status change hook: update affected 0 rows, skipping event creation")
			return
		}
		if affected != matched {
			applied = confirmAppliedStatusChanges(ctx, m, pending, config)
		}
	}

	for _, ev := range applied {
		config.Logger.Info("Agent %s status changed: %s → %s", ev.agentID, ev.oldStatus, ev.newStatus)

		_, err := m.Client().RegistryEvent.Create().
			SetEventType(ev.eventType).
			SetAgentID(ev.agentID).
			SetTimestamp(now).
			SetData(createEventDataForStatusChange(ev.oldStatus, ev.newStatus, now)).
			Save(ctx)
		if err != nil {
			config.Logger.Error("Failed to create registry event for agent %s status change (%s → %s): %v",
				ev.agentID, ev.oldStatus, ev.newStatus, err)
			// Don't fail the mutation if event creation fails
			// This ensures the status update still happens even if audit fails
		} else {
			config.Logger.Info("Created %s event for agent %s status change (%s → %s)",
				ev.eventType, ev.agentID, ev.oldStatus, ev.newStatus)
		}
	}
}

// confirmAppliedStatusChanges handles a bulk update whose affected count
// differs from the number of agents it matched before running, so the count
// alone cannot say which rows changed. It keeps the agents whose stored status now equals
// the new status. Every status update in the registry targets a single agent
// ID, so this path only serves ad-hoc bulk updates.
func confirmAppliedStatusChanges(ctx context.Context, m *ent.AgentMutation, pending []pendingStatusEvent, config *StatusChangeHookConfig) []pendingStatusEvent {
	var applied []pendingStatusEvent
	for _, ev := range pending {
		current, err := m.Client().Agent.Get(ctx, ev.agentID)
		if err != nil {
			config.Logger.Warning("Failed to re-read agent %s after bulk status update, skipping event creation: %v", ev.agentID, err)
			continue
		}
		if current.Status == ev.newStatus {
			applied = append(applied, ev)
		}
	}
	return applied
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
func createEventDataForStatusChange(oldStatus, newStatus agent.Status, detectedAt time.Time) map[string]interface{} {
	eventData := map[string]interface{}{
		"reason":           "status_change",
		"old_status":       oldStatus.String(),
		"new_status":       newStatus.String(),
		"detected_at":      detectedAt.Format(time.RFC3339),
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
