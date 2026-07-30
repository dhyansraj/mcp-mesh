package tracing

import (
	"context"
	"fmt"
	"strconv"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

// TestAccumulatorOnlyManagerPropagatesRetention is issue #1424's "trimming must
// not depend on one process" item: meshui builds its own TracingConfig and
// previously left Retention at zero, so it consumed the stream through its own
// group but never trimmed it. If the registry was down, nothing bounded the
// stream.
func TestAccumulatorOnlyManagerPropagatesRetention(t *testing.T) {
	tm, err := NewAccumulatorOnlyManager(&TracingConfig{
		Enabled:        true,
		RedisURL:       "redis://127.0.0.1:1", // never dialled; consumer connects lazily
		StreamName:     "mesh:trace",
		ConsumerGroup:  "mcp-mesh-ui-dashboard",
		ConsumerName:   "ui-test",
		BatchSize:      100,
		BlockTimeout:   time.Second,
		TraceRetention: 6 * time.Hour,
	})
	if err != nil {
		t.Fatalf("NewAccumulatorOnlyManager: %v", err)
	}
	defer func() {
		if tm.consumer != nil {
			tm.consumer.cancel()
		}
	}()

	if tm.consumer == nil {
		t.Fatal("no consumer built")
	}
	if tm.consumer.retention != 6*time.Hour {
		t.Fatalf("consumer retention = %s, want 6h: meshui must honour MCP_MESH_TRACE_RETENTION", tm.consumer.retention)
	}
}

// TestTraceRetentionFromEnvMatchesRegistry pins that meshui and the registry
// derive retention from the same parser, so the two processes cannot drift to
// different trim windows.
func TestTraceRetentionFromEnvMatchesRegistry(t *testing.T) {
	for _, v := range []string{"", "48h", "0", "-1h", "garbage"} {
		t.Setenv("MCP_MESH_TRACE_RETENTION", v)
		ui := TraceRetentionFromEnv()
		registry := DefaultTracingConfig().TraceRetention
		if ui != registry {
			t.Fatalf("MCP_MESH_TRACE_RETENTION=%q: meshui got %s, registry got %s", v, ui, registry)
		}
	}
}

// TestUIConsumerTrimsStream proves the meshui-side trim actually shears the
// stream against a real Redis: entries older than the retention window are
// removed by the same TrimStream the registry uses.
func TestUIConsumerTrimsStream(t *testing.T) {
	url := redisURLForTest(t)

	stream := fmt.Sprintf("test:uitrim:%d", time.Now().UnixNano())
	tm, err := NewAccumulatorOnlyManager(&TracingConfig{
		Enabled:        true,
		RedisURL:       url,
		StreamName:     stream,
		ConsumerGroup:  "mcp-mesh-ui-dashboard",
		ConsumerName:   "ui-test",
		BatchSize:      100,
		BlockTimeout:   100 * time.Millisecond,
		TraceRetention: time.Hour,
	})
	if err != nil {
		t.Fatalf("NewAccumulatorOnlyManager: %v", err)
	}
	sc := tm.consumer
	defer sc.cancel()

	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatalf("ParseURL: %v", err)
	}
	client := redis.NewClient(opts)
	defer client.Close()
	ctx := context.Background()
	defer client.Del(ctx, stream)

	// 100 entries stamped 2h old (past the window) and 100 stamped now.
	oldMs := time.Now().Add(-2 * time.Hour).UnixMilli()
	nowMs := time.Now().UnixMilli()
	for i := 0; i < 100; i++ {
		if err := client.XAdd(ctx, &redis.XAddArgs{
			Stream: stream,
			ID:     strconv.FormatInt(oldMs, 10) + "-" + strconv.Itoa(i),
			Values: map[string]interface{}{"span_id": fmt.Sprintf("old-%d", i)},
		}).Err(); err != nil {
			t.Fatalf("XADD old: %v", err)
		}
	}
	for i := 0; i < 100; i++ {
		if err := client.XAdd(ctx, &redis.XAddArgs{
			Stream: stream,
			ID:     strconv.FormatInt(nowMs, 10) + "-" + strconv.Itoa(i),
			Values: map[string]interface{}{"span_id": fmt.Sprintf("new-%d", i)},
		}).Err(); err != nil {
			t.Fatalf("XADD new: %v", err)
		}
	}

	if n, _ := client.XLen(ctx, stream).Result(); n != 200 {
		t.Fatalf("XLEN = %d, want 200 before trimming", n)
	}

	sc.mu.Lock()
	sc.client = client
	sc.connectionState = StateConnected
	sc.mu.Unlock()

	removed, err := sc.TrimStream()
	if err != nil {
		t.Fatalf("TrimStream: %v", err)
	}
	if removed == 0 {
		t.Fatal("meshui trimmed 0 entries: retention is not reaching the UI consumer")
	}

	after, err := client.XLen(ctx, stream).Result()
	if err != nil {
		t.Fatalf("XLEN: %v", err)
	}
	if after >= 200 {
		t.Fatalf("XLEN = %d after trim, want < 200", after)
	}
	// XTRIM MINID ~ is approximate (whole macro-node steps), so assert the
	// direction and that nothing recent was lost, not an exact count.
	if after < 100 {
		t.Fatalf("XLEN = %d after trim: entries inside the retention window were removed", after)
	}
}
