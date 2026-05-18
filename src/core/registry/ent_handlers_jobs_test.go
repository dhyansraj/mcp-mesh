package registry

// Minimal HTTP-level coverage for POST /jobs and GET /jobs/{job_id}.
// Mirrors newAuditEndpointTestEnv from audit_endpoint_test.go: a real Gin
// router wired to the production EntBusinessLogicHandlers backed by an
// in-memory Ent client.

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry/generated"
)

func newJobsEndpointTestEnv(t *testing.T) (*httptest.Server, func()) {
	t.Helper()
	_, service, cleanup := newAuditTestEnv(t)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)

	return srv, func() {
		srv.Close()
		cleanup()
	}
}

func TestCreateJob_PushMode_Happy(t *testing.T) {
	srv, cleanup := newJobsEndpointTestEnv(t)
	defer cleanup()

	owner := "claude-provider-replica-2"
	body, _ := json.Marshal(generated.CreateJobRequest{
		Capability:       "plan_trip",
		SubmittedBy:      "orchestrate-replica-1",
		SubmittedPayload: map[string]interface{}{"user_id": "u-123"},
		OwnerInstanceId:  &owner,
	})

	resp, err := http.Post(srv.URL+"/jobs", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusCreated, resp.StatusCode)

	var created generated.CreateJobResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&created))
	assert.NotEmpty(t, created.Id, "server should mint a job id")
	assert.Equal(t, generated.JobStatus("working"), created.Status)
	require.NotNil(t, created.OwnerInstanceId)
	assert.Equal(t, owner, *created.OwnerInstanceId)

	// Round-trip: GET /jobs/{id} should return the same row.
	getResp, err := http.Get(srv.URL + "/jobs/" + created.Id)
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)

	var fetched generated.Job
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&fetched))
	assert.Equal(t, created.Id, fetched.Id)
	assert.Equal(t, "plan_trip", fetched.Capability)
	assert.Equal(t, generated.JobStatus("working"), fetched.Status)
	assert.Equal(t, 0, fetched.AttemptCount)
	assert.Equal(t, 1, fetched.MaxRetries)
	assert.Equal(t, "orchestrate-replica-1", fetched.SubmittedBy)
	require.NotNil(t, fetched.OwnerInstanceId)
	assert.Equal(t, owner, *fetched.OwnerInstanceId)
	assert.Greater(t, fetched.SubmittedAt, 0, "submitted_at should be a positive Unix epoch")
}

func TestCreateJob_PullMode_OwnerOmitted(t *testing.T) {
	srv, cleanup := newJobsEndpointTestEnv(t)
	defer cleanup()

	body, _ := json.Marshal(generated.CreateJobRequest{
		Capability:       "render_report",
		SubmittedBy:      "orchestrate-replica-1",
		SubmittedPayload: map[string]interface{}{"doc_id": "d-1"},
	})

	resp, err := http.Post(srv.URL+"/jobs", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusCreated, resp.StatusCode)

	var created generated.CreateJobResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&created))
	assert.Nil(t, created.OwnerInstanceId, "pull-mode submission should leave owner NULL")

	// Confirm the persisted row also has owner=NULL.
	getResp, err := http.Get(srv.URL + "/jobs/" + created.Id)
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)

	var fetched generated.Job
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&fetched))
	assert.Nil(t, fetched.OwnerInstanceId)
}

func TestCreateJob_ValidationErrors(t *testing.T) {
	srv, cleanup := newJobsEndpointTestEnv(t)
	defer cleanup()

	tests := []struct {
		name string
		body string
	}{
		{"missing capability", `{"submitted_by":"a","submitted_payload":{}}`},
		{"missing submitted_by", `{"capability":"x","submitted_payload":{}}`},
		{"missing submitted_payload", `{"capability":"x","submitted_by":"a"}`},
		{"malformed json", `{not json`},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			resp, err := http.Post(srv.URL+"/jobs", "application/json", strings.NewReader(tc.body))
			require.NoError(t, err)
			defer resp.Body.Close()
			assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
		})
	}
}

func TestGetJob_NotFound(t *testing.T) {
	srv, cleanup := newJobsEndpointTestEnv(t)
	defer cleanup()

	resp, err := http.Get(srv.URL + "/jobs/does-not-exist")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

// TestCancelEventGrace_EnvVar pins the parsing & clamping behaviour for
// MCP_MESH_CANCEL_EVENT_GRACE_MS. The exported helper `cancelEventGrace`
// is sync.Once-cached for the process lifetime; we exercise the parsing
// path directly so each subtest sees a fresh read.
func TestCancelEventGrace_EnvVar(t *testing.T) {
	tests := []struct {
		name string
		set  bool
		val  string
		want time.Duration
	}{
		{
			name: "unset returns default",
			set:  false,
			want: cancelEventGraceDefault,
		},
		{
			name: "explicit small value honoured",
			set:  true,
			val:  "150",
			want: 150 * time.Millisecond,
		},
		{
			name: "zero disables grace",
			set:  true,
			val:  "0",
			want: 0,
		},
		{
			name: "huge value clamped to cap",
			// 24h in ms = 86400000. Cap is 10000ms. An operator
			// who set this would otherwise block every cancel call
			// for 24h; the cap keeps things sane.
			set:  true,
			val:  "86400000",
			want: time.Duration(cancelEventGraceMaxMs) * time.Millisecond,
		},
		{
			name: "negative falls back to default",
			set:  true,
			val:  "-5",
			want: cancelEventGraceDefault,
		},
		{
			name: "malformed string falls back to default",
			set:  true,
			val:  "not-a-number",
			want: cancelEventGraceDefault,
		},
		{
			name: "exactly at cap is honoured (boundary)",
			set:  true,
			val:  "10000",
			want: time.Duration(cancelEventGraceMaxMs) * time.Millisecond,
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if tc.set {
				t.Setenv("MCP_MESH_CANCEL_EVENT_GRACE_MS", tc.val)
			} else {
				// t.Setenv with empty also works but the explicit
				// path makes the intent obvious in test output.
				t.Setenv("MCP_MESH_CANCEL_EVENT_GRACE_MS", "")
			}
			got := parseCancelEventGraceFromEnv()
			assert.Equal(t, tc.want, got, "MCP_MESH_CANCEL_EVENT_GRACE_MS=%q", tc.val)
		})
	}
}
