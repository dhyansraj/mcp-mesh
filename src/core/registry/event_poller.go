package registry

import (
	"context"
	"sync"
	"time"

	"mcp-mesh/src/core/logger"
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
	service  *EntService
	hub      *EventHub
	logger   *logger.Logger
	interval time.Duration
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	mu       sync.RWMutex
	running  bool
}

// NewEventPoller creates a new poller that diffs agent state and publishes events
func NewEventPoller(service *EntService, hub *EventHub, logger *logger.Logger, interval time.Duration) *EventPoller {
	return &EventPoller{
		service:  service,
		hub:      hub,
		logger:   logger,
		interval: interval,
	}
}

// Start begins the background polling goroutine
func (p *EventPoller) Start() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		p.logger.Warning("Event poller is already running")
		return
	}

	p.running = true
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	p.wg.Add(1)

	go func() {
		defer p.wg.Done()
		p.logger.Info("Starting dashboard event poller (interval: %v)", p.interval)

		lastSnap := make(map[string]agentSnapshot)

		ticker := time.NewTicker(p.interval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				p.poll(lastSnap)
			case <-ctx.Done():
				p.logger.Info("Dashboard event poller stopped")
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
	p.logger.Info("Dashboard event poller stopped successfully")
}

func (p *EventPoller) poll(lastSnap map[string]agentSnapshot) {
	// Skip polling when no dashboard clients are connected
	if p.hub.SubscriberCount() == 0 {
		return
	}

	resp, err := p.service.ListAgents(nil)
	if err != nil {
		p.logger.Warning("Event poller: failed to list agents: %v", err)
		return
	}

	events := diffAgents(lastSnap, resp.Agents)
	for _, ev := range events {
		p.hub.Publish(ev)
	}
}

// diffAgents compares current agents against the last snapshot, emits events,
// and updates lastSnap in place. Exported for testing.
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
