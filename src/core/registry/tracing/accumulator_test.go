package tracing

import (
	"fmt"
	"io"
	"log"
	"testing"
	"time"
)

// newTestAccumulator returns an accumulator with a quiet logger and the given
// ring size. Background goroutines are NOT started — tests drive finalization
// directly to keep them deterministic and fast.
func newTestAccumulator(t *testing.T, ringSize int) *TraceAccumulator {
	t.Helper()
	logger := log.New(io.Discard, "", 0)
	return NewTraceAccumulator(ringSize, logger)
}

// makeStartEvent builds a span_start event for the given trace/span/agent.
// Pass parent="" for a root span.
func makeStartEvent(traceID, spanID, parent, agent string) *TraceEvent {
	var parentPtr *string
	if parent != "" {
		p := parent
		parentPtr = &p
	}
	return &TraceEvent{
		TraceID:    traceID,
		SpanID:     spanID,
		ParentSpan: parentPtr,
		AgentName:  agent,
		Operation:  "test_op",
		EventType:  "span_start",
		Timestamp:  float64(time.Now().UnixNano()) / 1e9,
		Runtime:    "go",
	}
}

// makeEndEvent builds a span_end event. For root span, pass parent="".
func makeEndEvent(traceID, spanID, parent, agent string, durationMs int64, success bool) *TraceEvent {
	var parentPtr *string
	if parent != "" {
		p := parent
		parentPtr = &p
	}
	d := durationMs
	s := success
	return &TraceEvent{
		TraceID:    traceID,
		SpanID:     spanID,
		ParentSpan: parentPtr,
		AgentName:  agent,
		Operation:  "test_op",
		EventType:  "span_end",
		Timestamp:  float64(time.Now().UnixNano()) / 1e9,
		DurationMS: &d,
		Success:    &s,
		Runtime:    "go",
	}
}

// finalizeNow forces any active traces with a seen root span to finalize
// immediately, regardless of the grace period. It mutates RootSeen to be far
// enough in the past then calls the package's finalizeReadyTraces helper.
func finalizeNow(ta *TraceAccumulator) {
	ta.mu.Lock()
	past := time.Now().Add(-2 * traceGracePeriod)
	for _, at := range ta.activeTraces {
		if at.RootSeen != nil {
			at.RootSeen = &past
		}
	}
	ta.mu.Unlock()
	ta.finalizeReadyTraces()
}

// pushTrace simulates a single-span trace from a single agent that finalizes
// immediately.
func pushTrace(ta *TraceAccumulator, traceID, agent string) {
	_ = ta.ProcessTraceEvent(makeStartEvent(traceID, traceID+"-s", "", agent))
	_ = ta.ProcessTraceEvent(makeEndEvent(traceID, traceID+"-s", "", agent, 5, true))
	finalizeNow(ta)
}

// pushTraceMulti simulates a trace with one root span on rootAgent and one
// child span on childAgent — both agents end up in the trace's Agents list.
func pushTraceMulti(ta *TraceAccumulator, traceID, rootAgent, childAgent string) {
	rootID := traceID + "-r"
	childID := traceID + "-c"
	_ = ta.ProcessTraceEvent(makeStartEvent(traceID, rootID, "", rootAgent))
	_ = ta.ProcessTraceEvent(makeStartEvent(traceID, childID, rootID, childAgent))
	_ = ta.ProcessTraceEvent(makeEndEvent(traceID, childID, rootID, childAgent, 2, true))
	_ = ta.ProcessTraceEvent(makeEndEvent(traceID, rootID, "", rootAgent, 5, true))
	finalizeNow(ta)
}

// TestAgentActivity_NoIncrementOnSpanEvent verifies that span events alone do
// not bump the activity counter — only finalized traces in the ring buffer do.
func TestAgentActivity_NoIncrementOnSpanEvent(t *testing.T) {
	ta := newTestAccumulator(t, 20)

	// Send several span_start events without any root_end → no finalization.
	_ = ta.ProcessTraceEvent(makeStartEvent("t1", "s1", "", "agent-a"))
	_ = ta.ProcessTraceEvent(makeStartEvent("t1", "s2", "s1", "agent-b"))
	_ = ta.ProcessTraceEvent(makeStartEvent("t2", "s3", "", "agent-a"))

	got := ta.GetAgentActivity()
	if len(got) != 0 {
		t.Fatalf("expected empty activity before finalization, got %v", got)
	}
}

// TestAgentActivity_IncrementsOnFinalize verifies that once a trace is
// finalized into the ring buffer, every agent in it gains +1 in the count.
func TestAgentActivity_IncrementsOnFinalize(t *testing.T) {
	ta := newTestAccumulator(t, 20)

	pushTraceMulti(ta, "t1", "agent-a", "agent-b")

	got := ta.GetAgentActivity()
	if got["agent-a"] != 1 {
		t.Errorf("agent-a: expected 1, got %d (full map: %v)", got["agent-a"], got)
	}
	if got["agent-b"] != 1 {
		t.Errorf("agent-b: expected 1, got %d (full map: %v)", got["agent-b"], got)
	}
	if len(got) != 2 {
		t.Errorf("expected 2 agents, got %d (%v)", len(got), got)
	}
}

// TestAgentActivity_MatchesRecentTraces verifies that for each agent, the
// activity count exactly equals the number of recent traces containing that
// agent — the property that makes the badge match the detail tab by
// construction.
func TestAgentActivity_MatchesRecentTraces(t *testing.T) {
	ta := newTestAccumulator(t, 20)

	pushTrace(ta, "t1", "agent-a")
	pushTraceMulti(ta, "t2", "agent-a", "agent-b")
	pushTrace(ta, "t3", "agent-c")
	pushTraceMulti(ta, "t4", "agent-b", "agent-a")

	activity := ta.GetAgentActivity()
	recent := ta.GetRecentTraces(0)

	// Recompute expected counts from /trace/recent equivalent.
	expected := make(map[string]int)
	for _, s := range recent {
		for _, a := range s.Agents {
			expected[a]++
		}
	}

	for agent, want := range expected {
		if got := activity[agent]; got != want {
			t.Errorf("agent %s: activity=%d, expected (from recent)=%d", agent, got, want)
		}
	}
	for agent := range activity {
		if _, ok := expected[agent]; !ok {
			t.Errorf("agent %s present in activity but not in recent", agent)
		}
	}
}

// TestAgentActivity_DecrementsOnRingEviction verifies that when the ring
// buffer rolls over and an old trace is evicted, agents that only appeared in
// the evicted trace lose their count, and agents that still appear in newer
// traces retain a count equal to the number of remaining traces they're in.
func TestAgentActivity_DecrementsOnRingEviction(t *testing.T) {
	const ringSize = 3
	ta := newTestAccumulator(t, ringSize)

	// Fill the ring with traces: t1=agent-x, t2=agent-y, t3=agent-y
	pushTrace(ta, "t1", "agent-x")
	pushTrace(ta, "t2", "agent-y")
	pushTrace(ta, "t3", "agent-y")

	got := ta.GetAgentActivity()
	if got["agent-x"] != 1 {
		t.Fatalf("setup: agent-x expected 1, got %d", got["agent-x"])
	}
	if got["agent-y"] != 2 {
		t.Fatalf("setup: agent-y expected 2, got %d", got["agent-y"])
	}

	// Push a 4th trace from agent-y → evicts t1 (the only agent-x trace).
	pushTrace(ta, "t4", "agent-y")

	got = ta.GetAgentActivity()
	if _, ok := got["agent-x"]; ok {
		t.Errorf("agent-x should have been evicted, but still in map: %v", got)
	}
	if got["agent-y"] != 3 {
		t.Errorf("agent-y expected 3 after eviction, got %d", got["agent-y"])
	}
}

// TestAgentActivity_BadgeNeverExceedsRingSize verifies the headline invariant:
// an agent's activity count cannot exceed the ring buffer size, no matter how
// many traces are processed.
func TestAgentActivity_BadgeNeverExceedsRingSize(t *testing.T) {
	const ringSize = 5
	ta := newTestAccumulator(t, ringSize)

	for i := 0; i < 50; i++ {
		pushTrace(ta, fmt.Sprintf("trace-%d", i), "spammy-agent")
	}

	got := ta.GetAgentActivity()
	if got["spammy-agent"] > ringSize {
		t.Errorf("agent count %d exceeded ring size %d", got["spammy-agent"], ringSize)
	}
	if got["spammy-agent"] != ringSize {
		t.Errorf("expected exactly %d (ring full of this agent), got %d", ringSize, got["spammy-agent"])
	}

	// And it must equal the number of recent traces containing that agent.
	recent := ta.GetRecentTraces(0)
	count := 0
	for _, s := range recent {
		for _, a := range s.Agents {
			if a == "spammy-agent" {
				count++
				break
			}
		}
	}
	if got["spammy-agent"] != count {
		t.Errorf("activity count %d != recent-trace count %d", got["spammy-agent"], count)
	}
}

// TestAgentActivity_EmptyOnFreshAccumulator verifies the initial state.
func TestAgentActivity_EmptyOnFreshAccumulator(t *testing.T) {
	ta := newTestAccumulator(t, 20)
	got := ta.GetAgentActivity()
	if len(got) != 0 {
		t.Errorf("fresh accumulator should have empty activity, got %v", got)
	}
}
