package registry

// HTTP-level coverage for the three Phase 1 follow-up handlers:
//
//   - POST /jobs/batch  (SubmitJobBatch)
//   - POST /jobs/claim  (ClaimJobs)
//   - POST /jobs/{id}/cancel  (CancelJob)
//
// We share the in-memory test env from newAuditTestEnv via an extended
// helper that also returns the live EntService so individual tests can
// seed/inspect job rows directly.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

// newJobsEndpointTestEnvWithService is the extended sibling of
// newJobsEndpointTestEnv: same wiring but also returns the EntService so
// tests can seed Job rows directly without going through HTTP.
func newJobsEndpointTestEnvWithService(t *testing.T) (*httptest.Server, *EntService, func()) {
	t.Helper()
	_, service, cleanup := newAuditTestEnv(t)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	handlers := NewEntBusinessLogicHandlers(service)
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)

	return srv, service, func() {
		srv.Close()
		cleanup()
	}
}

func seedJob(t *testing.T, service *EntService, id, capability string, owner *string, opts ...func(*CreateJobInput)) *ent.Job {
	t.Helper()
	in := &CreateJobInput{
		ID:               id,
		Capability:       capability,
		SubmittedBy:      "test-submitter",
		SubmittedPayload: map[string]interface{}{"k": "v"},
		OwnerInstanceID:  owner,
		MaxRetries:       3,
	}
	for _, opt := range opts {
		opt(in)
	}
	created, err := service.CreateJob(context.Background(), in)
	require.NoError(t, err, "seed job %s", id)
	return created
}

// seedJobAtTime is like seedJob but pins submitted_at to a specific
// timestamp. submitted_at is schema-Immutable so we have to set it on
// Create rather than via a follow-up Update — used by the FIFO ordering
// test to deterministically place one row before another.
func seedJobAtTime(t *testing.T, service *EntService, id, capability string, owner *string, submittedAt time.Time, opts ...func(*CreateJobInput)) *ent.Job {
	t.Helper()
	builder := service.entDB.Job.Create().
		SetID(id).
		SetCapability(capability).
		SetSubmittedPayload(map[string]interface{}{"k": "v"}).
		SetStatus(job.StatusWorking).
		SetAttemptCount(0).
		SetMaxRetries(3).
		SetSubmittedAt(submittedAt).
		SetSubmittedBy("test-submitter")
	if owner != nil && *owner != "" {
		builder = builder.SetOwnerInstanceID(*owner)
	}
	in := &CreateJobInput{MaxRetries: 3}
	for _, opt := range opts {
		opt(in)
	}
	if in.MaxRetries != 3 {
		builder = builder.SetMaxRetries(in.MaxRetries)
	}
	if in.MaxDuration != nil {
		builder = builder.SetMaxDuration(*in.MaxDuration)
	}
	created, err := builder.Save(context.Background())
	require.NoError(t, err, "seed job %s", id)
	return created
}

// withMaxRetries customizes a seedJob input.
func withMaxRetries(n int) func(*CreateJobInput) {
	return func(in *CreateJobInput) { in.MaxRetries = n }
}

// withMaxDuration customizes a seedJob input.
func withMaxDuration(secs int) func(*CreateJobInput) {
	return func(in *CreateJobInput) { in.MaxDuration = &secs }
}

// ---------- SubmitJobBatch ----------

func TestSubmitJobBatch_Happy_MixedDeltas(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	jobA := seedJob(t, service, "job-a", "render", &owner)
	jobB := seedJob(t, service, "job-b", "render", &owner)

	progress := float32(0.42)
	msg := "halfway"
	completed := generated.JobStatus("completed")
	resultPayload := map[string]interface{}{"itinerary": "ok"}

	body, _ := json.Marshal(generated.JobBatchRequest{
		InstanceId: owner,
		Deltas: []generated.JobDelta{
			{Id: jobA.ID, Progress: &progress, ProgressMessage: &msg},
			{Id: jobB.ID, Status: &completed, Result: &resultPayload},
		},
	})
	resp, err := http.Post(srv.URL+"/jobs/batch", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var br generated.JobBatchResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&br))
	assert.Equal(t, 2, br.Accepted)
	assert.Empty(t, br.Rejected)

	// Re-fetch and verify the updates landed (including last_heartbeat_at).
	a, err := service.GetJob(context.Background(), jobA.ID)
	require.NoError(t, err)
	require.NotNil(t, a.Progress)
	assert.InDelta(t, 0.42, *a.Progress, 0.0001)
	require.NotNil(t, a.ProgressMessage)
	assert.Equal(t, "halfway", *a.ProgressMessage)
	assert.NotNil(t, a.LastHeartbeatAt, "any accepted delta should refresh last_heartbeat_at")
	assert.Equal(t, job.StatusWorking, a.Status)

	b, err := service.GetJob(context.Background(), jobB.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCompleted, b.Status)
	assert.Equal(t, "ok", b.Result["itinerary"])
}

func TestSubmitJobBatch_RejectsNotOwner(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	other := "producer-b"
	j := seedJob(t, service, "job-x", "render", &owner)

	progress := float32(0.1)
	body, _ := json.Marshal(generated.JobBatchRequest{
		InstanceId: other, // wrong owner
		Deltas:     []generated.JobDelta{{Id: j.ID, Progress: &progress}},
	})
	resp, err := http.Post(srv.URL+"/jobs/batch", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var br generated.JobBatchResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&br))
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, j.ID, br.Rejected[0].Id)
	assert.Equal(t, JobDeltaRejectionNotOwner, br.Rejected[0].Reason)
}

func TestSubmitJobBatch_RejectsAlreadyTerminal(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-done", "render", &owner)

	// Drive the row into terminal=completed via the service directly.
	_, err := service.entDB.Job.UpdateOneID(j.ID).
		SetStatus(job.StatusCompleted).
		Save(context.Background())
	require.NoError(t, err)

	progress := float32(0.9)
	body, _ := json.Marshal(generated.JobBatchRequest{
		InstanceId: owner,
		Deltas:     []generated.JobDelta{{Id: j.ID, Progress: &progress}},
	})
	resp, err := http.Post(srv.URL+"/jobs/batch", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var br generated.JobBatchResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&br))
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionAlreadyTerminal, br.Rejected[0].Reason)
}

func TestSubmitJobBatch_ValidationErrors(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	cases := []struct {
		name string
		body string
	}{
		{"missing instance_id", `{"deltas":[{"id":"x"}]}`},
		{"empty deltas", `{"instance_id":"a","deltas":[]}`},
		{"delta missing id", `{"instance_id":"a","deltas":[{}]}`},
		{"malformed json", `{not json`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resp, err := http.Post(srv.URL+"/jobs/batch", "application/json", strings.NewReader(tc.body))
			require.NoError(t, err)
			defer resp.Body.Close()
			assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
		})
	}
}

// ---------- ClaimJobs ----------

func TestClaimJobs_Happy_ClaimsOldestPending(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// Seed two pending (owner=NULL) jobs in the same capability with a
	// known submitted_at gap so FIFO is deterministic in tests.
	now := time.Now().UTC()
	older := seedJobAtTime(t, service, "job-older", "render", nil, now.Add(-30*time.Second), withMaxRetries(2), withMaxDuration(120))
	_ = seedJobAtTime(t, service, "job-newer", "render", nil, now, withMaxRetries(2))

	body, _ := json.Marshal(generated.ClaimJobsRequest{
		Capability: "render",
		InstanceId: "claimer-1",
	})
	resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.ClaimJobsResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	require.Len(t, cr.Claimed, 1, "single-claim per round-trip")
	assert.Equal(t, older.ID, cr.Claimed[0].Id, "FIFO: oldest claimed first")
	assert.Equal(t, 1, cr.Claimed[0].AttemptCount, "attempt_count incremented from 0 to 1")
	require.NotNil(t, cr.Claimed[0].LeaseExpiresAt)
	require.NotNil(t, cr.Claimed[0].MaxDuration)
	assert.Equal(t, 120, *cr.Claimed[0].MaxDuration)

	// Re-fetch and verify owner pinned + lease set.
	updated, err := service.GetJob(context.Background(), older.ID)
	require.NoError(t, err)
	require.NotNil(t, updated.OwnerInstanceID)
	assert.Equal(t, "claimer-1", *updated.OwnerInstanceID)
	assert.NotNil(t, updated.LeaseExpiresAt)
	assert.NotNil(t, updated.LastHeartbeatAt)
}

func TestClaimJobs_Empty_NoPending(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	body, _ := json.Marshal(generated.ClaimJobsRequest{
		Capability: "render",
		InstanceId: "claimer-1",
	})
	resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode, "no work is not an error")

	var cr generated.ClaimJobsResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	assert.Empty(t, cr.Claimed)
}

func TestClaimJobs_RetryBudgetExhausted(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// Pending job whose attempt_count has exceeded max_retries → must NOT
	// claim. Under the Sidekiq/Celery semantic (max_retries = retries on
	// top of the initial attempt), a job is still claimable while
	// attempt_count <= max_retries; exhausted iff strictly greater.
	// With only this one candidate available the response is empty.
	j := seedJob(t, service, "job-exhausted", "render", nil, withMaxRetries(2))
	_, err := service.entDB.Job.UpdateOneID(j.ID).
		SetAttemptCount(3). // > MaxRetries (2 retries already used after initial attempt)
		Save(context.Background())
	require.NoError(t, err)

	body, _ := json.Marshal(generated.ClaimJobsRequest{
		Capability: "render",
		InstanceId: "claimer-1",
	})
	resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.ClaimJobsResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	assert.Empty(t, cr.Claimed, "exhausted retry budget → no claim")
}

func TestClaimJobs_ConcurrentRace_ExactlyOneWinner(t *testing.T) {
	// Race coverage: two parallel /jobs/claim requests against the SAME
	// single pending job must produce exactly one winner. SQLite's
	// single-writer + our guarded UPDATE (WHERE owner IS NULL) make this
	// safe; the test verifies it stays that way.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	j := seedJob(t, service, "job-race", "render", nil)

	const N = 4
	var (
		wg       sync.WaitGroup
		claimed  int32
		empty    int32
		mistakes int32
	)
	wg.Add(N)
	for i := 0; i < N; i++ {
		i := i
		go func() {
			defer wg.Done()
			body, _ := json.Marshal(generated.ClaimJobsRequest{
				Capability: "render",
				InstanceId: fmt.Sprintf("claimer-%d", i),
			})
			resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
			if err != nil {
				atomic.AddInt32(&mistakes, 1)
				return
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				atomic.AddInt32(&mistakes, 1)
				return
			}
			var cr generated.ClaimJobsResponse
			if err := json.NewDecoder(resp.Body).Decode(&cr); err != nil {
				atomic.AddInt32(&mistakes, 1)
				return
			}
			switch len(cr.Claimed) {
			case 0:
				atomic.AddInt32(&empty, 1)
			case 1:
				if cr.Claimed[0].Id == j.ID {
					atomic.AddInt32(&claimed, 1)
				}
			default:
				atomic.AddInt32(&mistakes, 1)
			}
		}()
	}
	wg.Wait()

	assert.Zero(t, atomic.LoadInt32(&mistakes), "no claimer should error or get >1 row")
	assert.Equal(t, int32(1), atomic.LoadInt32(&claimed), "exactly one winner")
	assert.Equal(t, int32(N-1), atomic.LoadInt32(&empty), "the rest see no work")
}

func TestClaimJobs_ValidationErrors(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	cases := []struct {
		name string
		body string
	}{
		{"missing capability", `{"instance_id":"a"}`},
		{"missing instance_id", `{"capability":"x"}`},
		{"malformed json", `{not json`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", strings.NewReader(tc.body))
			require.NoError(t, err)
			defer resp.Body.Close()
			assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
		})
	}
}

// ---------- CancelJob ----------

func TestCancelJob_OrphanOwnerNull(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	j := seedJob(t, service, "job-orphan", "render", nil)

	body, _ := json.Marshal(generated.CancelJobRequest{Reason: ptrString("user requested")})
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/jobs/"+j.ID+"/cancel", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.CancelJobResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	assert.Equal(t, generated.JobStatus("cancelled"), cr.Status)
	assert.Nil(t, cr.ForwardedToInstanceId, "no owner means no forward")

	// Persisted row reflects the cancel.
	updated, err := service.GetJob(context.Background(), j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCancelled, updated.Status)
	require.NotNil(t, updated.Error)
	assert.Contains(t, *updated.Error, "user requested")
}

func TestCancelJob_OwnedForwardsToOwner(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// Stand up a fake owner agent that records the cancel callback.
	// ``hits`` stays atomic so the polling loop below can read it without
	// holding the mutex; ``gotURL``/``gotBody`` are written in the handler
	// goroutine and read by the main test goroutine after the poll, so
	// they need explicit synchronization to keep ``go test -race`` happy.
	var (
		mu      sync.Mutex
		gotURL  string
		gotBody []byte
		hits    int32
	)
	owner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		gotURL = r.URL.Path
		gotBody = body
		mu.Unlock()
		atomic.AddInt32(&hits, 1)
		w.WriteHeader(http.StatusOK)
	}))
	defer owner.Close()

	// Parse host/port back out so we can register the agent in the registry.
	hostPort := strings.TrimPrefix(owner.URL, "http://")
	host, port := splitHostPort(t, hostPort)
	ownerID := "owner-replica-1"
	registerOwnerAgent(t, service, ownerID, host, port)

	ownerInstance := ownerID
	j := seedJob(t, service, "job-owned", "render", &ownerInstance)

	body, _ := json.Marshal(generated.CancelJobRequest{Reason: ptrString("client cancel")})
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/jobs/"+j.ID+"/cancel", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Trace-ID", "trace-cancel-1")
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.CancelJobResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	assert.Equal(t, generated.JobStatus("cancelled"), cr.Status)
	require.NotNil(t, cr.ForwardedToInstanceId)
	assert.Equal(t, ownerID, *cr.ForwardedToInstanceId)

	// The forward to the owner runs in a goroutine so the cancel
	// response can return immediately. Poll briefly for the hit;
	// 2s is well under the 5s cancelForwardTimeout, so a flake here
	// would mean a real regression rather than test timing noise.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if atomic.LoadInt32(&hits) >= 1 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	// Owner saw the forward.
	assert.Equal(t, int32(1), atomic.LoadInt32(&hits), "owner should receive exactly one cancel forward")
	mu.Lock()
	gotURLCopy := gotURL
	gotBodyCopy := append([]byte(nil), gotBody...)
	mu.Unlock()
	assert.Equal(t, "/jobs/"+j.ID+"/cancel", gotURLCopy)
	assert.Contains(t, string(gotBodyCopy), "client cancel")
}

func TestCancelJob_NotFound(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	resp, err := http.Post(srv.URL+"/jobs/missing-id/cancel", "application/json", strings.NewReader(""))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestCancelJob_AlreadyTerminalReturns409(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-done", "render", &owner)
	_, err := service.entDB.Job.UpdateOneID(j.ID).
		SetStatus(job.StatusCompleted).
		Save(context.Background())
	require.NoError(t, err)

	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/cancel", "application/json", strings.NewReader(""))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusConflict, resp.StatusCode)
}

// TestCancelForward_ShutdownAbortsInFlight verifies the W3 re-review fix:
// the cancel-forward goroutine spawned by ``forwardCancelToOwner`` MUST
// be wired into the registry's graceful-shutdown context + WaitGroup so
// cancelling the shutdown context aborts the in-flight HTTP forward and
// the WaitGroup reflects that the goroutine has exited.
//
// Without the fix the goroutine used a detached ``context.Background()``
// and was effectively orphaned on shutdown — operators saw no log trace,
// the cancel didn't reach the owner, and the goroutine ran on past
// process stop until its 5s per-call timeout.
//
// The test pins the realistic mid-flight case: the owner agent is
// properly registered (so ``GetAgent`` succeeds), the goroutine reaches
// the ``client.Do`` call, and the owner's HTTP handler hangs until the
// REGISTRY-side request context is cancelled. Cancelling the shutdown
// context propagates through ``fwdCtx`` to the transport, which aborts
// the in-flight call; the goroutine then exits via the
// "abandoned: registry shutting down" path and ``shutdownWG`` drains
// well under ``cancelForwardTimeout`` (5s) — proving the cancellation
// actually short-circuited the wait rather than tripping the per-call
// timeout cap.
func TestCancelForward_ShutdownAbortsInFlight(t *testing.T) {
	_, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	// Owner side: hang on the inbound request context. ``httptest.Server``
	// wires the HTTP request's Context to the underlying TCP read so when
	// the registry-side transport cancels the request, this handler's
	// ``r.Context()`` gets Done() and we can return cleanly. Without that
	// linkage the goroutine would leak past the test, so we add a hard
	// stop channel to guarantee cleanup even if the shutdown wiring is
	// broken (which is what we're testing).
	hardStop := make(chan struct{})
	owner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-hardStop:
		}
	}))
	// IMPORTANT defer order: ``close(hardStop)`` MUST run BEFORE
	// ``owner.Close()`` (defers fire LIFO, so we register them in
	// owner-then-hardStop order). Without this, ``owner.Close()`` would
	// block waiting for the in-flight handler — and the handler would
	// never exit because we'd never close ``hardStop`` — and the test
	// would deadlock instead of cleanly tearing down on failure.
	defer owner.Close()
	defer close(hardStop)

	hostPort := strings.TrimPrefix(owner.URL, "http://")
	host, port := splitHostPort(t, hostPort)
	ownerID := "owner-shutdown-1"
	registerOwnerAgent(t, service, ownerID, host, port)

	ownerInstance := ownerID
	j := seedJob(t, service, "job-shutdown-1", "render", &ownerInstance)

	// Build handlers wired into a shutdown ctx + WG so the cancel
	// forward registers itself on the graceful-shutdown machinery.
	shutdownCtx, shutdownCancel := context.WithCancel(context.Background())
	defer shutdownCancel()
	shutdownWG := &sync.WaitGroup{}
	handlers := NewEntBusinessLogicHandlersWithShutdown(service, shutdownCtx, shutdownWG)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	generated.RegisterHandlers(router, handlers)
	srv := httptest.NewServer(router)
	defer srv.Close()

	body, _ := json.Marshal(generated.CancelJobRequest{Reason: ptrString("shutdown")})
	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/cancel", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	require.NoError(t, resp.Body.Close())
	require.Equal(t, http.StatusOK, resp.StatusCode, "cancel response should return immediately regardless of forward")

	// Give the forward goroutine a moment to start the HTTP call and
	// park in the transport. 200ms is plenty for an in-process loopback
	// to reach the owner's ``r.Context().Done()`` parking spot.
	time.Sleep(200 * time.Millisecond)

	// Cancel the shutdown context; the forward's transport should
	// observe the cancellation and the goroutine should exit well
	// before cancelForwardTimeout=5s.
	startWait := time.Now()
	shutdownCancel()

	drained := make(chan struct{})
	go func() {
		shutdownWG.Wait()
		close(drained)
	}()

	select {
	case <-drained:
		elapsed := time.Since(startWait)
		// The cancellation MUST short-circuit the wait — not silently
		// time out at the per-call cap. 3s leaves margin for slow CI
		// while still being way under the 5s cancelForwardTimeout that
		// would indicate the cancellation didn't propagate.
		assert.Less(t, elapsed, 3*time.Second, "WG drain took longer than expected; shutdown context did not short-circuit the forward")
	case <-time.After(4 * time.Second):
		t.Fatalf("shutdown WG did not drain within 4s; cancel-forward goroutine ignored shutdown context")
	}
}

// TestCancelForward_LegacyConstructorStillWorks pins the back-compat
// behaviour: callers using the zero-arg ``NewEntBusinessLogicHandlers``
// (tests, older callers without shutdown wiring) MUST still get a
// best-effort cancel forward. The internal WaitGroup is private and
// never waited on.
func TestCancelForward_LegacyConstructorStillWorks(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// Owner that records hits and returns 200.
	var hits int32
	owner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.WriteHeader(http.StatusOK)
	}))
	defer owner.Close()

	hostPort := strings.TrimPrefix(owner.URL, "http://")
	host, port := splitHostPort(t, hostPort)
	ownerID := "owner-legacy-1"
	registerOwnerAgent(t, service, ownerID, host, port)

	ownerInstance := ownerID
	j := seedJob(t, service, "job-legacy-1", "render", &ownerInstance)

	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/cancel", "application/json", strings.NewReader(""))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	// Forward should still land best-effort.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if atomic.LoadInt32(&hits) >= 1 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	assert.Equal(t, int32(1), atomic.LoadInt32(&hits), "legacy constructor should still forward best-effort")
}

// ---------- helpers ----------

func ptrString(s string) *string { return &s }

func splitHostPort(t *testing.T, hp string) (string, int) {
	t.Helper()
	idx := strings.LastIndex(hp, ":")
	require.Greater(t, idx, 0, "bad host:port %q", hp)
	host := hp[:idx]
	var port int
	_, err := fmt.Sscanf(hp[idx+1:], "%d", &port)
	require.NoError(t, err)
	return host, port
}

// registerOwnerAgent inserts a minimal Agent row so GetAgent inside the
// cancel forwarder can look up the owner's HTTP endpoint.
func registerOwnerAgent(t *testing.T, service *EntService, id, host string, port int) {
	t.Helper()
	_, err := service.entDB.Agent.Create().
		SetID(id).
		SetName(id).
		SetHTTPHost(host).
		SetHTTPPort(port).
		Save(context.Background())
	require.NoError(t, err, "register owner agent")
}
