package registry

// Coverage for the durable, framework-persisted recvEvent cursor (issue #1277,
// Wave 1). Pins that:
//
//   - ApplyJobDeltas persists a delta's RecvCursor to the job row.
//   - A superseded-epoch delta carrying a RecvCursor is fenced and does NOT
//     advance the persisted cursor (it rides the same guarded UPDATE as
//     progress, so a stale-epoch UPDATE affects 0 rows).
//   - Reclaim (expired-lease sweep AND admin force-reclaim) retains the cursor.
//   - ClaimNextJob / POST /jobs/claim return the persisted cursor so a
//     re-claimed controller can resume.
//
// Reuses newJobsEndpointTestEnvWithService + seedJob + claimVia + expireLease
// from the sibling job test files.

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry/generated"
)

func TestApplyJobDeltas_PersistsRecvCursor(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-persist", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	cursor := map[string]int64{"": 3, "A": 5}
	accepted, rej, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)
	require.Empty(t, rej)
	require.Equal(t, 1, accepted)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, cursor, got.RecvCursor, "delta's recv_cursor must persist to the row")
}

func TestApplyJobDeltas_NilRecvCursor_LeavesColumnUntouched(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-nil", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	// Establish a cursor.
	base := map[string]int64{"": 2}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: base},
	})
	require.NoError(t, err)

	// A subsequent progress-only delta with NO recv_cursor must not wipe it.
	progress := 0.5
	_, _, err = service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, Progress: &progress},
	})
	require.NoError(t, err)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, base, got.RecvCursor, "nil recv_cursor must leave the column untouched")
}

func TestApplyJobDeltas_StaleEpoch_DoesNotAdvanceRecvCursor(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-fence", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	base := map[string]int64{"": 2}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: base},
	})
	require.NoError(t, err)

	// A superseded (stale epoch 0) delta tries to advance the cursor. The
	// epoch fence rejects it claim_superseded and the guarded UPDATE affects 0
	// rows, so the persisted cursor MUST NOT advance.
	stale := int64(0)
	advanced := map[string]int64{"": 99}
	accepted, rej, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &stale, RecvCursor: advanced},
	})
	require.NoError(t, err)
	assert.Equal(t, 0, accepted)
	require.Len(t, rej, 1)
	assert.Equal(t, JobDeltaRejectionClaimSuperseded, rej[0].Reason)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, base, got.RecvCursor,
		"a superseded delta must NOT advance the persisted recv_cursor")
}

func TestApplyJobDeltas_RecvCursor_LowerIncomingDoesNotRegress(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-noregress", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	// Persist a high watermark.
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: map[string]int64{"": 10}},
	})
	require.NoError(t, err)

	// A later, LOWER incoming (reorder / duplicate / stale snapshot) must NOT
	// regress the persisted value — per-key max merge keeps 10.
	accepted, rej, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: map[string]int64{"": 4}},
	})
	require.NoError(t, err)
	require.Empty(t, rej)
	require.Equal(t, 1, accepted)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, map[string]int64{"": 10}, got.RecvCursor,
		"a lower incoming recv_cursor must NOT regress the higher persisted value")
}

func TestApplyJobDeltas_RecvCursor_PerKeyMaxMerge(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-merge", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	// Base: {"":5, "A":10, "B":2}.
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: map[string]int64{"": 5, "A": 10, "B": 2}},
	})
	require.NoError(t, err)

	// Incoming mixes lower / higher / new, and omits "B":
	//   "" : 3  (lower  → keep 5)
	//   "A": 12 (higher → 12)
	//   "C": 7  (new    → 7)
	//   "B" absent      → preserved at 2
	_, _, err = service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: map[string]int64{"": 3, "A": 12, "C": 7}},
	})
	require.NoError(t, err)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Equal(t, map[string]int64{"": 5, "A": 12, "B": 2, "C": 7}, got.RecvCursor,
		"per-key max merge: lower kept, higher advanced, absent preserved, new added")
}

func TestGetJob_HTTPResponseIncludesRecvCursor(t *testing.T) {
	// Wave 3 (#1277): the persisted recv_cursor is exposed on the status read
	// so operators / the reclaim-resume gate can `curl .../jobs/{id} | jq
	// .recv_cursor.work`.
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-getstatus", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	cursor := map[string]int64{"work": 8}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)

	resp, err := http.Get(srv.URL + "/jobs/" + seed.ID)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var j generated.Job
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&j))
	require.NotNil(t, j.RecvCursor, "status read must expose recv_cursor")
	assert.Equal(t, cursor, *j.RecvCursor)
	assert.Equal(t, int64(8), (*j.RecvCursor)["work"],
		"the reclaim-resume gate reads .recv_cursor.work")
}

func TestGetJob_HTTPResponseOmitsRecvCursorWhenAbsent(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()

	// A freshly seeded job that never flushed a cursor.
	seed := seedJob(t, service, "job-rc-nostatus", "render", nil)

	resp, err := http.Get(srv.URL + "/jobs/" + seed.ID)
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var j generated.Job
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&j))
	assert.Nil(t, j.RecvCursor, "a job with no cursor omits recv_cursor (no spurious {})")
}

func TestReclaimExpiredLease_RetainsRecvCursor(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-sweep", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	cursor := map[string]int64{"": 7}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)

	expireLease(t, service, seed.ID)
	reset, _, err := service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)
	require.Equal(t, 1, reset)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, got.OwnerInstanceID, "sweep reclaim clears the owner")
	assert.Equal(t, cursor, got.RecvCursor, "sweep reclaim MUST retain recv_cursor")
}

func TestForceReclaimJob_RetainsRecvCursor(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-force", "render", nil)
	claimed := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := claimed.ClaimEpoch

	cursor := map[string]int64{"": 4, "B": 9}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)

	_, prevOwner, err := service.ForceReclaimJob(ctx, seed.ID)
	require.NoError(t, err)
	require.NotNil(t, prevOwner)
	require.Equal(t, "replica-a", *prevOwner)

	got, err := service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	assert.Nil(t, got.OwnerInstanceID, "force reclaim clears the owner")
	assert.Equal(t, cursor, got.RecvCursor, "force reclaim MUST retain recv_cursor")
}

func TestClaimNextJob_ReturnsPersistedRecvCursor(t *testing.T) {
	_, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-claim", "render", nil)
	c1 := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := c1.ClaimEpoch

	cursor := map[string]int64{"": 5}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)

	// Reclaim, then re-claim: the fresh claim must carry the persisted cursor.
	expireLease(t, service, seed.ID)
	_, _, err = service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)

	c2 := claimVia(t, service, "render", "replica-a") // epoch 2
	assert.Equal(t, cursor, c2.RecvCursor, "re-claim returns the persisted recv_cursor")
}

func TestClaimJobs_HTTPResponseIncludesRecvCursor(t *testing.T) {
	srv, service, cleanup := newJobsEndpointTestEnvWithService(t)
	defer cleanup()
	ctx := context.Background()

	seed := seedJob(t, service, "job-rc-http", "render", nil)
	c1 := claimVia(t, service, "render", "replica-a") // epoch 1
	epoch := c1.ClaimEpoch

	cursor := map[string]int64{"": 6}
	_, _, err := service.ApplyJobDeltas(ctx, "replica-a", []JobDeltaInput{
		{ID: seed.ID, ClaimEpoch: &epoch, RecvCursor: cursor},
	})
	require.NoError(t, err)

	expireLease(t, service, seed.ID)
	_, _, err = service.ReclaimExpiredLeaseJobs(ctx)
	require.NoError(t, err)

	body, _ := json.Marshal(generated.ClaimJobsRequest{Capability: "render", InstanceId: "replica-a"})
	resp, err := http.Post(srv.URL+"/jobs/claim", "application/json", bytes.NewReader(body))
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)

	var cr generated.ClaimJobsResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&cr))
	require.Len(t, cr.Claimed, 1)
	require.NotNil(t, cr.Claimed[0].RecvCursor, "claim response must carry recv_cursor")
	assert.Equal(t, cursor, *cr.Claimed[0].RecvCursor)
}
