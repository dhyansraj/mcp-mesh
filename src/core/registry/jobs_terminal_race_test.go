package registry

// Coverage for #1581 — MeshJob terminal writes that carried no status
// predicate, so a completion landing in the window between the read and the
// write was silently overwritten (result discarded, job reported
// failed/cancelled).
//
// How the race is reproduced deterministically
// --------------------------------------------
// These tests inject the competing transition through an Ent mutation hook
// that fires immediately before the statement under test executes. The row is
// therefore in exactly the state the losing interleaving produces — terminal
// at the instant the guarded UPDATE evaluates its WHERE clause — which is what
// a PostgreSQL READ COMMITTED re-read sees when a concurrent completion
// commits in that window. This is the only way to model it here: the test
// backend is SQLite, whose transactions are SERIALIZABLE, so an out-of-band
// commit would not be visible to an open transaction at all.
//
// What that does and does not cover is spelled out per test.

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	entgo "entgo.io/ent"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/job"
)

// injectOnceBeforeJobUpdate installs a Job mutation hook that runs `inject`
// exactly once, just before the first update mutation matching `match` is
// executed. `inject` receives the client the mutation is running against —
// inside a transaction that is the transaction's own client, which is what
// makes the injected row state visible to the statement under test.
func injectOnceBeforeJobUpdate(
	client *ent.Client,
	match func(*ent.JobMutation) bool,
	inject func(ctx context.Context, c *ent.Client) error,
) func() bool {
	var (
		mu    sync.Mutex
		fired bool
	)
	client.Job.Use(func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			jm, ok := m.(*ent.JobMutation)
			if !ok || (jm.Op() != ent.OpUpdate && jm.Op() != ent.OpUpdateOne) {
				return next.Mutate(ctx, m)
			}
			mu.Lock()
			// The injected write is itself a Job update; claim the slot before
			// running it so this hook does not recurse.
			run := !fired && match(jm)
			if run {
				fired = true
			}
			mu.Unlock()
			if run {
				if err := inject(ctx, jm.Client()); err != nil {
					return nil, err
				}
			}
			return next.Mutate(ctx, m)
		})
	})
	// Returned as an accessor rather than a *bool so the flag is always read
	// under the same mutex the hook writes it under — the hook happens to run
	// on the caller's goroutine today, but nothing in the API guarantees that.
	return func() bool {
		mu.Lock()
		defer mu.Unlock()
		return fired
	}
}

// TestExpireDeadlinedJobs_LosesToConcurrentCompletion: the deadline sweep
// selects a non-terminal candidate, the handler's complete() commits, and the
// sweep then writes. Before #1581 the write was unconditional and clobbered
// the completion with failed/deadline_exceeded.
//
// Covers: the sweep's UPDATE observing an already-terminal row.
// Does not cover: two genuinely concurrent Postgres transactions (lock waits,
// commit ordering) — see the file header.
func TestExpireDeadlinedJobs_LosesToConcurrentCompletion(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-deadline-race", "render", nil)
	_, err := client.Job.UpdateOneID(j.ID).
		SetTotalDeadline(time.Now().UTC().Add(-5 * time.Minute)).
		Save(ctx)
	require.NoError(t, err, "put the job past its total_deadline")

	// The completion that lands between the sweep's SELECT and its UPDATE.
	injected := injectOnceBeforeJobUpdate(client,
		func(m *ent.JobMutation) bool {
			st, ok := m.Status()
			return ok && st == job.StatusFailed
		},
		func(ctx context.Context, c *ent.Client) error {
			return c.Job.UpdateOneID(j.ID).
				SetStatus(job.StatusCompleted).
				SetResult(map[string]interface{}{"answer": 42}).
				Exec(ctx)
		},
	)

	expired, err := service.ExpireDeadlinedJobs(ctx)
	require.NoError(t, err, "expiry sweep must not error when it loses the race")
	require.True(t, injected(), "test bug: the injected completion never ran")
	assert.Equal(t, 0, expired,
		"a job that completed under the sweep must not be counted as expired (#1581)")

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCompleted, got.Status,
		"the completion must survive the deadline sweep (#1581)")
	assert.Equal(t, map[string]interface{}{"answer": float64(42)}, got.Result,
		"the completed result must not be discarded")
	assert.Nil(t, got.Error, "no failure reason may be written over a completed job")
}

// TestExpireDeadlinedJobs_StillExpiresUnracedJob is the control for the
// predicate added above: the ordinary path must still reap.
func TestExpireDeadlinedJobs_StillExpiresUnracedJob(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	owner := "replica-a"
	j := seedJob(t, service, "job-deadline-plain", "render", &owner)
	_, err := client.Job.UpdateOneID(j.ID).
		SetTotalDeadline(time.Now().UTC().Add(-5 * time.Minute)).
		SetLeaseExpiresAt(time.Now().UTC().Add(2 * time.Minute)).
		Save(ctx)
	require.NoError(t, err, "put the job past its total_deadline")

	expired, err := service.ExpireDeadlinedJobs(ctx)
	require.NoError(t, err)
	assert.Equal(t, 1, expired)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusFailed, got.Status)
	require.NotNil(t, got.Error)
	assert.Equal(t, "deadline_exceeded", *got.Error)
	assert.Nil(t, got.LeaseExpiresAt, "lease must be cleared")
	assert.Nil(t, got.OwnerInstanceID, "owner must be cleared")
}

// TestCancelJob_LosesToConcurrentCompletion: CancelJob's in-transaction
// terminal check passed, then the completion committed, then the cancel wrote.
// Before #1581 the UPDATE carried no predicate and overwrote the completed row
// with `cancelled`, reporting success to the caller.
//
// Covers: the cancel UPDATE observing an already-terminal row → the caller
// gets ErrJobAlreadyTerminal (the 409 the handler already maps) and no
// `cancelled` status is written.
// Does not cover: the post-rollback row state under Postgres. Here the
// injected completion shares the cancel's transaction, so the rollback that
// follows ErrJobAlreadyTerminal also unwinds the injection and the row is left
// `working`; in production the competing completion is a separate committed
// transaction and survives untouched. The assertion is therefore "cancel did
// not win", not "the completion is still there".
func TestCancelJob_LosesToConcurrentCompletion(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	owner := "replica-a"
	j := seedJob(t, service, "job-cancel-race", "render", &owner)

	injected := injectOnceBeforeJobUpdate(client,
		func(m *ent.JobMutation) bool {
			st, ok := m.Status()
			return ok && st == job.StatusCancelled
		},
		func(ctx context.Context, c *ent.Client) error {
			return c.Job.UpdateOneID(j.ID).
				SetStatus(job.StatusCompleted).
				SetResult(map[string]interface{}{"answer": 42}).
				Exec(ctx)
		},
	)

	updated, prevOwner, err := service.CancelJob(ctx, j.ID, "user asked")
	require.True(t, injected(), "test bug: the injected completion never ran")
	require.Error(t, err, "cancel must not report success after losing the race (#1581)")
	assert.True(t, errors.Is(err, ErrJobAlreadyTerminal),
		"losing the race must surface as already-terminal (409), got: %v", err)
	assert.Nil(t, updated)
	assert.Nil(t, prevOwner)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.NotEqual(t, job.StatusCancelled, got.Status,
		"cancel must never overwrite a job that reached a terminal state first (#1581)")
	assert.Nil(t, got.Error, "no `cancelled: ...` reason may be written over the race winner")
}

// TestCancelJob_StillCancelsLiveJob is the control for the predicate added
// above: an ordinary cancel of a live job still works, still reports the
// previous owner, and still records the reason.
func TestCancelJob_StillCancelsLiveJob(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	owner := "replica-a"
	j := seedJob(t, service, "job-cancel-plain", "render", &owner)

	updated, prevOwner, err := service.CancelJob(ctx, j.ID, "user asked")
	require.NoError(t, err)
	require.NotNil(t, updated)
	assert.Equal(t, job.StatusCancelled, updated.Status)
	require.NotNil(t, updated.Error)
	assert.Equal(t, "cancelled: user asked", *updated.Error)
	require.NotNil(t, prevOwner)
	assert.Equal(t, owner, *prevOwner)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCancelled, got.Status)
}

// TestClaimNextJob_LosesToConcurrentCancel: an unowned job can be cancelled
// while a worker is claiming it. The claim's guard only re-asserted
// `owner IS NULL`, so it attached an owner to the cancelled row and handed a
// cancelled job to a worker.
//
// Covers: the claim UPDATE observing a row that left `working` after the
// candidate SELECT.
// Does not cover: two workers racing each other (that half of the guard —
// owner IS NULL — is pre-existing and covered by the claim tests in
// ent_handlers_jobs_admin_test.go).
func TestClaimNextJob_LosesToConcurrentCancel(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-claim-race", "render", nil)

	// The cancel of an unowned job that commits between the candidate SELECT
	// and the claim UPDATE.
	injected := injectOnceBeforeJobUpdate(client,
		func(m *ent.JobMutation) bool {
			_, ok := m.OwnerInstanceID()
			return ok
		},
		func(ctx context.Context, c *ent.Client) error {
			return c.Job.UpdateOneID(j.ID).
				SetStatus(job.StatusCancelled).
				SetError("cancelled: superseded").
				Exec(ctx)
		},
	)

	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err, "losing the claim race is not an error — it is 'no work'")
	require.True(t, injected(), "test bug: the injected cancel never ran")
	assert.Nil(t, claimed,
		"a cancelled job must never be handed to a worker (#1581)")

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusCancelled, got.Status, "the cancel must stand")
	assert.Nil(t, got.OwnerInstanceID, "no owner may be attached to a cancelled job")
	assert.Equal(t, 0, got.AttemptCount, "a lost claim must not burn an attempt")
}

// TestClaimNextJob_StillClaimsLiveJob is the control for the `status=working`
// half of the claim guard: the ordinary claim path is unaffected.
func TestClaimNextJob_StillClaimsLiveJob(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-claim-plain", "render", nil)

	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed, "a pending job must still be claimable")
	assert.Equal(t, j.ID, claimed.ID)
	require.NotNil(t, claimed.OwnerInstanceID)
	assert.Equal(t, "replica-a", *claimed.OwnerInstanceID)
	assert.Equal(t, 1, claimed.AttemptCount)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Equal(t, job.StatusWorking, got.Status)
}

// TestReleaseJob_LosesToConcurrentCompletion: ReleaseJob read the row, found
// it live and owned by the caller, then wrote without a predicate. A
// completion committing in that window had its owner and lease cleared —
// mutating a finished job — and this is the exhausted variant, so its status
// was additionally stamped `failed` and its result discarded.
//
// Covers: the release UPDATE observing an already-terminal row → the caller
// gets ErrJobAlreadyTerminal (the 409 the handler already maps) and neither
// the owner/lease clear nor the exhausted `failed` stamp is applied.
// Does not cover: the post-rollback row state under Postgres, for the same
// reason as the CancelJob test above — the injected completion shares the
// release transaction, so the rollback unwinds it too.
func TestReleaseJob_LosesToConcurrentCompletion(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-release-race", "render", nil)
	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed)
	// Push the row past its retry budget so release would take the terminal
	// (exhausted → failed) branch — the destructive half of the race.
	_, err = client.Job.UpdateOneID(j.ID).SetAttemptCount(9).SetMaxRetries(3).Save(ctx)
	require.NoError(t, err)

	injected := injectOnceBeforeJobUpdate(client,
		func(m *ent.JobMutation) bool {
			return m.OwnerInstanceIDCleared()
		},
		func(ctx context.Context, c *ent.Client) error {
			return c.Job.UpdateOneID(j.ID).
				SetStatus(job.StatusCompleted).
				SetResult(map[string]interface{}{"answer": 42}).
				Exec(ctx)
		},
	)

	released, err := service.ReleaseJob(ctx, j.ID, "replica-a", "handler raised")
	require.True(t, injected(), "test bug: the injected completion never ran")
	require.Error(t, err, "release must not report success after losing the race (#1581)")
	assert.True(t, errors.Is(err, ErrJobAlreadyTerminal),
		"losing to a completion must surface as already-terminal (409), got: %v", err)
	assert.Nil(t, released)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.NotEqual(t, job.StatusFailed, got.Status,
		"release must never stamp `failed` over a job that completed first (#1581)")
	assert.Nil(t, got.Error, "no exhausted-release reason may be written over the race winner")
	require.NotNil(t, got.OwnerInstanceID,
		"a lost release must not clear the owner of a job it no longer owns (#1581)")
}

// TestReleaseJob_LosesToConcurrentReclaim: the sweep can reclaim an expired
// lease (clearing the owner) between the ownership check and the write. The
// guard re-asserts the owner, so the release loses and is reported as 403
// rather than clearing a lease the reclaimer just handed to someone else.
func TestReleaseJob_LosesToConcurrentReclaim(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-release-reclaim", "render", nil)
	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed)

	injected := injectOnceBeforeJobUpdate(client,
		func(m *ent.JobMutation) bool {
			return m.OwnerInstanceIDCleared()
		},
		func(ctx context.Context, c *ent.Client) error {
			// A reclaim hands the row to another replica.
			return c.Job.UpdateOneID(j.ID).
				SetOwnerInstanceID("replica-b").
				Exec(ctx)
		},
	)

	released, err := service.ReleaseJob(ctx, j.ID, "replica-a", "handler raised")
	require.True(t, injected(), "test bug: the injected reclaim never ran")
	require.Error(t, err, "release must not succeed against a row it no longer owns (#1581)")
	assert.True(t, errors.Is(err, ErrJobNotOwner),
		"losing to a reclaim must surface as not-owner (403), got: %v", err)
	assert.Nil(t, released)

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	require.NotNil(t, got.OwnerInstanceID)
	assert.Equal(t, "replica-a", *got.OwnerInstanceID,
		"the rollback leaves the pre-injection owner; the point is that the "+
			"release did not clear it")
}

// TestReleaseJob_StillReleasesOwnedJob is the control for the predicate added
// above: the ordinary release path still clears owner + lease and leaves the
// row claimable.
func TestReleaseJob_StillReleasesOwnedJob(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	j := seedJob(t, service, "job-release-plain", "render", nil)
	claimed, err := service.ClaimNextJob(ctx, "render", "replica-a")
	require.NoError(t, err)
	require.NotNil(t, claimed)
	require.NotNil(t, claimed.LeaseExpiresAt)

	released, err := service.ReleaseJob(ctx, j.ID, "replica-a", "handler raised")
	require.NoError(t, err)
	require.NotNil(t, released)
	assert.Equal(t, job.StatusWorking, released.Status, "budget remains, row stays claimable")
	assert.Nil(t, released.OwnerInstanceID, "owner must be cleared")
	assert.Nil(t, released.LeaseExpiresAt, "lease must be cleared")

	got, err := client.Job.Get(ctx, j.ID)
	require.NoError(t, err)
	assert.Nil(t, got.OwnerInstanceID)
}
