package registry

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEventHub_SubscribeAndPublish(t *testing.T) {
	hub := NewEventHub()

	ch := hub.Subscribe()
	defer hub.Unsubscribe(ch)

	event := DashboardEvent{
		Type:      "agent_registered",
		AgentID:   "test-agent-1",
		AgentName: "test-agent",
		Timestamp: time.Now().UTC(),
	}

	hub.Publish(event)

	select {
	case received := <-ch:
		assert.Equal(t, "agent_registered", received.Type)
		assert.Equal(t, "test-agent-1", received.AgentID)
		assert.Equal(t, "test-agent", received.AgentName)
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event")
	}
}

func TestEventHub_MultipleSubscribers(t *testing.T) {
	hub := NewEventHub()

	ch1 := hub.Subscribe()
	ch2 := hub.Subscribe()
	defer hub.Unsubscribe(ch1)
	defer hub.Unsubscribe(ch2)

	event := DashboardEvent{
		Type:    "agent_healthy",
		AgentID: "agent-abc",
	}

	hub.Publish(event)

	for _, ch := range []chan DashboardEvent{ch1, ch2} {
		select {
		case received := <-ch:
			assert.Equal(t, "agent_healthy", received.Type)
		case <-time.After(time.Second):
			t.Fatal("timed out waiting for event")
		}
	}
}

func TestEventHub_SlowClientDoesNotBlock(t *testing.T) {
	hub := NewEventHub()

	ch := hub.Subscribe()
	defer hub.Unsubscribe(ch)

	// Fill the channel buffer (capacity is 64)
	for i := 0; i < 64; i++ {
		hub.Publish(DashboardEvent{Type: "fill", AgentID: "x"})
	}

	// This publish should not block even though the channel is full
	done := make(chan struct{})
	go func() {
		hub.Publish(DashboardEvent{Type: "overflow", AgentID: "y"})
		close(done)
	}()

	select {
	case <-done:
		// Publish returned without blocking
	case <-time.After(time.Second):
		t.Fatal("Publish blocked on a full subscriber channel")
	}
}

func TestEventHub_Unsubscribe(t *testing.T) {
	hub := NewEventHub()

	ch := hub.Subscribe()
	assert.Equal(t, 1, hub.SubscriberCount())

	hub.Unsubscribe(ch)
	assert.Equal(t, 0, hub.SubscriberCount())

	// Double-unsubscribe should not panic
	hub.Unsubscribe(ch)
}

func TestEventHub_SubscriberCount(t *testing.T) {
	hub := NewEventHub()
	require.Equal(t, 0, hub.SubscriberCount())

	ch1 := hub.Subscribe()
	require.Equal(t, 1, hub.SubscriberCount())

	ch2 := hub.Subscribe()
	require.Equal(t, 2, hub.SubscriberCount())

	hub.Unsubscribe(ch1)
	require.Equal(t, 1, hub.SubscriberCount())

	hub.Unsubscribe(ch2)
	require.Equal(t, 0, hub.SubscriberCount())
}

func TestEventHub_PublishAfterUnsubscribe(t *testing.T) {
	hub := NewEventHub()

	ch1 := hub.Subscribe()
	ch2 := hub.Subscribe()
	hub.Unsubscribe(ch1)

	event := DashboardEvent{Type: "test", AgentID: "a"}
	hub.Publish(event)

	select {
	case received := <-ch2:
		assert.Equal(t, "test", received.Type)
	case <-time.After(time.Second):
		t.Fatal("remaining subscriber did not receive event")
	}

	hub.Unsubscribe(ch2)
}
