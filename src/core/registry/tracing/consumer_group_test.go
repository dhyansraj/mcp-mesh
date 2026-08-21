package tracing

import (
	"bytes"
	"io"
	"os"
	"strings"
	"testing"
)

// The literal the registry has always used. Spelled out here rather than
// referenced through the constant so a rename of DefaultTraceConsumerGroup's
// VALUE cannot slip through green: existing deployments already have this
// group on their Redis stream, and changing it silently would make an upgraded
// registry re-read from wherever the new group's cursor starts.
const historicalConsumerGroup = "mcp-mesh-registry-processors"

func TestTraceConsumerGroupFromEnv(t *testing.T) {
	t.Run("unset keeps the historical default", func(t *testing.T) {
		// t.Setenv registers the restore; unset after it to test the absent case.
		t.Setenv("MCP_MESH_TRACE_CONSUMER_GROUP", "")
		if err := os.Unsetenv("MCP_MESH_TRACE_CONSUMER_GROUP"); err != nil {
			t.Fatalf("unsetenv: %v", err)
		}
		if got := TraceConsumerGroupFromEnv(); got != historicalConsumerGroup {
			t.Errorf("TraceConsumerGroupFromEnv() = %q, want %q", got, historicalConsumerGroup)
		}
	})

	t.Run("empty is treated as unset", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_CONSUMER_GROUP", "")
		if got := TraceConsumerGroupFromEnv(); got != historicalConsumerGroup {
			t.Errorf("TraceConsumerGroupFromEnv() = %q, want %q", got, historicalConsumerGroup)
		}
	})

	t.Run("set overrides", func(t *testing.T) {
		t.Setenv("MCP_MESH_TRACE_CONSUMER_GROUP", "mcp-mesh-registry-scratch")
		if got := TraceConsumerGroupFromEnv(); got != "mcp-mesh-registry-scratch" {
			t.Errorf("TraceConsumerGroupFromEnv() = %q, want %q", got, "mcp-mesh-registry-scratch")
		}
	})
}

// TestConsumerGroupDefaultsAreOneSource guards the reason the two literals were
// collapsed (#1536): manager.go and consumer.go each carried the same string,
// only one of them was the effective default, and a future change could move
// one without the other. Both configs now resolve through the same helper.
func TestConsumerGroupDefaultsAreOneSource(t *testing.T) {
	t.Setenv("MCP_MESH_TRACE_CONSUMER_GROUP", "")
	if err := os.Unsetenv("MCP_MESH_TRACE_CONSUMER_GROUP"); err != nil {
		t.Fatalf("unsetenv: %v", err)
	}

	if got := DefaultTracingConfig().ConsumerGroup; got != historicalConsumerGroup {
		t.Errorf("DefaultTracingConfig().ConsumerGroup = %q, want %q", got, historicalConsumerGroup)
	}
	if got := DefaultStreamConsumerConfig().ConsumerGroup; got != historicalConsumerGroup {
		t.Errorf("DefaultStreamConsumerConfig().ConsumerGroup = %q, want %q", got, historicalConsumerGroup)
	}

	t.Setenv("MCP_MESH_TRACE_CONSUMER_GROUP", "mcp-mesh-registry-scratch")
	if got := DefaultTracingConfig().ConsumerGroup; got != "mcp-mesh-registry-scratch" {
		t.Errorf("DefaultTracingConfig().ConsumerGroup = %q, want the override", got)
	}
	if got := DefaultStreamConsumerConfig().ConsumerGroup; got != "mcp-mesh-registry-scratch" {
		t.Errorf("DefaultStreamConsumerConfig().ConsumerGroup = %q, want the override", got)
	}
}

func TestSingleReaderWarning(t *testing.T) {
	t.Run("silent in stream-through mode", func(t *testing.T) {
		if got := singleReaderWarning(true, "otlp"); got != "" {
			t.Errorf("singleReaderWarning(stream-through) = %q, want empty", got)
		}
	})

	for _, exporter := range []string{"console", "json"} {
		t.Run("fires for "+exporter, func(t *testing.T) {
			got := singleReaderWarning(false, exporter)
			if got == "" {
				t.Fatalf("singleReaderWarning(correlation, %q) is empty, want a warning", exporter)
			}
			if !strings.Contains(got, exporter) {
				t.Errorf("warning does not name the exporter that triggered it: %q", got)
			}
			if !strings.Contains(got, "replica") {
				t.Errorf("warning does not mention replicas: %q", got)
			}
		})
	}
}

// TestNewTracingManagerWarnsOnlyInCorrelationMode exercises the constructor
// rather than the helper, because the helper returning a string proves nothing
// about whether an operator ever sees it.
//
// The redirect wraps CONSTRUCTION: log.New binds os.Stdout when the manager's
// logger is built, so a swap made afterwards would capture nothing.
func TestNewTracingManagerWarnsOnlyInCorrelationMode(t *testing.T) {
	tests := []struct {
		name        string
		exporter    string
		wantWarning bool
	}{
		{"console correlates locally", "console", true},
		{"otlp streams through to Tempo", "otlp", false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			config := DefaultTracingConfig()
			config.Enabled = true
			config.ExporterType = tc.exporter
			config.TraceRetention = 0 // no trim loop; nothing is Start()ed here
			config.RedisURL = "redis://127.0.0.1:6379"

			out := captureStdout(t, func() {
				manager, err := NewTracingManager(config)
				if err != nil {
					t.Fatalf("NewTracingManager(%s): %v", tc.exporter, err)
				}
				if err := manager.Stop(); err != nil {
					t.Errorf("Stop(): %v", err)
				}
			})

			gotWarning := strings.Contains(out, "assumes a single registry reader")
			if gotWarning != tc.wantWarning {
				t.Errorf("warning present = %v, want %v.\ncaptured:\n%s", gotWarning, tc.wantWarning, out)
			}
		})
	}
}

func captureStdout(t *testing.T, fn func()) string {
	t.Helper()

	orig := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	os.Stdout = w

	captured := make(chan string, 1)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		captured <- buf.String()
	}()

	func() {
		defer func() {
			_ = w.Close()
			os.Stdout = orig
		}()
		fn()
	}()

	return <-captured
}
