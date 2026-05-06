package registry

// Handlers for the MeshJob substrate (long-running async tool calls). See
// MESHJOB_DESIGN.org for the full state machine, lease semantics, retry
// rules, and the push/pull submission modes.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/registry/generated"
)

// cancelForwardTimeout is the wall-clock cap on the registry → owner
// HTTP forward in CancelJob. Short on purpose: if the owner doesn't ack
// quickly we proceed to mark the row cancelled regardless. The
// heartbeat/lease + sweep loop guarantees correctness even when the
// forward is dropped.
const cancelForwardTimeout = 5 * time.Second

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
			SubmittedPayload: claimed.SubmittedPayload,
			MaxDuration:      claimed.MaxDuration,
		}
		if claimed.LeaseExpiresAt != nil {
			v := int(claimed.LeaseExpiresAt.Unix())
			entry.LeaseExpiresAt = &v
		}
		resp.Claimed = append(resp.Claimed, entry)
	}
	c.JSON(http.StatusOK, resp)
}

// CancelJob implements POST /jobs/{job_id}/cancel.
//
// Three scenarios per the design:
//   - Owned (alive): registry forwards cancel to the owner replica's HTTP
//     endpoint, then marks the row cancelled regardless of forward outcome
//     (best-effort forward; lease/sweep guarantees eventual correctness).
//   - Unowned (orphan / pre-claim): registry directly marks cancelled.
//   - Already terminal: 409 Conflict.
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

	// Best-effort owner notification. Errors are logged but never affect
	// the response — the registry row is the source of truth, and the
	// owner's lease will time out even if the forward never lands.
	resp := generated.CancelJobResponse{
		Status:                generated.JobStatus(string(updated.Status)),
		ForwardedToInstanceId: prevOwner,
	}
	if prevOwner != nil {
		h.forwardCancelToOwner(c, *prevOwner, jobId, reason)
	}
	c.JSON(http.StatusOK, resp)
}

// forwardCancelToOwner POSTs the cancel to the owner agent's HTTP endpoint
// best-effort. Any failure (agent unknown, unreachable, non-2xx) is logged
// and swallowed: the registry row already shows status=cancelled, and the
// owner's lease will expire if the message is missed.
//
// Header propagation matches proxyRequest in ent_handlers.go (#310 trace
// headers + X-Mesh-Timeout). We deliberately do not pull in the heavier
// mTLS path here — Phase 1 ships HTTP forwarding only; HTTPS support
// piggybacks on the proxy refactor later.
func (h *EntBusinessLogicHandlers) forwardCancelToOwner(c *gin.Context, ownerInstanceID, jobID, reason string) {
	ctx := c.Request.Context()

	agentRow, err := h.entService.GetAgent(ctx, ownerInstanceID)
	if err != nil || agentRow == nil {
		log.Printf("[meshjob] cancel forward skipped: owner %q not found in registry (job=%s, err=%v)", ownerInstanceID, jobID, err)
		return
	}
	if agentRow.HTTPHost == "" || agentRow.HTTPPort == 0 {
		log.Printf("[meshjob] cancel forward skipped: owner %q has no HTTP endpoint registered (job=%s)", ownerInstanceID, jobID)
		return
	}

	url := fmt.Sprintf("http://%s:%d/jobs/%s/cancel", agentRow.HTTPHost, agentRow.HTTPPort, jobID)

	body := strings.NewReader("")
	if reason != "" {
		// Mirror the on-wire CancelJobRequest shape so the agent runtime
		// can decode the same struct it would on a direct client call.
		body = strings.NewReader(fmt.Sprintf(`{"reason":%q}`, reason))
	}

	fwdCtx, cancel := context.WithTimeout(ctx, cancelForwardTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(fwdCtx, http.MethodPost, url, body)
	if err != nil {
		log.Printf("[meshjob] cancel forward build failed (owner=%s, job=%s): %v", ownerInstanceID, jobID, err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	// Trace-header propagation matches the proxy path (#310). We set these
	// directly rather than going through the MCP_MESH_PROPAGATE_HEADERS
	// allowlist because the cancel forward is a fixed, registry-internal
	// destination — no operator opt-in needed for these well-known headers.
	if traceID := c.Request.Header.Get("X-Trace-ID"); traceID != "" {
		req.Header.Set("X-Trace-ID", traceID)
	}
	if parentSpan := c.Request.Header.Get("X-Parent-Span"); parentSpan != "" {
		req.Header.Set("X-Parent-Span", parentSpan)
	}
	if meshTimeout := c.Request.Header.Get("X-Mesh-Timeout"); meshTimeout != "" {
		req.Header.Set("X-Mesh-Timeout", meshTimeout)
	}

	client := &http.Client{Timeout: cancelForwardTimeout}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[meshjob] cancel forward to %s failed (job=%s): %v", url, jobID, err)
		return
	}
	defer resp.Body.Close()
	// Drain to allow connection reuse; ignore body content.
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 300 {
		log.Printf("[meshjob] cancel forward to %s returned status %d (job=%s)", url, resp.StatusCode, jobID)
	}
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
