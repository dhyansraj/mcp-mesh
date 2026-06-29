package registry

// Tests for the job-related sweep extensions wired in alongside the #837
// stale-agent sweep machinery: orphan-job reroute, expired-lease reclaim,
// and total_deadline expiry. Reuses newSweepTestEnv from sweep_test.go
// for the same in-memory Ent + mock-clock setup.

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/ent/jobevent"
)

// countJobEventsOfType returns how many JobEvent rows of the given type
// exist for a job. Used by the stale-reaping tests to assert exactly one
// synthetic `stale` event is posted (and re-running the sweep doesn't add
// another).
func countJobEventsOfType(t *testing.T, client *ent.Client, jobID, eventType string) int {
	t.Helper()
	n, err := client.JobEvent.Query().
		Where(jobevent.JobID(jobID), jobevent.TypeEQ(eventType)).
		Count(context.Background())
	if err != nil {
		t.Fatalf("count %s events for %s: %v", eventType, jobID, err)
	}
	return n
}

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

// TestSweep_ReclaimExpiredLeaseJobs_ResetsRetryable verifies that a
// working job whose CURRENT lease has genuinely expired — no accepted
// delta inside the lease window (any accepted delta would have extended
// the lease via ApplyJobDeltas), owner agent still healthy and
// heartbeating (so the orphan reroute does NOT act) — is reset to
// claimable with the exact same field semantics as the orphan reset:
// owner cleared, lease cleared, last_heartbeat_at cleared, attempt_count
// untouched.
//
// Lease times are seeded relative to real time.Now() because
// ReclaimExpiredLeaseJobs (like ExpireDeadlinedJobs) compares against
// time.Now().UTC() internally, not the injected sweep clock.
func TestSweep_ReclaimExpiredLeaseJobs_ResetsRetryable(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Healthy, recently-updated owner — neither purgeStaleAgents nor the
	// orphan reroute will touch this job; only the lease phase can.
	seedAgent(t, client, "wedged-owner", agent.StatusHealthy, now)
	owner := "wedged-owner"
	j := seedJobRow(t, client, "job-lease-retry", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	// Expired lease, UTC-pinned to match the production comparison path.
	// last_heartbeat_at is OLDER than the lease — the only state an
	// expired lease can legitimately coexist with, since every accepted
	// delta now refreshes heartbeat AND lease together. A silent wedged
	// handler produces exactly this row.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(-5 * time.Minute)).
		SetLastHeartbeatAt(time.Now().UTC().Add(-10 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsReset != 0 || res.jobsExhausted != 0 {
		t.Fatalf("setup: expected orphan phase to skip live owner, got reset=%d exhausted=%d", res.jobsReset, res.jobsExhausted)
	}
	if res.jobsLeaseReset != 1 {
		t.Errorf("expected 1 lease-expired job reset, got %d", res.jobsLeaseReset)
	}
	if res.jobsLeaseFailed != 0 {
		t.Errorf("expected 0 lease-expired jobs failed, got %d", res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working (claimable) after lease reclaim, got %s", got.Status)
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
	// when the next replica picks the job up. Mirrors the orphan reset.
	if got.AttemptCount != 1 {
		t.Errorf("expected attempt_count unchanged at 1 (claim increments, not lease reclaim), got %d", got.AttemptCount)
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_MarksExhausted verifies that an
// expired-lease job whose attempt_count has exceeded max_retries is
// moved to status=failed with the lease-expired error rather than being
// recycled.
func TestSweep_ReclaimExpiredLeaseJobs_MarksExhausted(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "wedged-owner-2", agent.StatusHealthy, now)
	owner := "wedged-owner-2"
	// attempt_count=4, max_retries=3 → strictly exceeded → exhausted.
	j := seedJobRow(t, client, "job-lease-exhausted", "render", &owner, job.StatusWorking, 4, 3, now.Add(-10*time.Minute))

	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(-5 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 0 {
		t.Errorf("expected 0 lease-expired jobs reset, got %d", res.jobsLeaseReset)
	}
	if res.jobsLeaseFailed != 1 {
		t.Errorf("expected 1 lease-expired job failed, got %d", res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if got.Error == nil || *got.Error != "lease expired: no completion within lease window" {
		t.Errorf("expected error 'lease expired: no completion within lease window', got %v", got.Error)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared on exhausted, got %v", *got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared on exhausted, got %v", got.LeaseExpiresAt)
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_UnexpiredLeaseUntouched verifies
// that a working job whose lease is still in the future is NOT touched
// by the lease phase — healthy in-flight jobs see no behavior change.
func TestSweep_ReclaimExpiredLeaseJobs_UnexpiredLeaseUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "inflight-owner", agent.StatusHealthy, now)
	owner := "inflight-owner"
	j := seedJobRow(t, client, "job-lease-live", "render", &owner, job.StatusWorking, 1, 3, now.Add(-1*time.Minute))

	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(10 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 0 || res.jobsLeaseFailed != 0 {
		t.Errorf("expected no lease action for unexpired lease, got reset=%d failed=%d", res.jobsLeaseReset, res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
	if got.OwnerInstanceID == nil || *got.OwnerInstanceID != owner {
		t.Errorf("expected owner preserved, got %v", got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt == nil {
		t.Errorf("expected lease preserved, got nil")
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_NullLeaseUntouched verifies that a
// working job with a NULL lease_expires_at (legacy rows, or rows pinned
// at create time that were never claimed) is never touched by the lease
// phase.
func TestSweep_ReclaimExpiredLeaseJobs_NullLeaseUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "null-lease-owner", agent.StatusHealthy, now)
	owner := "null-lease-owner"
	// No lease set at all — seedJobRow leaves lease_expires_at NULL.
	j := seedJobRow(t, client, "job-lease-null", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 0 || res.jobsLeaseFailed != 0 {
		t.Errorf("expected no lease action for NULL lease, got reset=%d failed=%d", res.jobsLeaseReset, res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
	if got.OwnerInstanceID == nil || *got.OwnerInstanceID != owner {
		t.Errorf("expected owner preserved, got %v", got.OwnerInstanceID)
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_DeltaExtendedLeaseUntouched verifies
// the lease-extension contract end to end: a job whose claim-time lease
// has lapsed but whose owner posted an accepted /jobs/batch delta is NOT
// reclaimed — ApplyJobDeltas extended lease_expires_at, so the sweep sees
// a fresh lease and skips the row. Without the extension this job would
// be reclaimed mid-execution and its eventual completion rejected
// not_owner.
func TestSweep_ReclaimExpiredLeaseJobs_DeltaExtendedLeaseUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, service, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "chatty-owner", agent.StatusHealthy, now)
	owner := "chatty-owner"
	j := seedJobRow(t, client, "job-lease-extended", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	// Claim-time lease already lapsed — without the delta below the sweep
	// would reclaim this row.
	staleLease := time.Now().UTC().Add(-5 * time.Minute)
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(staleLease).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	// Owner posts a progress delta: the accepted delta must extend the
	// lease (now + 300s default window — the job has no max_duration).
	progress := 0.5
	accepted, rejected, err := service.ApplyJobDeltas(ctx, owner, []JobDeltaInput{{ID: j.ID, Progress: &progress}})
	if err != nil {
		t.Fatalf("ApplyJobDeltas: %v", err)
	}
	if accepted != 1 || len(rejected) != 0 {
		t.Fatalf("expected delta accepted, got accepted=%d rejected=%v", accepted, rejected)
	}

	mid, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job after delta: %v", err)
	}
	if mid.LeaseExpiresAt == nil {
		t.Fatalf("expected lease extended by accepted delta, got nil")
	}
	if !mid.LeaseExpiresAt.After(time.Now().UTC()) {
		t.Fatalf("expected lease extended into the future, got %v", mid.LeaseExpiresAt)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 0 || res.jobsLeaseFailed != 0 {
		t.Errorf("expected no lease action for delta-extended lease, got reset=%d failed=%d", res.jobsLeaseReset, res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
	if got.OwnerInstanceID == nil || *got.OwnerInstanceID != owner {
		t.Errorf("expected owner preserved after extension, got %v", got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt == nil {
		t.Errorf("expected extended lease preserved, got nil")
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_InputRequiredResumeExtendsLease covers
// the input_required round trip: a job parked in input_required with a
// still-valid lease is not reclaimed (the producer extends the lease while
// waiting for a consumer answer), then resumes via an accepted
// status=working delta. The resume delta must extend the lease so the
// freshly resumed job is not instantly reclaimed on the next sweep tick.
//
// Note: an input_required job whose lease has genuinely EXPIRED *is* now
// reclaimed by the lease phase (issue #1229 C1 — see
// TestSweep_ReclaimExpiredLeaseJobs_InputRequiredReclaimedRetryable). This
// test keeps the lease valid during tick 1 so the park is legitimate.
func TestSweep_ReclaimExpiredLeaseJobs_InputRequiredResumeExtendsLease(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, service, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "paused-owner", agent.StatusHealthy, now)
	owner := "paused-owner"
	j := seedJobRow(t, client, "job-input-required", "render", &owner, job.StatusInputRequired, 1, 3, now.Add(-30*time.Minute))

	// Still-valid lease: the producer's input_required delta extended it
	// while the job waits for a consumer answer.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(20 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	// Tick 1: the parked job must NOT be reclaimed — its lease is valid.
	res1, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce (paused): %v", err)
	}
	if res1.jobsLeaseReset != 0 || res1.jobsLeaseFailed != 0 {
		t.Fatalf("expected parked job untouched, got reset=%d failed=%d", res1.jobsLeaseReset, res1.jobsLeaseFailed)
	}

	// Resume: owner posts status=working. The accepted delta must extend
	// the long-expired lease in the same write.
	st := string(job.StatusWorking)
	accepted, rejected, err := service.ApplyJobDeltas(ctx, owner, []JobDeltaInput{{ID: j.ID, Status: &st}})
	if err != nil {
		t.Fatalf("ApplyJobDeltas (resume): %v", err)
	}
	if accepted != 1 || len(rejected) != 0 {
		t.Fatalf("expected resume delta accepted, got accepted=%d rejected=%v", accepted, rejected)
	}

	mid, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job after resume: %v", err)
	}
	if mid.Status != job.StatusWorking {
		t.Fatalf("expected status=working after resume, got %s", mid.Status)
	}
	if mid.LeaseExpiresAt == nil || !mid.LeaseExpiresAt.After(time.Now().UTC()) {
		t.Fatalf("expected resume delta to extend lease into the future, got %v", mid.LeaseExpiresAt)
	}

	// Tick 2: the resumed job carries a fresh lease — must be untouched.
	res2, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce (resumed): %v", err)
	}
	if res2.jobsLeaseReset != 0 || res2.jobsLeaseFailed != 0 {
		t.Errorf("expected resumed job untouched, got reset=%d failed=%d", res2.jobsLeaseReset, res2.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
	if got.OwnerInstanceID == nil || *got.OwnerInstanceID != owner {
		t.Errorf("expected owner preserved through resume, got %v", got.OwnerInstanceID)
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

// TestSweep_ReclaimExpiredLeaseJobs_InputRequiredReclaimedRetryable is the
// C1 bug-fix coverage: an input_required job whose lease has expired (the
// producer posted an input_required delta — which extends the lease — then
// parked waiting for a consumer answer that never came, and the lease
// lapsed) is reclaimed by the lease phase exactly like a working job. Before
// the StatusIn(working, input_required) filter change this row orphaned
// forever holding a claim slot.
func TestSweep_ReclaimExpiredLeaseJobs_InputRequiredReclaimedRetryable(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Healthy owner so the orphan reroute doesn't fire — only the lease
	// phase can act, and only because input_required is now in scope.
	seedAgent(t, client, "parked-owner", agent.StatusHealthy, now)
	owner := "parked-owner"
	j := seedJobRow(t, client, "job-ir-lease-retry", "render", &owner, job.StatusInputRequired, 1, 3, now.Add(-30*time.Minute))

	// Expired lease, UTC-pinned to match the production comparison path.
	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(-5 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 1 {
		t.Errorf("expected 1 input_required job reclaimed (reset), got %d", res.jobsLeaseReset)
	}
	if res.jobsLeaseFailed != 0 {
		t.Errorf("expected 0 lease-failed, got %d", res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working (claimable) after reclaim, got %s", got.Status)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared, got %v", got.LeaseExpiresAt)
	}
	if got.AttemptCount != 1 {
		t.Errorf("expected attempt_count unchanged at 1, got %d", got.AttemptCount)
	}
}

// TestSweep_ReclaimExpiredLeaseJobs_InputRequiredReclaimedExhausted verifies
// the exhausted branch of the C1 fix: an input_required job past its retry
// budget with an expired lease is marked failed rather than recycled.
func TestSweep_ReclaimExpiredLeaseJobs_InputRequiredReclaimedExhausted(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "parked-owner-2", agent.StatusHealthy, now)
	owner := "parked-owner-2"
	// attempt_count=4, max_retries=3 → strictly exceeded → exhausted.
	j := seedJobRow(t, client, "job-ir-lease-exhausted", "render", &owner, job.StatusInputRequired, 4, 3, now.Add(-30*time.Minute))

	if _, err := client.Job.UpdateOneID(j.ID).
		SetLeaseExpiresAt(time.Now().UTC().Add(-5 * time.Minute)).
		Save(ctx); err != nil {
		t.Fatalf("seed lease: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsLeaseReset != 0 {
		t.Errorf("expected 0 lease-reset, got %d", res.jobsLeaseReset)
	}
	if res.jobsLeaseFailed != 1 {
		t.Errorf("expected 1 lease-failed (exhausted input_required), got %d", res.jobsLeaseFailed)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if got.Error == nil || *got.Error != "lease expired: no completion within lease window" {
		t.Errorf("expected lease-expired error, got %v", got.Error)
	}
}

// TestSweep_ResetOrphanedJobs_InputRequiredOrphanReclaimed verifies the C1
// fix for the orphan-reroute phase: an input_required job whose owner agent
// has been purged is reset to claimable (previously left orphaned forever).
func TestSweep_ResetOrphanedJobs_InputRequiredOrphanReclaimed(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "ir-orphan-owner", agent.StatusUnhealthy, now.Add(-3*time.Hour))
	owner := "ir-orphan-owner"
	j := seedJobRow(t, client, "job-ir-orphan", "render", &owner, job.StatusInputRequired, 1, 3, now.Add(-10*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsReset != 1 {
		t.Errorf("expected 1 input_required orphan reset, got %d", res.jobsReset)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working after orphan reset, got %s", got.Status)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}
}

// TestSweep_ExpireStaleJobs_NoDeadlineReaped is the core C2 case: a non-
// terminal job with total_deadline=NULL whose submitted_at is older than the
// stale timeout is marked failed with the `stale:` reason AND a synthetic
// `stale` JobEvent is posted.
func TestSweep_ExpireStaleJobs_NoDeadlineReaped(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour, JobStaleTimeout: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Live owner so this is NOT an orphan; no lease so the lease phase
	// skips it; no total_deadline so ExpireDeadlinedJobs skips it. The
	// stale phase is the only one that can act.
	seedAgent(t, client, "stale-owner", agent.StatusHealthy, now)
	owner := "stale-owner"
	// submitted_at 2h ago > 1h stale timeout → reaped.
	j := seedJobRow(t, client, "job-stale", "render", &owner, job.StatusWorking, 1, 3, now.Add(-2*time.Hour))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsStaled != 1 {
		t.Errorf("expected 1 job staled, got %d", res.jobsStaled)
	}
	if res.jobsDeadlined != 0 {
		t.Errorf("expected 0 deadlined (no total_deadline), got %d", res.jobsDeadlined)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if got.Error == nil || *got.Error != staleJobError {
		t.Errorf("expected error %q, got %v", staleJobError, got.Error)
	}
	if got.LeaseExpiresAt != nil {
		t.Errorf("expected lease cleared, got %v", got.LeaseExpiresAt)
	}
	if got.OwnerInstanceID != nil {
		t.Errorf("expected owner cleared, got %v", *got.OwnerInstanceID)
	}

	if n := countJobEventsOfType(t, client, j.ID, "stale"); n != 1 {
		t.Errorf("expected exactly 1 synthetic stale event, got %d", n)
	}
}

// TestSweep_ExpireStaleJobs_InputRequiredReaped verifies the stale ceiling
// also covers input_required jobs (non-terminal, no total_deadline).
func TestSweep_ExpireStaleJobs_InputRequiredReaped(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour, JobStaleTimeout: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "stale-ir-owner", agent.StatusHealthy, now)
	owner := "stale-ir-owner"
	j := seedJobRow(t, client, "job-stale-ir", "render", &owner, job.StatusInputRequired, 1, 3, now.Add(-2*time.Hour))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsStaled != 1 {
		t.Errorf("expected 1 input_required job staled, got %d", res.jobsStaled)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusFailed {
		t.Errorf("expected status=failed, got %s", got.Status)
	}
	if n := countJobEventsOfType(t, client, j.ID, "stale"); n != 1 {
		t.Errorf("expected 1 stale event, got %d", n)
	}
}

// TestSweep_ExpireStaleJobs_DeadlineSetUntouched verifies that a job which
// DID set its own total_deadline is NOT touched by the stale phase — it is
// left to ExpireDeadlinedJobs. The stale ceiling is a default for jobs that
// didn't opt into an explicit deadline.
func TestSweep_ExpireStaleJobs_DeadlineSetUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour, JobStaleTimeout: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "deadline-owner", agent.StatusHealthy, now)
	owner := "deadline-owner"
	// Old submitted_at (would be stale) BUT total_deadline is set in the
	// FUTURE — ExpireStaleJobs must skip it (total_deadline IS NULL filter),
	// and ExpireDeadlinedJobs must skip it too (deadline not yet passed).
	j := seedJobRow(t, client, "job-has-deadline", "render", &owner, job.StatusWorking, 1, 3, now.Add(-2*time.Hour))
	if _, err := client.Job.UpdateOneID(j.ID).
		SetTotalDeadline(time.Now().UTC().Add(1 * time.Hour)).
		Save(ctx); err != nil {
		t.Fatalf("seed deadline: %v", err)
	}

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsStaled != 0 {
		t.Errorf("expected 0 staled (job set its own total_deadline), got %d", res.jobsStaled)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
	if n := countJobEventsOfType(t, client, j.ID, "stale"); n != 0 {
		t.Errorf("expected no stale event, got %d", n)
	}
}

// TestSweep_ExpireStaleJobs_FreshJobUntouched verifies that a job submitted
// recently (within the stale timeout) is NOT reaped.
func TestSweep_ExpireStaleJobs_FreshJobUntouched(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour, JobStaleTimeout: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "fresh-owner", agent.StatusHealthy, now)
	owner := "fresh-owner"
	// submitted_at 10m ago < 1h timeout → untouched.
	j := seedJobRow(t, client, "job-fresh", "render", &owner, job.StatusWorking, 1, 3, now.Add(-10*time.Minute))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsStaled != 0 {
		t.Errorf("expected 0 staled (fresh job), got %d", res.jobsStaled)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved, got %s", got.Status)
	}
}

// TestSweep_ExpireStaleJobs_DisabledByZeroTimeout verifies that with
// JobStaleTimeout==0 (the default) the stale phase does not run at all — an
// old, deadline-less job is left untouched.
func TestSweep_ExpireStaleJobs_DisabledByZeroTimeout(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour} // JobStaleTimeout left at 0
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "disabled-owner", agent.StatusHealthy, now)
	owner := "disabled-owner"
	j := seedJobRow(t, client, "job-stale-disabled", "render", &owner, job.StatusWorking, 1, 3, now.Add(-5*time.Hour))

	res, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if res.jobsStaled != 0 {
		t.Errorf("expected 0 staled (phase disabled), got %d", res.jobsStaled)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Status != job.StatusWorking {
		t.Errorf("expected status=working preserved when disabled, got %s", got.Status)
	}
	if n := countJobEventsOfType(t, client, j.ID, "stale"); n != 0 {
		t.Errorf("expected no stale event when disabled, got %d", n)
	}
}

// TestSweep_ExpireStaleJobs_Idempotent verifies that re-running the sweep
// over an already-reaped (now terminal) job does not double-fail it or post
// a second stale event — the guarded update no-ops on the terminal row.
func TestSweep_ExpireStaleJobs_Idempotent(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour, JobStaleTimeout: 1 * time.Hour}
	client, _, sweep, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	seedAgent(t, client, "idem-owner", agent.StatusHealthy, now)
	owner := "idem-owner"
	j := seedJobRow(t, client, "job-stale-idem", "render", &owner, job.StatusWorking, 1, 3, now.Add(-2*time.Hour))

	res1, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce (1): %v", err)
	}
	if res1.jobsStaled != 1 {
		t.Fatalf("first tick: expected 1 staled, got %d", res1.jobsStaled)
	}

	res2, err := sweep.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce (2): %v", err)
	}
	if res2.jobsStaled != 0 {
		t.Errorf("second tick: expected 0 staled (already terminal), got %d", res2.jobsStaled)
	}

	if n := countJobEventsOfType(t, client, j.ID, "stale"); n != 1 {
		t.Errorf("expected exactly 1 stale event after two ticks, got %d", n)
	}

	got, err := client.Job.Get(ctx, j.ID)
	if err != nil {
		t.Fatalf("reload job: %v", err)
	}
	if got.Error == nil || *got.Error != staleJobError {
		t.Errorf("expected stale error preserved, got %v", got.Error)
	}
}
