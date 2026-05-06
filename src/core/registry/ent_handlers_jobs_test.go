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
