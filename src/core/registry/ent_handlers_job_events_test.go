package registry

// HTTP-level coverage for the JobEvent injection substrate (issue #1032):
//
//   - POST /jobs/{job_id}/events        (PostJobEvent)
//   - GET  /jobs/{job_id}/events        (ListJobEvents — incl. long-poll)
//   - synthetic `cancelled` event posted by CancelJob handler
//
// Reuses newJobsEndpointTestEnvWithService from
// ent_handlers_jobs_extended_test.go: same in-memory Ent + Gin router
// wiring, but also returns the live EntService for direct seeding.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

// ---------- PostJobEvent ----------

func TestPostJobEvent_Success(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-1", "render", &owner)

	body, _ := json.Marshal(generated.JobEventPostRequest{
		Type:    "extend_deadline",
		Payload: map[string]interface{}{"by_seconds": float64(60)},
	})
	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var posted generated.JobEventPostResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&posted))
	assert.Equal(t, j.ID, posted.JobId)
	assert.Equal(t, int64(1), posted.Seq, "first event for a job lands on seq=1")
	assert.Greater(t, posted.CreatedAt, 0)

	// Round-trip through GET to confirm the row landed and round-trips
	// the payload intact.
	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events")
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)
	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	require.Len(t, listed.Events, 1)
	assert.Equal(t, int64(1), listed.Events[0].Seq)
	assert.Equal(t, "extend_deadline", listed.Events[0].Type)
	require.NotNil(t, listed.Events[0].Payload)
	payloadMap, ok := listed.Events[0].Payload.(map[string]interface{})
	require.True(t, ok, "expected payload to round-trip as a JSON object map")
	assert.Equal(t, float64(60), payloadMap["by_seconds"])
	assert.Equal(t, int64(1), listed.NextAfter)
}

func TestPostJobEvent_404OnMissingJob(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	body, _ := json.Marshal(generated.JobEventPostRequest{Type: "ping"})
	resp, err := http.Post(srv.URL+"/jobs/does-not-exist/events", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestPostJobEvent_409OnTerminalJob(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-done-evt", "render", &owner)
	// Drive the row into terminal=completed directly.
	_, err := service.entDB.Job.UpdateOneID(j.ID).
		SetStatus(job.StatusCompleted).
		Save(context.Background())
	require.NoError(t, err)

	body, _ := json.Marshal(generated.JobEventPostRequest{Type: "extend_deadline"})
	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusConflict, resp.StatusCode)
}

func TestPostJobEvent_400OnMissingType(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-bad", "render", &owner)

	resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", strings.NewReader(`{}`))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
}

func TestPostJobEvent_AssignsMonotonicSeq(t *testing.T) {
	// Three goroutines fire concurrent posts at the same job. The
	// service layer relies on the (job_id, seq) UNIQUE index + small
	// retry loop to land each event on a distinct sequential seq —
	// no gaps, no collisions, exactly 1..N.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-mono", "render", &owner)

	const N = 3
	var wg sync.WaitGroup
	seqs := make([]int64, N)
	errs := make([]error, N)

	// Barrier: all goroutines block on `ready` until we close it, so
	// they fire their HTTP posts as simultaneously as the runtime
	// allows. Without the barrier the first goroutine usually runs to
	// completion before its siblings have even been scheduled, which
	// makes the concurrent-retry path effectively untested.
	ready := make(chan struct{})

	for i := 0; i < N; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			<-ready
			body, _ := json.Marshal(generated.JobEventPostRequest{
				Type:    fmt.Sprintf("event-%d", idx),
				Payload: map[string]interface{}{"i": float64(idx)},
			})
			resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
			if err != nil {
				errs[idx] = err
				return
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				errs[idx] = fmt.Errorf("post %d: status %d", idx, resp.StatusCode)
				return
			}
			var p generated.JobEventPostResponse
			if err := json.NewDecoder(resp.Body).Decode(&p); err != nil {
				errs[idx] = err
				return
			}
			seqs[idx] = p.Seq
		}(i)
	}
	// Fire all goroutines simultaneously now that they're scheduled.
	close(ready)
	wg.Wait()

	for i, err := range errs {
		require.NoError(t, err, "post %d", i)
	}

	// Collect into a set: should be exactly {1, 2, 3} — sequential and
	// no duplicates. (Order within the set is non-deterministic across
	// the goroutines, which is fine.)
	seen := make(map[int64]bool)
	for _, s := range seqs {
		assert.GreaterOrEqual(t, s, int64(1))
		assert.LessOrEqual(t, s, int64(N))
		seen[s] = true
	}
	assert.Len(t, seen, N, "expected %d distinct seqs across concurrent posters, got %v", N, seqs)
}

// ---------- ListJobEvents ----------

func TestListJobEvents_FilterByType(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-filter", "render", &owner)

	for _, tp := range []string{"A", "B", "C"} {
		body, _ := json.Marshal(generated.JobEventPostRequest{Type: tp})
		resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
		require.NoError(t, err)
		resp.Body.Close()
		require.Equal(t, http.StatusOK, resp.StatusCode)
	}

	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events?types=A,B")
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)
	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	require.Len(t, listed.Events, 2)
	types := []string{listed.Events[0].Type, listed.Events[1].Type}
	assert.ElementsMatch(t, []string{"A", "B"}, types)
}

func TestListJobEvents_AfterSeq(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-after", "render", &owner)

	for i := 0; i < 5; i++ {
		body, _ := json.Marshal(generated.JobEventPostRequest{Type: fmt.Sprintf("e%d", i)})
		resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
		require.NoError(t, err)
		resp.Body.Close()
		require.Equal(t, http.StatusOK, resp.StatusCode)
	}

	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events?after=2")
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)
	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	require.Len(t, listed.Events, 3, "expected events 3,4,5")
	assert.Equal(t, int64(3), listed.Events[0].Seq)
	assert.Equal(t, int64(4), listed.Events[1].Seq)
	assert.Equal(t, int64(5), listed.Events[2].Seq)
	assert.Equal(t, int64(5), listed.NextAfter)
}

func TestListJobEvents_404OnMissingJob(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	resp, err := http.Get(srv.URL + "/jobs/missing-id/events")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestListJobEvents_LongPollTimeout(t *testing.T) {
	// wait=1 on an empty event log should return within ~1s with an
	// empty events array and next_after echoing the caller's after.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-poll-empty", "render", &owner)

	start := time.Now()
	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events?wait=1")
	elapsed := time.Since(start)
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)

	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	assert.Empty(t, listed.Events)
	assert.Equal(t, int64(0), listed.NextAfter)
	// Should have waited approximately the full second (allow for the
	// 100ms polling cadence — return any time between 0.9s and 2s).
	assert.GreaterOrEqual(t, elapsed, 900*time.Millisecond,
		"wait=1 should hold the connection ~1s")
	assert.LessOrEqual(t, elapsed, 2*time.Second,
		"wait=1 should not block far beyond its budget")
}

func TestListJobEvents_LongPollWakesOnPost(t *testing.T) {
	// Start a long-poll (wait=5s); after 200ms a sibling goroutine posts
	// an event. The poll should return within ~300ms — well below the
	// 5s budget — proving the inner-loop wake-up actually fires.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	owner := "producer-a"
	j := seedJob(t, service, "job-evt-poll-wake", "render", &owner)

	go func() {
		time.Sleep(200 * time.Millisecond)
		body, _ := json.Marshal(generated.JobEventPostRequest{Type: "tick"})
		resp, err := http.Post(srv.URL+"/jobs/"+j.ID+"/events", "application/json", bytes.NewReader(body))
		if err == nil {
			resp.Body.Close()
		}
	}()

	start := time.Now()
	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events?wait=5")
	elapsed := time.Since(start)
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)

	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	require.Len(t, listed.Events, 1)
	assert.Equal(t, "tick", listed.Events[0].Type)
	// Should wake within a few poll cycles of the sibling's 200ms timer.
	// Generous upper bound to keep this stable on loaded CI runners.
	assert.LessOrEqual(t, elapsed, 1500*time.Millisecond,
		"long-poll should wake within ~1.5s of the post landing")
}

// ---------- CancelJob synthetic event ----------

func TestCancelJob_PostsSyntheticCancelEvent(t *testing.T) {
	// Cancelling a working job should leave a `{type: "cancelled"}` event
	// in its log — that's the signal task=True handlers parked on
	// recv_event use to unwind. The reason posted to the cancel
	// endpoint should round-trip through the event payload.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	j := seedJob(t, service, "job-evt-cancel", "render", nil)

	body, _ := json.Marshal(generated.CancelJobRequest{Reason: ptrString("user requested")})
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/jobs/"+j.ID+"/cancel", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	// List events: the synthetic cancel event should be the only row.
	getResp, err := http.Get(srv.URL + "/jobs/" + j.ID + "/events")
	require.NoError(t, err)
	defer getResp.Body.Close()
	require.Equal(t, http.StatusOK, getResp.StatusCode)

	var listed generated.JobEventListResponse
	require.NoError(t, json.NewDecoder(getResp.Body).Decode(&listed))
	require.Len(t, listed.Events, 1, "expected one synthetic cancel event")
	ev := listed.Events[0]
	assert.Equal(t, "cancelled", ev.Type)
	require.NotNil(t, ev.Payload)
	payloadMap, ok := ev.Payload.(map[string]interface{})
	require.True(t, ok, "expected synthetic cancel payload to be a JSON object map")
	assert.Equal(t, "user requested", payloadMap["reason"])
}

// ---------- Sweep GC ----------

func TestSweep_DeletesEventsForTerminalJobAfterGrace(t *testing.T) {
	now := time.Date(2026, 5, 17, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, service, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()
	ctx := context.Background()

	// Seed a terminal job whose last_heartbeat_at is 2 hours back —
	// older than the 1h retention window, so the sweep should GC its
	// events.
	owner := "owner-1"
	j := seedJobRow(t, client, "job-gc-1", "render", &owner, job.StatusCompleted, 1, 1, now.Add(-3*time.Hour))
	_, err := client.Job.UpdateOneID(j.ID).
		SetLastHeartbeatAt(now.Add(-2 * time.Hour)).
		Save(ctx)
	require.NoError(t, err)

	// Two events on the row — both should disappear.
	for i := 0; i < 2; i++ {
		_, _, perr := service.PostJobEvent(ctx, j.ID, fmt.Sprintf("e%d", i), nil, nil, "", true)
		require.NoError(t, perr)
	}

	res, err := sweep.runOnce(ctx)
	require.NoError(t, err)
	assert.Equal(t, 2, res.jobEventsPurged, "expected 2 events purged for stale terminal job")

	remaining, err := service.ListJobEvents(ctx, j.ID, 0, nil, 0, 100)
	require.NoError(t, err)
	assert.Empty(t, remaining)
}

func TestSweep_PreservesEventsForActiveJob(t *testing.T) {
	now := time.Date(2026, 5, 17, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, service, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()
	ctx := context.Background()

	// Working (non-terminal) job — events must be preserved regardless
	// of how old the row is, since a tailer might still be parked on
	// recv_event waiting for them.
	owner := "owner-active"
	j := seedJobRow(t, client, "job-active", "render", &owner, job.StatusWorking, 1, 3, now.Add(-5*time.Hour))

	for i := 0; i < 3; i++ {
		_, _, perr := service.PostJobEvent(ctx, j.ID, fmt.Sprintf("e%d", i), nil, nil, "", false)
		require.NoError(t, perr)
	}

	res, err := sweep.runOnce(ctx)
	require.NoError(t, err)
	assert.Equal(t, 0, res.jobEventsPurged, "events for non-terminal jobs must be preserved")

	remaining, err := service.ListJobEvents(ctx, j.ID, 0, nil, 0, 100)
	require.NoError(t, err)
	assert.Len(t, remaining, 3)
}

// Compile-time reference so go vet won't complain about unused imports if
// the test file is trimmed in the future.
var _ = strings.Split
