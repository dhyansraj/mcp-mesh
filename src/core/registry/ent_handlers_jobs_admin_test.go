package registry

// Coverage for the job-observability + admin surfaces added in issues
// #1264 (claim_epoch / owner / lease in GET /jobs/{id}), #1265 (admin
// force-reclaim POST /jobs/{id}/reclaim) and #1267 (registry drain mode).
//
// Reuses newJobsEndpointTestEnvWithService + seedJob from
// ent_handlers_jobs_extended_test.go.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

// newAdminDrainTestServer builds a minimal Server exposing just the
// /admin/drain routes (POST/DELETE/GET) so the drain admin wiring can be
// exercised end-to-end over HTTP.
func newAdminDrainTestServer(t *testing.T) (*httptest.Server, *EntService, func()) {
	t.Helper()
	_, service, cleanup := newAuditTestEnv(t)

	gin.SetMode(gin.TestMode)
	engine := gin.New()
	s := &Server{service: service, logger: service.logger}
	engine.POST("/admin/drain", s.handleDrainStart)
	engine.DELETE("/admin/drain", s.handleDrainStop)
	engine.GET("/admin/drain", s.handleDrainStatus)

	srv := httptest.NewServer(engine)
	return srv, service, func() {
		srv.Close()
		cleanup()
	}
}

// ---------- #1264: GET /jobs/{id} exposes fencing / lease state ----------

func TestGetJob_ExposesClaimEpochOwnerAttemptLease(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-status", "render", nil)
	// Claim it so owner/epoch/attempt/lease are all populated.
	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed)

	resp, err := http.Get(srv.URL + "/jobs/" + seed.ID)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var j generated.Job
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&j))

	assert.Equal(t, int64(1), j.ClaimEpoch, "claim_epoch present and bumped by the claim")
	require.NotNil(t, j.OwnerInstanceId, "owner_instance_id present after claim")
	assert.Equal(t, "replica-a", *j.OwnerInstanceId)
	assert.Equal(t, 1, j.AttemptCount, "attempt_count present and bumped by the claim")
	require.NotNil(t, j.LeaseExpiresAt, "lease_expires_at present after claim")
	assert.Greater(t, *j.LeaseExpiresAt, 0)
}

// ---------- #1265: admin force-reclaim ----------

func reclaimViaHTTP(t *testing.T, srvURL, jobID string) (int, []byte) {
	t.Helper()
	resp, err := http.Post(srvURL+"/jobs/"+jobID+"/reclaim", "application/json", nil)
	require.NoError(t, err)
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	require.NoError(t, err)
	return resp.StatusCode, body
}

func TestReclaimJob_ForcesReclaimabilityAndNextClaimBumpsEpoch(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-reclaim", "render", nil)

	// First claim → owner=replica-a, epoch 1.
	c1, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, c1)
	assert.Equal(t, int64(1), c1.ClaimEpoch)

	// Force-reclaim over HTTP.
	status, body := reclaimViaHTTP(t, srv.URL, seed.ID)
	require.Equal(t, http.StatusOK, status, "body: %s", string(body))

	var rr generated.ReclaimJobResponse
	require.NoError(t, json.Unmarshal(body, &rr))
	assert.Equal(t, generated.Working, rr.Status, "reclaimed job is working/claimable")
	require.NotNil(t, rr.PreviousOwnerInstanceId, "evicted owner reported")
	assert.Equal(t, "replica-a", *rr.PreviousOwnerInstanceId)
	assert.Equal(t, int64(1), rr.ClaimEpoch, "reclaim MUST NOT bump claim_epoch")

	// Row is now claimable: owner cleared, lease cleared, epoch unchanged.
	after, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, after.OwnerInstanceID, "reclaim clears owner")
	assert.Nil(t, after.LeaseExpiresAt, "reclaim clears lease")
	assert.Equal(t, job.StatusWorking, after.Status)
	assert.Equal(t, int64(1), after.ClaimEpoch)

	// The NEXT claim mints the next epoch — this is what fences the superseded
	// execution (even by the same instance).
	c2, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, c2, "job re-claimable after reclaim")
	assert.Equal(t, seed.ID, c2.ID)
	assert.Equal(t, int64(2), c2.ClaimEpoch, "next claim after reclaim bumps epoch 1 -> 2")
}

func TestReclaimJob_TerminalJobIsConflictNoOp(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	owner := "replica-a"
	seed := seedJob(t, service, "job-reclaim-terminal", "render", &owner)
	// Drive it terminal via cancel.
	_, _, err := service.CancelJob(ctx, seed.ID, "")
	require.NoError(t, err)

	status, body := reclaimViaHTTP(t, srv.URL, seed.ID)
	require.Equal(t, http.StatusConflict, status, "terminal job cannot be reclaimed; body: %s", string(body))

	// Terminal state is untouched.
	after, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCancelled, after.Status)
}

func TestReclaimJob_NotFoundIs404(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	status, _ := reclaimViaHTTP(t, srv.URL, "no-such-job")
	require.Equal(t, http.StatusNotFound, status)
}

// TestForceReclaimJob_RaceWithCompletion_NeverResurrects exercises the
// read-then-guarded-write discipline: a completion committing around the
// reclaim must never leave a COMPLETED job resurrected to working/ownerless
// (which would cause silent double execution). We run reclaim and complete
// concurrently over many iterations and assert the invariant every time:
// once a completion is accepted, the job stays completed and the reclaim
// reports a conflict (409-class) rather than clobbering it.
func TestForceReclaimJob_RaceWithCompletion_NeverResurrects(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	for i := 0; i < 40; i++ {
		// Unique job + capability per iteration so a reclaimed (working,
		// ownerless) leftover from a prior iteration cannot be re-claimed here.
		id := fmt.Sprintf("race-job-%d", i)
		capName := fmt.Sprintf("render-%d", i)
		_ = seedJob(t, service, id, capName, nil)
		claimed, err := service.ClaimNextJob(ctx, capName, "replica-a")
		require.NoError(t, err)
		require.NotNil(t, claimed)
		epoch := claimed.ClaimEpoch
		completedStatus := string(job.StatusCompleted)

		var (
			wg             sync.WaitGroup
			reclaimErr     error
			completeAccept int
		)
		wg.Add(2)
		go func() {
			defer wg.Done()
			accepted, _, derr := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{{
				ID:         claimed.ID,
				ClaimEpoch: &epoch,
				Status:     &completedStatus,
				Result:     map[string]interface{}{"ok": true},
			}})
			require.NoError(t, derr)
			completeAccept = accepted
		}()
		go func() {
			defer wg.Done()
			_, _, reclaimErr = service.ForceReclaimJob(ctx, claimed.ID)
		}()
		wg.Wait()

		after, err := service.GetJob(ctx, claimed.ID)
		require.NoError(t, err)

		// The invariant: an accepted completion is NEVER overwritten back to
		// working. If the completion landed, the job must still be completed
		// and the reclaim must have failed with a conflict.
		if completeAccept == 1 {
			assert.Equal(t, job.StatusCompleted, after.Status,
				"iter %d: accepted completion must not be resurrected", i)
			require.Error(t, reclaimErr, "iter %d: reclaim must lose to a committed completion", i)
			assert.True(t,
				errorIsAny(reclaimErr, ErrJobAlreadyTerminal, ErrJobReclaimConflict),
				"iter %d: reclaim must report a conflict, got %v", i, reclaimErr)
		} else {
			// Completion was rejected → reclaim won the race first; job is
			// working+ownerless and claimable again.
			require.NoError(t, reclaimErr, "iter %d: reclaim should succeed when it wins", i)
			assert.Equal(t, job.StatusWorking, after.Status, "iter %d", i)
			assert.Nil(t, after.OwnerInstanceID, "iter %d", i)
		}
	}
}

func errorIsAny(err error, targets ...error) bool {
	for _, tgt := range targets {
		if errors.Is(err, tgt) {
			return true
		}
	}
	return false
}

func TestForceReclaimJob_UnclaimedJobHasNilPreviousOwner(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-reclaim-unowned", "render", nil)
	updated, prevOwner, err := service.ForceReclaimJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, prevOwner, "no owner to evict on an unclaimed job")
	assert.Equal(t, job.StatusWorking, updated.Status)
	assert.Equal(t, int64(0), updated.ClaimEpoch, "unclaimed reclaim leaves epoch at 0")
}

// ---------- #1267: registry drain mode ----------

func TestDrain_BlocksClaims_ResumeUnblocks(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-drain", "render", nil)

	// Draining: claim returns no work, job stays queued, no attempt burn.
	service.SetDraining(true)
	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	assert.Nil(t, claimed, "no work dispatched while draining")

	after, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, after.OwnerInstanceID, "job stays unclaimed while draining")
	assert.Equal(t, 0, after.AttemptCount, "no attempt burned while draining")
	assert.Equal(t, int64(0), after.ClaimEpoch, "no epoch bump while draining")

	// Resume: the same job is claimable again.
	service.SetDraining(false)
	claimed, err = service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed, "job claimable after resume")
	assert.Equal(t, seed.ID, claimed.ID)
	assert.Equal(t, 1, claimed.AttemptCount)
	assert.Equal(t, int64(1), claimed.ClaimEpoch)
}

func TestDrain_SubmissionsStillQueue(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	// Submissions are accepted while draining; they just don't get claimed.
	service.SetDraining(true)
	seed := seedJob(t, service, "job-drain-submit", "render", nil)
	require.Equal(t, job.StatusWorking, seed.Status)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, got.OwnerInstanceID, "queued, unclaimed while draining")

	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	assert.Nil(t, claimed, "still no dispatch for the freshly-submitted job")
}

func TestCountLiveClaims_CountsNonTerminalOwnedJobs(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	owner := "replica-a"
	// Owned + working → counts.
	_ = seedJob(t, service, "live-1", "render", &owner)
	// Owned + working → counts.
	_ = seedJob(t, service, "live-2", "render", &owner)
	// Unclaimed → does not count.
	_ = seedJob(t, service, "queued-1", "render", nil)
	// Owned but terminal → does not count.
	terminal := seedJob(t, service, "term-1", "render", &owner)
	_, _, err := service.CancelJob(ctx, terminal.ID, "")
	require.NoError(t, err)

	n, err := service.CountLiveClaims(ctx)
	require.NoError(t, err)
	assert.Equal(t, 2, n, "only non-terminal owned jobs are live claims")
}

func TestDrainStatus_HTTP_ReportsDrainingAndLiveClaims(t *testing.T) {
	// This exercises the full admin route wiring via a Server (not just the
	// generated jobs router), covering handleDrainStart/Stop/Status.
	srv, service, cleanup := newAdminDrainTestServer(t)
	defer cleanup()

	owner := "replica-a"
	_ = seedJob(t, service, "drain-live", "render", &owner)

	// GET before draining.
	st := getDrainState(t, srv.URL)
	assert.False(t, st.Draining)
	assert.Equal(t, 1, st.LiveClaims)

	// POST → draining.
	st = doDrain(t, http.MethodPost, srv.URL)
	assert.True(t, st.Draining)
	assert.Equal(t, 1, st.LiveClaims)
	assert.True(t, service.IsDraining())

	// DELETE → resumed.
	st = doDrain(t, http.MethodDelete, srv.URL)
	assert.False(t, st.Draining)
	assert.False(t, service.IsDraining())
}

type drainStateWire struct {
	Draining   bool `json:"draining"`
	LiveClaims int  `json:"live_claims"`
}

func getDrainState(t *testing.T, base string) drainStateWire {
	t.Helper()
	resp, err := http.Get(base + "/admin/drain")
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)
	var st drainStateWire
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&st))
	return st
}

func doDrain(t *testing.T, method, base string) drainStateWire {
	t.Helper()
	req, err := http.NewRequest(method, base+"/admin/drain", nil)
	require.NoError(t, err)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)
	var st drainStateWire
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&st))
	return st
}
