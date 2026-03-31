package ui

import (
	"sync"
	"time"
)

// DashboardEvent represents an event for the dashboard SSE stream
type DashboardEvent struct {
	Type      string                 `json:"type"`
	AgentID   string                 `json:"agent_id"`
	AgentName string                 `json:"agent_name,omitempty"`
	Runtime   string                 `json:"runtime,omitempty"`
	Status    string                 `json:"status,omitempty"`
	Data      map[string]interface{} `json:"data,omitempty"`
	Timestamp time.Time              `json:"timestamp"`
}

// EventHub is an in-memory pub/sub hub for dashboard SSE clients
type EventHub struct {
	mu          sync.RWMutex
	subscribers map[chan DashboardEvent]struct{}
}

func NewEventHub() *EventHub {
	return &EventHub{
		subscribers: make(map[chan DashboardEvent]struct{}),
	}
}

// Subscribe creates a new subscriber channel
func (h *EventHub) Subscribe() chan DashboardEvent {
	h.mu.Lock()
	defer h.mu.Unlock()
	ch := make(chan DashboardEvent, 64)
	h.subscribers[ch] = struct{}{}
	return ch
}

// Unsubscribe removes a subscriber and closes its channel
func (h *EventHub) Unsubscribe(ch chan DashboardEvent) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.subscribers[ch]; ok {
		delete(h.subscribers, ch)
		close(ch)
	}
}

// Publish sends an event to all subscribers (non-blocking)
func (h *EventHub) Publish(event DashboardEvent) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for ch := range h.subscribers {
		select {
		case ch <- event:
		default:
			// Skip slow clients to prevent blocking
		}
	}
}

// SubscriberCount returns the number of active subscribers
func (h *EventHub) SubscriberCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.subscribers)
}
