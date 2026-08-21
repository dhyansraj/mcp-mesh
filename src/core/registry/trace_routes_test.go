package registry

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/tracing"
)

// The registry serves exactly four /trace/* routes, and #1540 removed the
// TraceAccumulator that sat behind none of them. This file is the executable
// form of that table: it drives all four against a real stream-through
// TracingManager and a stub Tempo, so "the accumulator is unreachable from the
// registry" is a passing test rather than a grep of the handlers.
//
//	GET /trace/status     -> GetInfo()  (config + consumer + correlator)
//	GET /trace/info       -> GetInfo()  (same)
//	GET /trace/stats      -> GetStats() (nil in stream-through mode)
//	GET /trace/:trace_id  -> GetTrace() (Tempo in stream-through mode)

const stubTempoTrace = `{"batches":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"agent-a"}}]},` +
	`"scopeSpans":[{"spans":[{"traceId":"abc123","spanId":"s1","name":"do_work",` +
	`"startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000000500000000","attributes":[]}]}]}]}`

// newTraceRouteFixture wires the four routes onto a Server carrying the manager
// the registry actually builds, plus a stub Tempo that serves one trace and
// 404s "missingtrace". Returns the engine and the manager.
func newTraceRouteFixture(t *testing.T, exporter string) (*gin.Engine, *tracing.TracingManager, *int32) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	var tempoHits int32
	tempo := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&tempoHits, 1)
		if strings.HasSuffix(r.URL.Path, "/api/traces/missingtrace") {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(stubTempoTrace))
	}))
	t.Cleanup(tempo.Close)

	tm, err := tracing.NewTracingManager(&tracing.TracingConfig{
		Enabled:           true,
		RedisURL:          "redis://127.0.0.1:1", // never dialled; nothing calls Start
		StreamName:        "mesh:trace",
		ConsumerGroup:     tracing.DefaultTraceConsumerGroup,
		ConsumerName:      "registry-route-test",
		BatchSize:         100,
		BlockTimeout:      time.Second,
		TraceTimeout:      5 * time.Minute,
		TraceRetention:    0,
		ExporterType:      exporter,
		EnableStats:       true,
		TelemetryEndpoint: "localhost:4317",
		TelemetryProtocol: "grpc",
		TempoQueryURL:     tempo.URL,
	})
	if err != nil {
		t.Fatalf("NewTracingManager(%s): %v", exporter, err)
	}

	s := &Server{tracingManager: tm}
	e := gin.New()
	e.GET("/trace/status", s.handleTracingStatus)
	e.GET("/trace/stats", s.handleTracingStats)
	e.GET("/trace/info", s.handleTracingInfo)
	e.GET("/trace/:trace_id", s.handleTraceGet)
	return e, tm, &tempoHits
}

func getJSON(t *testing.T, e *gin.Engine, path string) (int, map[string]interface{}) {
	t.Helper()
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
	var body map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET %s: response is not a JSON object: %v (%s)", path, err, w.Body.String())
	}
	return w.Code, body
}

// TestTraceRoutesServedWithoutAccumulator drives every registry trace route
// against a manager that has no accumulator. Each must answer exactly as it
// always has: the accumulator was never in any of these paths, so removing it
// can only be visible here as a panic or an empty answer.
func TestTraceRoutesServedWithoutAccumulator(t *testing.T) {
	e, tm, tempoHits := newTraceRouteFixture(t, "otlp")

	if tm.GetAccumulator() != nil {
		t.Fatal("the registry manager built an accumulator; #1540 removed it")
	}

	t.Run("status, info and stats make no network call", func(t *testing.T) {
		for _, path := range []string{"/trace/status", "/trace/info", "/trace/stats"} {
			if code, _ := getJSON(t, e, path); code != http.StatusOK {
				t.Fatalf("GET %s = %d, want 200", path, code)
			}
		}
		if n := atomic.LoadInt32(tempoHits); n != 0 {
			t.Errorf("Tempo was queried %d times by status/info/stats; those routes answer from local state, "+
				"and a fallback that starts dialling is worse than one that never ran", n)
		}
	})

	t.Run("status and info answer from config and consumer", func(t *testing.T) {
		for _, path := range []string{"/trace/status", "/trace/info"} {
			code, body := getJSON(t, e, path)
			if code != http.StatusOK {
				t.Fatalf("GET %s = %d, want 200", path, code)
			}
			if body["enabled"] != true {
				t.Errorf("GET %s: enabled = %v, want true", path, body["enabled"])
			}
			if body["stream_through_mode"] != true {
				t.Errorf("GET %s: stream_through_mode = %v, want true", path, body["stream_through_mode"])
			}
			if body["exporter_type"] != "otlp" {
				t.Errorf("GET %s: exporter_type = %v, want otlp", path, body["exporter_type"])
			}
			consumer, ok := body["consumer"].(map[string]interface{})
			if !ok {
				t.Fatalf("GET %s: no consumer block: %v", path, body)
			}
			if consumer["consumer_group"] != tracing.DefaultTraceConsumerGroup {
				t.Errorf("GET %s: consumer_group = %v", path, consumer["consumer_group"])
			}
			// Stream-through mode has no correlator, and never had an
			// accumulator block to lose.
			if _, present := body["correlator"]; present {
				t.Errorf("GET %s: unexpected correlator block in stream-through mode", path)
			}
		}
	})

	t.Run("stats reports unavailable", func(t *testing.T) {
		code, body := getJSON(t, e, "/trace/stats")
		if code != http.StatusOK {
			t.Fatalf("GET /trace/stats = %d, want 200", code)
		}
		if body["stats_available"] != false {
			t.Errorf("stats_available = %v, want false (GetStats returns nil in stream-through mode)", body["stats_available"])
		}
	})

	t.Run("trace lookup is served by Tempo", func(t *testing.T) {
		code, body := getJSON(t, e, "/trace/abc123")
		if code != http.StatusOK {
			t.Fatalf("GET /trace/abc123 = %d, want 200: the Tempo path is the sink that matters", code)
		}
		if body["TraceID"] != "abc123" {
			t.Errorf("TraceID = %v, want abc123", body["TraceID"])
		}
		spans, _ := body["Spans"].([]interface{})
		if len(spans) != 1 {
			t.Fatalf("Spans = %d, want 1 (from the stub Tempo)", len(spans))
		}

		code, body = getJSON(t, e, "/trace/missingtrace")
		if code != http.StatusNotFound {
			t.Errorf("GET /trace/missingtrace = %d, want 404", code)
		}
		if body["error"] != "trace not found" {
			t.Errorf("error = %v, want \"trace not found\"", body["error"])
		}
	})
}

// TestTraceRoutesUnchangedInCorrelationMode covers the branch #1540 did not
// touch. Correlation mode never had an accumulator, so its answers must be
// identical: a correlator block on status/info, and a local (empty) trace
// lookup that does NOT reach out to Tempo.
func TestTraceRoutesUnchangedInCorrelationMode(t *testing.T) {
	e, tm, tempoHits := newTraceRouteFixture(t, "console")

	if tm.GetAccumulator() != nil {
		t.Fatal("correlation mode built an accumulator")
	}

	code, body := getJSON(t, e, "/trace/status")
	if code != http.StatusOK {
		t.Fatalf("GET /trace/status = %d, want 200", code)
	}
	if body["stream_through_mode"] != false {
		t.Errorf("stream_through_mode = %v, want false", body["stream_through_mode"])
	}
	if _, ok := body["correlator"].(map[string]interface{}); !ok {
		t.Errorf("correlation mode lost its correlator block: %v", body)
	}

	// The correlator holds nothing, and the stub Tempo must not be consulted:
	// a fallback that starts making network calls would be a regression even
	// though it returns the "right" shape.
	code, _ = getJSON(t, e, "/trace/abc123")
	if code != http.StatusNotFound {
		t.Errorf("GET /trace/abc123 in correlation mode = %d, want 404 from the empty local correlator", code)
	}
	if n := atomic.LoadInt32(tempoHits); n != 0 {
		t.Errorf("correlation mode queried Tempo %d times; it must answer from the local correlator", n)
	}
}
