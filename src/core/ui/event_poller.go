package ui

import (
	"context"
	"log"
	"sync"
	"time"

	"mcp-mesh/src/core/registry"
	"mcp-mesh/src/core/registry/generated"
)

// agentSnapshot tracks the last-known state of an agent for diff detection
type agentSnapshot struct {
	Name                 string
	Status               string
	Runtime              string
	DependenciesResolved int
	TotalDependencies    int
}

// EventPoller polls the agent list periodically and publishes lifecycle events
type EventPoller struct {
	service  *registry.EntService
	hub      *EventHub
	interval time.Duration
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	mu       sync.RWMutex
	running  bool
}

// NewEventPoller creates a new poller that diffs agent state and publishes events
func NewEventPoller(service *registry.EntService, hub *EventHub, interval time.Duration) *EventPoller {
	return &EventPoller{
		service:  service,
		hub:      hub,
		interval: interval,
	}
}

// Start begins the background polling goroutine
func (p *EventPoller) Start() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		log.Printf("ui: event poller is already running")
		return
	}

	p.running = true
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	p.wg.Add(1)

	go func() {
		defer p.wg.Done()
		log.Printf("ui: starting dashboard event poller (interval: %v)", p.interval)

		lastSnap := make(map[string]agentSnapshot)

		ticker := time.NewTicker(p.interval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				p.poll(lastSnap)
			case <-ctx.Done():
				log.Printf("ui: dashboard event poller stopped")
				return
			}
		}
	}()
}

// Stop gracefully stops the event poller
func (p *EventPoller) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.running {
		return
	}

	p.running = false
	if p.cancel != nil {
		p.cancel()
	}
	p.wg.Wait()
	log.Printf("ui: dashboard event poller stopped successfully")
}

func (p *EventPoller) poll(lastSnap map[string]agentSnapshot) {
	// Skip polling when no dashboard clients are connected
	if p.hub.SubscriberCount() == 0 {
		return
	}

	resp, err := p.service.ListAgents(nil)
	if err != nil {
		log.Printf("ui: event poller: failed to list agents: %v", err)
		return
	}

	events := diffAgents(lastSnap, resp.Agents)
	for _, ev := range events {
		// Issue #982 Part B: the snapshot diff doesn't carry the
		// human-readable transition reason, so live "agent_unhealthy"
		// events used to ship without `data.reason` while the
		// history-backfill path (which reads the persisted registry
		// event) had it. Look up the latest matching registry event
		// for the agent and copy its `reason` across so the live
		// stream matches what F5/backfill renders.
		enrichEventReason(p.service, &ev)
		p.hub.Publish(ev)
	}
}

// enrichEventReason fills in ev.Data["reason"] from the most recent matching
// registry event when the snapshot diff produced a status-transition event
// that should carry a reason (agent_unhealthy / agent_deregistered). Failures
// to look up are non-fatal — the event still ships, just without a reason
// (matching the prior behaviour).
//
// The status-change hook (status_hooks.go) and the explicit unregister /
// stale-on-startup paths in ent_service.go all write the registry event in
// the same DB transaction as the status flip, so by the time the next poller
// tick observes the diff the row is already committed and queryable.
func enrichEventReason(svc *registry.EntService, ev *DashboardEvent) {
	if ev == nil {
		return
	}
	var registryEventType string
	switch ev.Type {
	case "agent_unhealthy":
		registryEventType = "unhealthy"
	case "agent_deregistered":
		registryEventType = "unregister"
	default:
		return
	}
	if ev.AgentID == "" {
		return
	}
	if ev.Data != nil {
		if _, alreadySet := ev.Data["reason"]; alreadySet {
			return
		}
	}

	rows, err := svc.ListRecentEventsFiltered(1, registryEventType, ev.AgentID, "")
	if err != nil || len(rows) == 0 {
		return
	}
	reason, ok := rows[0].Data["reason"].(string)
	if !ok || reason == "" {
		return
	}
	if ev.Data == nil {
		ev.Data = map[string]interface{}{}
	}
	ev.Data["reason"] = reason
}

// diffAgents compares current agents against the last snapshot, emits events,
// and updates lastSnap in place.
func diffAgents(lastSnap map[string]agentSnapshot, agents []generated.AgentInfo) []DashboardEvent {
	var events []DashboardEvent
	now := time.Now().UTC()

	currentIDs := make(map[string]struct{}, len(agents))

	for _, a := range agents {
		currentIDs[a.Id] = struct{}{}

		runtime := ""
		if a.Runtime != nil {
			runtime = string(*a.Runtime)
		}

		snap := agentSnapshot{
			Name:                 a.Name,
			Status:               string(a.Status),
			Runtime:              runtime,
			DependenciesResolved: a.DependenciesResolved,
			TotalDependencies:    a.TotalDependencies,
		}

		prev, existed := lastSnap[a.Id]
		if !existed {
			events = append(events, DashboardEvent{
				Type:      "agent_registered",
				AgentID:   a.Id,
				AgentName: a.Name,
				Runtime:   runtime,
				Status:    string(a.Status),
				Data: map[string]interface{}{
					"total_dependencies":    a.TotalDependencies,
					"dependencies_resolved": a.DependenciesResolved,
				},
				Timestamp: now,
			})
		} else {
			if prev.Status != snap.Status {
				eventType := "agent_unhealthy"
				if snap.Status == "healthy" {
					eventType = "agent_healthy"
				}
				events = append(events, DashboardEvent{
					Type:      eventType,
					AgentID:   a.Id,
					AgentName: a.Name,
					Runtime:   runtime,
					Status:    snap.Status,
					Data: map[string]interface{}{
						"previous_status": prev.Status,
					},
					Timestamp: now,
				})
			}

			if prev.DependenciesResolved != snap.DependenciesResolved || prev.TotalDependencies != snap.TotalDependencies {
				eventType := "dependency_resolved"
				if snap.DependenciesResolved < prev.DependenciesResolved {
					eventType = "dependency_lost"
				}
				events = append(events, DashboardEvent{
					Type:      eventType,
					AgentID:   a.Id,
					AgentName: a.Name,
					Runtime:   runtime,
					Data: map[string]interface{}{
						"previous_resolved": prev.DependenciesResolved,
						"current_resolved":  snap.DependenciesResolved,
						"previous_total":    prev.TotalDependencies,
						"current_total":     snap.TotalDependencies,
					},
					Timestamp: now,
				})
			}
		}

		lastSnap[a.Id] = snap
	}

	// Detect deregistered agents
	for id, prev := range lastSnap {
		if _, exists := currentIDs[id]; !exists {
			events = append(events, DashboardEvent{
				Type:      "agent_deregistered",
				AgentID:   id,
				AgentName: prev.Name,
				Runtime:   prev.Runtime,
				Timestamp: now,
			})
			delete(lastSnap, id)
		}
	}

	return events
}
