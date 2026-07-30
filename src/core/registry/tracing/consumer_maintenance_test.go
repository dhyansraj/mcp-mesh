package tracing

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

// redisURLForTest returns the Redis URL to exercise the consumer-group
// housekeeping against, or skips the test. Set MCP_MESH_TEST_REDIS_URL to a
// throwaway Redis (e.g. redis://localhost:6399) to run these; they are skipped
// by default so `go test ./...` needs no external service.
func redisURLForTest(t *testing.T) string {
	t.Helper()
	url := os.Getenv("MCP_MESH_TEST_REDIS_URL")
	if url == "" {
		t.Skip("set MCP_MESH_TEST_REDIS_URL to run consumer-group housekeeping tests against a real Redis")
	}

	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatalf("bad MCP_MESH_TEST_REDIS_URL %q: %v", url, err)
	}
	c := redis.NewClient(opts)
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := c.Ping(ctx).Err(); err != nil {
		t.Skipf("Redis at %s unreachable: %v", url, err)
	}
	return url
}

// failingProcessor fails the first n ProcessTraceEvent calls for a given span
// ID, then succeeds. Models the "processing failed, entry stuck in the PEL"
// case from #1424.
type failingProcessor struct {
	failuresLeft int
	seen         []string
}

func (fp *failingProcessor) ProcessTraceEvent(event *TraceEvent) error {
	fp.seen = append(fp.seen, event.SpanID)
	if fp.failuresLeft > 0 {
		fp.failuresLeft--
		return fmt.Errorf("simulated processing failure for %s", event.SpanID)
	}
	return nil
}

// newConnectedConsumer builds a StreamConsumer wired to a real Redis on a
// per-test stream/group, with the connection established synchronously (no
// background connectionManager, so the test drives everything).
func newConnectedConsumer(t *testing.T, url string, processor TraceEventProcessor) (*StreamConsumer, *redis.Client, string) {
	t.Helper()

	stream := fmt.Sprintf("test:trace:%s:%d", t.Name(), time.Now().UnixNano())
	group := "test-group"

	sc, err := NewStreamConsumer(&StreamConsumerConfig{
		RedisURL:      url,
		StreamName:    stream,
		ConsumerGroup: group,
		ConsumerName:  "live-consumer",
		BatchSize:     10,
		BlockTimeout:  100 * time.Millisecond,
		Enabled:       true,
	}, processor)
	if err != nil {
		t.Fatalf("NewStreamConsumer: %v", err)
	}

	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatalf("ParseURL: %v", err)
	}
	client := redis.NewClient(opts)

	sc.mu.Lock()
	sc.client = client
	sc.connectionState = StateConnected
	sc.mu.Unlock()

	ctx := context.Background()
	if err := client.XGroupCreateMkStream(ctx, stream, group, "0").Err(); err != nil {
		t.Fatalf("XGroupCreateMkStream: %v", err)
	}

	t.Cleanup(func() {
		client.Del(context.Background(), stream)
		client.Close()
		sc.cancel()
	})

	return sc, client, stream
}

func xaddTraceEvent(t *testing.T, client *redis.Client, stream, traceID, spanID string) string {
	t.Helper()
	id, err := client.XAdd(context.Background(), &redis.XAddArgs{
		Stream: stream,
		Values: map[string]interface{}{
			"trace_id":    traceID,
			"span_id":     spanID,
			"agent_name":  "test-agent",
			"operation":   "test_op",
			"timestamp":   fmt.Sprintf("%d", time.Now().Unix()),
			"duration_ms": "5",
		},
	}).Result()
	if err != nil {
		t.Fatalf("XADD: %v", err)
	}
	return id
}

// TestReclaimPendingRecoversStuckEntry proves the PEL does not grow forever:
// an entry whose processing failed (delivered, never ACKed) is reclaimed,
// reprocessed and ACKed, dropping group pending back to zero.
//
// Before #1424 the entry was unreachable: XREADGROUP uses ">" (new messages
// only) and nothing in the repo issued XCLAIM/XAUTOCLAIM/XPENDING.
func TestReclaimPendingRecoversStuckEntry(t *testing.T) {
	url := redisURLForTest(t)
	fp := &failingProcessor{failuresLeft: 1}
	sc, client, stream := newConnectedConsumer(t, url, fp)
	ctx := context.Background()

	msgID := xaddTraceEvent(t, client, stream, "trace-1", "span-1")

	// First delivery: processMessage fails, so processNextBatch logs and skips
	// the ACK — exactly the pre-existing behaviour that stranded the entry.
	if err := sc.processNextBatch(); err != nil {
		t.Fatalf("processNextBatch: %v", err)
	}

	pending, err := client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING: %v", err)
	}
	if pending.Count != 1 {
		t.Fatalf("group pending = %d, want 1 (entry should be stuck in the PEL)", pending.Count)
	}

	// A second XREADGROUP must NOT see it — this is the "never re-read" half
	// of the bug, asserted rather than assumed.
	if err := sc.processNextBatch(); err != nil {
		t.Fatalf("processNextBatch (2nd): %v", err)
	}
	if len(fp.seen) != 1 {
		t.Fatalf("processor saw %d deliveries, want 1: XREADGROUP \">\" must not redeliver", len(fp.seen))
	}

	// Now reclaim. Drop the idle threshold to zero for the test so we don't
	// have to wait pelMinIdle.
	reclaimed, dropped, err := sc.reclaimPendingWithIdle(0)
	if err != nil {
		t.Fatalf("ReclaimPending: %v", err)
	}
	if reclaimed != 1 || dropped != 0 {
		t.Fatalf("reclaimed=%d dropped=%d, want 1 and 0", reclaimed, dropped)
	}

	pending, err = client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING after reclaim: %v", err)
	}
	if pending.Count != 0 {
		t.Fatalf("group pending = %d after reclaim, want 0", pending.Count)
	}
	if len(fp.seen) != 2 {
		t.Fatalf("processor saw %d deliveries, want 2 (original + reclaim)", len(fp.seen))
	}
	_ = msgID
}

// TestReclaimPendingDropsPoisonPill proves a permanently-failing entry does
// not sit in the PEL forever either: after pelMaxDeliveries attempts it is
// ACKed and logged rather than retried indefinitely.
func TestReclaimPendingDropsPoisonPill(t *testing.T) {
	url := redisURLForTest(t)
	fp := &failingProcessor{failuresLeft: 1000} // always fails
	sc, client, stream := newConnectedConsumer(t, url, fp)
	ctx := context.Background()

	xaddTraceEvent(t, client, stream, "trace-poison", "span-poison")

	if err := sc.processNextBatch(); err != nil {
		t.Fatalf("processNextBatch: %v", err)
	}

	// Each reclaim pass bumps the delivery counter. Converge on the drop.
	totalDropped := 0
	for i := 0; i < pelMaxDeliveries+3; i++ {
		_, dropped, err := sc.reclaimPendingWithIdle(0)
		if err != nil {
			t.Fatalf("ReclaimPending pass %d: %v", i, err)
		}
		totalDropped += dropped
		if totalDropped > 0 {
			break
		}
	}

	if totalDropped != 1 {
		t.Fatalf("dropped = %d, want 1: a permanently-failing entry must not stay pending forever", totalDropped)
	}

	pending, err := client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING: %v", err)
	}
	if pending.Count != 0 {
		t.Fatalf("group pending = %d after the poison-pill drop, want 0", pending.Count)
	}
}

// slowProcessor succeeds, but takes `delay` per message. Models a reclaim pass
// whose per-message work (a blocking OTLP export, a slow DB write) is slow
// enough to burn the pass-wide deadline.
type slowProcessor struct {
	delay time.Duration
	seen  []string
}

func (sp *slowProcessor) ProcessTraceEvent(event *TraceEvent) error {
	time.Sleep(sp.delay)
	sp.seen = append(sp.seen, event.SpanID)
	return nil
}

// TestReclaimPendingAcksAfterBatchDeadlineExpires proves a slow reclaim pass
// still ACKs what it processed. The pass-wide context is shared across up to
// pelReclaimBatch messages with a processMessage between each ACK; when a
// shared deadline was used for the ACKs too, every message after the deadline
// expired was processed and then left in the PEL — reclaimed and reprocessed
// on every later pass, forever.
func TestReclaimPendingAcksAfterBatchDeadlineExpires(t *testing.T) {
	url := redisURLForTest(t)

	// Shrink the pass-wide deadline so the third message's ACK is guaranteed to
	// fall outside it (3 x 150ms of processing against a 250ms pass budget).
	origBatchTimeout := pelBatchTimeout
	pelBatchTimeout = 250 * time.Millisecond
	t.Cleanup(func() { pelBatchTimeout = origBatchTimeout })

	sp := &slowProcessor{delay: 150 * time.Millisecond}
	sc, client, stream := newConnectedConsumer(t, url, sp)
	ctx := context.Background()

	// Strand three entries in the PEL under a dead consumer.
	for i := 0; i < 3; i++ {
		xaddTraceEvent(t, client, stream, fmt.Sprintf("trace-slow-%d", i), fmt.Sprintf("span-slow-%d", i))
	}
	if err := client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    "test-group",
		Consumer: "registry-dead-slow",
		Streams:  []string{stream, ">"},
		Count:    3,
		Block:    10 * time.Millisecond,
	}).Err(); err != nil && err != redis.Nil {
		t.Fatalf("seed pending entries: %v", err)
	}

	pending, err := client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING: %v", err)
	}
	if pending.Count != 3 {
		t.Fatalf("group pending = %d before reclaim, want 3", pending.Count)
	}

	reclaimed, dropped, err := sc.reclaimPendingWithIdle(0)
	if err != nil {
		t.Fatalf("ReclaimPending: %v", err)
	}
	if len(sp.seen) != 3 {
		t.Fatalf("processor saw %d messages, want 3", len(sp.seen))
	}
	if reclaimed != 3 || dropped != 0 {
		t.Fatalf("reclaimed=%d dropped=%d, want 3 and 0: a message processed after the pass deadline expired must still be ACKed", reclaimed, dropped)
	}

	pending, err = client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING after reclaim: %v", err)
	}
	if pending.Count != 0 {
		t.Fatalf("group pending = %d after reclaim, want 0: processed-but-unacked entries stay in the PEL and are reprocessed forever", pending.Count)
	}
}

// TestReapIdleConsumersRemovesDeadEntry proves the group does not accumulate a
// permanent entry per pod restart. Consumer names embed hostname+PID, so a
// restarted registry leaves the old name behind forever without
// XGROUP DELCONSUMER.
func TestReapIdleConsumersRemovesDeadEntry(t *testing.T) {
	url := redisURLForTest(t)
	sc, client, stream := newConnectedConsumer(t, url, &failingProcessor{})
	ctx := context.Background()

	// Simulate three prior pod incarnations plus the live one.
	xaddTraceEvent(t, client, stream, "t", "s")
	for _, dead := range []string{"registry-pod-a-11", "registry-pod-b-22", "registry-pod-c-33"} {
		if err := client.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    "test-group",
			Consumer: dead,
			Streams:  []string{stream, ">"},
			Count:    1,
			Block:    10 * time.Millisecond,
		}).Err(); err != nil && err != redis.Nil {
			t.Fatalf("seed consumer %s: %v", dead, err)
		}
	}
	if err := sc.processNextBatch(); err != nil {
		t.Fatalf("processNextBatch: %v", err)
	}

	consumers, err := client.XInfoConsumers(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XINFO CONSUMERS: %v", err)
	}
	if len(consumers) != 4 {
		t.Fatalf("consumers = %d, want 4 (3 dead + 1 live)", len(consumers))
	}

	// Reclaim first (as runMaintenance does) so any dead consumer's pending
	// entries move to us and it can be safely deleted.
	if _, _, err := sc.reclaimPendingWithIdle(0); err != nil {
		t.Fatalf("ReclaimPending: %v", err)
	}

	// Zero idle threshold for the test rather than waiting an hour.
	reaped, err := sc.reapIdleConsumersWithTimeout(0)
	if err != nil {
		t.Fatalf("ReapIdleConsumers: %v", err)
	}
	if reaped != 3 {
		t.Fatalf("reaped = %d, want 3", reaped)
	}

	consumers, err = client.XInfoConsumers(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XINFO CONSUMERS after reap: %v", err)
	}
	if len(consumers) != 1 {
		t.Fatalf("consumers = %d after reap, want 1", len(consumers))
	}
	if consumers[0].Name != "live-consumer" {
		t.Fatalf("surviving consumer = %q, want the live one", consumers[0].Name)
	}
}

// TestReapIdleConsumersSkipsSelfAndPendingHolders guards the two ways this
// could destroy data: reaping ourselves, or reaping a consumer that still owns
// PEL entries (XGROUP DELCONSUMER discards them).
func TestReapIdleConsumersSkipsSelfAndPendingHolders(t *testing.T) {
	url := redisURLForTest(t)
	sc, client, stream := newConnectedConsumer(t, url, &failingProcessor{failuresLeft: 1000})
	ctx := context.Background()

	xaddTraceEvent(t, client, stream, "t1", "s1")
	// A dead consumer that still holds a pending entry.
	if err := client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    "test-group",
		Consumer: "registry-dead-with-pending",
		Streams:  []string{stream, ">"},
		Count:    1,
		Block:    10 * time.Millisecond,
	}).Err(); err != nil && err != redis.Nil {
		t.Fatalf("seed pending holder: %v", err)
	}
	// The live consumer reads (and fails), so it also has pending work.
	xaddTraceEvent(t, client, stream, "t2", "s2")
	if err := sc.processNextBatch(); err != nil {
		t.Fatalf("processNextBatch: %v", err)
	}

	reaped, err := sc.reapIdleConsumersWithTimeout(0)
	if err != nil {
		t.Fatalf("ReapIdleConsumers: %v", err)
	}
	if reaped != 0 {
		t.Fatalf("reaped = %d, want 0: consumers holding PEL entries must be left alone", reaped)
	}

	consumers, err := client.XInfoConsumers(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XINFO CONSUMERS: %v", err)
	}
	if len(consumers) != 2 {
		t.Fatalf("consumers = %d, want 2 (nothing reaped)", len(consumers))
	}

	pending, err := client.XPending(ctx, stream, "test-group").Result()
	if err != nil {
		t.Fatalf("XPENDING: %v", err)
	}
	if pending.Count != 2 {
		t.Fatalf("group pending = %d, want 2: no PEL entry may be discarded by the reap", pending.Count)
	}
}

// TestMaintenanceNoOpsWhenDisconnected verifies both housekeeping entry points
// are safe to call with no Redis connection — the maintenance loop runs on a
// timer regardless of connection state.
func TestMaintenanceNoOpsWhenDisconnected(t *testing.T) {
	sc, err := NewStreamConsumer(&StreamConsumerConfig{
		RedisURL:      "redis://127.0.0.1:1",
		StreamName:    "mesh:trace",
		ConsumerGroup: "g",
		Enabled:       true,
	}, &failingProcessor{})
	if err != nil {
		t.Fatalf("NewStreamConsumer: %v", err)
	}
	defer sc.cancel()

	reclaimed, dropped, err := sc.ReclaimPending()
	if err != nil || reclaimed != 0 || dropped != 0 {
		t.Fatalf("ReclaimPending while disconnected = (%d, %d, %v), want (0, 0, nil)", reclaimed, dropped, err)
	}
	reaped, err := sc.ReapIdleConsumers()
	if err != nil || reaped != 0 {
		t.Fatalf("ReapIdleConsumers while disconnected = (%d, %v), want (0, nil)", reaped, err)
	}

	// Also safe on a disabled consumer (tracing off).
	off, err := NewStreamConsumer(&StreamConsumerConfig{Enabled: false}, &failingProcessor{})
	if err != nil {
		t.Fatalf("NewStreamConsumer(disabled): %v", err)
	}
	if _, _, err := off.ReclaimPending(); err != nil {
		t.Fatalf("ReclaimPending on disabled consumer: %v", err)
	}
	if _, err := off.ReapIdleConsumers(); err != nil {
		t.Fatalf("ReapIdleConsumers on disabled consumer: %v", err)
	}
}
