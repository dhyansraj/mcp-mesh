package tracing

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

// seedSpan adds a stream entry with a distinguishable span_id so RangeEvents'
// ordering and truncation behavior can be asserted by span_id sequence.
func seedSpan(t *testing.T, client *redis.Client, stream string, ts time.Time, span string) {
	t.Helper()
	id := fmt.Sprintf("%d-0", ts.UnixMilli())
	if err := client.XAdd(context.Background(), &redis.XAddArgs{
		Stream: stream,
		ID:     id,
		Values: map[string]interface{}{"trace_id": "t", "span_id": span},
	}).Err(); err != nil {
		t.Fatalf("failed to seed span %s: %v", span, err)
	}
}

// TestRangeEventsChronologicalOrder verifies RangeEvents returns events oldest→
// newest even though it reads newest-first via XREVRANGE.
func TestRangeEventsChronologicalOrder(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	now := time.Now()
	seedSpan(t, client, stream, now.Add(-3*time.Minute), "s1")
	seedSpan(t, client, stream, now.Add(-2*time.Minute), "s2")
	seedSpan(t, client, stream, now.Add(-1*time.Minute), "s3")

	sc := newTestConsumer(client, stream, time.Hour)

	events, truncated, err := sc.RangeEvents("0-0", 50000, 1000)
	if err != nil {
		t.Fatalf("RangeEvents failed: %v", err)
	}
	if truncated {
		t.Errorf("expected truncated=false when under cap")
	}
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d", len(events))
	}
	want := []string{"s1", "s2", "s3"}
	for i, e := range events {
		if e.SpanID != want[i] {
			t.Errorf("event[%d]: expected span %s, got %s (order not chronological)", i, want[i], e.SpanID)
		}
	}
}

// TestRangeEventsTruncationKeepsNewest verifies that when the maxEntries cap is
// hit, the flag is set AND the retained slice is the newest entries (still
// returned in chronological order).
func TestRangeEventsTruncationKeepsNewest(t *testing.T) {
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer client.Close()

	const stream = "mesh:trace"
	base := time.Now().Add(-time.Hour)
	// 5 entries s0..s4, oldest first.
	for i := 0; i < 5; i++ {
		seedSpan(t, client, stream, base.Add(time.Duration(i)*time.Second), fmt.Sprintf("s%d", i))
	}

	sc := newTestConsumer(client, stream, time.Hour)

	// Cap at 2: the two NEWEST (s3, s4) must be retained, in chronological order.
	events, truncated, err := sc.RangeEvents("0-0", 2, 1)
	if err != nil {
		t.Fatalf("RangeEvents failed: %v", err)
	}
	if !truncated {
		t.Errorf("expected truncated=true when cap hit before range exhausted")
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 events at cap, got %d", len(events))
	}
	if events[0].SpanID != "s3" || events[1].SpanID != "s4" {
		t.Errorf("expected newest [s3 s4] chronological, got [%s %s]", events[0].SpanID, events[1].SpanID)
	}
}
