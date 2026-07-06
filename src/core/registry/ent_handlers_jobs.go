package registry

// Handlers for the MeshJob substrate (long-running async tool calls). See
// MESHJOB_DESIGN.org for the full state machine, lease semantics, retry
// rules, and the push/pull submission modes.

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/registry/generated"
)

// cancelForwardTimeout is the wall-clock cap on the registry → owner
// HTTP forward in CancelJob. Short on purpose: if the owner doesn't ack
// quickly we proceed to mark the row cancelled regardless. The row is
// already terminal at that point, so a dropped forward only means the
// owner keeps executing until its next /jobs/batch delta is rejected
// as already_terminal — registry-side state stays correct either way.
const cancelForwardTimeout = 5 * time.Second

// cancelEventGraceDefault is the wall-clock pause between posting the
// synthetic "cancelled" event and HTTP-forwarding the cancel to the
// owner instance. The grace gives any producer parked on recv_event
// a window to observe the event and return cleanly before its task
// is interrupted via CancelledError. See issue #1032.
//
// Tunable via MCP_MESH_CANCEL_EVENT_GRACE_MS (positive integer); 0
// disables the grace and reverts to immediate cancel-forward (pre-#1032
// behavior).
const cancelEventGraceDefault = 200 * time.Millisecond

// cancelEventGraceMaxMs caps the operator-supplied
// MCP_MESH_CANCEL_EVENT_GRACE_MS. The grace is meant to be a "brief
// window" for producers parked on recv_event to wake and unwind
// cleanly; anything beyond ~10s starts blocking every cancel call
// for an operationally noticeable amount of time and is almost
// certainly a misconfiguration. Values above the cap are clamped
// with a logged warning rather than rejected, so a bad env var
// doesn't take down cancellation entirely.
const cancelEventGraceMaxMs = 10000

var (
	cancelGraceOnce   sync.Once
	cancelGraceCached time.Duration
)

// cancelEventGrace returns the cached grace duration. The env var is
// parsed exactly once (process lifetime) — repeat reads in the cancel
// handler hot path would re-tokenise the string on every call for no
// gain, since the registry-process environment doesn't change after
// startup. Operators tweaking the value must restart the registry,
// which matches every other env-driven knob in the registry.
func cancelEventGrace() time.Duration {
	cancelGraceOnce.Do(func() {
		cancelGraceCached = parseCancelEventGraceFromEnv()
	})
	return cancelGraceCached
}

func parseCancelEventGraceFromEnv() time.Duration {
	v := os.Getenv("MCP_MESH_CANCEL_EVENT_GRACE_MS")
	if v == "" {
		return cancelEventGraceDefault
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		// Malformed input falls back to the default. The runtime
		// warning is the operator-visible discovery surface for the
		// misconfiguration.
		log.Printf("[meshjob] warning: MCP_MESH_CANCEL_EVENT_GRACE_MS=%q is not a non-negative integer; falling back to %s", v, cancelEventGraceDefault)
		return cancelEventGraceDefault
	}
	if n > cancelEventGraceMaxMs {
		log.Printf("[meshjob] warning: MCP_MESH_CANCEL_EVENT_GRACE_MS=%d exceeds cap %dms; clamping", n, cancelEventGraceMaxMs)
		n = cancelEventGraceMaxMs
	}
	return time.Duration(n) * time.Millisecond
}

// CreateJob implements POST /jobs.
//
// Two submission modes are supported through a single endpoint:
//   - Push mode: the request includes `owner_instance_id` (the submitter has
//     pre-resolved a target replica via mesh dep resolution). The job row is
//     created with that instance pinned as owner.
//   - Pull mode: `owner_instance_id` is omitted. The row is created with
//     owner NULL; a capability replica must atomically claim it via
//     POST /jobs/claim before execution.
func (h *EntBusinessLogicHandlers) CreateJob(c *gin.Context) {
	var req generated.CreateJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	if req.Capability == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "capability is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.SubmittedBy == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "submitted_by is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.SubmittedPayload == nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "submitted_payload is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	maxRetries := 1
	if req.MaxRetries != nil {
		if *req.MaxRetries < 0 {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     "max_retries must be non-negative",
				Timestamp: time.Now().UTC(),
			})
			return
		}
		maxRetries = *req.MaxRetries
	}
	if req.MaxDuration != nil && *req.MaxDuration < 1 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "max_duration must be positive",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	created, err := h.entService.CreateJob(c.Request.Context(), &CreateJobInput{
		ID:               uuid.NewString(),
		Capability:       req.Capability,
		SubmittedBy:      req.SubmittedBy,
		SubmittedPayload: req.SubmittedPayload,
		OwnerInstanceID:  req.OwnerInstanceId,
		MaxRetries:       maxRetries,
		MaxDuration:      req.MaxDuration,
		TotalDeadline:    req.TotalDeadline,
	})
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to create job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.CreateJobResponse{
		Id:              created.ID,
		Status:          generated.JobStatus(string(created.Status)),
		OwnerInstanceId: created.OwnerInstanceID,
	}
	c.JSON(http.StatusCreated, resp)
}

// ListJobs implements GET /jobs (issue #973). Read-only observability
// endpoint backing the meshui Jobs page + future `meshctl` listing.
//
// Validation rules:
//   - `status` is a comma-separated list of JobStatus values. Empty / absent
//     = all statuses. Unknown tokens (e.g. "running") return 400.
//   - `limit` defaults to 50 and is bounded at [1, 200]. Out-of-range = 400.
//   - `cursor` is opaque; malformed cursors = 400 (never 500).
//
// Filters compose with AND; pagination order is (submitted_at DESC, id DESC).
func (h *EntBusinessLogicHandlers) ListJobs(c *gin.Context, _ generated.ListJobsParams) {
	// Bind from the same query string we received. We bind through our own
	// JobQueryParams (form-tagged) so the status csv -> []string split lives
	// here, not in oapi-generated code.
	var q JobQueryParams
	if err := c.ShouldBindQuery(&q); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid query parameters: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Distinguish "limit absent" (use default 50) from "limit=0" (invalid).
	// The form-tagged JobQueryParams binding can't tell the two apart on
	// its own — both decode to int(0). Peek the raw query to disambiguate.
	limit := q.Limit
	if _, present := c.Request.URL.Query()["limit"]; !present {
		limit = 50
	}
	if limit < 1 || limit > 200 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("limit must be in [1, 200], got %d", limit),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	var statuses []string
	if s := strings.TrimSpace(q.Status); s != "" {
		// Split, trim, validate each token against the JobStatus enum.
		// Reject the whole request on any unknown value rather than
		// silently dropping it — operators would rather see "you typo'd
		// running" than an empty result set.
		raw := strings.Split(s, ",")
		statuses = make([]string, 0, len(raw))
		for _, t := range raw {
			t = strings.TrimSpace(t)
			if t == "" {
				continue
			}
			switch generated.JobStatus(t) {
			case generated.Working, generated.InputRequired,
				generated.Completed, generated.Failed, generated.Cancelled:
				statuses = append(statuses, t)
			default:
				c.JSON(http.StatusBadRequest, generated.ErrorResponse{
					Error:     fmt.Sprintf("invalid status %q: must be one of working,input_required,completed,failed,cancelled", t),
					Timestamp: time.Now().UTC(),
				})
				return
			}
		}
	}

	resp, err := h.entService.ListJobs(c.Request.Context(), &JobsListInput{
		Statuses:        statuses,
		OwnerInstanceID: strings.TrimSpace(q.OwnerInstanceID),
		Capability:      strings.TrimSpace(q.Capability),
		SubmittedSince:  q.SubmittedSince,
		Limit:           limit,
		Cursor:          strings.TrimSpace(q.Cursor),
	})
	if err != nil {
		// Cursor decode failures surface as 400 — they're caller-induced,
		// not registry-side faults. Anything else is treated as a backend
		// problem (503).
		msg := err.Error()
		if strings.Contains(msg, "invalid cursor") || strings.Contains(msg, "invalid status") {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     msg,
				Timestamp: time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to list jobs: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	c.JSON(http.StatusOK, resp)
}

// GetJob implements GET /jobs/{job_id}. All status reads terminate here —
// no replica-side caching, no owner-bound routing. Possession of the
// job_id (UUID) is the capability for read access (presigned-URL semantics
// — see Auth model in the design doc).
func (h *EntBusinessLogicHandlers) GetJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	j, err := h.entService.GetJob(c.Request.Context(), jobId)
	if err != nil {
		if ent.IsNotFound(err) {
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to fetch job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	c.JSON(http.StatusOK, jobToAPI(j))
}

// SubmitJobBatch implements POST /jobs/batch.
//
// Accepts a coalesced batch of per-job deltas from a single producer
// instance. Each delta is applied independently — partial success is the
// spec; rejections are surfaced per-id with a stable reason code.
//
// Every accepted non-terminal delta extends the job's lease (see
// ApplyJobDeltas), so this endpoint doubles as the producer's heartbeat
// against the expired-lease sweep.
func (h *EntBusinessLogicHandlers) SubmitJobBatch(c *gin.Context) {
	var req generated.JobBatchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.InstanceId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if len(req.Deltas) == 0 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "deltas must not be empty",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	deltas := make([]JobDeltaInput, 0, len(req.Deltas))
	for _, d := range req.Deltas {
		if d.Id == "" {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     "every delta requires a non-empty id",
				Timestamp: time.Now().UTC(),
			})
			return
		}
		in := JobDeltaInput{
			ID:              d.Id,
			ClaimEpoch:      d.ClaimEpoch,
			ProgressMessage: d.ProgressMessage,
			Error:           d.Error,
		}
		if d.Progress != nil {
			p := float64(*d.Progress)
			in.Progress = &p
		}
		if d.Status != nil {
			s := string(*d.Status)
			in.Status = &s
		}
		if d.Result != nil {
			in.Result = *d.Result
		}
		if d.RecvCursor != nil {
			in.RecvCursor = *d.RecvCursor
		}
		deltas = append(deltas, in)
	}

	accepted, rejections, err := h.entService.ApplyJobDeltas(c.Request.Context(), req.InstanceId, deltas)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to apply deltas: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.JobBatchResponse{Accepted: accepted}
	resp.Rejected = make([]struct {
		Id     string `json:"id"`
		Reason string `json:"reason"`
	}, 0, len(rejections))
	for _, r := range rejections {
		resp.Rejected = append(resp.Rejected, struct {
			Id     string `json:"id"`
			Reason string `json:"reason"`
		}{Id: r.ID, Reason: r.Reason})
	}
	c.JSON(http.StatusOK, resp)
}

// ClaimJobs implements POST /jobs/claim.
//
// Single-claim per round-trip (see Resolved Decisions). Race-free across
// concurrent claimers via guarded UPDATE inside the service layer; "no
// work available" is a 200 with claimed=[] (not an error).
//
// Fencing: every successful claim bumps the job's claim_epoch (see
// ClaimNextJob), returned here as ClaimedJob.claim_epoch. The owner echoes it
// on /jobs/batch deltas and on executor reads of GET /jobs/{id}/events; a
// reclaim + fresh claim (even by the SAME instance in a single-replica
// deployment) mints a new epoch, so the previous execution's writes and reads
// are fenced as claim_superseded. State stays consistent (the first terminal
// delta wins) AND the superseded handler is signalled to abort. See
// ReclaimExpiredLeaseJobs and AuthorizeExecutorRead.
func (h *EntBusinessLogicHandlers) ClaimJobs(c *gin.Context) {
	var req generated.ClaimJobsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.Capability == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "capability is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if req.InstanceId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	claimed, err := h.entService.ClaimNextJob(c.Request.Context(), req.Capability, req.InstanceId)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to claim job: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.ClaimJobsResponse{Claimed: []generated.ClaimedJob{}}
	if claimed != nil {
		entry := generated.ClaimedJob{
			Id:               claimed.ID,
			AttemptCount:     claimed.AttemptCount,
			ClaimEpoch:       claimed.ClaimEpoch,
			SubmittedPayload: claimed.SubmittedPayload,
			MaxDuration:      claimed.MaxDuration,
		}
		if claimed.LeaseExpiresAt != nil {
			v := int(claimed.LeaseExpiresAt.Unix())
			entry.LeaseExpiresAt = &v
		}
		// Return the persisted durable recvEvent cursor (issue #1277) so a
		// re-claimed controller can resume after the last processed position.
		// nil (never recorded) → omitted.
		if claimed.RecvCursor != nil {
			rc := claimed.RecvCursor
			entry.RecvCursor = &rc
		}
		resp.Claimed = append(resp.Claimed, entry)
	}
	c.JSON(http.StatusOK, resp)
}

// ReleaseJob implements POST /jobs/{job_id}/release.
//
// Producer-side voluntary lease release. Called by the SDK when a tool
// handler raises an exception that matches the tool's `retry_on` whitelist —
// instead of marking the job failed (which burns the retry budget on a
// transient error), the SDK calls release so a peer replica can re-claim
// the job within ~5s (the HEAD-heartbeat cadence).
//
// Validates:
//   - 404 when the job_id is unknown
//   - 403 when caller's instance_id != current owner_instance_id
//     (release is owner-only — only the holding replica may relinquish)
//   - 409 when the job is already terminal (cannot release a finished job)
//
// On success the response carries the post-update status and attempt_count.
// Status stays `working` when there's retry budget left (claim already
// incremented attempt_count when picking the row up; release does NOT
// increment). Transitions to `failed` (terminal, with
// `error="exhausted (release): <reason>"`) when the row's existing
// attempt_count is already past max_retries — i.e. the handler raised on
// the row's final allowed attempt.
func (h *EntBusinessLogicHandlers) ReleaseJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	var req generated.ReleaseJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	if strings.TrimSpace(req.InstanceId) == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	instanceID := strings.TrimSpace(req.InstanceId)
	reason := ""
	if req.Reason != nil {
		reason = *req.Reason
	}

	updated, err := h.entService.ReleaseJob(c.Request.Context(), jobId, instanceID, reason)
	if err != nil {
		switch {
		case ent.IsNotFound(err):
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobNotOwner):
			c.JSON(http.StatusForbidden, generated.ErrorResponse{
				Error:     "caller is not the current owner of this job",
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobAlreadyTerminal):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job is already in a terminal state",
				Timestamp: time.Now().UTC(),
			})
		default:
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to release job: %v", err),
				Timestamp: time.Now().UTC(),
			})
		}
		return
	}

	resp := generated.ReleaseJobResponse{
		Status:       generated.JobStatus(string(updated.Status)),
		AttemptCount: updated.AttemptCount,
	}
	c.JSON(http.StatusOK, resp)
}

// CancelJob implements POST /jobs/{job_id}/cancel.
//
// Three scenarios per the design:
//   - Owned (alive): registry forwards cancel to the owner replica's HTTP
//     endpoint, then marks the row cancelled regardless of forward outcome
//     (best-effort forward; the row is terminal regardless, so registry
//     state is correct even when the forward is dropped).
//   - Unowned (orphan / pre-claim): registry directly marks cancelled.
//   - Already terminal: 409 Conflict.
//
// Ordering (see issue #1032 / tc26): status transition → synthetic
// "cancelled" event post → grace window → HTTP cancel-forward. The grace
// gives a producer parked on recv_event a chance to observe the synthetic
// event and unwind cleanly before the forward raises CancelledError on
// the task body. See cancelEventGrace().
func (h *EntBusinessLogicHandlers) CancelJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Body is optional. Absence/empty body is fine.
	var req generated.CancelJobRequest
	if c.Request.ContentLength > 0 {
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, generated.ErrorResponse{
				Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
				Timestamp: time.Now().UTC(),
			})
			return
		}
	}
	reason := ""
	if req.Reason != nil {
		reason = *req.Reason
	}

	updated, prevOwner, err := h.entService.CancelJob(c.Request.Context(), jobId, reason)
	if err != nil {
		switch {
		case ent.IsNotFound(err):
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobAlreadyTerminal):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job is already in a terminal state",
				Timestamp: time.Now().UTC(),
			})
		default:
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to cancel job: %v", err),
				Timestamp: time.Now().UTC(),
			})
		}
		return
	}

	// Synthetic event: any task=True handler currently parked on
	// recv_event sees a `{type: "cancelled"}` event in its log and can
	// unwind cleanly. We post AFTER the registry row has transitioned
	// to terminal=cancelled, so allowTerminal=true bypasses the
	// "no events on terminal jobs" guard. Best-effort: if the post fails
	// the cancel itself still succeeded — log and continue.
	//
	// Use a detached background context (with a small timeout) for the
	// write so a client disconnect mid-cancel doesn't strand the
	// synthetic event. The registry row is already terminal at this
	// point; landing the event is what lets long-polling consumers
	// unwind cleanly, and we don't want that bound to the caller's
	// connection liveness. The grace-window wait below still honours
	// c.Request.Context() so a disconnected caller doesn't pay for the
	// full grace.
	evCtx, evCancel := context.WithTimeout(context.Background(), 5*time.Second)
	if _, _, evErr := h.entService.PostJobEvent(
		evCtx,
		jobId,
		"cancelled",
		map[string]interface{}{"reason": reason},
		nil,
		extractPostedByIdentity(c),
		true,
	); evErr != nil {
		log.Printf("[meshjob] warning: failed to post synthetic cancel event for job %s: %v", jobId, evErr)
	}
	evCancel()

	// Grace window for producers parked on recv_event to observe the
	// synthetic event and return cleanly before the HTTP cancel-forward
	// raises CancelledError on the task body. See issue #1032 / tc26.
	//
	// Honour the client's request context — if the caller disconnects
	// (e.g. ctrl-C'd a `meshctl jobs cancel`) we abandon the grace
	// immediately rather than holding the goroutine for up to 10s. The
	// registry row is already terminal at this point, so the synthetic
	// event has landed regardless of whether we sleep out the full
	// grace; cutting it short on disconnect just saves a goroutine.
	if grace := cancelEventGrace(); grace > 0 {
		select {
		case <-c.Request.Context().Done():
			// Client gone; skip the wait.
		case <-time.After(grace):
		}
	}

	// Best-effort owner notification. Errors are logged but never affect
	// the response — the registry row is the source of truth (already
	// terminal=cancelled), so a missed forward only means the owner keeps
	// working until its next /jobs/batch delta is rejected as
	// already_terminal.
	resp := generated.CancelJobResponse{
		Status:                generated.JobStatus(string(updated.Status)),
		ForwardedToInstanceId: prevOwner,
	}
	if prevOwner != nil {
		h.forwardCancelToOwner(c, *prevOwner, jobId, reason)
	}
	c.JSON(http.StatusOK, resp)
}

// ReclaimJob implements POST /jobs/{job_id}/reclaim.
//
// Admin force-reclaim: forces the lease-expiry path for a single job exactly
// as the sweep's ReclaimExpiredLeaseJobs does — clears owner + lease +
// last_heartbeat, normalises status to `working` so the row is claimable
// again, and leaves claim_epoch UNTOUCHED (the next claim mints the new
// generation, fencing the superseded execution). See ForceReclaimJob.
//
// Terminal jobs are rejected 409 (mirrors CancelJob's already-terminal idiom)
// — there is no owner to evict. Same auth posture as CancelJob (possession of
// job_id is the capability).
func (h *EntBusinessLogicHandlers) ReclaimJob(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	updated, prevOwner, err := h.entService.ForceReclaimJob(c.Request.Context(), jobId)
	if err != nil {
		switch {
		case ent.IsNotFound(err):
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobAlreadyTerminal):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job is already in a terminal state",
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobReclaimConflict):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job was re-claimed concurrently; reclaim not applied",
				Timestamp: time.Now().UTC(),
			})
		default:
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to reclaim job: %v", err),
				Timestamp: time.Now().UTC(),
			})
		}
		return
	}

	c.JSON(http.StatusOK, generated.ReclaimJobResponse{
		Status:                  generated.JobStatus(string(updated.Status)),
		PreviousOwnerInstanceId: prevOwner,
		ClaimEpoch:              updated.ClaimEpoch,
	})
}

// forwardCancelToOwner POSTs the cancel to the owner agent's HTTP endpoint
// best-effort. Any failure (agent unknown, unreachable, non-2xx) is logged
// and swallowed: the registry row already shows status=cancelled, and a
// missed forward only delays the owner noticing via its next rejected
// /jobs/batch delta.
//
// Scheme handling: when the agent registered an entity_id (i.e. presented
// a TLS client cert at registration time) we dial https with the registry's
// own mTLS bundle. Otherwise we dial http. Mirrors the scheme-selection
// in proxyRequest's isRegisteredAgentEndpoint path.
//
// Trace-header propagation matches the proxy path (#310) — we set the
// well-known headers explicitly rather than going through the
// MCP_MESH_PROPAGATE_HEADERS allowlist because the cancel forward is a
// fixed, registry-internal destination and no operator opt-in is needed.
//
// Goroutine-driven dispatch: the cancel response to the original HTTP
// caller does NOT wait for the forward to land. The registry row is
// already marked cancelled before this is called; the forward is purely
// a best-effort signal to abort an in-flight handler. Spawning the
// forward into a goroutine keeps the public response p99 close to the
// DB write latency rather than the owner-agent round-trip + 5s timeout.
//
// Shutdown coordination: when the handlers were constructed with the
// production ``NewEntBusinessLogicHandlersWithShutdown`` constructor,
// the goroutine derives its HTTP-request context from
// ``h.shutdownCtx`` and registers on ``h.shutdownWG``. ``Server.Stop``
// cancels ``shutdownCtx`` (cleanly aborting in-flight forwards via the
// transport's context-cancellation hook) and then waits on
// ``shutdownWG`` for the goroutines to drain — surfacing any abandoned
// forwards in the log instead of letting them run on after the
// registry is supposedly stopped. When constructed with the legacy
// zero-arg ``NewEntBusinessLogicHandlers`` (tests), the parent context
// falls back to ``context.Background()`` and the WaitGroup is a
// private no-op so the existing best-effort behaviour is preserved.
func (h *EntBusinessLogicHandlers) forwardCancelToOwner(c *gin.Context, ownerInstanceID, jobID, reason string) {
	// Capture the request-scoped values BEFORE detaching: the request
	// context dies when the response is sent, so we copy headers we
	// need and derive the forward context from the server's
	// shutdown-aware context (see struct doc) so a registry stop cleanly
	// aborts in-flight forwards instead of letting them run to their
	// 5s per-call timeout on a goroutine the process can't observe.
	traceID := c.Request.Header.Get("X-Trace-ID")
	parentSpan := c.Request.Header.Get("X-Parent-Span")
	meshTimeout := c.Request.Header.Get("X-Mesh-Timeout")

	parentCtx := h.shutdownCtx
	if parentCtx == nil {
		parentCtx = context.Background()
	}

	// Reserve a slot on the shutdown WaitGroup BEFORE go-statement so a
	// shutdown that races with this handler still observes the goroutine
	// in its Wait. The matching Done() lives at the top of the goroutine
	// via ``defer`` so a panic inside the forward can't leak the slot.
	h.shutdownWG.Add(1)

	go func() {
		defer h.shutdownWG.Done()

		fwdCtx, cancel := context.WithTimeout(parentCtx, cancelForwardTimeout)
		defer cancel()

		agentRow, err := h.entService.GetAgent(fwdCtx, ownerInstanceID)
		if err != nil || agentRow == nil {
			log.Printf("[meshjob] cancel forward skipped: owner %q not found in registry (job=%s, err=%v)", ownerInstanceID, jobID, err)
			return
		}
		if agentRow.HTTPHost == "" || agentRow.HTTPPort == 0 {
			log.Printf("[meshjob] cancel forward skipped: owner %q has no HTTP endpoint registered (job=%s)", ownerInstanceID, jobID)
			return
		}

		// Scheme: https only when the agent has registered an entity_id
		// (mTLS bundle present). Matches the scheme decision baked into
		// the agents-list endpoint and proxyRequest's
		// isRegisteredAgentEndpoint path.
		scheme := "http"
		if agentRow.EntityID != nil && *agentRow.EntityID != "" {
			scheme = "https"
		}
		url := fmt.Sprintf("%s://%s:%d/jobs/%s/cancel", scheme, agentRow.HTTPHost, agentRow.HTTPPort, jobID)

		body := strings.NewReader("")
		if reason != "" {
			// Mirror the on-wire CancelJobRequest shape so the agent runtime
			// can decode the same struct it would on a direct client call.
			body = strings.NewReader(fmt.Sprintf(`{"reason":%q}`, reason))
		}

		req, err := http.NewRequestWithContext(fwdCtx, http.MethodPost, url, body)
		if err != nil {
			log.Printf("[meshjob] cancel forward build failed (owner=%s, job=%s): %v", ownerInstanceID, jobID, err)
			return
		}
		req.Header.Set("Content-Type", "application/json")

		if traceID != "" {
			req.Header.Set("X-Trace-ID", traceID)
		}
		if parentSpan != "" {
			req.Header.Set("X-Parent-Span", parentSpan)
		}
		if meshTimeout != "" {
			req.Header.Set("X-Mesh-Timeout", meshTimeout)
		}

		client, err := h.cancelForwardClient(scheme)
		if err != nil {
			log.Printf("[meshjob] cancel forward TLS init failed (owner=%s, job=%s): %v", ownerInstanceID, jobID, err)
			return
		}

		resp, err := client.Do(req)
		if err != nil {
			// Distinguish a registry-shutdown cancellation from a "real"
			// network error so operators see that the forward was
			// abandoned by us, not lost to an owner-side fault.
			// ``parentCtx.Err()`` is sticky once the parent is cancelled,
			// so checking it here reliably attributes the failure to
			// shutdown even when ``fwdCtx`` reports the wrapped
			// cancellation.
			if parentCtx.Err() != nil {
				log.Printf("[meshjob] cancel forward to %s abandoned: registry shutting down (job=%s, err=%v)", url, jobID, err)
			} else {
				log.Printf("[meshjob] cancel forward to %s failed (job=%s): %v", url, jobID, err)
			}
			return
		}
		defer resp.Body.Close()
		// Drain to allow connection reuse; ignore body content.
		_, _ = io.Copy(io.Discard, resp.Body)
		if resp.StatusCode >= 300 {
			log.Printf("[meshjob] cancel forward to %s returned status %d (job=%s)", url, resp.StatusCode, jobID)
		}
	}()
}

// cancelForwardClient builds a one-shot http.Client for forwarding a
// cancel to an owner agent. For ``https`` targets we attach the same
// mTLS configuration (CA + client cert/key, peer chain verification with
// hostname verification disabled) that proxyRequest uses — the same env
// vars (MCP_MESH_TLS_CA / _CERT / _KEY) gate both code paths so misconfig
// surfaces consistently.
func (h *EntBusinessLogicHandlers) cancelForwardClient(scheme string) (*http.Client, error) {
	client := &http.Client{Timeout: cancelForwardTimeout}
	if scheme != "https" {
		return client, nil
	}

	caPath := os.Getenv("MCP_MESH_TLS_CA")
	certPath := os.Getenv("MCP_MESH_TLS_CERT")
	keyPath := os.Getenv("MCP_MESH_TLS_KEY")
	if caPath == "" || certPath == "" || keyPath == "" {
		return nil, fmt.Errorf("https cancel forward requires MCP_MESH_TLS_CA / MCP_MESH_TLS_CERT / MCP_MESH_TLS_KEY (got ca=%q cert=%q key=%q)", caPath, certPath, keyPath)
	}

	caBytes, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", caPath, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caBytes) {
		return nil, fmt.Errorf("parse CA cert from %s (empty or malformed PEM)", caPath)
	}

	clientCert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load client cert/key (%s, %s): %w", certPath, keyPath, err)
	}

	tlsConfig := &tls.Config{
		// Skip hostname check (--tls-auto certs are 127.0.0.1/::1 SANs only)
		// but still verify the peer chain against the mesh CA.
		InsecureSkipVerify: true,
		Certificates:       []tls.Certificate{clientCert},
		VerifyConnection: func(cs tls.ConnectionState) error {
			if len(cs.PeerCertificates) == 0 {
				return fmt.Errorf("no peer certificates presented")
			}
			opts := x509.VerifyOptions{
				Roots:         caPool,
				Intermediates: x509.NewCertPool(),
			}
			for _, cert := range cs.PeerCertificates[1:] {
				opts.Intermediates.AddCert(cert)
			}
			_, err := cs.PeerCertificates[0].Verify(opts)
			return err
		},
	}
	client.Transport = &http.Transport{TLSClientConfig: tlsConfig}
	return client, nil
}

// jobToAPI converts an Ent Job entity into the OpenAPI Job representation.
//
// Field mapping notes:
//   - Time fields (submitted_at, lease_expires_at, last_heartbeat_at,
//     total_deadline) are persisted as time.Time but exposed as Unix epoch
//     seconds (`integer`) per the OpenAPI schema.
//   - `progress` is float64 in Ent but float32 in the generated API type.
func jobToAPI(j *ent.Job) generated.Job {
	api := generated.Job{
		Id:               j.ID,
		Capability:       j.Capability,
		Status:           generated.JobStatus(string(j.Status)),
		SubmittedPayload: j.SubmittedPayload,
		AttemptCount:     j.AttemptCount,
		ClaimEpoch:       j.ClaimEpoch,
		MaxRetries:       j.MaxRetries,
		SubmittedAt:      int(j.SubmittedAt.Unix()),
		OwnerInstanceId:  j.OwnerInstanceID,
		ProgressMessage:  j.ProgressMessage,
		Error:            j.Error,
		MaxDuration:      j.MaxDuration,
	}
	if j.Progress != nil {
		p := float32(*j.Progress)
		api.Progress = &p
	}
	if j.Result != nil {
		r := j.Result
		api.Result = &r
	}
	if j.SubmittedBy != nil {
		api.SubmittedBy = *j.SubmittedBy
	}
	if j.TotalDeadline != nil {
		v := int(j.TotalDeadline.Unix())
		api.TotalDeadline = &v
	}
	if j.LeaseExpiresAt != nil {
		v := int(j.LeaseExpiresAt.Unix())
		api.LeaseExpiresAt = &v
	}
	if j.LastHeartbeatAt != nil {
		v := int(j.LastHeartbeatAt.Unix())
		api.LastHeartbeatAt = &v
	}
	return api
}

// CreateJobInput collects the fields the service layer needs to persist a
// new job row. Mirrors the OpenAPI CreateJobRequest plus a server-generated
// ID so the handler controls UUID minting.
type CreateJobInput struct {
	ID               string
	Capability       string
	SubmittedBy      string
	SubmittedPayload map[string]interface{}
	OwnerInstanceID  *string
	MaxRetries       int
	MaxDuration      *int
	TotalDeadline    *int // Unix epoch seconds; converted to time.Time on persist
}

// listJobEventsMaxWait caps the long-poll timeout to 60 seconds. Mirrors
// the OpenAPI `wait` parameter's `maximum: 60` — kept here as a server-side
// guard so a hand-rolled client bypassing schema validation can't pin a
// goroutine for hours.
const listJobEventsMaxWait = 60

// listJobEventsMaxLimit mirrors the OpenAPI `limit` schema's maximum.
const listJobEventsMaxLimit = 500

// PostJobEvent implements POST /jobs/{job_id}/events.
//
// Appends an event to the per-job event log. Sequence numbers are assigned
// server-side as a per-job monotonic counter (UNIQUE (job_id, seq) index
// enforces the invariant under concurrent posters; the service layer
// retries on conflict).
//
// Returns 404 if the parent job is unknown, 409 if the job is already
// terminal (external posters can't inject events into a finished job —
// the internal CancelJob path opts past this guard via allowTerminal).
func (h *EntBusinessLogicHandlers) PostJobEvent(c *gin.Context, jobId string) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	var req generated.JobEventPostRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	normalizedType := strings.TrimSpace(req.Type)
	if normalizedType == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "type is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	payload := req.Payload
	var traceContext map[string]interface{}
	if req.TraceContext != nil {
		traceContext = *req.TraceContext
	}

	postedBy := extractPostedByIdentity(c)

	seq, createdAt, err := h.entService.PostJobEvent(
		c.Request.Context(),
		jobId,
		normalizedType,
		payload,
		traceContext,
		postedBy,
		false, // not the internal cancel path
	)
	if err != nil {
		switch {
		case errors.Is(err, ErrJobNotFound):
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
		case errors.Is(err, ErrJobTerminal):
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     "job is already in a terminal state",
				Timestamp: time.Now().UTC(),
			})
		default:
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to post job event: %v", err),
				Timestamp: time.Now().UTC(),
			})
		}
		return
	}

	c.JSON(http.StatusOK, generated.JobEventPostResponse{
		JobId:     jobId,
		Seq:       seq,
		CreatedAt: int(createdAt.Unix()),
	})
}

// ListJobEvents implements GET /jobs/{job_id}/events.
//
// Returns events with seq > after, optionally filtered to a comma-separated
// allowlist of types. When `wait` is non-zero (capped at 60s) the call
// long-polls — the registry sleeps in 100ms increments until matching
// events arrive or the deadline expires.
//
// next_after in the response is the seq of the last returned event (or the
// same `after` the caller sent if nothing arrived). Callers feed it back
// in to skip past already-seen events.
//
// Executor vs. observer read: when the caller supplies BOTH instance_id and
// claim_epoch the read is fenced against the job's current owner + claim
// generation — a stale pair returns 409 claim_superseded, a matching pair on
// a live job extends the lease (poll-liveness credit). Either param absent is
// an anonymous observer read, served unchanged with no lease side-effects.
func (h *EntBusinessLogicHandlers) ListJobEvents(c *gin.Context, jobId string, params generated.ListJobEventsParams) {
	if jobId == "" {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "job_id is required",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Executor vs. observer read. Both instance_id AND claim_epoch identify
	// the caller as the job's current owner: the read is fenced (409
	// claim_superseded if stale) and, when valid, extends the lease
	// (poll-liveness). Either param absent ⇒ anonymous observer read, served
	// byte-identically to before with no lease side-effects (A2A / UI /
	// meshctl / recv_event-without-identity all rely on this).
	hasInstance := params.InstanceId != nil && *params.InstanceId != ""
	hasEpoch := params.ClaimEpoch != nil
	if hasInstance != hasEpoch {
		// Half-supplied identity: the two params are paired by contract, so a
		// lone one is almost certainly an SDK bug. Fail loudly rather than
		// silently degrading to an observer read (which would drop fencing and
		// poll-liveness credit without any signal).
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "instance_id and claim_epoch must be supplied together (both for an executor read, or neither for an observer read)",
			Timestamp: time.Now().UTC(),
		})
		return
	}
	executorRead := hasInstance && hasEpoch
	if executorRead {
		outcome, err := h.entService.AuthorizeExecutorRead(
			c.Request.Context(), jobId, *params.InstanceId, *params.ClaimEpoch,
		)
		if err != nil {
			if errors.Is(err, ErrJobNotFound) {
				c.JSON(http.StatusNotFound, generated.ErrorResponse{
					Error:     fmt.Sprintf("job not found: %s", jobId),
					Timestamp: time.Now().UTC(),
				})
				return
			}
			c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
				Error:     fmt.Sprintf("Failed to authorize executor read: %v", err),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		if outcome == ExecutorReadSuperseded {
			c.JSON(http.StatusConflict, generated.ErrorResponse{
				Error:     JobDeltaRejectionClaimSuperseded,
				Timestamp: time.Now().UTC(),
			})
			return
		}
		// ExecutorReadExtended / ExecutorReadTerminal fall through to serve
		// events exactly as an observer read would (terminal jobs got no lease
		// write; live matches got their lease extended above). AuthorizeExecutorRead
		// already proved the job exists, so the event read below skips the
		// redundant existence lookup (see executorRead branch).
	}

	after := int64(0)
	if params.After != nil && *params.After > 0 {
		after = *params.After
	}

	var types []string
	if params.Types != nil {
		raw := strings.Split(*params.Types, ",")
		for _, t := range raw {
			t = strings.TrimSpace(t)
			if t != "" {
				types = append(types, t)
			}
		}
	}

	waitSeconds := 0
	if params.Wait != nil {
		waitSeconds = *params.Wait
		if waitSeconds < 0 {
			waitSeconds = 0
		}
		if waitSeconds > listJobEventsMaxWait {
			waitSeconds = listJobEventsMaxWait
		}
	}

	limit := 100
	if params.Limit != nil && *params.Limit > 0 {
		limit = *params.Limit
		if limit > listJobEventsMaxLimit {
			limit = listJobEventsMaxLimit
		}
	}

	// Executor reads already confirmed existence in AuthorizeExecutorRead, so
	// they use the existence-check-free core; observer reads use the public
	// wrapper (which does the Exist lookup that surfaces 404).
	var (
		events []*ent.JobEvent
		err    error
	)
	if executorRead {
		events, err = h.entService.listJobEventsCore(
			c.Request.Context(),
			jobId,
			after,
			types,
			time.Duration(waitSeconds)*time.Second,
			limit,
		)
	} else {
		events, err = h.entService.ListJobEvents(
			c.Request.Context(),
			jobId,
			after,
			types,
			time.Duration(waitSeconds)*time.Second,
			limit,
		)
	}
	if err != nil {
		if errors.Is(err, ErrJobNotFound) {
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("job not found: %s", jobId),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to list job events: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	resp := generated.JobEventListResponse{
		Events:    make([]generated.JobEvent, 0, len(events)),
		NextAfter: after,
	}
	for _, e := range events {
		resp.Events = append(resp.Events, jobEventToAPI(e))
		if e.Seq > resp.NextAfter {
			resp.NextAfter = e.Seq
		}
	}
	c.JSON(http.StatusOK, resp)
}

// jobEventToAPI converts an Ent JobEvent into the OpenAPI representation.
// Mirrors jobToAPI's field-mapping style: Time fields exposed as Unix epoch
// seconds; optional JSON columns surfaced via the generated pointer type.
func jobEventToAPI(e *ent.JobEvent) generated.JobEvent {
	out := generated.JobEvent{
		JobId:     e.JobID,
		Seq:       e.Seq,
		Type:      e.Type,
		CreatedAt: int(e.CreatedAt.Unix()),
	}
	if len(e.Payload) > 0 {
		// Payload is stored as raw JSON bytes; decode back to a
		// language-agnostic interface{} so arbitrary JSON shapes
		// (object / array / scalar) round-trip through the API. On
		// decode failure (corrupt row), surface the raw text rather
		// than dropping the field silently.
		var v interface{}
		if err := json.Unmarshal(e.Payload, &v); err == nil {
			out.Payload = v
		} else {
			out.Payload = string(e.Payload)
		}
	}
	if len(e.TraceContext) > 0 {
		tc := map[string]interface{}(e.TraceContext)
		out.TraceContext = &tc
	}
	if e.PostedBy != nil {
		v := *e.PostedBy
		out.PostedBy = &v
	}
	return out
}

// extractPostedByIdentity recovers the sender's identity for a job-event
// post. The TLS middleware sets `entity_id` in the gin context on every
// mTLS-authenticated request; absence is normal in tests and in
// non-TLS local deployments — we return "" and let the service layer
// treat the field as optional.
func extractPostedByIdentity(c *gin.Context) string {
	if v, ok := c.Get("entity_id"); ok {
		if id, ok := v.(string); ok {
			return id
		}
	}
	return ""
}
