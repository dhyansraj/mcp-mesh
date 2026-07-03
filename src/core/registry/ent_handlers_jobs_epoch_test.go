package registry

// Coverage for claim-epoch fencing and poll-liveness (issue #1252, Phases 1+2).
//
//   - ClaimNextJob mints a fresh claim_epoch on every claim; reclaim leaves it
//     untouched and the NEXT claim bumps it again.
//   - POST /jobs/batch fences a stale (owner, claim_epoch) pair as
//     claim_superseded (cross-instance AND same-instance re-claim); an absent
//     epoch falls back to owner-only validation (version-skew soft-degrade).
//   - GET /jobs/{id}/events distinguishes executor reads (identity supplied →
//     lease extended, stale → 409) from observer reads (no identity → no lease
//     side-effects); terminal jobs never fence an executor read.
//   - cappedPollLease honors total_deadline / max_duration reap ceilings.
//
// Reuses newJobsEndpointTestEnvWithService + seedJob from
// ent_handlers_jobs_extended_test.go.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

// expireLease forces a job's lease into the past so ReclaimExpiredLeaseJobs
// treats it as orphaned on the next scan.
func expireLease(t *testing.T, service *EntService, jobID string) {
	t.Helper()
	past := time.Now().UTC().Add(-time.Hour)
	_, err := service.entDB.Job.UpdateOneID(jobID).SetLeaseExpiresAt(past).Save(context.Background())
	require.NoError(t, err, "expire lease for %s", jobID)
}

// ---------- ClaimNextJob mints / reclaim preserves ----------

func TestClaimNextJob_BumpsClaimEpoch_ReclaimPreservesNextClaimBumpsAgain(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	// Pending, unclaimed job (owner=NULL, epoch=0 default).
	seed := seedJob(t, service, "job-epoch", "render", nil)
	assert.Equal(t, int64(0), seed.ClaimEpoch, "unclaimed job starts at epoch 0")

	// First claim → epoch 1.
	c1, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, c1)
	assert.Equal(t, int64(1), c1.ClaimEpoch, "first claim bumps epoch 0 -> 1")

	// Expire lease + reclaim: owner cleared, status back to working, but the
	// epoch MUST be left untouched (reclaim is not a claim).
	expireLease(t, service, seed.ID)
	reset, _, err := service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)
	require.Equal(t, 1, reset)

	afterReclaim, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, afterReclaim.OwnerInstanceID, "reclaim clears owner")
	assert.Equal(t, job.StatusWorking, afterReclaim.Status)
	assert.Equal(t, int64(1), afterReclaim.ClaimEpoch, "reclaim MUST NOT bump claim_epoch")

	// Re-claim (same instance is allowed) → epoch 2.
	c2, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, c2)
	assert.Equal(t, seed.ID, c2.ID, "same job re-claimed")
	assert.Equal(t, int64(2), c2.ClaimEpoch, "re-claim after reclaim bumps epoch 1 -> 2")
}

func TestClaimJobs_ResponseIncludesClaimEpoch(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	_ = seedJob(t, service, "job-claim-epoch", "render", nil)

	body, _ := json.Marshal(generated.ClaimJobsRequest{Capability: "render", InstanceId: "replica-a"})
	resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.ClaimJobsResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	require.Len(t, cr.Claimed, 1)
	assert.Equal(t, int64(1), cr.Claimed[0].ClaimEpoch, "claim response carries the minted epoch")
}

// ---------- /jobs/batch epoch fencing ----------

// claimVia claims the oldest pending job in a capability and returns the
// claimed row (with its minted epoch).
func claimVia(t *testing.T, service *EntService, capability, instance string) *ent.Job {
	t.Helper()
	claimed, err := service.ClaimNextJob(context.Background(), capability, instance)
	require.NoError(t, err)
	require.NotNil(t, claimed, "expected a claimable job")
	return claimed
}

func postBatchDelta(t *testing.T, srvURL, instance string, delta generated.JobDelta) generated.JobBatchResponse {
	t.Helper()
	body, _ := json.Marshal(generated.JobBatchRequest{
		InstanceId: instance,
		Deltas:     []generated.JobDelta{delta},
	})
	resp, err := http.Post(srvURL+"/jobs/batch", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)
	var br generated.JobBatchResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&br))
	return br
}

func TestSubmitJobBatch_StaleEpoch_RejectedClaimSuperseded(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	_ = seedJob(t, service, "job-batch-epoch", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	require.Equal(t, int64(1), claimed.ClaimEpoch)

	progress := float32(0.5)
	staleEpoch := int64(0)
	currentEpoch := int64(1)

	// Correct owner, stale epoch → claim_superseded (NOT not_owner).
	br := postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: claimed.ID, ClaimEpoch: &staleEpoch, Progress: &progress,
	})
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, br.Rejected[0].Reason)

	// Correct owner + current epoch → accepted.
	br = postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: claimed.ID, ClaimEpoch: &currentEpoch, Progress: &progress,
	})
	assert.Equal(t, 1, br.Accepted)
	assert.Empty(t, br.Rejected)
}

func TestSubmitJobBatch_SameInstanceReclaim_StaleEpochSuperseded(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-reclaim-epoch", "render", nil)
	_ = claimVia(t, service, "render", "replica-a") // epoch 1

	// Reclaim, then the SAME instance re-claims → epoch 2. Pre-#1252 this had
	// zero fencing; the old (epoch 1) execution's deltas passed the owner check.
	expireLease(t, service, seed.ID)
	_, _, err := service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)
	reclaimed := claimVia(t, service, "render", "replica-a") // same instance, epoch 2
	require.Equal(t, int64(2), reclaimed.ClaimEpoch)

	progress := float32(0.7)
	oldEpoch := int64(1)
	newEpoch := int64(2)

	// The superseded (epoch 1) execution — same instance_id — is now fenced.
	br := postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: seed.ID, ClaimEpoch: &oldEpoch, Progress: &progress,
	})
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, br.Rejected[0].Reason)

	// The current (epoch 2) execution writes fine.
	br = postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: seed.ID, ClaimEpoch: &newEpoch, Progress: &progress,
	})
	assert.Equal(t, 1, br.Accepted)
}

func TestSubmitJobBatch_AbsentEpoch_FallsBackToOwnerOnly(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-legacy-epoch", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	require.Equal(t, int64(1), claimed.ClaimEpoch)

	progress := float32(0.3)

	// Old SDK: no claim_epoch on the delta. Correct owner → accepted despite
	// the row now sitting at epoch 1 (owner-only validation).
	br := postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: seed.ID, Progress: &progress,
	})
	assert.Equal(t, 1, br.Accepted, "absent epoch → legacy owner-only accept")
	assert.Empty(t, br.Rejected)

	// Old SDK, wrong owner → still not_owner (unchanged).
	br = postBatchDelta(t, srv.URL, "replica-b", generated.JobDelta{
		Id: seed.ID, Progress: &progress,
	})
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionNotOwner, br.Rejected[0].Reason)
}

func TestSubmitJobBatch_CrossInstanceEpochBearing_Superseded(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-cross-epoch", "render", nil)
	_ = claimVia(t, service, "render", "replica-a") // owner=replica-a, epoch 1

	// A DIFFERENT instance that once held the job (it echoes an epoch) but has
	// since lost it to replica-a. Owner mismatch + epoch present → the sender
	// must be told it was superseded, NOT a bare not_owner (which the Rust
	// core would not translate into an abort).
	progress := float32(0.5)
	epoch := int64(1)
	br := postBatchDelta(t, srv.URL, "replica-b", generated.JobDelta{
		Id: seed.ID, ClaimEpoch: &epoch, Progress: &progress,
	})
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, br.Rejected[0].Reason,
		"epoch-bearing cross-instance delta must be fenced, not not_owner")
}

func TestSubmitJobBatch_ReclaimedUnclaimedEpochBearing_Superseded(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-reclaimed-epoch", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1

	// Reclaim: owner cleared to NULL, status back to working, epoch preserved.
	expireLease(t, service, seed.ID)
	_, _, err := service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)

	// The original owner posts a delta echoing its (still-current-numbered but
	// no-longer-owned) epoch. owner=NULL ⇒ owner mismatch, and an epoch is
	// present ⇒ claim_superseded even though the epoch number itself matches.
	progress := float32(0.6)
	br := postBatchDelta(t, srv.URL, "replica-a", generated.JobDelta{
		Id: seed.ID, ClaimEpoch: &claimed.ClaimEpoch, Progress: &progress,
	})
	assert.Equal(t, 0, br.Accepted)
	require.Len(t, br.Rejected, 1)
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, br.Rejected[0].Reason,
		"epoch-bearing delta on a reclaimed owner=NULL row must be fenced")
}

// ---------- GET /jobs/{id}/events executor vs observer reads ----------

func getEvents(t *testing.T, url string) (*http.Response, generated.JobEventListResponse) {
	t.Helper()
	resp, err := http.Get(url)
	require.NoError(t, err)
	var listed generated.JobEventListResponse
	if resp.StatusCode == http.StatusOK {
		require.NoError(t, json.NewDecoder(resp.Body).Decode(&listed))
	}
	resp.Body.Close()
	return resp, listed
}

func leaseOf(t *testing.T, service *EntService, jobID string) *time.Time {
	t.Helper()
	j, err := service.GetJob(context.Background(), jobID)
	require.NoError(t, err)
	return j.LeaseExpiresAt
}

func TestListJobEvents_ExecutorRead_ExtendsLease(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-exec-read", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1, lease ~now+300s

	// Pull the lease back to now+5s so an executor read can visibly extend it.
	near := time.Now().UTC().Add(5 * time.Second)
	_, err := service.entDB.Job.UpdateOneID(seed.ID).SetLeaseExpiresAt(near).Save(context.Background())
	require.NoError(t, err)

	url := fmt.Sprintf("%s/jobs/%s/events?instance_id=replica-a&claim_epoch=%d", srv.URL, seed.ID, claimed.ClaimEpoch)
	resp, _ := getEvents(t, url)
	require.Equal(t, http.StatusOK, resp.StatusCode)

	extended := leaseOf(t, service, seed.ID)
	require.NotNil(t, extended)
	assert.True(t, extended.After(near), "executor read must extend the lease past its prior value")
}

func TestListJobEvents_ObserverRead_NeverTouchesLease(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-obs-read", "render", nil)
	_ = claimVia(t, service, "render", "replica-a")

	near := time.Now().UTC().Add(5 * time.Second).Truncate(time.Second)
	_, err := service.entDB.Job.UpdateOneID(seed.ID).SetLeaseExpiresAt(near).Save(context.Background())
	require.NoError(t, err)

	// No identity params → anonymous observer read.
	resp, _ := getEvents(t, srv.URL+"/jobs/"+seed.ID+"/events")
	require.Equal(t, http.StatusOK, resp.StatusCode)

	after := leaseOf(t, service, seed.ID)
	require.NotNil(t, after)
	assert.True(t, after.Equal(near), "observer read must not touch the lease")
}

func TestListJobEvents_StaleExecutorRead_409ClaimSuperseded(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-stale-read", "render", nil)
	_ = claimVia(t, service, "render", "replica-a") // epoch 1

	// Wrong epoch (stale) with the right owner → 409 claim_superseded.
	url := fmt.Sprintf("%s/jobs/%s/events?instance_id=replica-a&claim_epoch=0", srv.URL, seed.ID)
	resp, err := http.Get(url)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusConflict, resp.StatusCode)
	var er generated.ErrorResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&er))
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, er.Error)

	// Wrong owner (matching epoch) → also 409.
	url = fmt.Sprintf("%s/jobs/%s/events?instance_id=replica-b&claim_epoch=1", srv.URL, seed.ID)
	resp2, err := http.Get(url)
	require.NoError(t, err)
	defer resp2.Body.Close()
	assert.Equal(t, http.StatusConflict, resp2.StatusCode)
}

func TestListJobEvents_TerminalJob_ExecutorRead_200NoLeaseWrite(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-terminal-read", "render", nil)
	_ = claimVia(t, service, "render", "replica-a") // epoch 1

	// Drive terminal and capture the lease at that moment.
	_, err := service.entDB.Job.UpdateOneID(seed.ID).SetStatus(job.StatusCompleted).Save(ctx)
	require.NoError(t, err)
	before := leaseOf(t, service, seed.ID)

	// Executor read on a terminal job must NOT 409 even with a STALE epoch,
	// and must not write the lease (a handler may poll right after completion).
	url := fmt.Sprintf("%s/jobs/%s/events?instance_id=replica-a&claim_epoch=999", srv.URL, seed.ID)
	resp, err := http.Get(url)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode, "terminal executor read never 409s")

	after := leaseOf(t, service, seed.ID)
	if before == nil {
		assert.Nil(t, after)
	} else {
		require.NotNil(t, after)
		assert.True(t, after.Equal(*before), "terminal executor read must not write the lease")
	}
}

func TestListJobEvents_ExecutorRead_CappedAtTotalDeadline(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-capped-read", "render", nil, withMaxDuration(300))
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1

	now := time.Now().UTC()
	// Current lease well before the total_deadline so the read will extend it;
	// total_deadline sits far below the 300s lease window so the cap bites.
	deadline := now.Add(10 * time.Second).Truncate(time.Second)
	_, err := service.entDB.Job.UpdateOneID(seed.ID).
		SetLeaseExpiresAt(now.Add(2 * time.Second)).
		SetTotalDeadline(deadline).
		Save(ctx)
	require.NoError(t, err)

	url := fmt.Sprintf("%s/jobs/%s/events?instance_id=replica-a&claim_epoch=%d", srv.URL, seed.ID, claimed.ClaimEpoch)
	resp, _ := getEvents(t, url)
	require.Equal(t, http.StatusOK, resp.StatusCode)

	extended := leaseOf(t, service, seed.ID)
	require.NotNil(t, extended)
	assert.True(t, extended.Equal(deadline) || extended.Before(deadline),
		"poll-liveness lease must be capped at total_deadline, got %v (deadline %v)", extended, deadline)
	assert.True(t, extended.Before(now.Add(300*time.Second)),
		"capped lease must sit below the uncapped max_duration window")
}

func TestListJobEvents_HalfSuppliedIdentity_400(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	seed := seedJob(t, service, "job-half-pair", "render", nil)
	_ = claimVia(t, service, "render", "replica-a") // epoch 1

	// instance_id / claim_epoch are paired by contract; a lone one is an SDK
	// bug and must fail loudly (400) rather than silently degrade to an
	// observer read (dropping fencing + poll-liveness with no signal).
	cases := []struct {
		name string
		qs   string
	}{
		{"instance_id without claim_epoch", "instance_id=replica-a"},
		{"claim_epoch without instance_id", "claim_epoch=1"},
		{"empty instance_id with claim_epoch", "instance_id=&claim_epoch=1"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resp, err := http.Get(fmt.Sprintf("%s/jobs/%s/events?%s", srv.URL, seed.ID, tc.qs))
			require.NoError(t, err)
			defer resp.Body.Close()
			assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
		})
	}
}

func TestListJobEvents_ExecutorRead_404OnMissingJob(t *testing.T) {
	srv, _, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// Executor read on an unknown job: AuthorizeExecutorRead is the sole
	// existence gate on this path (the event read skips the redundant Exist),
	// so 404 must still surface.
	resp, err := http.Get(srv.URL + "/jobs/missing-id/events?instance_id=replica-a&claim_epoch=1")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

// ---------- cappedPollLease unit coverage ----------

func TestCappedPollLease(t *testing.T) {
	now := time.Unix(1_700_000_000, 0).UTC()
	md := 120
	submitted := now.Add(-30 * time.Second)

	base := &ent.Job{MaxDuration: &md, SubmittedAt: submitted}

	// No caps → now + max_duration lease window.
	assert.Equal(t, now.Add(120*time.Second), cappedPollLease(base, now, 0),
		"uncapped: extend by the max_duration lease window")

	// total_deadline below the window → capped at total_deadline.
	td := now.Add(10 * time.Second)
	withTD := &ent.Job{MaxDuration: &md, SubmittedAt: submitted, TotalDeadline: &td}
	assert.Equal(t, td, cappedPollLease(withTD, now, 0), "total_deadline caps the lease")

	// total_deadline above the window → the window wins (never extended past it).
	tdFar := now.Add(500 * time.Second)
	withFarTD := &ent.Job{MaxDuration: &md, SubmittedAt: submitted, TotalDeadline: &tdFar}
	assert.Equal(t, now.Add(120*time.Second), cappedPollLease(withFarTD, now, 0),
		"lease never extends past its own window")

	// Stale ceiling with staleTimeout < max_duration → effective = max_duration;
	// ceiling = submitted + 120 = now+90, below window now+120 → capped at now+90.
	assert.Equal(t, submitted.Add(120*time.Second), cappedPollLease(base, now, 60*time.Second),
		"stale ceiling = submitted_at + max(staleTimeout, max_duration)")

	// Stale ceiling with staleTimeout > max_duration → effective = staleTimeout;
	// ceiling = now-30+600 = now+570, above window now+120 → window wins.
	assert.Equal(t, now.Add(120*time.Second), cappedPollLease(base, now, 600*time.Second),
		"stale ceiling above the window does not extend it")

	// total_deadline set → stale ceiling is ignored (stale sweep only scans
	// jobs with a NULL total_deadline), so the td cap stands regardless of staleTimeout.
	assert.Equal(t, td, cappedPollLease(withTD, now, 600*time.Second),
		"stale ceiling never applies when total_deadline is set")

	// No max_duration → 300s default window; staleTimeout=60 → ceiling now+30.
	noMD := &ent.Job{SubmittedAt: submitted}
	assert.Equal(t, submitted.Add(60*time.Second), cappedPollLease(noMD, now, 60*time.Second),
		"default 300s window still capped by the stale ceiling")
}
