package tracing

import (
	"runtime"
	"testing"
	"time"
)

// newRegistryManagerForTest builds the manager the REGISTRY builds, in the mode
// the charts ship (TRACE_EXPORTER_TYPE=otlp). The Redis URL is never dialled:
// NewStreamConsumer connects lazily and nothing here calls Start.
func newRegistryManagerForTest(t *testing.T, exporter string) *TracingManager {
	t.Helper()

	tm, err := NewTracingManager(&TracingConfig{
		Enabled:           true,
		RedisURL:          "redis://127.0.0.1:1",
		StreamName:        "mesh:trace",
		ConsumerGroup:     DefaultTraceConsumerGroup,
		ConsumerName:      "registry-test",
		BatchSize:         100,
		BlockTimeout:      time.Second,
		TraceTimeout:      time.Minute,
		TraceRetention:    0, // no trim loop; nothing is Start()ed here
		ExporterType:      exporter,
		TelemetryEndpoint: "localhost:4317",
		TelemetryProtocol: "grpc",
	})
	if err != nil {
		t.Fatalf("NewTracingManager(%s): %v", exporter, err)
	}
	t.Cleanup(func() {
		if tm.consumer != nil {
			tm.consumer.cancel()
		}
	})
	return tm
}

// newUIManagerForTest builds the manager MESHUI builds, exactly as
// cmd/mcp-mesh-ui does: NewAccumulatorOnlyManager with an extra processor.
func newUIManagerForTest(t *testing.T) *TracingManager {
	t.Helper()

	tm, err := NewAccumulatorOnlyManager(&TracingConfig{
		Enabled:        true,
		RedisURL:       "redis://127.0.0.1:1",
		StreamName:     "mesh:trace",
		ConsumerGroup:  "mcp-mesh-ui-dashboard",
		ConsumerName:   "ui-test",
		BatchSize:      100,
		BlockTimeout:   time.Second,
		TraceRetention: 0,
	}, noopProcessor{})
	if err != nil {
		t.Fatalf("NewAccumulatorOnlyManager: %v", err)
	}
	t.Cleanup(func() {
		if tm.consumer != nil {
			tm.consumer.cancel()
		}
	})
	return tm
}

// TestRegistryManagerBuildsNoAccumulator is the guard for #1540. The registry
// built a TraceAccumulator that nothing on the registry side ever read: every
// method that consults it is called only from src/core/ui, and meshui builds
// its own manager. It cost two goroutines, ~90 ns and ~25 B of accumulator work
// on every span event, and up to ~21 MB of edge aggregates per replica.
//
// It was also a trap: fed from a Redis consumer group, each of N replicas would
// hold roughly 1/N of the mesh's traffic, so any registry route later wired to
// GetEdgeStats or GetRecentTraces would have under-reported by about the
// replica count with no error and no warning.
//
// The assertion is paired ON PURPOSE. TracingManager is the same struct for
// both processes, so "accumulator is nil" alone would be a false invariant —
// meshui's accumulator is the point of that process. What must hold is the
// DIFFERENCE: the registry constructor leaves it nil, the meshui constructor
// does not.
func TestRegistryManagerBuildsNoAccumulator(t *testing.T) {
	registry := newRegistryManagerForTest(t, "otlp")
	if registry.GetAccumulator() != nil {
		t.Error("the registry's stream-through manager built a TraceAccumulator; " +
			"nothing on the registry side reads one, and at N replicas it would hold ~1/N of the traffic (#1540)")
	}

	ui := newUIManagerForTest(t)
	if ui.GetAccumulator() == nil {
		t.Error("meshui's accumulator-only manager has no TraceAccumulator; " +
			"the dashboard reads that accumulator and #1540 must not have touched this path")
	}
}

// TestRegistryProcessorDoesNotFanOutToAccumulator closes the gap the field
// check alone leaves. Setting tm.accumulator and adding the accumulator to the
// processor fan-out are two separate lines, so an accumulator could be
// reattached to the pipeline — paying the per-event cost and holding the
// memory — while GetAccumulator still returned nil. The registry's processor
// must therefore BE the stream-through exporter, not a fan-out containing one.
func TestRegistryProcessorDoesNotFanOutToAccumulator(t *testing.T) {
	registry := newRegistryManagerForTest(t, "otlp")

	switch p := registry.processor.(type) {
	case *StreamThroughProcessor:
		// Export and nothing else, which is the whole point.
	case *MultiProcessor:
		for _, sub := range p.processors {
			if _, isAcc := sub.(*TraceAccumulator); isAcc {
				t.Fatal("the registry's processor fans out to a TraceAccumulator (#1540)")
			}
		}
		t.Errorf("the registry's processor is a %T; stream-through mode exports and does nothing else", p)
	default:
		t.Errorf("the registry's processor is a %T, want *StreamThroughProcessor", p)
	}
}

// TestRegistryManagerReadsReturnEmptyWithoutAccumulator pins the API shape the
// nil field leaves behind. These methods are not called from the registry
// today; if one ever is, it must return empty rather than panic.
func TestRegistryManagerReadsReturnEmptyWithoutAccumulator(t *testing.T) {
	tm := newRegistryManagerForTest(t, "otlp")

	if got := tm.ListTraces(10, 0); len(got) != 0 {
		t.Errorf("ListTraces = %d traces, want 0", len(got))
	}
	if got := tm.SearchTraces(TraceSearchCriteria{Limit: 10}); len(got) != 0 {
		t.Errorf("SearchTraces = %d traces, want 0", len(got))
	}
	if got := tm.GetTraceCount(); got != 0 {
		t.Errorf("GetTraceCount = %d, want 0", got)
	}
	if got := tm.GetTotalFinalized(); got != 0 {
		t.Errorf("GetTotalFinalized = %d, want 0", got)
	}
	if got := tm.GetTotalErrors(); got != 0 {
		t.Errorf("GetTotalErrors = %d, want 0", got)
	}
	if got := tm.GetAgentActivity(); len(got) != 0 {
		t.Errorf("GetAgentActivity = %v, want empty", got)
	}

	// GetRecentTraces and GetEdgeStats fall through to Tempo when the
	// accumulator is nil. With no Tempo client configured they must return
	// empty and not dial anything.
	if tm.tempoClient != nil {
		t.Fatal("test fixture configured a Tempo client; it must not have one")
	}
	recent, err := tm.GetRecentTraces(10)
	if err != nil || len(recent) != 0 {
		t.Errorf("GetRecentTraces = (%d, %v), want (0, nil)", len(recent), err)
	}
	edges, err := tm.GetEdgeStats(10)
	if err != nil || len(edges) != 0 {
		t.Errorf("GetEdgeStats = (%d, %v), want (0, nil)", len(edges), err)
	}
}

// TestRegistryStartStopWithNilAccumulator exercises the sequencing that used to
// be guaranteed by the accumulator existing. Start must still start the
// consumer, Stop must not dereference the nil accumulator, and the pair must
// leave no goroutine behind — including the trim loop, whose Stop ordering runs
// before the accumulator branch.
func TestRegistryStartStopWithNilAccumulator(t *testing.T) {
	tm, err := NewTracingManager(&TracingConfig{
		Enabled:           true,
		RedisURL:          "redis://127.0.0.1:1", // refused; the consumer retries in the background
		StreamName:        "mesh:trace",
		ConsumerGroup:     DefaultTraceConsumerGroup,
		ConsumerName:      "registry-startstop",
		BatchSize:         100,
		BlockTimeout:      100 * time.Millisecond,
		TraceTimeout:      time.Minute,
		TraceRetention:    time.Hour, // non-zero: the trim loop must run and stop
		ExporterType:      "otlp",
		TelemetryEndpoint: "localhost:4317",
		TelemetryProtocol: "grpc",
	})
	if err != nil {
		t.Fatalf("NewTracingManager: %v", err)
	}
	if tm.GetAccumulator() != nil {
		t.Fatal("fixture built an accumulator; the point of this test is the nil path")
	}

	runtime.GC()
	before := runtime.NumGoroutine()

	if err := tm.Start(); err != nil {
		t.Fatalf("Start: %v", err)
	}
	if running, _ := tm.consumer.GetConsumerInfo()["running"].(bool); !running {
		t.Error("Start returned but the consumer is not running; dropping the accumulator must not skip the consumer")
	}
	if tm.trimStop == nil {
		t.Error("Start did not launch the trim loop")
	}

	time.Sleep(200 * time.Millisecond)

	if err := tm.Stop(); err != nil {
		// A refused Redis connection can surface as a consumer stop error; the
		// nil-accumulator path is what is under test, and a panic would have
		// failed the test already.
		t.Logf("Stop returned: %v (tolerated: Redis is intentionally unreachable)", err)
	}

	// Give the consumer's background loops a moment to unwind.
	deadline := time.Now().Add(5 * time.Second)
	var after int
	for time.Now().Before(deadline) {
		runtime.GC()
		after = runtime.NumGoroutine()
		if after <= before {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if after > before {
		buf := make([]byte, 1<<16)
		buf = buf[:runtime.Stack(buf, true)]
		t.Errorf("goroutines %d -> %d after Start/Stop; leak:\n%s", before, after, buf)
	}
}

// TestAccumulatorOnlyManagerStillAccumulates proves meshui's pipeline is
// untouched end to end, not merely that its field is non-nil: a span event fed
// to the manager's processor must still reach the accumulator's aggregates.
func TestAccumulatorOnlyManagerStillAccumulates(t *testing.T) {
	tm := newUIManagerForTest(t)

	// Fed through tm.processor, not the accumulator directly: the fan-out is
	// part of what meshui relies on and part of what #1540 touched.
	events := []*TraceEvent{
		makeCalleeSpan("t1", "span-parent", "", "caller", "handle", 1, true),
		makeCalleeSpan("t1", "span-child", "span-parent", "provider", "do_work", 42, true),
	}
	for _, e := range events {
		if err := tm.processor.ProcessTraceEvent(e); err != nil {
			t.Fatalf("ProcessTraceEvent: %v", err)
		}
	}

	acc := tm.GetAccumulator()
	if acc == nil {
		t.Fatal("meshui manager has no accumulator")
	}
	acc.FinalizeAllActive()

	if got := acc.EdgeStatCount(); got != 1 {
		t.Fatalf("meshui accumulator recorded %d edges, want 1: its pipeline must be unaffected by #1540", got)
	}
	edges, err := tm.GetEdgeStats(10)
	if err != nil {
		t.Fatalf("GetEdgeStats: %v", err)
	}
	if len(edges) != 1 || edges[0].Source != "caller" || edges[0].Target != "provider" || edges[0].TargetFunction != "do_work" {
		t.Fatalf("meshui GetEdgeStats = %+v, want one caller->provider/do_work edge", edges)
	}
}
