package cli

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// captureStdout temporarily redirects os.Stdout and returns whatever was
// written to it during the callback. Used to assert on the audit command's
// rendered output.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	orig := os.Stdout
	r, w, err := os.Pipe()
	require.NoError(t, err)
	os.Stdout = w

	done := make(chan string)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.String()
	}()

	fn()
	w.Close()
	os.Stdout = orig
	return <-done
}

// makeFlippedEvent builds an AuditEvent whose embedded trace describes a
// 4-candidate decision that flipped from prior_chosen → new winner.
func makeFlippedEvent() AuditEvent {
	data := map[string]interface{}{
		"consumer":  "consumer-1",
		"dep_index": 0,
		"spec": map[string]interface{}{
			"capability":         "employee",
			"tags":               []interface{}{"api"},
			"version_constraint": ">=2.0",
			"schema_mode":        "none",
		},
		"stages": []interface{}{
			map[string]interface{}{
				"stage": "capability_match",
				"kept":  []interface{}{"hr-v2", "legacy-emp", "test-emp"},
			},
			map[string]interface{}{
				"stage": "tags",
				"kept":  []interface{}{"hr-v2", "legacy-emp"},
				"evicted": []interface{}{
					map[string]interface{}{
						"id":     "test-emp",
						"reason": "MissingTag",
						"details": map[string]interface{}{
							"missing": []interface{}{"api"},
						},
					},
				},
			},
			map[string]interface{}{"stage": "version", "kept": []interface{}{"hr-v2", "legacy-emp"}},
			map[string]interface{}{"stage": "schema", "kept": []interface{}{"hr-v2", "legacy-emp"}},
			map[string]interface{}{"stage": "health", "kept": []interface{}{"hr-v2", "legacy-emp"}},
			map[string]interface{}{
				"stage":  "tiebreaker",
				"kept":   []interface{}{"hr-v2", "legacy-emp"},
				"chosen": "hr-v2",
				"reason": "HighestScoreFirst",
			},
		},
		"chosen": map[string]interface{}{
			"agent_id":      "hr-v2",
			"endpoint":      "http://hr-v2:8080",
			"function_name": "do_thing",
		},
		"prior_chosen": "legacy-emp",
	}
	return AuditEvent{
		EventType:    "dependency_resolved",
		AgentID:      "consumer-1",
		FunctionName: "do_thing",
		Timestamp:    time.Date(2026, 4, 29, 19, 42, 11, 0, time.UTC),
		Data:         data,
	}
}

// TestAudit_PrintTable_FlipShowsChange asserts the tabular formatter renders
// the chosen producer, the candidate funnel, and the (was X) flip indicator.
func TestAudit_PrintTable_FlipShowsChange(t *testing.T) {
	out := captureStdout(t, func() {
		printAuditTable("consumer-1", []AuditEvent{makeFlippedEvent()})
	})

	assert.Contains(t, out, "consumer-1")
	assert.Contains(t, out, "TIMESTAMP")
	assert.Contains(t, out, "DEP")
	assert.Contains(t, out, "CHOSEN")
	assert.Contains(t, out, "CANDIDATES")
	assert.Contains(t, out, "CHANGE")

	// One row with chosen=hr-v2, candidates 3 → 2, and (was legacy-emp).
	assert.Contains(t, out, "hr-v2")
	assert.Contains(t, out, "3 → 2")
	assert.Contains(t, out, "(was legacy-emp)")
}

// TestAudit_PrintTree_RendersStagesAndEviction asserts the explain mode
// renders each stage, the eviction reason, and the chosen producer.
func TestAudit_PrintTree_RendersStagesAndEviction(t *testing.T) {
	out := captureStdout(t, func() {
		printAuditTree("consumer-1", []AuditEvent{makeFlippedEvent()})
	})

	// Per-event header line.
	assert.Contains(t, out, "dep[0]")
	assert.Contains(t, out, "capability=employee")

	// Stage names appear.
	for _, stage := range []string{"capability_match", "tags", "version", "schema", "health", "tiebreaker"} {
		assert.Contains(t, out, stage, "expected stage %s in tree output", stage)
	}

	// Eviction reason rendered with details.
	assert.Contains(t, out, "test-emp")
	assert.Contains(t, out, "MissingTag")
	assert.Contains(t, out, "missing=[api]")

	// Chosen producer.
	assert.Contains(t, out, "chosen: hr-v2")
	assert.Contains(t, out, "endpoint=http://hr-v2:8080")

	// Flip indicator.
	assert.Contains(t, out, "prior_chosen: legacy-emp")
	assert.Contains(t, out, "chosen flipped")
}

// TestAudit_PrintTree_Unresolved asserts unresolved events show "no resolution".
func TestAudit_PrintTree_Unresolved(t *testing.T) {
	data := map[string]interface{}{
		"consumer":  "consumer-1",
		"dep_index": 0,
		"spec": map[string]interface{}{
			"capability":  "ping",
			"tags":        []interface{}{"required"},
			"schema_mode": "none",
		},
		"stages": []interface{}{
			map[string]interface{}{
				"stage": "capability_match",
				"kept":  []interface{}{"wrong-1", "wrong-2"},
			},
			map[string]interface{}{
				"stage": "tags",
				"kept":  []interface{}{},
				"evicted": []interface{}{
					map[string]interface{}{"id": "wrong-1", "reason": "MissingTag"},
					map[string]interface{}{"id": "wrong-2", "reason": "MissingTag"},
				},
			},
		},
	}
	ev := AuditEvent{
		EventType: "dependency_unresolved",
		AgentID:   "consumer-1",
		Timestamp: time.Now().UTC(),
		Data:      data,
	}

	out := captureStdout(t, func() {
		printAuditTree("consumer-1", []AuditEvent{ev})
	})

	assert.Contains(t, out, "no resolution")
	assert.Contains(t, out, "MissingTag")
	assert.Contains(t, out, "wrong-1")
}

// TestAudit_FetchEvents_PassesQueryParams confirms the HTTP client wires
// agent_id, function_name, and limit through to the registry endpoint.
func TestAudit_FetchEvents_PassesQueryParams(t *testing.T) {
	gotQuery := ""
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotQuery = r.URL.RawQuery
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(AuditEventsResponse{
			Events: []AuditEvent{makeFlippedEvent()},
			Count:  1,
		})
	}))
	defer srv.Close()

	events, err := fetchAuditEvents(srv.Client(), srv.URL, "consumer-1", "do_thing", 50)
	require.NoError(t, err)
	require.Len(t, events, 1)
	assert.Equal(t, "consumer-1", events[0].AgentID)

	// All three filters should have ridden the request.
	assert.Contains(t, gotQuery, "agent_id=consumer-1")
	assert.Contains(t, gotQuery, "function_name=do_thing")
	assert.Contains(t, gotQuery, "limit=50")
}

// TestAudit_ExtractDepIndex covers the JSON-decoded number tolerance.
func TestAudit_ExtractDepIndex(t *testing.T) {
	cases := []struct {
		name string
		data map[string]interface{}
		want int
		ok   bool
	}{
		{"float64", map[string]interface{}{"dep_index": float64(2)}, 2, true},
		{"int", map[string]interface{}{"dep_index": int(3)}, 3, true},
		{"int64", map[string]interface{}{"dep_index": int64(4)}, 4, true},
		{"missing", map[string]interface{}{}, 0, false},
		{"nil_data", nil, 0, false},
		{"string_unsupported", map[string]interface{}{"dep_index": "5"}, 0, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := extractDepIndex(tc.data)
			assert.Equal(t, tc.ok, ok)
			if tc.ok {
				assert.Equal(t, tc.want, got)
			}
		})
	}
}

// TestAudit_TruncateBoundaries sanity-checks the small string helper used by
// the table formatter.
func TestAudit_TruncateBoundaries(t *testing.T) {
	assert.Equal(t, "abc", truncate("abc", 5))
	assert.Equal(t, "abcde", truncate("abcde", 5))
	got := truncate("abcdefghij", 5)
	assert.True(t, strings.HasSuffix(got, "…"))
	assert.Equal(t, 5, len([]rune(got)))
}
