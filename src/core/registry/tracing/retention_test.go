package tracing

import (
	"context"
	"fmt"
	"io"
	"log"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

// --- helpers ---

type noopProcessor struct{}

func (noopProcessor) ProcessTraceEvent(*TraceEvent) error { return nil }

type noopExporter struct{}

func (noopExporter) ExportTrace(*CompletedTrace) error { return nil }

// seedStreamEntry adds an entry with an explicit millisecond-timestamp ID
// (the same ID shape producers generate via XADD *).
func seedStreamEntry(t *testing.T, client *redis.Client, stream string, ts time.Time, seq int) string {
	t.Helper()
	id := fmt.Sprintf("%d-%d", ts.UnixMilli(), seq)
	if err := client.XAdd(context.Background(), &redis.XAddArgs{
		Stream: stream,
		ID:     id,
		Values: map[string]interface{}{"trace_id": "t", "span_id": "s"},
	}).Err(); err != nil {
		t.Fatalf("failed to seed stream entry %s: %v", id, err)
	}
	return id
}

func newTestConsumer(client *redis.Client, stream string, retention time.Duration) *StreamConsumer {
	return &StreamConsumer{
		enabled:         true,
		client:          client,
		connectionState: StateConnected,
		streamName:      stream,
		retention:       retention,
		logger:          log.New(io.Discard, "", 0),
		ctx:             context.Background(),
	}
}

// --- env parsing (mirrors the MCP_MESH_RETENTION conventions) ---

func TestParseTraceRetentionFromEnv(t *testing.T) {
	t.Run("unset defaults to 24h", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_RETENTION", "")
		if got := parseTraceRetentionFromEnv(); got != defaultTraceRetention {
			t.Errorf("expected default %s, got %s", defaultTraceRetention, got)
		}
	})

	t.Run("valid duration is used", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_RETENTION", "48h")
		if got := parseTraceRetentionFromEnv(); got != 48*time.Hour {
			t.Errorf("expected 48h, got %s", got)
		}
	})

	t.Run("zero disables", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_RETENTION", "0")
		if got := parseTraceRetentionFromEnv(); got != 0 {
			t.Errorf("expected 0 (disabled), got %s", got)
		}
	})

	t.Run("negative falls back to default", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_RETENTION", "-1h")
		if got := parseTraceRetentionFromEnv(); got != defaultTraceRetention {
			t.Errorf("expected default %s, got %s", defaultTraceRetention, got)
		}
	})

	t.Run("invalid falls back to default", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_RETENTION", "not-a-duration")
		if got := parseTraceRetentionFromEnv(); got != defaultTraceRetention {
			t.Errorf("expected default %s, got %s", defaultTraceRetention, got)
		}
	})
}

// --- stream trimming ---
//
// TrimStream uses XTRIM MINID ~ (XTrimMinIDApprox). miniredis treats `~` as
// exact, so the exact-count assertions below hold; real Redis approximate
// trimming may retain entries past the cutoff until a macro-node boundary.
// If these tests ever move to testcontainers/real Redis, relax the equalities
// to "at most N remaining / at least M removed".

func TestTrimStreamRemovesOnlyEntriesOlderThanRetention(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	now := time.Now()

	// Two entries past the 1h retention window, two within it.
	seedStreamEntry(t, client, stream, now.Add(-3*time.Hour), 0)
	seedStreamEntry(t, client, stream, now.Add(-2*time.Hour), 0)
	keep1 := seedStreamEntry(t, client, stream, now.Add(-30*time.Minute), 0)
	keep2 := seedStreamEntry(t, client, stream, now.Add(-time.Minute), 0)

	sc := newTestConsumer(client, stream, time.Hour)

	removed, err := sc.TrimStream()
	if err != nil {
		t.Fatalf("TrimStream failed: %v", err)
	}
	if removed != 2 {
		t.Errorf("expected 2 entries removed, got %d", removed)
	}

	entries, err := client.XRange(context.Background(), stream, "-", "+").Result()
	if err != nil {
		t.Fatalf("XRange failed: %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("expected 2 entries remaining, got %d", len(entries))
	}
	if entries[0].ID != keep1 || entries[1].ID != keep2 {
		t.Errorf("expected remaining entries [%s %s], got [%s %s]", keep1, keep2, entries[0].ID, entries[1].ID)
	}
}

func TestTrimStreamDisabledWithZeroRetention(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	seedStreamEntry(t, client, stream, time.Now().Add(-48*time.Hour), 0)
	seedStreamEntry(t, client, stream, time.Now().Add(-36*time.Hour), 0)

	sc := newTestConsumer(client, stream, 0)

	removed, err := sc.TrimStream()
	if err != nil {
		t.Fatalf("TrimStream failed: %v", err)
	}
	if removed != 0 {
		t.Errorf("expected no entries removed with retention=0, got %d", removed)
	}

	length, err := client.XLen(context.Background(), stream).Result()
	if err != nil {
		t.Fatalf("XLen failed: %v", err)
	}
	if length != 2 {
		t.Errorf("expected stream untouched (2 entries), got %d", length)
	}
}

func TestTrimStreamNoopWhenDisconnected(t *testing.T) {
	sc := &StreamConsumer{
		enabled:         true,
		connectionState: StateDisconnected,
		streamName:      "mesh:trace",
		retention:       time.Hour,
		logger:          log.New(io.Discard, "", 0),
		ctx:             context.Background(),
	}

	removed, err := sc.TrimStream()
	if err != nil {
		t.Fatalf("TrimStream should no-op when disconnected, got error: %v", err)
	}
	if removed != 0 {
		t.Errorf("expected 0 removed when disconnected, got %d", removed)
	}
}

// TestStartupTrimRunsOnConnect exercises the full consumer connect path:
// the recovery trim must fire as part of (re)connection, before any periodic
// tick — this is the cleanup path after a registry outage.
func TestStartupTrimRunsOnConnect(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	now := time.Now()
	seedStreamEntry(t, client, stream, now.Add(-3*time.Hour), 0)
	seedStreamEntry(t, client, stream, now.Add(-2*time.Hour), 0)
	seedStreamEntry(t, client, stream, now.Add(-time.Minute), 0)

	consumer, err := NewStreamConsumer(&StreamConsumerConfig{
		RedisURL:      "redis://" + mr.Addr(),
		StreamName:    stream,
		ConsumerGroup: "test-group",
		ConsumerName:  "test-consumer",
		BatchSize:     10,
		BlockTimeout:  100 * time.Millisecond,
		Enabled:       true,
		Retention:     time.Hour,
	}, noopProcessor{})
	if err != nil {
		t.Fatalf("NewStreamConsumer failed: %v", err)
	}
	consumer.logger = log.New(io.Discard, "", 0)

	if err := consumer.Start(); err != nil {
		t.Fatalf("consumer Start failed: %v", err)
	}
	defer consumer.Stop()

	// XACK never deletes entries, so the consumer reading the stream cannot
	// shrink it — only the startup trim can.
	deadline := time.Now().Add(5 * time.Second)
	for {
		length, err := client.XLen(context.Background(), stream).Result()
		if err == nil && length == 1 {
			return // startup trim removed the two expired entries
		}
		if time.Now().After(deadline) {
			t.Fatalf("startup trim did not run: stream length=%d (want 1)", length)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func TestStartupTrimSkippedWhenRetentionDisabled(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	seedStreamEntry(t, client, stream, time.Now().Add(-48*time.Hour), 0)
	seedStreamEntry(t, client, stream, time.Now().Add(-36*time.Hour), 0)

	consumer, err := NewStreamConsumer(&StreamConsumerConfig{
		RedisURL:      "redis://" + mr.Addr(),
		StreamName:    stream,
		ConsumerGroup: "test-group",
		ConsumerName:  "test-consumer",
		BatchSize:     10,
		BlockTimeout:  100 * time.Millisecond,
		Enabled:       true,
		Retention:     0,
	}, noopProcessor{})
	if err != nil {
		t.Fatalf("NewStreamConsumer failed: %v", err)
	}
	consumer.logger = log.New(io.Discard, "", 0)

	if err := consumer.Start(); err != nil {
		t.Fatalf("consumer Start failed: %v", err)
	}
	defer consumer.Stop()

	// Wait until connected (and therefore past the point where the startup
	// trim would have run), then verify the stream is untouched.
	deadline := time.Now().Add(5 * time.Second)
	for !consumer.IsConnected() {
		if time.Now().After(deadline) {
			t.Fatal("consumer never connected")
		}
		time.Sleep(50 * time.Millisecond)
	}
	// Small grace so a (buggy) trim issued right after connect would land.
	time.Sleep(200 * time.Millisecond)

	length, err := client.XLen(context.Background(), stream).Result()
	if err != nil {
		t.Fatalf("XLen failed: %v", err)
	}
	if length != 2 {
		t.Errorf("expected stream untouched with retention=0 (2 entries), got %d", length)
	}
}

// --- correlator completed-trace store bounds ---

func newQuietCorrelator(t *testing.T, retention time.Duration) *SpanCorrelator {
	t.Helper()
	sc := NewSpanCorrelator(noopExporter{}, 5*time.Minute, retention)
	sc.logger = log.New(io.Discard, "", 0)
	t.Cleanup(func() { _ = sc.Stop() })
	return sc
}

func makeCompletedTrace(id string, endTime time.Time) *CompletedTrace {
	return &CompletedTrace{
		TraceID:   id,
		StartTime: endTime.Add(-time.Second),
		EndTime:   endTime,
		Duration:  time.Second,
		Success:   true,
		SpanCount: 1,
	}
}

func TestCorrelatorCompletedTraceCountCap(t *testing.T) {
	sc := newQuietCorrelator(t, 0)
	sc.maxStoredTraces = 30

	base := time.Now().Add(-time.Hour)
	for i := 0; i < 31; i++ {
		sc.storeCompletedTrace(makeCompletedTrace(fmt.Sprintf("trace-%03d", i), base.Add(time.Duration(i)*time.Second)))
	}

	if count := sc.GetTraceCount(); count > sc.maxStoredTraces {
		t.Errorf("store exceeded cap: %d > %d", count, sc.maxStoredTraces)
	}

	// Oldest entries are evicted first (cleanup removes at least 10).
	for i := 0; i < 10; i++ {
		id := fmt.Sprintf("trace-%03d", i)
		if _, ok := sc.GetTrace(id); ok {
			t.Errorf("expected oldest trace %s to be evicted", id)
		}
	}

	// Newest entry stays queryable.
	if _, ok := sc.GetTrace("trace-030"); !ok {
		t.Error("expected newest trace trace-030 to remain queryable")
	}
}

func TestCorrelatorCompletedTraceAgePruning(t *testing.T) {
	sc := newQuietCorrelator(t, time.Hour)

	now := time.Now()
	sc.storeCompletedTrace(makeCompletedTrace("expired-1", now.Add(-3*time.Hour)))
	sc.storeCompletedTrace(makeCompletedTrace("expired-2", now.Add(-2*time.Hour)))
	sc.storeCompletedTrace(makeCompletedTrace("recent", now.Add(-5*time.Minute)))

	sc.pruneExpiredCompletedTraces()

	if _, ok := sc.GetTrace("expired-1"); ok {
		t.Error("expected expired-1 to be pruned")
	}
	if _, ok := sc.GetTrace("expired-2"); ok {
		t.Error("expected expired-2 to be pruned")
	}
	if _, ok := sc.GetTrace("recent"); !ok {
		t.Error("expected recent trace to remain queryable")
	}
	if count := sc.GetTraceCount(); count != 1 {
		t.Errorf("expected 1 trace after pruning, got %d", count)
	}
}

func TestCorrelatorAgePruningDisabledWithZeroRetention(t *testing.T) {
	sc := newQuietCorrelator(t, 0)

	sc.storeCompletedTrace(makeCompletedTrace("old", time.Now().Add(-100*time.Hour)))
	sc.pruneExpiredCompletedTraces()

	if _, ok := sc.GetTrace("old"); !ok {
		t.Error("expected age pruning to be disabled with retention=0")
	}
}
