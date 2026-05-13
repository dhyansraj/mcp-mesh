package registry

// Service-layer methods for the MeshJob substrate. Wraps the Ent client
// `Job` entity for the registry's /jobs endpoints. See MESHJOB_DESIGN.org.

import (
	"context"
	"encoding/base64"
	"fmt"
	"strconv"
	"strings"
	"time"

	entsql "entgo.io/ent/dialect/sql"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/job"
	"mcp-mesh/src/core/registry/generated"
)

// pendingJobsHeaderCap mirrors the OpenAPI X-Mesh-Pending-Jobs schema
// (maximum: 100). Producers don't need an exact count past the cap — the
// HEAD hint is opportunistic and the SDK only needs to know "there is work
// to claim", so we clip large pending pools to keep the header bounded.
const pendingJobsHeaderCap = 100

// defaultClaimLeaseSeconds is the lease duration applied at claim time when
// the job has no explicit `max_duration`. Matches the soft-timeout default
// documented in MESHJOB_DESIGN.org > Layered timeouts (300s).
const defaultClaimLeaseSeconds = 300

// claimMaxAttempts caps the number of optimistic-update retries inside a
// single ClaimNextJob call. Each retry pulls the next FIFO candidate after
// a concurrent peer wins the previous one. Bound is small because (a) a
// single replica only races peers in its own capability group and (b) at
// most one row is claimed per round-trip — long contention loops would
// indicate a runaway and should fail fast rather than spin.
const claimMaxAttempts = 8

// CreateJob persists a new job row. Caller is responsible for generating
// the ID (UUID) and applying defaults; this method does the mechanical
// translation from CreateJobInput to the Ent builder.
//
// `OwnerInstanceID == nil` is the pull-mode case — owner is left NULL so
// that a future POST /jobs/claim can attach a replica.
func (s *EntService) CreateJob(ctx context.Context, in *CreateJobInput) (*ent.Job, error) {
	if in == nil {
		return nil, fmt.Errorf("CreateJob: input is nil")
	}
	if in.ID == "" {
		return nil, fmt.Errorf("CreateJob: id is required")
	}
	if in.Capability == "" {
		return nil, fmt.Errorf("CreateJob: capability is required")
	}

	builder := s.entDB.Job.Create().
		SetID(in.ID).
		SetCapability(in.Capability).
		SetSubmittedPayload(in.SubmittedPayload).
		SetStatus(job.StatusWorking).
		SetAttemptCount(0).
		SetMaxRetries(in.MaxRetries).
		SetSubmittedAt(time.Now().UTC())

	if in.SubmittedBy != "" {
		builder = builder.SetSubmittedBy(in.SubmittedBy)
	}
	if in.OwnerInstanceID != nil && *in.OwnerInstanceID != "" {
		builder = builder.SetOwnerInstanceID(*in.OwnerInstanceID)
	}
	if in.MaxDuration != nil {
		builder = builder.SetMaxDuration(*in.MaxDuration)
	}
	if in.TotalDeadline != nil {
		builder = builder.SetTotalDeadline(time.Unix(int64(*in.TotalDeadline), 0).UTC())
	}

	created, err := builder.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create job: %w", err)
	}
	return created, nil
}

// GetJob fetches a single job row by ID. Returns ent.NotFoundError if no
// row matches, which the handler maps to HTTP 404.
func (s *EntService) GetJob(ctx context.Context, jobID string) (*ent.Job, error) {
	return s.entDB.Job.Query().
		Where(job.IDEQ(jobID)).
		Only(ctx)
}

// jobsListDefaultLimit / jobsListMaxLimit mirror the OpenAPI bounds for
// GET /jobs (issue #973). Kept here rather than the handler so the service
// is self-consistent when called from non-HTTP code paths (e.g. tests).
const (
	jobsListDefaultLimit = 50
	jobsListMaxLimit     = 200
)

// ListJobs implements GET /jobs (issue #973). Read-only listing with
// keyset pagination on (submitted_at DESC, id DESC). Cursor is an opaque
// base64-encoded "<unix>:<id>" string identifying the last row of the
// previous page; the next page is "everything strictly after that key in
// descending order".
//
// Pagination strategy: SELECT limit+1 rows and, if we got more than `limit`,
// drop the extra row and emit a cursor pointing at the LAST row we kept.
// That last row IS the next cursor — its (submitted_at, id) becomes the
// "strictly less than" boundary for the next call. We don't peek past it.
//
// Filters compose with AND. An empty `Statuses` slice means "all statuses".
// `OwnerInstanceID` / `Capability` are exact matches when non-empty.
// `SubmittedSince` (Unix epoch seconds) is GTE.
//
// jobToAPI (in ent_handlers_jobs.go, same package) handles the Ent → OpenAPI
// row mapping. We keep that helper where it is so the existing /jobs/{id}
// handler doesn't churn — Go package visibility lets us call it directly
// from the service file.
func (s *EntService) ListJobs(ctx context.Context, in *JobsListInput) (*generated.JobsListResponse, error) {
	if in == nil {
		return nil, fmt.Errorf("ListJobs: input is nil")
	}

	limit := in.Limit
	if limit <= 0 {
		limit = jobsListDefaultLimit
	}
	if limit > jobsListMaxLimit {
		return nil, fmt.Errorf("ListJobs: limit %d exceeds max %d", limit, jobsListMaxLimit)
	}

	q := s.entDB.Job.Query()

	if len(in.Statuses) > 0 {
		statuses := make([]job.Status, 0, len(in.Statuses))
		for _, raw := range in.Statuses {
			st := job.Status(raw)
			if err := job.StatusValidator(st); err != nil {
				return nil, fmt.Errorf("ListJobs: invalid status %q: %w", raw, err)
			}
			statuses = append(statuses, st)
		}
		q = q.Where(job.StatusIn(statuses...))
	}
	if in.OwnerInstanceID != "" {
		q = q.Where(job.OwnerInstanceIDEQ(in.OwnerInstanceID))
	}
	if in.Capability != "" {
		q = q.Where(job.CapabilityEQ(in.Capability))
	}
	if in.SubmittedSince > 0 {
		q = q.Where(job.SubmittedAtGTE(time.Unix(in.SubmittedSince, 0).UTC()))
	}

	// Cursor: rows STRICTLY AFTER the previous page's last row, in
	// descending order. (submitted_at, id) keyset:
	//   submitted_at < cur.submitted_at
	//   OR (submitted_at = cur.submitted_at AND id < cur.id)
	if in.Cursor != "" {
		cursorTime, cursorID, err := decodeJobsCursor(in.Cursor)
		if err != nil {
			return nil, fmt.Errorf("ListJobs: invalid cursor: %w", err)
		}
		q = q.Where(
			job.Or(
				job.SubmittedAtLT(cursorTime),
				job.And(job.SubmittedAtEQ(cursorTime), job.IDLT(cursorID)),
			),
		)
	}

	rows, err := q.
		Order(job.BySubmittedAt(entsql.OrderDesc()), job.ByID(entsql.OrderDesc())).
		Limit(limit + 1).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("ListJobs: query failed: %w", err)
	}

	resp := &generated.JobsListResponse{Jobs: []generated.Job{}}
	if len(rows) > limit {
		// More pages available; the row at index `limit-1` becomes the
		// next cursor. We drop the peek row (`rows[limit]`) — it stays
		// for the next page to pick up.
		rows = rows[:limit]
		last := rows[limit-1]
		cursor := encodeJobsCursor(last.SubmittedAt, last.ID)
		resp.NextCursor = &cursor
	}
	for _, r := range rows {
		resp.Jobs = append(resp.Jobs, jobToAPI(r))
	}
	return resp, nil
}

// encodeJobsCursor packs the keyset (submitted_at, id) into the opaque
// base64 string returned in JobsListResponse.next_cursor. Format is
// "<unix>:<id>" before encoding — versionless because the cursor is
// short-lived (browser-page-scoped) and the registry is the only producer.
func encodeJobsCursor(submittedAt time.Time, id string) string {
	raw := fmt.Sprintf("%d:%s", submittedAt.UnixNano(), id)
	return base64.RawURLEncoding.EncodeToString([]byte(raw))
}

// decodeJobsCursor reverses encodeJobsCursor. Returns a descriptive error
// the handler surfaces as 400 — bad cursors never bubble up as 500.
func decodeJobsCursor(cursor string) (time.Time, string, error) {
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return time.Time{}, "", fmt.Errorf("decode base64: %w", err)
	}
	parts := strings.SplitN(string(raw), ":", 2)
	if len(parts) != 2 || parts[1] == "" {
		return time.Time{}, "", fmt.Errorf("malformed cursor payload")
	}
	nano, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return time.Time{}, "", fmt.Errorf("parse timestamp: %w", err)
	}
	return time.Unix(0, nano).UTC(), parts[1], nil
}

// JobDeltaInput is the service-layer view of a single per-job delta. Mirrors
// generated.JobDelta but uses unexported types so the service does not depend
// on the OpenAPI package directly (handler is responsible for the mapping).
type JobDeltaInput struct {
	ID              string
	Status          *string // optional; validated against job.Status enum
	Progress        *float64
	ProgressMessage *string
	Result          map[string]interface{}
	Error           *string
}

// JobDeltaRejection captures why a single delta was not applied. The handler
// surfaces these in the JobBatchResponse.rejected list.
type JobDeltaRejection struct {
	ID     string
	Reason string
}

// Reasons surfaced in JobBatchResponse.rejected[].reason. Stable strings —
// callers may dispatch on them.
const (
	JobDeltaRejectionNotFound        = "not_found"
	JobDeltaRejectionNotOwner        = "not_owner"
	JobDeltaRejectionAlreadyTerminal = "already_terminal"
	JobDeltaRejectionInvalidStatus   = "invalid_status"
)

// ApplyJobDeltas processes a batch of per-job deltas from a single producer
// instance. Each delta is applied independently — partial success is the
// spec (see MESHJOB_DESIGN.org > "Producer-side flow" Tick step). Returns
// the number of accepted deltas plus a per-delta rejection list.
//
// Lease semantics: any accepted delta refreshes `last_heartbeat_at` (the
// batch itself counts as a lease extension), matching the design's
// "POST /jobs/batch → progress + heartbeat (lease extension)" comment.
func (s *EntService) ApplyJobDeltas(ctx context.Context, instanceID string, deltas []JobDeltaInput) (int, []JobDeltaRejection, error) {
	if instanceID == "" {
		return 0, nil, fmt.Errorf("ApplyJobDeltas: instance_id is required")
	}
	if len(deltas) == 0 {
		return 0, nil, fmt.Errorf("ApplyJobDeltas: deltas must not be empty")
	}

	accepted := 0
	rejections := make([]JobDeltaRejection, 0)
	now := time.Now().UTC()

	for _, d := range deltas {
		j, err := s.entDB.Job.Query().Where(job.IDEQ(d.ID)).Only(ctx)
		if err != nil {
			if ent.IsNotFound(err) {
				rejections = append(rejections, JobDeltaRejection{ID: d.ID, Reason: JobDeltaRejectionNotFound})
				continue
			}
			return accepted, rejections, fmt.Errorf("query job %s: %w", d.ID, err)
		}

		if j.OwnerInstanceID == nil || *j.OwnerInstanceID != instanceID {
			rejections = append(rejections, JobDeltaRejection{ID: d.ID, Reason: JobDeltaRejectionNotOwner})
			continue
		}
		if isTerminalStatus(j.Status) {
			rejections = append(rejections, JobDeltaRejection{ID: d.ID, Reason: JobDeltaRejectionAlreadyTerminal})
			continue
		}

		// Validate status transition before any writes.
		var newStatus *job.Status
		if d.Status != nil {
			st := job.Status(*d.Status)
			if err := job.StatusValidator(st); err != nil {
				rejections = append(rejections, JobDeltaRejection{ID: d.ID, Reason: JobDeltaRejectionInvalidStatus})
				continue
			}
			newStatus = &st
		}

		upd := s.entDB.Job.UpdateOneID(d.ID).SetLastHeartbeatAt(now)
		if d.Progress != nil {
			upd = upd.SetProgress(*d.Progress)
		}
		if d.ProgressMessage != nil {
			upd = upd.SetProgressMessage(*d.ProgressMessage)
		}
		if newStatus != nil {
			upd = upd.SetStatus(*newStatus)
			// Terminal-only payloads. Result is meaningful for completed,
			// error for failed; we accept them silently if attached to the
			// matching terminal status (per JobDelta schema comments).
			if *newStatus == job.StatusCompleted && d.Result != nil {
				upd = upd.SetResult(d.Result)
			}
			if *newStatus == job.StatusFailed && d.Error != nil {
				upd = upd.SetError(*d.Error)
			}
		}

		if _, err := upd.Save(ctx); err != nil {
			return accepted, rejections, fmt.Errorf("update job %s: %w", d.ID, err)
		}
		accepted++
	}

	return accepted, rejections, nil
}

// ClaimNextJob atomically claims a single pending job for the calling
// instance. Returns (nil, nil) when no work is available — "no work" is
// not an error (see Resolved Decisions).
//
// Atomicity strategy (race-free on both Postgres and SQLite without
// requiring SKIP LOCKED, which the generated Ent builders here don't
// surface as a Modify hook):
//
//   1. SELECT the oldest claimable candidate (FIFO by submitted_at) for the
//      requested capability with status='working' AND owner_instance_id IS
//      NULL.
//   2. UPDATE the row with a guarded WHERE: id=? AND owner_instance_id IS
//      NULL. Exactly one of N concurrent writers will see RowsAffected=1;
//      the rest see 0 because the predicate failed under SQLite's
//      single-writer serialization or Postgres's row-level write lock.
//   3. If we lost the race, loop and try the next candidate (capped at
//      `claimMaxAttempts`). FIFO is preserved because step 1 always picks
//      the oldest remaining.
//
// This is the "atomic UPDATE ... WHERE owner IS NULL" pattern from the
// design doc's "Reschedule via HEAD hint + claim" section, just split into
// SELECT + guarded UPDATE for portability across the two backends.
func (s *EntService) ClaimNextJob(ctx context.Context, capability, instanceID string) (*ent.Job, error) {
	if capability == "" {
		return nil, fmt.Errorf("ClaimNextJob: capability is required")
	}
	if instanceID == "" {
		return nil, fmt.Errorf("ClaimNextJob: instance_id is required")
	}

	now := time.Now().UTC()

	for attempt := 0; attempt < claimMaxAttempts; attempt++ {
		candidate, err := s.entDB.Job.Query().
			Where(
				job.CapabilityEQ(capability),
				job.StatusEQ(job.StatusWorking),
				job.OwnerInstanceIDIsNil(),
			).
			Order(job.BySubmittedAt(entsql.OrderAsc())).
			Limit(1).
			First(ctx)
		if err != nil {
			if ent.IsNotFound(err) {
				return nil, nil // No claimable row — caller treats as "no work".
			}
			return nil, fmt.Errorf("query candidate: %w", err)
		}

		// Retry-budget guard. We don't push this into the WHERE clause
		// because attempt_count > max_retries should be a permanent skip
		// (the orphan-reroute sweep won't pick it back up either); a
		// future cron sweep will mark it failed/exhausted. For now, just
		// don't claim — and don't loop on this candidate either, because
		// the next FIFO candidate would be identical until the sweep
		// retires it. Treat "oldest is over budget" as "no work".
		//
		// Semantic: max_retries = retries on top of the initial attempt
		// (Sidekiq/Celery/Resque convention). max_retries=1 ⇒ at most 2
		// total claims (1 initial + 1 retry on crash). attempt_count is
		// incremented at claim time, so a job is still claimable while
		// attempt_count <= max_retries (i.e. exhausted iff strictly
		// greater).
		if candidate.AttemptCount > candidate.MaxRetries {
			return nil, nil
		}

		leaseSeconds := defaultClaimLeaseSeconds
		if candidate.MaxDuration != nil && *candidate.MaxDuration > 0 {
			leaseSeconds = *candidate.MaxDuration
		}
		leaseExpires := now.Add(time.Duration(leaseSeconds) * time.Second)

		// Guarded update: only succeed if owner is still NULL. Concurrent
		// claimers race here; exactly one wins, the rest see Affected=0.
		affected, err := s.entDB.Job.Update().
			Where(
				job.IDEQ(candidate.ID),
				job.OwnerInstanceIDIsNil(),
			).
			SetOwnerInstanceID(instanceID).
			AddAttemptCount(1).
			SetLeaseExpiresAt(leaseExpires).
			SetLastHeartbeatAt(now).
			Save(ctx)
		if err != nil {
			return nil, fmt.Errorf("update candidate %s: %w", candidate.ID, err)
		}
		if affected == 0 {
			// Someone else won this row; refresh `now` and try the next
			// FIFO candidate.
			continue
		}

		// Re-fetch so we return the post-update row (Update().Save returns
		// only the affected count, not the entity).
		claimed, err := s.entDB.Job.Query().Where(job.IDEQ(candidate.ID)).Only(ctx)
		if err != nil {
			return nil, fmt.Errorf("reload claimed job %s: %w", candidate.ID, err)
		}
		return claimed, nil
	}

	// Hit the contention cap without claiming. Treat as "no work" rather
	// than erroring — the next claim round-trip will retry from scratch.
	return nil, nil
}

// CancelJob marks a job as cancelled in the registry. Returns the updated
// row plus the previous owner_instance_id (if any) so the handler can
// decide whether to forward the cancel to a still-alive owner replica.
//
// Returns ent.NotFoundError if the job does not exist (handler: 404), and
// ErrJobAlreadyTerminal if the job is already in a terminal state (handler:
// 409).
func (s *EntService) CancelJob(ctx context.Context, jobID string, reason string) (*ent.Job, *string, error) {
	if jobID == "" {
		return nil, nil, fmt.Errorf("CancelJob: job_id is required")
	}

	var (
		updated   *ent.Job
		prevOwner *string
	)

	err := s.entDB.Transaction(ctx, func(tx *ent.Tx) error {
		current, err := tx.Job.Query().Where(job.IDEQ(jobID)).Only(ctx)
		if err != nil {
			return err // includes ent.NotFoundError
		}
		if isTerminalStatus(current.Status) {
			return ErrJobAlreadyTerminal
		}

		if current.OwnerInstanceID != nil {
			owner := *current.OwnerInstanceID
			prevOwner = &owner
		}

		upd := tx.Job.UpdateOneID(jobID).
			SetStatus(job.StatusCancelled).
			SetLastHeartbeatAt(time.Now().UTC())
		// Preserve the optional reason. Phase 1 stores it in the existing
		// `error` column (prefixed) rather than adding a schema field for
		// a minor feature — see MESHJOB_DESIGN.org > Step 3 notes.
		if r := strings.TrimSpace(reason); r != "" {
			upd = upd.SetError("cancelled: " + r)
		}
		u, err := upd.Save(ctx)
		if err != nil {
			return fmt.Errorf("update job: %w", err)
		}
		updated = u
		return nil
	})

	if err != nil {
		return nil, nil, err
	}
	return updated, prevOwner, nil
}

// ErrJobAlreadyTerminal is returned by CancelJob when the target job has
// already reached a terminal state. The handler maps this to HTTP 409.
var ErrJobAlreadyTerminal = fmt.Errorf("job is already in a terminal state")

// ErrJobNotOwner is returned by ReleaseJob when the caller's instance_id
// does not match the current owner_instance_id. The handler maps this to
// HTTP 403 — release is owner-only.
var ErrJobNotOwner = fmt.Errorf("caller is not the current owner of this job")

// ReleaseJob voluntarily releases the lease on a `working` job so a peer
// replica can re-claim and retry. Used by the Python/TS/Java SDKs when a
// handler raised a `retry_on`-matched exception — instead of marking the
// job failed (which would terminate it), the SDK releases the lease and
// the registry's HEAD-heartbeat path drives a fast (<5s) re-claim by a
// peer replica.
//
// Atomic update:
//   - clears `owner_instance_id` and `lease_expires_at`
//   - leaves `attempt_count` UNCHANGED — the claim that produced the
//     current owner already incremented it; release is the OFF-side of
//     that same attempt and must not double-count
//   - if `attempt_count > max_retries` (the claim already pushed the row
//     past its budget AND the handler raised on that final allowed
//     attempt), transitions status to `failed` with
//     `error="exhausted (release): <reason>"` (terminal — mirrors the
//     orphan-sweep budget-exhaustion path)
//   - otherwise leaves status=`working`, ready for the next claim
//
// Returns:
//   - `ent.NotFoundError` when the job_id is unknown (handler: 404)
//   - `ErrJobNotOwner` when `instanceID` is not the current owner (403)
//   - `ErrJobAlreadyTerminal` when the job is already terminal (409)
func (s *EntService) ReleaseJob(ctx context.Context, jobID, instanceID, reason string) (*ent.Job, error) {
	if jobID == "" {
		return nil, fmt.Errorf("ReleaseJob: job_id is required")
	}
	if instanceID == "" {
		return nil, fmt.Errorf("ReleaseJob: instance_id is required")
	}

	var updated *ent.Job
	err := s.entDB.Transaction(ctx, func(tx *ent.Tx) error {
		current, err := tx.Job.Query().Where(job.IDEQ(jobID)).Only(ctx)
		if err != nil {
			return err // includes ent.NotFoundError
		}
		if isTerminalStatus(current.Status) {
			return ErrJobAlreadyTerminal
		}
		// Owner must match. We allow a missing owner only by failing the
		// 403 path — release is meaningful only when there IS an owner to
		// release, so a NULL owner with mismatched instance_id is the same
		// "not yours" error.
		if current.OwnerInstanceID == nil || *current.OwnerInstanceID != instanceID {
			return ErrJobNotOwner
		}

		now := time.Now().UTC()

		upd := tx.Job.UpdateOneID(jobID).
			ClearOwnerInstanceID().
			ClearLeaseExpiresAt().
			SetLastHeartbeatAt(now)

		// Budget check uses the existing attempt_count (NOT +1). The claim
		// path increments at claim time, so by the time we get here the
		// current value already reflects "this attempt". If the handler
		// raised on the row's final allowed attempt (i.e. claim already
		// pushed attempt_count past max_retries), no more retries are
		// possible — tip the row into terminal=failed.
		//
		// We mirror the orphan-sweep path's reason wording so operators
		// can grep both paths the same way; the "(release)" qualifier
		// disambiguates voluntary release from orphan reroute.
		if current.AttemptCount > current.MaxRetries {
			errMsg := "exhausted (release): max retries exceeded"
			if r := strings.TrimSpace(reason); r != "" {
				errMsg = fmt.Sprintf("exhausted (release): %s", r)
			}
			upd = upd.SetStatus(job.StatusFailed).SetError(errMsg)
		}
		// Otherwise: status stays `working`, owner cleared, attempt_count
		// untouched — row is ready for the next claim round-trip, which
		// will increment attempt_count itself.

		u, err := upd.Save(ctx)
		if err != nil {
			return fmt.Errorf("update job: %w", err)
		}
		updated = u
		return nil
	})

	if err != nil {
		return nil, err
	}
	return updated, nil
}

// isTerminalStatus reports whether a job.Status is one of the terminal
// values (no further transitions allowed). Mirrors the design doc's state
// machine.
func isTerminalStatus(s job.Status) bool {
	switch s {
	case job.StatusCompleted, job.StatusFailed, job.StatusCancelled:
		return true
	default:
		return false
	}
}

// CountPendingJobsForAgent returns the count of unclaimed jobs whose
// capability is served by agentID's group (= other agents sharing this
// agent_name) and which still have retry budget. Used by the HEAD
// /heartbeat handler to set the X-Mesh-Pending-Jobs header so replicas
// know to call POST /jobs/claim.
//
// Scoping per design doc ("Pending-jobs scoping: per-agent capability
// set"): agents sharing the same agent_name are replicas of the same
// capability set; the count is computed across that group, not the
// individual instance ID. A pending job for capability X notifies only
// the replicas whose agent_name actually serves X.
//
// Returns 0 (no error) when:
//   - agent record is missing
//   - agent group serves zero capabilities
//   - no jobs are pending in those capabilities
//
// Counts are clipped at pendingJobsHeaderCap to honor the OpenAPI schema
// (maximum: 100). The header is opportunistic, not exact; a saturated
// queue just shows "100" and the next claim/heartbeat round-trip drains
// it further.
//
// Performance: this runs on every HEAD heartbeat (~5s per agent).
// Backed by the jobs_pending_by_capability index (full index in Phase 1;
// partial WHERE owner IS NULL to follow up).
func (s *EntService) CountPendingJobsForAgent(ctx context.Context, agentID string) (int, error) {
	if agentID == "" {
		return 0, nil
	}

	// Look up the agent_name (group identity, not instance ID).
	a, err := s.entDB.Client.Agent.Query().
		Where(agent.IDEQ(agentID)).
		Only(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return 0, nil
		}
		return 0, fmt.Errorf("lookup agent %s: %w", agentID, err)
	}

	// Capabilities served by every replica that shares this agent_name.
	// We collect distinct capability strings; a single replica registering
	// the same capability under multiple function_names should not be
	// double-counted.
	var capRows []string
	if err := s.entDB.Client.Capability.Query().
		Where(capability.HasAgentWith(agent.NameEQ(a.Name))).
		Select(capability.FieldCapability).
		Scan(ctx, &capRows); err != nil {
		return 0, fmt.Errorf("collect capabilities for agent group %s: %w", a.Name, err)
	}
	if len(capRows) == 0 {
		return 0, nil
	}
	capSet := make(map[string]struct{}, len(capRows))
	caps := make([]string, 0, len(capRows))
	for _, c := range capRows {
		if c == "" {
			continue
		}
		if _, ok := capSet[c]; ok {
			continue
		}
		capSet[c] = struct{}{}
		caps = append(caps, c)
	}
	if len(caps) == 0 {
		return 0, nil
	}

	// Pending = working AND owner IS NULL AND capability IN (...) AND
	// attempt_count <= max_retries. The retry-budget guard is a Go-side
	// filter because Ent doesn't expose field-vs-field comparisons; we
	// fetch the candidate AttemptCount/MaxRetries pair via a small Select
	// and filter in memory. Clipped at pendingJobsHeaderCap+1 so we don't
	// pull more rows than we'll ever need to report.
	//
	// Semantic: max_retries counts retries on top of the initial attempt;
	// a job is still claimable while attempt_count <= max_retries.
	//
	// TODO(perf): this runs on every HEAD heartbeat (~5s per replica).
	// The current implementation pulls up to (pendingJobsHeaderCap+1)
	// rows and filters AttemptCount <= MaxRetries in Go because Ent
	// doesn't expose field-vs-field comparisons. With many pending jobs
	// per capability the SELECT + Go-side filter becomes measurable.
	// Follow-up: drop into a raw SQL predicate (`attempt_count <=
	// max_retries`) via Ent's `sql.OrderBy`/raw predicate so the DB
	// does the comparison directly. Acceptable as-is for v1 (cap of
	// 100 rows + small audience). Tracking issue: TBD.
	type minimal struct {
		AttemptCount int `json:"attempt_count"`
		MaxRetries   int `json:"max_retries"`
	}
	var rows []minimal
	if err := s.entDB.Client.Job.Query().
		Where(
			job.StatusEQ(job.StatusWorking),
			job.OwnerInstanceIDIsNil(),
			job.CapabilityIn(caps...),
		).
		Limit(pendingJobsHeaderCap + 1).
		Select(job.FieldAttemptCount, job.FieldMaxRetries).
		Scan(ctx, &rows); err != nil {
		return 0, fmt.Errorf("count pending jobs for agent group %s: %w", a.Name, err)
	}

	count := 0
	for _, r := range rows {
		if r.AttemptCount <= r.MaxRetries {
			count++
			if count >= pendingJobsHeaderCap {
				return pendingJobsHeaderCap, nil
			}
		}
	}
	return count, nil
}

// ResetOrphanedJobs handles the orphan-reroute phase of the registry sweep.
// For every working job whose owner_instance_id no longer maps to a
// registered agent row, the job is either:
//
//   - reset to claimable (owner=NULL, lease cleared) when attempt_count <=
//     max_retries — the next live replica picks it up via POST /jobs/claim.
//     attempt_count is NOT incremented here; the claim itself counts as
//     the attempt (see ClaimNextJob's AddAttemptCount(1)).
//
//   - marked failed (status=failed, error="orphaned: max retries exceeded")
//     when attempt_count > max_retries — no claim path will retry it.
//
// Semantic: max_retries = retries on top of the initial attempt
// (Sidekiq/Celery/Resque convention). attempt_count is incremented at
// claim time, so a crashed first attempt has attempt_count=1, and a job
// with max_retries=1 still has retry budget (1 <= 1).
//
// Detection signal: owner_instance_id is either not in the agents table
// OR points to an agent whose status is not `healthy`. An
// unhealthy/unknown owner is treated as effectively gone — its pinned
// jobs are released so capability-matching agents can pick them up.
// This shortcuts the previous two-stage path (wait for retention →
// purge agent → release jobs) which left pinned jobs stalled for the
// retention period (default 1h) after a deliberate `meshctl stop`.
// Payload-based MeshJob semantics make this safe: `submitted_payload`
// is self-contained, so any healthy agent with the matching capability
// can resume work once `owner_instance_id` is cleared.
func (s *EntService) ResetOrphanedJobs(ctx context.Context) (reset, exhausted int, err error) {
	// Collect candidate orphan jobs: working + has an owner.
	candidates, err := s.entDB.Client.Job.Query().
		Where(
			job.StatusEQ(job.StatusWorking),
			job.OwnerInstanceIDNotNil(),
		).
		All(ctx)
	if err != nil {
		return 0, 0, fmt.Errorf("query orphan candidates: %w", err)
	}
	if len(candidates) == 0 {
		return 0, 0, nil
	}

	// Build the set of distinct owner IDs once and resolve liveness in a
	// single query (avoids N round-trips for N orphans).
	ownerSet := make(map[string]struct{})
	for _, j := range candidates {
		if j.OwnerInstanceID != nil && *j.OwnerInstanceID != "" {
			ownerSet[*j.OwnerInstanceID] = struct{}{}
		}
	}
	ownerIDs := make([]string, 0, len(ownerSet))
	for id := range ownerSet {
		ownerIDs = append(ownerIDs, id)
	}

	liveSet := make(map[string]struct{})
	if len(ownerIDs) > 0 {
		var liveRows []string
		if err := s.entDB.Client.Agent.Query().
			Where(
				agent.IDIn(ownerIDs...),
				agent.StatusEQ(agent.StatusHealthy),
			).
			Select(agent.FieldID).
			Scan(ctx, &liveRows); err != nil {
			return 0, 0, fmt.Errorf("query live owners: %w", err)
		}
		for _, id := range liveRows {
			liveSet[id] = struct{}{}
		}
	}

	now := time.Now().UTC()
	for _, j := range candidates {
		if j.OwnerInstanceID == nil {
			continue
		}
		if _, alive := liveSet[*j.OwnerInstanceID]; alive {
			continue
		}

		if j.AttemptCount > j.MaxRetries {
			if _, uerr := s.entDB.Client.Job.UpdateOneID(j.ID).
				SetStatus(job.StatusFailed).
				SetError("orphaned: max retries exceeded").
				ClearLeaseExpiresAt().
				ClearOwnerInstanceID().
				SetLastHeartbeatAt(now).
				Save(ctx); uerr != nil {
				return reset, exhausted, fmt.Errorf("mark exhausted job %s: %w", j.ID, uerr)
			}
			exhausted++
			continue
		}

		if _, uerr := s.entDB.Client.Job.UpdateOneID(j.ID).
			ClearOwnerInstanceID().
			ClearLeaseExpiresAt().
			ClearLastHeartbeatAt().
			Save(ctx); uerr != nil {
			return reset, exhausted, fmt.Errorf("reset orphan job %s: %w", j.ID, uerr)
		}
		reset++
	}
	return reset, exhausted, nil
}

// ExpireDeadlinedJobs handles the total_deadline cron phase of the sweep.
// For every non-terminal job whose total_deadline (opt-in column; default
// is NULL = unlimited per Resolved Decisions) has passed, mark the job
// failed with reason "deadline_exceeded" and clear lease/owner so no
// further processing happens. The vast majority of jobs skip this phase
// entirely because the column is NULL.
func (s *EntService) ExpireDeadlinedJobs(ctx context.Context) (int, error) {
	now := time.Now().UTC()

	candidates, err := s.entDB.Client.Job.Query().
		Where(
			job.TotalDeadlineNotNil(),
			job.TotalDeadlineLT(now),
			job.StatusNotIn(job.StatusCompleted, job.StatusFailed, job.StatusCancelled),
		).
		All(ctx)
	if err != nil {
		return 0, fmt.Errorf("query deadlined jobs: %w", err)
	}
	if len(candidates) == 0 {
		return 0, nil
	}

	expired := 0
	for _, j := range candidates {
		if _, uerr := s.entDB.Client.Job.UpdateOneID(j.ID).
			SetStatus(job.StatusFailed).
			SetError("deadline_exceeded").
			ClearLeaseExpiresAt().
			ClearOwnerInstanceID().
			SetLastHeartbeatAt(now).
			Save(ctx); uerr != nil {
			return expired, fmt.Errorf("expire deadlined job %s: %w", j.ID, uerr)
		}
		expired++
	}
	return expired, nil
}
