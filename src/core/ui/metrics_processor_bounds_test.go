package ui

import (
	"fmt"
	"testing"
	"time"

	"mcp-mesh/src/core/registry/tracing"
)

// metricEvent builds a completed span event carrying both an agent name and a
// model name, so one call feeds both MetricsProcessor maps through the real
// ProcessTraceEvent entry point.
func metricEvent(agent, model string) *tracing.TraceEvent {
	dur := int64(7)
	in := int64(11)
	out := int64(13)
	reqB := int64(100)
	respB := int64(200)
	ev := &tracing.TraceEvent{
		TraceID:         "t-" + agent,
		SpanID:          "s-" + agent,
		AgentName:       agent,
		Operation:       "call",
		DurationMS:      &dur,
		RequestBytes:    &reqB,
		ResponseBytes:   &respB,
		LlmInputTokens:  &in,
		LlmOutputTokens: &out,
	}
	if model != "" {
		m := model
		ev.LlmModel = &m
	}
	return ev
}

// TestMetricsProcessorUnboundedWithoutBounds is the "before" half of #1424:
// with both bounds off (the pre-fix behaviour) every distinct agent and model
// name adds a permanent map entry.
func TestMetricsProcessorUnboundedWithoutBounds(t *testing.T) {
	mp := NewMetricsProcessorWithBounds(tracing.AggregateBounds{})

	const churn = 2000
	for i := 0; i < churn; i++ {
		_ = mp.ProcessTraceEvent(metricEvent(
			fmt.Sprintf("agent-pod-%04d", i),
			fmt.Sprintf("vendor/model-%04d", i),
		))
	}

	agents, models := mp.AggregateCounts()
	if agents != churn || models != churn {
		t.Fatalf("unbounded processor: agents=%d models=%d, want %d each (documents pre-fix growth)", agents, models, churn)
	}
}

// TestMetricsProcessorKeyCapBoundsGrowth is the "after" half: the same churn
// under a key ceiling never exceeds it, checked after EVERY event.
func TestMetricsProcessorKeyCapBoundsGrowth(t *testing.T) {
	const cap = 50
	mp := NewMetricsProcessorWithBounds(tracing.AggregateBounds{
		Retention:  24 * time.Hour,
		MaxEntries: cap,
	})

	const churn = 2000
	for i := 0; i < churn; i++ {
		_ = mp.ProcessTraceEvent(metricEvent(
			fmt.Sprintf("agent-pod-%04d", i),
			fmt.Sprintf("vendor/model-%04d", i),
		))
		agents, models := mp.AggregateCounts()
		if agents > cap {
			t.Fatalf("after event %d: agent keys = %d exceeds cap %d", i, agents, cap)
		}
		if models > cap {
			t.Fatalf("after event %d: model keys = %d exceeds cap %d", i, models, cap)
		}
	}

	agents, models := mp.AggregateCounts()
	if agents == 0 || models == 0 {
		t.Fatalf("maps emptied entirely: agents=%d models=%d", agents, models)
	}

	// The read paths must still work off the bounded maps.
	if got := len(mp.GetAgentMetrics()); got > cap {
		t.Fatalf("GetAgentMetrics returned %d rows, exceeds cap %d", got, cap)
	}
	if got := len(mp.GetModelMetrics()); got > cap {
		t.Fatalf("GetModelMetrics returned %d rows, exceeds cap %d", got, cap)
	}
}

// TestMetricsProcessorAgePrune proves the primary bound with an injected
// clock: an agent/model that stopped reporting ages out, while one that is
// still reporting survives. A dashboard dropping a live agent is the failure
// mode this asserts against.
func TestMetricsProcessorAgePrune(t *testing.T) {
	base := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	clock := base
	mp := NewMetricsProcessorWithBounds(tracing.AggregateBounds{
		Retention:  time.Hour,
		MaxEntries: 1000,
	})
	mp.now = func() time.Time { return clock }

	_ = mp.ProcessTraceEvent(metricEvent("retired-agent", "vendor/retired-model"))
	_ = mp.ProcessTraceEvent(metricEvent("live-agent", "vendor/live-model"))

	if agents, models := mp.AggregateCounts(); agents != 2 || models != 2 {
		t.Fatalf("agents=%d models=%d, want 2 each before pruning", agents, models)
	}

	// Two hours later only the live agent still reports. The write itself
	// triggers the (rate-limited) prune.
	clock = base.Add(2 * time.Hour)
	_ = mp.ProcessTraceEvent(metricEvent("live-agent", "vendor/live-model"))

	agents, models := mp.AggregateCounts()
	if agents != 1 || models != 1 {
		t.Fatalf("agents=%d models=%d after prune, want 1 each", agents, models)
	}
	for _, a := range mp.GetAgentMetrics() {
		if a.AgentName != "live-agent" {
			t.Errorf("unexpected surviving agent %q", a.AgentName)
		}
		if a.SpanCount != 2 {
			t.Errorf("live agent lost its counters: SpanCount=%d, want 2", a.SpanCount)
		}
	}
	for _, m := range mp.GetModelMetrics() {
		if m.Model != "vendor/live-model" {
			t.Errorf("unexpected surviving model %q", m.Model)
		}
	}
}

// TestMetricsProcessorAgePruneDisabled proves retention=0 really disables age
// pruning rather than quietly doing something else.
func TestMetricsProcessorAgePruneDisabled(t *testing.T) {
	base := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	clock := base
	mp := NewMetricsProcessorWithBounds(tracing.AggregateBounds{
		Retention:  0,
		MaxEntries: 1000,
	})
	mp.now = func() time.Time { return clock }

	_ = mp.ProcessTraceEvent(metricEvent("retired-agent", "vendor/retired-model"))

	clock = base.Add(10000 * time.Hour)
	_ = mp.ProcessTraceEvent(metricEvent("live-agent", "vendor/live-model"))

	if agents, models := mp.AggregateCounts(); agents != 2 || models != 2 {
		t.Fatalf("agents=%d models=%d, want 2 each (retention=0 must not prune)", agents, models)
	}
}

// TestMetricsProcessorPruneIsRateLimited guards the write path: the age prune
// is a full map scan, so it must not run on every event.
func TestMetricsProcessorPruneIsRateLimited(t *testing.T) {
	base := time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC)
	clock := base
	mp := NewMetricsProcessorWithBounds(tracing.AggregateBounds{
		Retention:  time.Minute,
		MaxEntries: 1000,
	})
	mp.now = func() time.Time { return clock }

	// First write primes nextPruneAt.
	_ = mp.ProcessTraceEvent(metricEvent("a", ""))

	// Move well past the retention window but stay inside the prune interval.
	clock = base.Add(tracing.AggregatePruneInterval - time.Millisecond)
	_ = mp.ProcessTraceEvent(metricEvent("b", ""))
	if agents, _ := mp.AggregateCounts(); agents != 2 {
		t.Fatalf("agents=%d, want 2: prune ran before the interval elapsed", agents)
	}

	// Cross the interval AND the retention window: "a" must now go.
	clock = base.Add(tracing.AggregatePruneInterval + time.Hour)
	_ = mp.ProcessTraceEvent(metricEvent("c", ""))
	if agents, _ := mp.AggregateCounts(); agents != 1 {
		t.Fatalf("agents=%d, want 1 after the interval elapsed", agents)
	}
}

// TestMetricsProcessorDefaultPathUnchanged is the no-regression guard: a
// normally sized mesh produces identical dashboard numbers under the shipped
// defaults and under no bounds at all.
func TestMetricsProcessorDefaultPathUnchanged(t *testing.T) {
	bounded := NewMetricsProcessor() // ships with DefaultAggregateBounds
	plain := NewMetricsProcessorWithBounds(tracing.AggregateBounds{})

	agents := []string{"frontend", "auth", "billing", "search"}
	models := []string{"anthropic/claude", "openai/gpt", "google/gemini"}
	for i := 0; i < 1000; i++ {
		ev := metricEvent(agents[i%len(agents)], models[i%len(models)])
		_ = bounded.ProcessTraceEvent(ev)
		_ = plain.ProcessTraceEvent(ev)
	}

	bAgents, bModels := bounded.GetAgentMetrics(), bounded.GetModelMetrics()
	pAgents, pModels := plain.GetAgentMetrics(), plain.GetModelMetrics()

	if len(bAgents) != len(pAgents) || len(bModels) != len(pModels) {
		t.Fatalf("shape differs under defaults: agents %d vs %d, models %d vs %d",
			len(bAgents), len(pAgents), len(bModels), len(pModels))
	}
	if len(bAgents) != len(agents) || len(bModels) != len(models) {
		t.Fatalf("unexpected cardinality: agents=%d models=%d", len(bAgents), len(bModels))
	}

	// Compare as keyed sets: GetAgentMetrics/GetModelMetrics sort by count with
	// an unstable sort, so equal-count rows have never had a deterministic
	// order. What must be identical is every row and every number.
	wantAgents := make(map[string]AgentMetricsData, len(pAgents))
	for _, a := range pAgents {
		wantAgents[a.AgentName] = a
	}
	for _, got := range bAgents {
		want, ok := wantAgents[got.AgentName]
		if !ok {
			t.Fatalf("agent %q missing under the shipped defaults", got.AgentName)
		}
		if got != want {
			t.Fatalf("agent %q differs under defaults:\n bounded=%+v\n   plain=%+v", got.AgentName, got, want)
		}
	}

	wantModels := make(map[string]ModelMetricsData, len(pModels))
	for _, m := range pModels {
		wantModels[m.Model] = m
	}
	for _, got := range bModels {
		want, ok := wantModels[got.Model]
		if !ok {
			t.Fatalf("model %q missing under the shipped defaults", got.Model)
		}
		if got != want {
			t.Fatalf("model %q differs under defaults:\n bounded=%+v\n   plain=%+v", got.Model, got, want)
		}
	}
}
