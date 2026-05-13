package registry

// HTTP-level coverage for GET /jobs (issue #973): generic, read-only
// jobs listing with keyset pagination. Mirrors the harness in
// ent_handlers_jobs_test.go (full Gin router + generated.RegisterHandlers
// + in-memory Ent client) but extends it so tests can seed rows directly
// through Ent — necessary because submitted_at otherwise defaults to
// time.Now() and we need deterministic timestamps for pagination tests.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

type listSeedRow struct {
	id          string
	capability  string
	status      string
	submittedAt time.Time
	submittedBy string
	owner       *string
}

// jobsListEnv ties one Ent client to one HTTP server so we can seed rows
// directly (controlling submitted_at) and observe them through the public
// /jobs endpoint.
type jobsListEnv struct {
	client  *ent.Client
	baseURL string
}

func newJobsListEnv(t *testing.T) (*jobsListEnv, func()) {
	t.Helper()
	client, service, dbCleanup := newAuditTestEnv(t)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)

	env := &jobsListEnv{client: client, baseURL: srv.URL}
	cleanup := func() {
		srv.Close()
		dbCleanup()
	}
	return env, cleanup
}

func (e *jobsListEnv) seed(t *testing.T, rows []listSeedRow) {
	t.Helper()
	ctx := context.Background()
	for _, r := range rows {
		builder := e.client.Job.Create().
			SetID(r.id).
			SetCapability(r.capability).
			SetSubmittedPayload(map[string]interface{}{"seeded": true}).
			SetStatus(job.Status(r.status)).
			SetAttemptCount(0).
			SetMaxRetries(1).
			SetSubmittedAt(r.submittedAt)
		if r.submittedBy != "" {
			builder = builder.SetSubmittedBy(r.submittedBy)
		}
		if r.owner != nil {
			builder = builder.SetOwnerInstanceID(*r.owner)
		}
		_, err := builder.Save(ctx)
		require.NoError(t, err, "seed job %s", r.id)
	}
}

func (e *jobsListEnv) get(t *testing.T, q url.Values) (int, *generated.JobsListResponse) {
	t.Helper()
	u := e.baseURL + "/jobs"
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	resp, err := http.Get(u)
	require.NoError(t, err)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return resp.StatusCode, nil
	}
	var out generated.JobsListResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&out))
	return resp.StatusCode, &out
}

// --- tests ---

func TestListJobs_EmptyDB(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	code, body := env.get(t, nil)
	require.Equal(t, http.StatusOK, code)
	assert.Empty(t, body.Jobs)
	assert.Nil(t, body.NextCursor)
}

func TestListJobs_InvalidLimit(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	for _, limit := range []string{"0", "201", "-1"} {
		t.Run("limit="+limit, func(t *testing.T) {
			code, _ := env.get(t, url.Values{"limit": []string{limit}})
			assert.Equal(t, http.StatusBadRequest, code)
		})
	}
}

func TestListJobs_InvalidStatus(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	// "running" was the pre-fix vocabulary; not a real status.
	code, _ := env.get(t, url.Values{"status": []string{"running"}})
	assert.Equal(t, http.StatusBadRequest, code)
}

func TestListJobs_InvalidCursor(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	code, _ := env.get(t, url.Values{"cursor": []string{"not-a-valid-base64-cursor!!!"}})
	assert.Equal(t, http.StatusBadRequest, code)
}

func TestListJobs_StatusFilterSingle(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	now := time.Now().UTC()
	env.seed(t, []listSeedRow{
		{id: "job-1", capability: "cap-a", status: "working", submittedAt: now.Add(-3 * time.Minute), submittedBy: "sub"},
		{id: "job-2", capability: "cap-a", status: "completed", submittedAt: now.Add(-2 * time.Minute), submittedBy: "sub"},
		{id: "job-3", capability: "cap-b", status: "failed", submittedAt: now.Add(-1 * time.Minute), submittedBy: "sub"},
	})

	code, body := env.get(t, url.Values{"status": []string{"completed"}})
	require.Equal(t, http.StatusOK, code)
	require.Len(t, body.Jobs, 1)
	assert.Equal(t, "job-2", body.Jobs[0].Id)
	assert.Equal(t, generated.JobStatus("completed"), body.Jobs[0].Status)
	assert.Nil(t, body.NextCursor)
}

func TestListJobs_StatusFilterMulti(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	now := time.Now().UTC()
	env.seed(t, []listSeedRow{
		{id: "job-1", capability: "cap-a", status: "working", submittedAt: now.Add(-3 * time.Minute), submittedBy: "sub"},
		{id: "job-2", capability: "cap-a", status: "completed", submittedAt: now.Add(-2 * time.Minute), submittedBy: "sub"},
		{id: "job-3", capability: "cap-b", status: "failed", submittedAt: now.Add(-1 * time.Minute), submittedBy: "sub"},
	})

	code, body := env.get(t, url.Values{"status": []string{"completed,failed"}})
	require.Equal(t, http.StatusOK, code)
	require.Len(t, body.Jobs, 2)
	// Descending submitted_at: job-3 first (most recent), then job-2.
	assert.Equal(t, "job-3", body.Jobs[0].Id)
	assert.Equal(t, "job-2", body.Jobs[1].Id)
}

func TestListJobs_OwnerFilter(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	ownerA := "replica-a"
	ownerB := "replica-b"
	now := time.Now().UTC()
	env.seed(t, []listSeedRow{
		{id: "job-1", capability: "cap", status: "working", submittedAt: now.Add(-3 * time.Minute), submittedBy: "sub", owner: &ownerA},
		{id: "job-2", capability: "cap", status: "working", submittedAt: now.Add(-2 * time.Minute), submittedBy: "sub", owner: &ownerB},
		{id: "job-3", capability: "cap", status: "working", submittedAt: now.Add(-1 * time.Minute), submittedBy: "sub"},
	})

	code, body := env.get(t, url.Values{"owner_instance_id": []string{ownerA}})
	require.Equal(t, http.StatusOK, code)
	require.Len(t, body.Jobs, 1)
	assert.Equal(t, "job-1", body.Jobs[0].Id)
}

func TestListJobs_CapabilityFilter(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	now := time.Now().UTC()
	env.seed(t, []listSeedRow{
		{id: "job-1", capability: "render", status: "working", submittedAt: now.Add(-3 * time.Minute), submittedBy: "sub"},
		{id: "job-2", capability: "plan", status: "working", submittedAt: now.Add(-2 * time.Minute), submittedBy: "sub"},
		{id: "job-3", capability: "render", status: "working", submittedAt: now.Add(-1 * time.Minute), submittedBy: "sub"},
	})

	code, body := env.get(t, url.Values{"capability": []string{"render"}})
	require.Equal(t, http.StatusOK, code)
	require.Len(t, body.Jobs, 2)
	assert.Equal(t, "job-3", body.Jobs[0].Id)
	assert.Equal(t, "job-1", body.Jobs[1].Id)
}

func TestListJobs_SubmittedSinceFilter(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	now := time.Now().UTC()
	env.seed(t, []listSeedRow{
		{id: "old", capability: "cap", status: "working", submittedAt: now.Add(-1 * time.Hour), submittedBy: "sub"},
		{id: "mid", capability: "cap", status: "working", submittedAt: now.Add(-10 * time.Minute), submittedBy: "sub"},
		{id: "new", capability: "cap", status: "working", submittedAt: now.Add(-1 * time.Minute), submittedBy: "sub"},
	})

	cutoff := now.Add(-30 * time.Minute).Unix()
	code, body := env.get(t, url.Values{"submitted_since": []string{fmt.Sprintf("%d", cutoff)}})
	require.Equal(t, http.StatusOK, code)
	require.Len(t, body.Jobs, 2)
	assert.Equal(t, "new", body.Jobs[0].Id)
	assert.Equal(t, "mid", body.Jobs[1].Id)
}

func TestListJobs_PaginationRoundTrip(t *testing.T) {
	env, cleanup := newJobsListEnv(t)
	defer cleanup()

	// 5 jobs at strictly-increasing submission times → descending page
	// order is job-5, job-4, job-3, job-2, job-1.
	now := time.Now().UTC()
	rows := make([]listSeedRow, 0, 5)
	for i := 1; i <= 5; i++ {
		rows = append(rows, listSeedRow{
			id:          fmt.Sprintf("job-%d", i),
			capability:  "cap",
			status:      "working",
			submittedAt: now.Add(time.Duration(i) * time.Second),
			submittedBy: "sub",
		})
	}
	env.seed(t, rows)

	collect := func(cursor string) *generated.JobsListResponse {
		q := url.Values{"limit": []string{"2"}}
		if cursor != "" {
			q.Set("cursor", cursor)
		}
		code, body := env.get(t, q)
		require.Equal(t, http.StatusOK, code)
		return body
	}

	page1 := collect("")
	require.Len(t, page1.Jobs, 2)
	assert.Equal(t, "job-5", page1.Jobs[0].Id)
	assert.Equal(t, "job-4", page1.Jobs[1].Id)
	require.NotNil(t, page1.NextCursor)

	page2 := collect(*page1.NextCursor)
	require.Len(t, page2.Jobs, 2)
	assert.Equal(t, "job-3", page2.Jobs[0].Id)
	assert.Equal(t, "job-2", page2.Jobs[1].Id)
	require.NotNil(t, page2.NextCursor)

	page3 := collect(*page2.NextCursor)
	require.Len(t, page3.Jobs, 1)
	assert.Equal(t, "job-1", page3.Jobs[0].Id)
	assert.Nil(t, page3.NextCursor, "final page should have null cursor")
}
