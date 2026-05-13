package registry

// Tests for the job-related sweep extensions wired in alongside the #837
// stale-agent sweep machinery: orphan-job reroute and total_deadline
// expiry. Reuses newSweepTestEnv from sweep_test.go for the same
// in-memory Ent + mock-clock setup.

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/job"
)

// seedJobRow inserts a Job row directly via Ent so tests can pin every
// field (owner, attempts, status, total_deadline) deterministically.
func seedJobRow(t *testing.T, client *ent.Client, id, capability string, owner *string, status job.Status, attemptCount, maxRetries int, submittedAt time.Time) *ent.Job {
	t.Helper()
	ctx := context.Background()
	builder := client.Job.Create().
		SetID(id).
		SetCapability(capability).
		SetStatus(status).
		SetAttemptCount(attemptCount).
		SetMaxRetries(maxRetries).
		SetSubmittedPayload(map[string]interface{}{"k": "v"}).
		SetSubmittedAt(submittedAt)
	if owner != nil && *owner != "" {
		builder = builder.SetOwnerInstanceID(*owner)
	}
	created, err := builder.Save(ctx)
	if err != nil {
		t.Fatalf("seed job %s: %v", id, err)
	}
	return created
}

// TestSweep_ResetOrphanedJobs_ResetsRetryable verifies that a working
// job whose owner agent has been purged from the agents table is reset
// (owner cleared, lease cleared) and is therefore claimable on the next
// claim round-trip.
func TestSweep_ResetOrphanedJobs_ResetsRetryable(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Stale unhealthy owner — purgeStaleAgents will delete it on this tick.
	seedAgent(t, client, "owner-replica-1", agent.StatusUnhealthy, now.Add(-3*time.Hour))
	owner := "owner-replica-1"
	j := seedJobRow(t, client, "job-orphan-retry", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	// Pre-set a lease so we can assert it was cleared.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(now.Add(5 * time.Minute)).
		SetLastHeartbeatAt(now.Add(-30 * time.Second)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.agentsPurged != 1 {
		t.Fatalf("setup: expected 1 agent purged, got %d", res.agentsPurged)
	}
	if res.jobsReset != 1 {
		t.Errorf("expected 1 job reset, got %d", res.jobsReset)
	}
	if res.jobsExhausted != 0 {
		t.Errorf("expected 0 jobs exhausted, got %d", res.jobsExhausted)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working after reset, got %s", got.Status)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared, got %v", got.LeaseExpiresAt)
	}
	if got.LastHeartbeatAt != nil {
		t.Errorf("expected last_heartbeat_at cleared, got %v", got.LastHeartbeatAt)
	}
	// attempt_count must NOT be incremented here — claim path increments
	// when the next replica picks the job up.
	if got.AttemptCount != 1 {
		t.Errorf("expected attempt_count unchanged at 1 (claim increments, not orphan reset), got %d", got.AttemptCount)
	}
}

// TestSweep_ResetOrphanedJobs_MarksExhausted verifies that an orphan
// job whose attempt_count has exceeded max_retries is moved to
// status=failed with a clear error reason rather than being recycled.
// Under the Sidekiq/Celery semantic (max_retries = retries on top of
// initial), exhaustion requires attempt_count > max_retries.
func TestSweep_ResetOrphanedJobs_MarksExhausted(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "owner-replica-2", agent.StatusUnhealthy, now.Add(-3*time.Hour))
	owner := "owner-replica-2"
	// attempt_count=4, max_retries=3 → strictly exceeded → exhausted.
	j := seedJobRow(t, client, "job-orphan-exhausted", "render", &owner, job.StatusWorking, 4, 3, now.Add(-10*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsReset != 0 {
		t.Errorf("expected 0 jobs reset, got %d", res.jobsReset)
	}
	if res.jobsExhausted != 1 {
		t.Errorf("expected 1 job exhausted, got %d", res.jobsExhausted)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if got.Error == nil || *got.Error != "orphaned: max retries exceeded" {
		t.Errorf("expected error 'orphaned: max retries exceeded', got %v", got.Error)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared on exhausted, got %v", *got.OwnerInstanceID)
	}
}

// TestSweep_ResetOrphanedJobs_LeavesLiveOwnersAlone verifies that a
// working job whose owner is still a registered agent is NOT touched
// by the orphan-reroute phase.
func TestSweep_ResetOrphanedJobs_LeavesLiveOwnersAlone(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "live-owner", agent.StatusHealthy, now)
	owner := "live-owner"
	j := seedJobRow(t, client, "job-live", "render", &owner, job.StatusWorking, 1, 3, now.Add(-1*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsReset != 0 || res.jobsExhausted != 0 {
		t.Errorf("expected no orphan action for live owner, got reset=%d exhausted=%d", res.jobsReset, res.jobsExhausted)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.OwnerInstanceID == nil || *got.OwnerInstanceID != owner {
		t.Errorf("expected owner preserved for live agent, got %v", got.OwnerInstanceID)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
}

// TestSweep_ResetOrphanedJobs_ReleasesUnhealthyOwnerPinnedJob verifies
// that a working job pinned to an agent whose status has flipped to
// `unhealthy` is released on the next sweep tick — without waiting for
// the retention timer to purge the agent row. Payload-based MeshJob
// semantics make this safe: the job's submitted_payload is
// self-contained, so any healthy agent with the matching capability
// can pick the orphan up via POST /jobs/claim once owner is cleared.
func TestSweep_ResetOrphanedJobs_ReleasesUnhealthyOwnerPinnedJob(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	// Retention well in the future relative to the seeded agent so
	// purgeStaleAgents would NOT touch the agent row on this tick;
	// the only path that can release the job is the new
	// status-gated liveness check.
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Recent updated_at → outside the retention window → agent row
	// survives this tick. Status=unhealthy is the only orphan signal.
	seedAgent(t, client, "unhealthy-owner", agent.StatusUnhealthy, now.Add(-1*time.Minute))
	owner := "unhealthy-owner"
	j := seedJobRow(t, client, "job-orphan-unhealthy", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	// Pre-set a lease so we can assert it was cleared.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(now.Add(5 * time.Minute)).
		SetLastHeartbeatAt(now.Add(-30 * time.Second)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.agentsPurged != 0 {
		t.Fatalf("setup: expected 0 agents purged (retention not elapsed), got %d", res.agentsPurged)
	}
	if res.jobsReset != 1 {
		t.Errorf("expected 1 job reset on unhealthy owner, got %d", res.jobsReset)
	}
	if res.jobsExhausted != 0 {
		t.Errorf("expected 0 jobs exhausted, got %d", res.jobsExhausted)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working (claimable) after release, got %s", got.Status)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared, got %v", got.LeaseExpiresAt)
	}
	if got.AttemptCount != 1 {
		t.Errorf("expected attempt_count unchanged at 1 (claim increments, not orphan reset), got %d", got.AttemptCount)
	}

	// The agent row itself must still exist — the retention timer
	// owns purge, not the orphan-release path.
	if _, err := client.Agent.Get(ctx, owner); err != nil {
		t.Errorf("expected unhealthy agent row preserved on this tick, got %v", err)
	}
}

// TestSweep_ResetOrphanedJobs_ReleasesUnknownOwnerPinnedJob verifies
// that the `unknown` agent status is also treated as not-live for the
// purposes of orphan release. Only `healthy` keeps a pinned job.
func TestSweep_ResetOrphanedJobs_ReleasesUnknownOwnerPinnedJob(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "unknown-owner", agent.StatusUnknown, now.Add(-1*time.Minute))
	owner := "unknown-owner"
	j := seedJobRow(t, client, "job-orphan-unknown", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsReset != 1 {
		t.Errorf("expected 1 job reset on unknown-status owner, got %d", res.jobsReset)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}
}

// TestSweep_ExpireDeadlinedJobs_PastDeadlineFails verifies that a non-
// terminal job whose total_deadline has passed is moved to failed with
// reason "deadline_exceeded" and has its lease/owner cleared.
func TestSweep_ExpireDeadlinedJobs_PastDeadlineFails(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Live owner so this is NOT mistaken for an orphan; the deadline
	// phase is the one acting here.
	seedAgent(t, client, "owner-replica-3", agent.StatusHealthy, now)
	owner := "owner-replica-3"
	j := seedJobRow(t, client, "job-deadlined", "render", &owner, job.StatusWorking, 1, 3, now.Add(-1*time.Hour))

	// Set total_deadline 5 minutes in the past + a still-valid lease.
	// UTC-pinned to match the production ExpireDeadlinedJobs comparison
	// path; SQLite's text-time roundtrip otherwise shifts a local-time
	// value by the local-vs-UTC offset, masking the comparison.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetTotalDeadline(time.Now().UTC().Add(-5 * time.Minute)).
		SetLeaseExpiresAt(time.Now().UTC().Add(2 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed deadline: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsDeadlined != 1 {
		t.Errorf("expected 1 job deadlined, got %d", res.jobsDeadlined)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if got.Error == nil || *got.Error != "deadline_exceeded" {
		t.Errorf("expected error 'deadline_exceeded', got %v", got.Error)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared after deadline, got %v", got.LeaseExpiresAt)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared after deadline, got %v", *got.OwnerInstanceID)
	}
}

// TestSweep_ExpireDeadlinedJobs_FutureDeadlineUntouched verifies that
// a job whose total_deadline is in the future is NOT touched, and a job
// without a total_deadline (the common case — column is opt-in) is also
// left alone.
func TestSweep_ExpireDeadlinedJobs_FutureDeadlineUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "owner-future", agent.StatusHealthy, now)
	owner := "owner-future"

	// Future deadline. Use UTC explicitly so the SQLite text-time
	// roundtrip doesn't shift the value relative to the production
	// path (ExpireDeadlinedJobs compares against time.Now().UTC()).
	jFuture := seedJobRow(t, client, "job-future", "render", &owner, job.StatusWorking, 0, 3, now)
	if _, err := client.Job.UpdateOneID(jFuture.ID).
		SetTotalDeadline(time.Now().UTC().Add(1 * time.Hour)).
		Save(ctx); err != nil {
		t.Fatalf("seed future deadline: %v", err)
	}

	// No deadline at all.
	jNone := seedJobRow(t, client, "job-no-deadline", "render", &owner, job.StatusWorking, 0, 3, now)

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsDeadlined != 0 {
		t.Errorf("expected 0 jobs deadlined, got %d", res.jobsDeadlined)
	}

	for _, id := range []string{jFuture.ID, jNone.ID} {
		got, err := client.Job.Get(ctx, id)
		if err != nil {
			t.Fatalf("reload %s: %v", id, err)
		}
		if got.Status != job.StatusWorking {
			t.Errorf("%s: expected status=working preserved, got %s", id, got.Status)
		}
	}
}

// TestSweep_ExpireDeadlinedJobs_TerminalUntouched verifies that a job
// already in a terminal state (completed/failed/cancelled) is NOT
// re-failed even if its total_deadline has passed.
func TestSweep_ExpireDeadlinedJobs_TerminalUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Completed job with a past deadline — must NOT be touched.
	jDone := seedJobRow(t, client, "job-completed", "render", nil, job.StatusCompleted, 1, 3, now.Add(-1*time.Hour))
	if _, err := client.Job.UpdateOneID(jDone.ID).
		SetTotalDeadline(time.Now().UTC().Add(-10 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed deadline on completed: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsDeadlined != 0 {
		t.Errorf("expected 0 jobs deadlined (terminal skipped), got %d", res.jobsDeadlined)
	}

	got, err := client.Job.Get(ctx, jDone.ID)
	if err != nil {
		t.Fatalf("reload completed job: %v", err)
	}
	if got.Status != job.StatusCompleted {
		t.Errorf("expected status=completed preserved, got %s", got.Status)
	}
}
